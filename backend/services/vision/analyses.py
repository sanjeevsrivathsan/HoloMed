"""Persisted chest X-ray screening runs (AIAnalysis), linked to a patient and, for DICOM input, a study.

The stored response is the screening output exactly as returned; nothing is re-scored or
re-interpreted when it is reopened.
"""
import hashlib
import json
from typing import Optional

from sqlmodel import Session, select

from ...models import AIAnalysis, Instance, Patient, Study, User
from . import results
from .schemas import VisionScreenResponse


def record(session: Session, user: User, patient: Patient, response: VisionScreenResponse, data: bytes,
           provider: str, study: Optional[Study] = None, instance: Optional[Instance] = None) -> AIAnalysis:
    payload = response.model_dump(mode="json")
    payload["result_id"] = None
    analysis = AIAnalysis(
        owner_id=user.id, patient_id=patient.id,
        study_id=study.id if study else None, instance_id=instance.id if instance else None,
        input_format=response.input.format, input_sha256=hashlib.sha256(data).hexdigest(), provider=provider,
        model_name=response.model.name, model_weights=response.model.weights,
        weight_sha256=response.model.weight_sha256,
        primary_pathology=response.primary_finding.pathology, primary_score=response.primary_finding.score,
        selected_target=response.explanation.target_pathology,
        response_json=json.dumps(payload), result_id=response.result_id,
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


def summary(session: Session, analysis: AIAnalysis) -> dict:
    study = session.get(Study, analysis.study_id) if analysis.study_id else None
    instance = session.get(Instance, analysis.instance_id) if analysis.instance_id else None
    return {
        "id": analysis.uid,
        "study_instance_uid": study.study_instance_uid if study else None,
        "sop_instance_uid": instance.sop_instance_uid if instance else None,
        "input_format": analysis.input_format,
        "provider": analysis.provider,
        "model_name": analysis.model_name,
        "model_weights": analysis.model_weights,
        "weight_sha256": analysis.weight_sha256,
        "primary_pathology": analysis.primary_pathology,
        "primary_score": analysis.primary_score,
        "selected_target": analysis.selected_target,
        "created_at": analysis.created_at.isoformat() + "Z",
    }


def reopen(session: Session, analysis: AIAnalysis) -> dict:
    """Full stored result plus a live result_id for requesting further text explanations."""
    response = json.loads(analysis.response_json)
    explanations = json.loads(analysis.text_explanations_json or "{}")
    live = results.get(analysis.result_id, analysis.owner_id) if analysis.result_id else None
    if live is None:
        scores = {f["pathology"]: f["score"] for f in response["findings"]}
        analysis.result_id = results.register(analysis.owner_id, scores, analysis.primary_pathology,
                                              analysis.model_weights, analysis.weight_sha256)
        session.add(analysis)
        session.commit()
        from ..explanation.cxr_explanation import TextExplanationResponse
        for target, payload in explanations.items():
            restored = TextExplanationResponse.model_validate({**payload, "result_id": analysis.result_id})
            results.put_explanation(analysis.result_id, analysis.owner_id, target, restored)
    response["result_id"] = analysis.result_id
    return {**summary(session, analysis), "response": response, "text_explanations": explanations}


def save_text_explanation(session: Session, owner_id: int, result_id: str, target: str, payload: dict) -> None:
    analysis = session.exec(select(AIAnalysis).where(AIAnalysis.result_id == result_id,
                                                     AIAnalysis.owner_id == owner_id)).first()
    if analysis is None:
        return
    stored = json.loads(analysis.text_explanations_json or "{}")
    stored[target] = payload
    analysis.text_explanations_json = json.dumps(stored)
    session.add(analysis)
    session.commit()
