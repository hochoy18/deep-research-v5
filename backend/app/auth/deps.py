"""FastAPI dependencies for the auth layer.

`get_db` is re-exported from `app.db.session` so the import surface stays
small. `get_current_user` turns a bearer header into a User, raising
`HTTPException(401)` on any failure.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import User
from ..db.session import get_db
from .service import AuthService


def get_auth_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(db, settings)


def _extract_bearer(request: Request) -> str:
    """Pull the bearer token out of the Authorization header."""
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
        )
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="expected `Authorization: Bearer <token>`",
        )
    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="empty bearer",
        )
    return token


def get_current_user(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> User:
    """FastAPI dependency: resolve the bearer to a User or raise 401."""
    token = _extract_bearer(request)
    try:
        return service.get_current_user(token)
    except Exception:
        # Don't leak which check failed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired bearer",
        )


def get_current_bearer(request: Request) -> str:
    """FastAPI dependency: return the bearer string (used by /logout)."""
    return _extract_bearer(request)