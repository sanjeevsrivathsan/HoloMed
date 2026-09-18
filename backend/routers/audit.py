from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, or_, select

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..dependencies.patient import get_optional_patient
from ..models import AuditLog, AuditRead, Patient, User

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


@router.get("", response_model=List[AuditRead])
def get_audit_logs(
    user: User = Depends(get_current_user),
    active: Optional[Patient] = Depends(get_optional_patient),
    session: Session = Depends(get_session)
):
    """Audit entries of the signed-in user; with an active patient, that patient's entries
    plus account-level entries (sign-in etc.), never another patient's."""
    stmt = select(AuditLog).where(AuditLog.user_id == user.id)
    if active is not None:
        stmt = stmt.where(or_(AuditLog.patient_id == active.id, AuditLog.patient_id.is_(None)))
    return session.exec(stmt.order_by(AuditLog.timestamp.desc())).all()
