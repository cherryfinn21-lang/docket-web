"""
Minimal auth: email + password, JWT bearer tokens.

What's NOT here, deliberately, for you to add before real launch:
  - Email verification (right now anyone can sign up with any email string)
  - Password reset flow
  - Rate limiting on login attempts (add this before launch — brute-force
    protection matters even for a small app)
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, FREE_SIGNUP_CREDITS
from db import User, get_session

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def signup(session: Session, email: str, password: str) -> User:
    existing = session.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with that email already exists.")
    user = User(email=email, password_hash=hash_password(password), credits=FREE_SIGNUP_CREDITS)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def login(session: Session, email: str, password: str) -> User:
    user = session.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    user = session.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return user


def require_credits(user: User, amount: int):
    if user.credits < amount and not user.subscription_active:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits (need {amount}, have {user.credits}). Buy more or subscribe.",
        )


def spend_credits(session: Session, user: User, amount: int):
    if user.subscription_active:
        return  # unlimited on the Pro plan — meter differently (e.g. daily cap) if you need to bound cost
    user.credits -= amount
    session.commit()
