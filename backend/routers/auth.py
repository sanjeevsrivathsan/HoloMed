from fastapi import APIRouter, Depends, Response, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from ..services.auth_service import get_demo_user, create_demo_user
from ..dependencies.auth import get_current_user

router = APIRouter()

@router.post("/api/v1/auth/login", tags=["Auth"])
def login(response: Response):
    """Demo login – creates or fetches a deterministic demo user and sets a secure cookie.
    No credentials required; works in local development.
    """
    user = get_demo_user()
    # Set a signed cookie (user_id) – simple approach for demo
    response.set_cookie(key="session", value=user.id, httponly=True, samesite="lax")
    return {"message": "Logged in as demo user", "email": user.email}

@router.post("/api/v1/auth/logout", tags=["Auth"])
def logout(response: Response, current_user=Depends(get_current_user)):
    """Clears the session cookie."""
    response.delete_cookie(key="session")
    return {"message": "Logged out"}


@router.get("/api/v1/auth/me", tags=["Auth"])
def get_me(current_user=Depends(get_current_user)):
    """Return info about the current demo user."""
    return {"id": current_user.id, "email": current_user.email}

