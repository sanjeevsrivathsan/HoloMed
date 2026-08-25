from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from ..dependencies.auth import get_current_user
from ..models.user import User

from ..services.auth_service import (
    create_user,
    authenticate_user,
    create_access_token,
)
from ..database import get_session


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(email: str, password: str, db: Session = Depends(get_session)):
    # Enforce minimum password length of 8 characters
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
    # Check if email already registered using SQLModel query
    stmt = select(User).where(User.email == email)
    existing = db.exec(stmt).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = create_user(email, password, db)
    return {"id": user.id, "email": user.email}

@router.post("/login")
def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_session)):
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token({"sub": str(user.id)})
    json_resp = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    json_resp.set_cookie(key="session", value=access_token, httponly=True, secure=False, samesite="lax")
    return json_resp

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="session")
    return {"detail": "Logged out"}

@router.post("/verify-email")
def verify_email():
    """Placeholder endpoint for future email verification flow.
    Currently returns a 501 Not Implemented response.
    """
    raise HTTPException(status_code=501, detail="Email verification not implemented")

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email}
