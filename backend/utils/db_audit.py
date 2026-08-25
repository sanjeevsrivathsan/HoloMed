import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def list_duplicate_dbs(base_dir: str = ".") -> list[Path]:
    """Return a list of all SQLite database files found under *base_dir*.
    The canonical production database is expected at ``./data/holomed.db``.
    This function is for diagnostic purposes only – it **does not delete** any files.
    """
    db_patterns = ("*.db", "*.sqlite", "*.sqlite3")
    found = []
    for pattern in db_patterns:
        for path in Path(base_dir).rglob(pattern):
            found.append(path.resolve())
    # Log a warning if more than the canonical DB is present
    canonical = Path(os.getenv("HOLUMED_DB_PATH", "./data/holomed.db")).resolve()
    extra = [p for p in found if p != canonical]
    if extra:
        logger.warning(
            "Duplicate SQLite database files detected: %s. Only %s is used by the application.",
            ", ".join(str(p) for p in extra),
            canonical,
        )
    else:
        logger.info("No duplicate SQLite databases found. Production DB: %s", canonical)
    return found
