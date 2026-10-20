"""Pydantic request/response schemas for the auth endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=72)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=72)


class TokenResponse(BaseModel):
    token: str
    user_id: uuid.UUID


class MeResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    created_at: datetime