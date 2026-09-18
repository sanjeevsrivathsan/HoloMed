from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List

from ..database import get_session
from ..models import MedicalMeasurement, MeasurementRead, MeasurementCreate, Patient, User
from ..dependencies.auth import get_current_user
from ..dependencies.patient import get_optional_patient
from .medical_data import log_action

router = APIRouter(prefix="/api/v1/measurements", tags=["Measurements"])

@router.get("", response_model=List[MeasurementRead])
def list_measurements(
    patient_id: int | None = None,
    user: User = Depends(get_current_user),
    active: Patient | None = Depends(get_optional_patient),
    session: Session = Depends(get_session)
):
    if active is not None:
        patient_id = active.id
    stmt = select(MedicalMeasurement).where(MedicalMeasurement.owner_id == user.id)
    if patient_id is not None:
        stmt = stmt.where(MedicalMeasurement.patient_id == patient_id)
    stmt = stmt.order_by(MedicalMeasurement.report_date.desc())
    measurements = session.exec(stmt).all()
    return measurements

@router.get("/{measurement_id}", response_model=MeasurementRead)
def get_measurement(
    measurement_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    measurement = session.get(MedicalMeasurement, measurement_id)
    if not measurement or measurement.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    return measurement

@router.post("", response_model=MeasurementRead)
def create_measurement(
    measurement_in: MeasurementCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    measurement = MedicalMeasurement.model_validate(measurement_in, update={"owner_id": user.id})
    session.add(measurement)
    session.commit()
    session.refresh(measurement)
    log_action(session, user.id, "measurement_created", {"measurement_id": measurement.id})
    session.commit()
    return measurement

@router.delete("/{measurement_id}")
def delete_measurement(
    measurement_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    measurement = session.get(MedicalMeasurement, measurement_id)
    if not measurement or measurement.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Measurement not found")
    
    session.delete(measurement)
    log_action(session, user.id, "measurement_deleted", {"measurement_id": measurement_id})
    session.commit()
    return {"ok": True}
