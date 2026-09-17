from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List

from ..database import get_session
from ..models import ConsentRecord, ConsentRead, ConsentCreate, User
from ..dependencies.auth import get_current_user
from .medical_data import log_action

router = APIRouter(prefix="/api/v1/consents", tags=["Consents"])

@router.get("", response_model=List[ConsentRead])
def list_consents(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    stmt = select(ConsentRecord).where(ConsentRecord.owner_id == user.id)
    consents = session.exec(stmt).all()
    return consents

@router.post("", response_model=ConsentRead)
def create_consent(
    consent_in: ConsentCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    consent = ConsentRecord.model_validate(consent_in, update={"owner_id": user.id})
    session.add(consent)
    session.commit()
    session.refresh(consent)
    log_action(session, user.id, "consent_created", {"consent_id": consent.id})
    session.commit()
    return consent

@router.put("/{consent_id}/revoke", response_model=ConsentRead)
def revoke_consent(
    consent_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    consent = session.get(ConsentRecord, consent_id)
    if not consent or consent.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Consent not found")
    
    consent.revoked = True
    session.add(consent)
    log_action(session, user.id, "consent_revoked", {"consent_id": consent.id})
    session.commit()
    session.refresh(consent)
    return consent

@router.delete("/{consent_id}")
def delete_consent(
    consent_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    consent = session.get(ConsentRecord, consent_id)
    if not consent or consent.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Consent not found")
    
    session.delete(consent)
    log_action(session, user.id, "consent_deleted", {"consent_id": consent_id})
    session.commit()
    return {"ok": True}
