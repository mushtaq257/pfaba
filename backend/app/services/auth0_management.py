from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from fastapi import HTTPException

from backend.app.config import get_settings

MANAGEMENT_TIMEOUT_SECONDS = 15
USERS_PER_PAGE = 100


def _management_domain() -> str:
    domain = get_settings().auth0_domain.strip()
    if domain.startswith("https://"):
        domain = domain[len("https://"):]
    elif domain.startswith("http://"):
        domain = domain[len("http://"):]
    return domain.rstrip("/")


def get_management_token() -> str:
    settings = get_settings()
    if not settings.auth0_management_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Auth0 Management API is not configured. Set "
                "AUTH0_MANAGEMENT_CLIENT_ID and AUTH0_MANAGEMENT_CLIENT_SECRET."
            ),
        )

    domain = _management_domain()
    try:
        response = requests.post(
            f"https://{domain}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": settings.auth0_management_client_id,
                "client_secret": settings.auth0_management_client_secret,
                "audience": f"https://{domain}/api/v2/",
                "scope": "read:users update:users create:users delete:users",
            },
            timeout=MANAGEMENT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail="Auth0 Management API could not be reached.",
        ) from exc

    if not response.ok:
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = {}
        error_code = error_payload.get("error") if isinstance(error_payload, dict) else None
        if error_code == "invalid_client":
            detail = (
                "Auth0 rejected the Management API client credentials. Verify the M2M "
                "client ID and secret belong to the same Auth0 tenant and that the "
                "backend was restarted after updating them."
            )
        elif error_code == "invalid_scope":
            detail = (
                "Auth0 rejected the requested Management API scopes. Authorize this "
                "M2M application for the Auth0 Management API with read:users, "
                "update:users, create:users, and delete:users."
            )
        elif error_code in {"access_denied", "unauthorized_client"}:
            detail = (
                "This M2M application is not authorized for the Auth0 Management API. "
                "Authorize it for that API and grant read:users, update:users, "
                "create:users, and delete:users."
            )
        else:
            detail = (
                "Auth0 rejected the Management API token request. Verify the M2M "
                "credentials, tenant domain, and Management API authorization."
            )
        raise HTTPException(
            status_code=502,
            detail=detail,
        )
    try:
        token_payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Auth0 returned an invalid Management API token response.",
        ) from exc
    token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
    if not isinstance(token, str) or not token:
        raise HTTPException(
            status_code=502,
            detail="Auth0 returned no Management API access token.",
        )
    return token


def _management_request(
    token: str,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Any:
    domain = _management_domain()
    try:
        response = requests.request(
            method,
            f"https://{domain}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=body,
            timeout=MANAGEMENT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail="Auth0 Management API could not be reached.",
        ) from exc

    if not response.ok:
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Auth0 user was not found.")
        if response.status_code == 403:
            raise HTTPException(
                status_code=502,
                detail="The Auth0 Management API client lacks the required scopes.",
            )
        if response.status_code == 409:
            raise HTTPException(
                status_code=409,
                detail="A user with that email or username already exists.",
            )
        if response.status_code == 400:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = {}
            error_message = ""
            if isinstance(error_payload, dict):
                error_message = str(
                    error_payload.get("message")
                    or error_payload.get("error_description")
                    or ""
                ).lower()
            if "password" in error_message or "weak" in error_message:
                detail = (
                    "Auth0 rejected the password. Check the tenant's password policy "
                    "and use a password that satisfies it."
                )
            elif "username" in error_message:
                detail = (
                    "Auth0 rejected the username. Check that the selected database "
                    "connection supports usernames and that the value is unique."
                )
            elif "connection" in error_message:
                detail = (
                    "Auth0 rejected the database connection. Choose an enabled Auth0 "
                    "database connection for this application."
                )
            elif method == "POST" and path == "/api/v2/users":
                detail = (
                    "Auth0 rejected user creation. Check the database connection, "
                    "required fields, unique email, and tenant password policy."
                )
            elif body and "password" in body:
                detail = (
                    "Auth0 rejected the password update. Confirm this is an Auth0 "
                    "database user and follow the tenant password policy."
                )
            else:
                detail = (
                    "Auth0 rejected the requested user update. Check the target "
                    "user's connection and status."
                )
            raise HTTPException(
                status_code=422,
                detail=detail,
            )
        raise HTTPException(
            status_code=502,
            detail="Auth0 Management API request failed.",
        )

    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Auth0 returned an invalid Management API response.",
        ) from exc


