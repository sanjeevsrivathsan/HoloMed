import os
import uuid
from typing import Optional

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "storage")
os.makedirs(STORAGE_DIR, exist_ok=True)

def store_file(file_bytes: bytes, filename: str) -> str:
    # Prevent directory traversal by stripping any path components
    safe_name = os.path.basename(filename)
    storage_key = f"{uuid.uuid4()}_{safe_name}"
    file_path = os.path.join(STORAGE_DIR, storage_key)
    with open(file_path, "wb") as f:
        f.write(file_bytes)
    return storage_key

def retrieve_file(storage_key: str, storage_provider: str = "local") -> Optional[bytes]:
    if storage_provider != "local":
        raise NotImplementedError(f"Storage provider {storage_provider} not supported.")
    file_path = os.path.join(STORAGE_DIR, storage_key)
    if not os.path.exists(file_path):
        return None
    with open(file_path, "rb") as f:
        return f.read()


def delete_file(storage_key: str, storage_provider: str = "local") -> None:
    """Remove a stored file (used only for synthetic demo documents)."""
    if storage_provider != "local":
        raise NotImplementedError(f"Storage provider {storage_provider} not supported.")
    file_path = os.path.join(STORAGE_DIR, os.path.basename(storage_key))
    if os.path.isfile(file_path):
        os.remove(file_path)
