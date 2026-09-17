from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime

from ..database import get_session
from ..models import Template, TemplateRead, TemplateCreate, User
from ..dependencies.auth import get_current_user
from .medical_data import log_action

router = APIRouter(prefix="/api/v1/templates", tags=["Templates"])

@router.get("", response_model=List[TemplateRead])
def list_templates(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    stmt = select(Template).where(Template.owner_id == user.id)
    templates = session.exec(stmt).all()
    return templates

@router.get("/{template_id}", response_model=TemplateRead)
def get_template(
    template_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    template = session.get(Template, template_id)
    if not template or template.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Template not found")
    return template

@router.post("", response_model=TemplateRead)
def create_template(
    template_in: TemplateCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    template = Template.model_validate(template_in, update={"owner_id": user.id})
    session.add(template)
    session.commit()
    session.refresh(template)
    log_action(session, user.id, "template_created", {"template_id": template.id})
    session.commit()
    return template

@router.put("/{template_id}", response_model=TemplateRead)
def update_template(
    template_id: int,
    template_in: TemplateCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    template = session.get(Template, template_id)
    if not template or template.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template_data = template_in.model_dump(exclude_unset=True)
    for key, value in template_data.items():
        setattr(template, key, value)
    
    template.updated_at = datetime.utcnow()
    
    session.add(template)
    log_action(session, user.id, "template_updated", {"template_id": template.id})
    session.commit()
    session.refresh(template)
    return template

@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    template = session.get(Template, template_id)
    if not template or template.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Template not found")
    
    session.delete(template)
    log_action(session, user.id, "template_deleted", {"template_id": template_id})
    session.commit()
    return {"ok": True}
