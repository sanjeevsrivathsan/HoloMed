import os
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from ..models.user import User
from ..database import get_session
from sqlmodel import Session, select

# Password hashing context using Argon2
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_user_by_email(email: str, session: Session) -> Optional[User]:
    stmt = select(User).where(User.email == email)
    return session.exec(stmt).first()

def authenticate_user(email: str, password: str, session: Session) -> Optional[User]:
    user = get_user_by_email(email, session)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

def create_user(email: str, password: str, session: Session) -> User:
    hashed = get_password_hash(password)
    user = User(email=email, hashed_password=hashed, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

def _get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is required for authentication")
    return secret

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "60"))))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _get_jwt_secret(), algorithm="HS256")
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"]) 
        return payload
    except JWTError as e:
        raise RuntimeError("Invalid JWT token") from e
