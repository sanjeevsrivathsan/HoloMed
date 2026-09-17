from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
import httpx

from ..config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
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

@router.get("/google")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Live Google verification cannot be performed")
    
    redirect_uri = "http://localhost:5173/api/v1/auth/google/callback"
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&redirect_uri={redirect_uri}"
        f"&access_type=offline"
    )
    return RedirectResponse(url=auth_url)

@router.get("/google/callback")
async def google_callback(code: str, db: Session = Depends(get_session)):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Live Google verification cannot be performed")
        
    redirect_uri = "http://localhost:5173/api/v1/auth/google/callback"
    
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )
        if token_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange Google code")
            
        access_token = token_res.json().get("access_token")
        
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get Google user info")
            
        user_info = user_res.json()
        
    email = user_info.get("email")
    google_id = user_info.get("id")
    
    if not email or not google_id:
        raise HTTPException(status_code=400, detail="Invalid Google user info")
        
    stmt = select(User).where(User.email == email)
    user = db.exec(stmt).first()
    
    if user:
        if user.google_id is None:
            user.google_id = google_id
            db.commit()
            db.refresh(user)
        elif user.google_id != google_id:
            raise HTTPException(status_code=400, detail="Email associated with a different Google account")
    else:
        user = User(email=email, google_id=google_id, hashed_password=None)
        db.add(user)
        db.commit()
        db.refresh(user)
        
    session_token = create_access_token({"sub": str(user.id)})
    
    response = RedirectResponse(url="/")
    response.set_cookie(key="session", value=session_token, httponly=True, secure=False, samesite="lax")
    return response
