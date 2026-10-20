"""FastAPI router for the four auth endpoints (P1).

  POST /auth/signup  → 201 {token, user_id}
  POST /auth/login   → 200 {token, user_id}
  POST /auth/logout  → 204
  GET  /auth/me      → 200 {user_id, username, created_at}

Status-code mapping (per issue #2 acceptance criteria):

  - duplicate username           → 409
  - field bounds violation       → 422
  - wrong credentials / blacklist → 401 (single message; no info leakage)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from ..db.models import User
from .deps import (
    get_auth_service,
    get_current_bearer,
    get_current_user,
)
from .schemas import LoginRequest, MeResponse, SignupRequest, TokenResponse
from .security import (
    DuplicateUserError,
    InvalidCredentialsError,
    InvalidTokenError,
    UsernameOutOfBoundsError,
    WeakPasswordError,
)
from .service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(
    body: SignupRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        issued = service.signup(body.username, body.password)
    except DuplicateUserError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already taken",
        )
    except (UsernameOutOfBoundsError, WeakPasswordError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return TokenResponse(token=issued.token, user_id=issued.user_id)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    try:
        issued = service.login(body.username, body.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    except UsernameOutOfBoundsError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return TokenResponse(token=issued.token, user_id=issued.user_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    bearer: str = Depends(get_current_bearer),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    # An invalid bearer never reaches this body: `get_current_bearer`
    # already raised 401. Any other failure (e.g. integrity on insert) is
    # a server error.
    service.logout(bearer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
def me(current: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user_id=current.id,
        username=current.username,
        created_at=current.created_at,
    )