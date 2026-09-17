from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List

from ..database import get_session
from ..models import StorageConnection, StorageConnectionRead, StorageConnectionCreate, User
from ..dependencies.auth import get_current_user
from .medical_data import log_action

router = APIRouter(prefix="/api/v1/storage-connections", tags=["Storage Connections"])

@router.get("", response_model=List[StorageConnectionRead])
def list_storage_connections(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    stmt = select(StorageConnection).where(StorageConnection.owner_id == user.id)
    connections = session.exec(stmt).all()
    return connections

@router.post("", response_model=StorageConnectionRead)
def create_storage_connection(
    conn_in: StorageConnectionCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    conn = StorageConnection.model_validate(conn_in, update={"owner_id": user.id})
    session.add(conn)
    session.commit()
    session.refresh(conn)
    log_action(session, user.id, "storage_connection_created", {"provider": conn.provider})
    session.commit()
    return conn

@router.put("/{conn_id}", response_model=StorageConnectionRead)
def update_storage_connection(
    conn_id: int,
    conn_in: StorageConnectionCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    conn = session.get(StorageConnection, conn_id)
    if not conn or conn.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Storage Connection not found")
    
    conn_data = conn_in.model_dump(exclude_unset=True)
    for key, value in conn_data.items():
        setattr(conn, key, value)
        
    session.add(conn)
    log_action(session, user.id, "storage_connection_updated", {"provider": conn.provider})
    session.commit()
    session.refresh(conn)
    return conn

@router.delete("/{conn_id}")
def delete_storage_connection(
    conn_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    conn = session.get(StorageConnection, conn_id)
    if not conn or conn.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Storage Connection not found")
    
    session.delete(conn)
    log_action(session, user.id, "storage_connection_deleted", {"provider": conn.provider})
    session.commit()
    return {"ok": True}
