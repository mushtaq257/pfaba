import logging

import requests
from fastapi import HTTPException, Request
from jose import jwt
from jose.exceptions import JWTError

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


def verify_token(token: str) -> dict:
    settings = get_settings()
    if not settings.auth0_domain or not settings.auth0_audience:
        return {"status": "dev_mode", "message": "Authentication disabled in local environment."}

    domain = settings.auth0_domain.strip()
    if domain.startswith("https://"):
        domain = domain[len("https://"):]
    elif domain.startswith("http://"):
        domain = domain[len("http://"):]
    domain = domain.rstrip("/")

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc

    key_id = unverified_header.get("kid")
    if unverified_header.get("alg") != "RS256" or not key_id:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")

    try:
        response = requests.get(
            f"https://{domain}/.well-known/jwks.json",
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Could not retrieve Auth0 signing keys (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Authentication provider is temporarily unavailable.",
        ) from exc

    try:
        jwks = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Authentication provider returned invalid signing keys.",
        ) from exc
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise HTTPException(
            status_code=502,
            detail="Authentication provider returned invalid signing keys.",
        )

    signing_key = next(
        (
            key for key in jwks["keys"]
            if isinstance(key, dict)
            and key.get("kid") == key_id
            and key.get("kty") == "RSA"
            and key.get("alg", "RS256") == "RS256"
            and key.get("use", "sig") == "sig"
        ),
        None,
    )
    if signing_key is None:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")

    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{domain}/",
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc


def get_auth_payload(request: Request) -> dict:
    settings = get_settings()
    authorization = request.headers.get("Authorization", "")

    if not settings.auth0_enabled:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured. Configure Auth0 before using this endpoint.",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required.")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer token format.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty.")
    payload = verify_token(token)
    if not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
        raise HTTPException(status_code=401, detail="The access token has no user identity.")
    return payload


def get_auth_roles(payload: dict) -> list[str]:
    roles = payload.get("roles")
    if roles is None:
        roles = next(
            (
                value for claim, value in payload.items()
                if isinstance(claim, str) and claim.endswith("/roles")
            ),
            [],
        )
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, list):
        return []
    return [role for role in roles if isinstance(role, str)]


def require_admin(request: Request) -> dict:
    payload = get_auth_payload(request)
    if not any(role.strip().casefold() == "admin" for role in get_auth_roles(payload)):
        raise HTTPException(status_code=403, detail="The admin role is required.")
    return payload
