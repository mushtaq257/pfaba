"""FastAPI application entry point for the finance advisor."""

from __future__ import annotations

from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.database import init_db
from backend.app.models import (
    AdminUserCreate,
    AdminUserPasswordUpdate,
    AdminUserStatusUpdate,
    ChatMessage,
    CurrencyConversionRequest,
    FinancialRequest,
    HistoricalPermissionsUpdate,
)
from backend.app.services.auth import get_auth_payload, get_auth_roles, require_admin
from backend.app.services.api_clients import fetch_exchange_rates, reverse_geocode_coordinates
from backend.app.services.auth0_management import (
    create_management_user,
    delete_management_user,
    list_management_users,
    set_user_enabled,
    set_user_password,
)
from backend.app.services.finance_agent import FinanceAgent
from backend.app.services.storage import (
    DEFAULT_HISTORICAL_PERMISSIONS,
    get_historical_permissions,
    get_historical_permissions_for_users,
    load_session,
    list_admin_audit_log,
    record_admin_audit_log,
    save_goals,
    save_transactions,
    set_historical_permissions,
    upsert_profile,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend" / "static"

init_db()

app = FastAPI(
    title="Personal Finance & Budget Advisor Agent",
    description=(
        "Conversational finance assistant with categorization, budgeting, "
        "and goal planning."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = FinanceAgent()


@app.get("/api/health")
def health() -> dict:
    """Return basic application health information."""
    return {
        "status": "ok",
        "service": get_settings().app_name,
    }


@app.get("/api/auth/config")
def auth_config() -> dict:
    """Expose non-secret Auth0 settings required by the frontend."""
    settings = get_settings()
    return {
        "status": "success",
        "data": {
            "enabled": settings.auth0_enabled,
            "domain": settings.auth0_domain or None,
            "audience": settings.auth0_audience or None,
            "client_id": settings.auth0_client_id or None,
        },
    }


@app.get("/api/auth/me")
def current_user(request: Request) -> dict:
    """Validate the caller's access token and return its Auth0 identity."""
    payload = get_auth_payload(request)
    display_name = (
        payload.get("name")
        or payload.get("nickname")
        or payload.get("preferred_username")
        or payload.get("email")
    )
    username = (
        payload.get("preferred_username")
        or payload.get("nickname")
        or payload.get("email")
        or payload["sub"]
    )
    return {
        "status": "success",
        "data": {
            "sub": payload["sub"],
            "display_name": display_name,
            "username": username,
            "roles": get_auth_roles(payload),
            "historical_permissions": get_historical_permissions(payload["sub"]),
        },
    }


@app.get("/api/admin/users")
def admin_list_users(request: Request) -> dict:
    """List Auth0 users and their app-specific historical permissions."""
    require_admin(request)
    users = list_management_users()
    permissions = get_historical_permissions_for_users(
        [user["user_id"] for user in users if user.get("user_id")]
    )
    for user in users:
        user["historical_permissions"] = permissions.get(
            user.get("user_id"),
            dict(DEFAULT_HISTORICAL_PERMISSIONS),
        )
    return {"status": "success", "data": {"users": users}}


@app.post("/api/admin/users", status_code=201)
def admin_create_user(payload: AdminUserCreate, request: Request) -> dict:
    """Create an Auth0 database user."""
    admin = require_admin(request)
    user = create_management_user(**payload.model_dump())
    user["historical_permissions"] = dict(DEFAULT_HISTORICAL_PERMISSIONS)
    record_admin_audit_log(
        admin["sub"],
        "user.created",
        user["user_id"],
        "Created user account",
    )
    return {"status": "success", "data": {"user": user}}


@app.patch("/api/admin/users/{user_id}/status")
def admin_update_user_status(
    user_id: str,
    payload: AdminUserStatusUpdate,
    request: Request,
) -> dict:
    """Enable or disable an Auth0 user."""
    admin = require_admin(request)
    if user_id == admin["sub"] and not payload.enabled:
        raise HTTPException(
            status_code=409,
            detail="You cannot disable the currently signed-in administrator.",
        )
    result = set_user_enabled(user_id, payload.enabled)
    record_admin_audit_log(
        admin["sub"],
        "user.enabled" if payload.enabled else "user.disabled",
        user_id,
        "Enabled user account" if payload.enabled else "Disabled user account",
    )
    return {"status": "success", "data": result}


@app.patch("/api/admin/users/{user_id}/password")
def admin_update_user_password(
    user_id: str,
    payload: AdminUserPasswordUpdate,
    request: Request,
) -> dict:
    """Set a new password for an Auth0 database user."""
    admin = require_admin(request)
    result = set_user_password(user_id, payload.password)
    record_admin_audit_log(
        admin["sub"],
        "user.password_updated",
        user_id,
        "Updated user password",
    )
    return {"status": "success", "data": result}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str, request: Request) -> dict:
    """Delete an Auth0 user."""
    admin = require_admin(request)
    if user_id == admin["sub"]:
        raise HTTPException(
            status_code=409,
            detail="You cannot delete the currently signed-in administrator.",
        )
    result = delete_management_user(user_id)
    record_admin_audit_log(
        admin["sub"],
        "user.deleted",
        user_id,
        "Deleted user account",
    )
    return {"status": "success", "data": result}


@app.patch("/api/admin/users/{user_id}/historical-permissions")
def admin_update_historical_permissions(
    user_id: str,
    payload: HistoricalPermissionsUpdate,
    request: Request,
) -> dict:
    """Set historical data permissions for a user."""
    admin = require_admin(request)
    if user_id == admin["sub"]:
        raise HTTPException(
            status_code=409,
            detail="Historical finance permissions do not apply to administrators.",
        )
    permissions = set_historical_permissions(
        user_id,
        payload.model_dump(),
        admin["sub"],
    )
    record_admin_audit_log(
        admin["sub"],
        "user.historical_permissions_updated",
        user_id,
        "Updated historical finance permissions",
    )
    return {"status": "success", "data": {"historical_permissions": permissions}}


@app.get("/api/admin/audit-log")
def admin_audit_log(request: Request) -> dict:
    """Return recent admin actions without credentials or sensitive payloads."""
    require_admin(request)
    return {"status": "success", "data": {"logs": list_admin_audit_log()}}


@app.get("/api/location/reverse")
def reverse_location(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
) -> dict:
    """Resolve browser-provided coordinates to a human-readable location."""
    try:
        location_data = reverse_geocode_coordinates(latitude, longitude)
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not resolve the device location. Please try again.",
        ) from exc
    return {"status": "success", "data": location_data}


@app.post("/api/currency/convert")
def convert_currency_amount(payload: CurrencyConversionRequest) -> dict:
    """Convert an amount using the configured ExchangeRate-API endpoint."""
    source = payload.from_currency.upper()
    target = payload.to_currency.upper()
    if source == target:
        rate = 1.0
    else:
        rates = fetch_exchange_rates(source)
        if not rates:
            raise HTTPException(
                status_code=503,
                detail="Exchange rates are unavailable. Please try again later.",
            )
        try:
            rate = float(rates[target])
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"No exchange rate is available for {target}.",
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail="The exchange-rate provider returned an invalid rate.",
            ) from exc

    return {
        "status": "success",
        "data": {
            "amount": payload.amount,
            "from_currency": source,
            "to_currency": target,
            "rate": rate,
            "converted_amount": round(payload.amount * rate, 2),
            "provider": "ExchangeRate-API",
        },
    }


