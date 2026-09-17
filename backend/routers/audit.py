from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List

from ..database import get_session
from ..models import AuditLog, AuditRead, User
from ..dependencies.auth import get_current_user

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])

@router.get("", response_model=List[AuditRead])
def get_audit_logs(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Retrieve audit logs for the authenticated user.
    """
    stmt = select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.timestamp.desc())
    logs = session.exec(stmt).all()
    return logs
