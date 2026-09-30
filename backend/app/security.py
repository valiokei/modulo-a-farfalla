from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User

hasher = PasswordHash.recommended()


def hash_password(value: str) -> str: return hasher.hash(value)
def verify_password(value: str, hashed: str) -> bool: return hasher.verify(value, hashed)


def make_token(user: User) -> str:
    return jwt.encode({"sub": user.id, "role": user.role.value, "exp": datetime.now(timezone.utc) + timedelta(days=7)}, settings.secret_key, algorithm="HS256")


async def current_user(access_token: str | None = Cookie(None), db: Session = Depends(get_db)) -> User:
    if not access_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    try:
        subject = jwt.decode(access_token, settings.secret_key, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
    user = db.get(User, subject)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return user

async def admin_user(user: User = Depends(current_user)) -> User:
    if user.role.value != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def require_roles(*roles: str):
    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role.value not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return dependency


async def coach_user(user: User = Depends(current_user)) -> User:
    if user.role.value not in ("admin", "coach"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Coach or admin role required")
    return user