@app.post("/api/finance/analyze")
def analyze_financial_profile(payload: FinancialRequest, request: Request) -> dict:
    """Persist the submitted financial profile and return its analysis."""
    auth_payload = get_auth_payload(request)
    session_id = auth_payload["sub"]
    upsert_profile(session_id, payload.income, payload.currency, payload.location)
    save_transactions(session_id, [txn.model_dump() for txn in payload.transactions])
    if payload.goal_name:
        save_goals(
            session_id,
            [{
                "name": payload.goal_name,
                "target": payload.goal_amount,
                "saved": payload.goal_saved,
            }],
        )
    result = agent.analyze(payload.model_copy(update={"session_id": session_id}))
    return {"status": "success", "data": result}


@app.post("/api/chat")
def chat_with_agent(payload: ChatMessage, request: Request) -> dict:
    """Process a chat message and persist the supplied financial context."""
    auth_payload = get_auth_payload(request)
    session_id = auth_payload["sub"]
    upsert_profile(session_id, payload.income or 0, payload.currency, payload.location)
    save_transactions(session_id, [txn.model_dump() for txn in payload.transactions])
    goals_payload = payload.goals
    if isinstance(goals_payload, list) and goals_payload:
        goals_payload = goals_payload[0]
    if isinstance(goals_payload, dict):
        save_goals(
            session_id,
            [{
                "name": goals_payload.get("name"),
                "target": goals_payload.get("target", 0),
                "saved": goals_payload.get("saved", 0),
            }],
        )
    result = agent.process_chat_message(payload.model_copy(update={"session_id": session_id}))
    return {"status": "success", "data": result}


@app.get("/api/session/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    """Return persisted financial data for a session."""
    auth_payload = get_auth_payload(request)
    if session_id != auth_payload["sub"]:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "success", "data": load_session(auth_payload["sub"])}


@app.get("/")
def serve_frontend() -> FileResponse:
    """Serve the frontend entry page."""
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
