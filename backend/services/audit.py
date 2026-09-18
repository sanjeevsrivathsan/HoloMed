import json
from typing import Optional

from sqlmodel import Session

from ..models import AuditLog


def log_action(session: Session, user_id: int, action: str, details: dict = None,
               patient_id: Optional[int] = None) -> None:
    """Append an audit entry (added to the session; the caller commits). Names/DOBs are never logged."""
    safe_details = {k: v for k, v in (details or {}).items() if "name" not in k.lower() and "dob" not in k.lower()}
    session.add(AuditLog(user_id=user_id, patient_id=patient_id, action=action,
                         details=json.dumps(safe_details) if safe_details else None))