def _format_user(user: Dict[str, Any]) -> Dict[str, Any]:
    identities = user.get("identities") or []
    connections = sorted({
        identity["connection"]
        for identity in identities
        if isinstance(identity, dict) and isinstance(identity.get("connection"), str)
    })
    database_connections = sorted({
        identity["connection"]
        for identity in identities
        if (
            isinstance(identity, dict)
            and identity.get("provider") == "auth0"
            and isinstance(identity.get("connection"), str)
        )
    })
    blocked = bool(user.get("blocked"))
    email = user.get("email") or ""
    username = user.get("username") or user.get("nickname") or email.partition("@")[0]
    return {
        "user_id": user.get("user_id"),
        "name": user.get("name") or user.get("nickname") or username,
        "username": username,
        "email": email,
        "email_verified": bool(user.get("email_verified")),
        "status": "Disabled" if blocked else "Active",
        "blocked": blocked,
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
        "logins_count": user.get("logins_count", 0),
        "connections": connections,
        "database_connections": database_connections,
    }


def list_management_users() -> List[Dict[str, Any]]:
    token = get_management_token()
    users: List[Dict[str, Any]] = []
    page = 0
    while True:
        result = _management_request(
            token,
            "GET",
            "/api/v2/users",
            params={
                "page": page,
                "per_page": USERS_PER_PAGE,
                "include_totals": "false",
            },
        )
        if not isinstance(result, list):
            raise HTTPException(
                status_code=502,
                detail="Auth0 returned an invalid user list.",
            )
        if any(not isinstance(user, dict) or not isinstance(user.get("user_id"), str) for user in result):
            raise HTTPException(
                status_code=502,
                detail="Auth0 returned an invalid user record.",
            )
        users.extend(_format_user(user) for user in result)
        if len(result) < USERS_PER_PAGE:
            return users
        page += 1


def _user_path(user_id: str) -> str:
    return f"/api/v2/users/{quote(user_id, safe='')}"


def create_management_user(
    name: str,
    email: str,
    username: Optional[str],
    password: str,
    connection: str,
) -> Dict[str, Any]:
    cleaned_name = name.strip()
    cleaned_email = email.strip()
    cleaned_connection = connection.strip()
    cleaned_username = username.strip() if username else None
    if not cleaned_name or not cleaned_email or not cleaned_connection:
        raise HTTPException(
            status_code=422,
            detail="Name, email, and database connection are required.",
        )
    if username is not None and not cleaned_username:
        raise HTTPException(status_code=422, detail="Username cannot be blank.")

    body: Dict[str, Any] = {
        "name": cleaned_name,
        "email": cleaned_email,
        "password": password,
        "connection": cleaned_connection,
    }
    if cleaned_username:
        body["username"] = cleaned_username

    result = _management_request(
        get_management_token(),
        "POST",
        "/api/v2/users",
        body=body,
    )
    if not isinstance(result, dict) or not isinstance(result.get("user_id"), str):
        raise HTTPException(
            status_code=502,
            detail="Auth0 returned an invalid response when creating the user.",
        )
    return _format_user(result)


def set_user_enabled(user_id: str, enabled: bool) -> Dict[str, Any]:
    token = get_management_token()
    result = _management_request(
        token,
        "PATCH",
        _user_path(user_id),
        body={"blocked": not enabled},
    )
    if not isinstance(result, dict) or not isinstance(result.get("blocked"), bool):
        raise HTTPException(
            status_code=502,
            detail="Auth0 returned an invalid user status response.",
        )
    blocked = result["blocked"]
    return {"user_id": user_id, "enabled": not blocked}


def set_user_password(user_id: str, password: str) -> Dict[str, Any]:
    token = get_management_token()
    user = _management_request(token, "GET", _user_path(user_id))
    if not isinstance(user, dict) or not isinstance(user.get("identities"), list):
        raise HTTPException(
            status_code=502,
            detail="Auth0 returned invalid identity data for this user.",
        )
    identities = user["identities"]
    database_identity = next(
        (
            identity for identity in identities or []
            if isinstance(identity, dict) and identity.get("provider") == "auth0"
        ),
        None,
    )
    connection = database_identity.get("connection") if database_identity else None
    if not connection:
        raise HTTPException(
            status_code=409,
            detail="Direct password changes are available only for Auth0 database users.",
        )

    _management_request(
        token,
        "PATCH",
        _user_path(user_id),
        body={"password": password, "connection": connection},
    )
    return {"user_id": user_id, "updated": True}


def delete_management_user(user_id: str) -> Dict[str, Any]:
    _management_request(
        get_management_token(),
        "DELETE",
        _user_path(user_id),
    )
    return {"user_id": user_id, "deleted": True}
