"""Patient ownership and the active-patient context.

Every patient-owned request is resolved to a Patient row owned by the signed-in user.
The frontend names the active patient in the ``X-HoloMed-Patient`` header (its uid);
the backend never trusts it without checking ownership. Requests without the header
use the user's default patient, so older clients keep working.
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from ..database import get_session
from ..models import Patient, User
from .auth import get_current_user

PATIENT_HEADER = "X-HoloMed-Patient"
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,31}$")
DEFAULT_NAME = "Patient 1"
MAX_NAME = 120


def normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def validate_code(code: str) -> str:
    code = normalize_code(code)
    if not CODE_PATTERN.fullmatch(code):
        raise HTTPException(status_code=422, detail="Patient ID must be 2-32 characters: letters, digits, '.', '_' or '-'.")
    return code


def validate_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(status_code=422, detail="Patient name is required.")
    if len(name) > MAX_NAME:
        raise HTTPException(status_code=422, detail=f"Patient name must be at most {MAX_NAME} characters.")
    return name


PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ().-]*$")


def validate_phone(phone: Optional[str]) -> Optional[str]:
    """International-friendly phone check: optional leading +, digits with spaces/()/./-, 6–15 digits."""
    phone = " ".join((phone or "").split())
    if not phone:
        return None
    digits = sum(c.isdigit() for c in phone)
    if len(phone) > 24 or not PHONE_PATTERN.fullmatch(phone) or not 6 <= digits <= 15:
        raise HTTPException(status_code=422, detail="Enter a valid phone number, e.g. +91 98765 43210.")
    return phone


def code_taken(session: Session, owner_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
    stmt = select(Patient.id).where(Patient.owner_id == owner_id, Patient.patient_code == code)
    if exclude_id is not None:
        stmt = stmt.where(Patient.id != exclude_id)
    return session.exec(stmt).first() is not None


def next_patient_code(session: Session, owner_id: int) -> str:
    codes = session.exec(select(Patient.patient_code).where(Patient.owner_id == owner_id)).all()
    numbers = [int(c[4:]) for c in codes if c and re.fullmatch(r"HML-\d+", c)]
    n = max(numbers, default=0) + 1
    while code_taken(session, owner_id, f"HML-{n:06d}"):
        n += 1
    return f"HML-{n:06d}"


def create_patient(session: Session, user: User, name: str, code: Optional[str] = None,
                   date_of_birth: Optional[str] = None, sex: Optional[str] = None,
                   age: Optional[int] = None, phone: Optional[str] = None) -> Patient:
    name = validate_name(name)
    code = validate_code(code) if code else next_patient_code(session, user.id)
    if code_taken(session, user.id, code):
        raise HTTPException(status_code=409, detail=f"Patient ID {code} already exists.")
    patient = Patient(owner_id=user.id, display_name=name, patient_code=code,
                      date_of_birth=date_of_birth, sex=sex, age=age, phone=validate_phone(phone))
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return patient


def default_patient(session: Session, user: User) -> Patient:
    patient = session.exec(select(Patient).where(Patient.owner_id == user.id).order_by(Patient.id)).first()
    if patient is None:
        patient = create_patient(session, user, DEFAULT_NAME)
    return patient


def owned_patient(session: Session, user: User, patient_uid: str) -> Patient:
    patient = session.exec(select(Patient).where(Patient.uid == patient_uid, Patient.owner_id == user.id)).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


def get_path_patient(patient_uid: str, user: User = Depends(get_current_user),
                     session: Session = Depends(get_session)) -> Patient:
    return owned_patient(session, user, patient_uid)


def get_active_patient(request: Request, user: User = Depends(get_current_user),
                       session: Session = Depends(get_session)) -> Patient:
    uid = request.headers.get(PATIENT_HEADER)
    return owned_patient(session, user, uid) if uid else default_patient(session, user)


def get_optional_patient(request: Request, user: User = Depends(get_current_user),
                         session: Session = Depends(get_session)) -> Optional[Patient]:
    """The patient named by the header, or None (list endpoints then span all of the user's patients)."""
    uid = request.headers.get(PATIENT_HEADER)
    return owned_patient(session, user, uid) if uid else None


def touch(patient: Patient) -> None:
    patient.updated_at = datetime.utcnow()
