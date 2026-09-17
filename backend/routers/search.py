from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List, Dict, Any
from pydantic import BaseModel

from ..database import get_session
from ..models import Report, MedicalMeasurement, User, SourceReference
from ..dependencies.auth import get_current_user

router = APIRouter(prefix="/api/v1/search", tags=["Search"])

@router.get("/source-references")
def get_source_references(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    return session.exec(select(SourceReference).where(SourceReference.owner_id == user.id)).all()

class SearchRequest(BaseModel):
    query: str

class SearchResponse(BaseModel):
    report_ids: List[int]
    measurement_ids: List[int]

@router.post("", response_model=SearchResponse)
def perform_search(
    request: SearchRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    query = request.query.lower()
    
    # Simple keyword-based mock search
    # In a real app, this would use embeddings or a search engine
    
    matched_reports = []
    reports = session.exec(select(Report).where(Report.owner_id == user.id)).all()
    for r in reports:
        # Check title, type, source, hospital
        text_to_search = f"{r.title} {r.type} {r.source} {r.hospital or ''} {r.laboratory or ''}".lower()
        if query in text_to_search or "report" in query or "imaging" in query:
            if "blood" in query and "blood" not in text_to_search:
                continue
            if "imaging" in query and r.type != "Imaging Report":
                continue
            matched_reports.append(r.id)
            
    matched_measurements = []
    measurements = session.exec(select(MedicalMeasurement).where(MedicalMeasurement.owner_id == user.id)).all()
    for m in measurements:
        text_to_search = f"{m.test_name} {m.flag} {m.hospital or ''} {m.comments or ''}".lower()
        if query in text_to_search or "abnormal" in query and m.flag == "abnormal":
            matched_measurements.append(m.id)
            
        if "hba1c" in query and "hba1c" in m.test_name.lower():
             if m.id not in matched_measurements:
                 matched_measurements.append(m.id)
                 
    return SearchResponse(
        report_ids=matched_reports,
        measurement_ids=matched_measurements
    )
