import os
from dotenv import load_dotenv

# Load .env if present
# Explicit paths: a bare load_dotenv() searches from this file's directory and would pick
# backend/.env instead of the .env in the repository root. The working-directory .env wins; when
# the server is started from another directory, the repository-root .env is used instead.
# Real environment variables always take precedence over .env values.
_REPO_ROOT_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists('.env'):
    load_dotenv('.env')
elif os.path.exists(_REPO_ROOT_ENV):
    load_dotenv(_REPO_ROOT_ENV)


def parse_cors_origins(value: str) -> list:
    """Comma-separated origins → exact-match list. Whitespace and trailing slashes are removed
    (browsers send Origin without them). "*" is dropped: with credentials it would let any site
    read authenticated responses."""
    origins = []
    for item in value.split(','):
        origin = item.strip().rstrip('/')
        if origin and origin != '*' and origin not in origins:
            origins.append(origin)
    return origins


# Environment variables with defaults
CORS_ORIGINS = parse_cors_origins(os.getenv('CORS_ORIGINS', 'http://localhost:5173'))
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', '')
DATABASE_URL = os.getenv('DATABASE_URL', f"sqlite:///./data/holomed.db")
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')  # backend-only secret; never logged or sent to the browser


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


# Deployment environment: development (default) | production
HOLOMED_ENV = os.getenv('HOLOMED_ENV', 'development').strip().lower()

# Google Sign-In (OpenID Connect authorization-code flow with PKCE).
# Register GOOGLE_REDIRECT_URI exactly in the Google Cloud OAuth client. The default matches local
# development, where the Vite dev server (:5173) proxies /api to the backend.
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5173/api/v1/auth/google/callback')
# Where the browser lands after Google sign-in (success, or ?auth_error=<code> on failure).
GOOGLE_POST_LOGIN_URL = os.getenv('GOOGLE_POST_LOGIN_URL', 'http://localhost:5173/')

# Session cookie. Secure defaults to true in production; local HTTP development needs false.
SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', HOLOMED_ENV == 'production')
# lax (default; frontend and API on the same site) | strict | none (cross-site; requires Secure).
# A frontend on another site (e.g. GitHub Pages calling api.<domain>) needs none: with lax the
# browser never sends the cookie on its fetch() calls and /auth/me returns 401.
SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'lax').strip().lower()

# Vision AI service (chest radiograph screening model, local checkpoint only)
# local (default, primary deployment): in-process model on this machine's GPU/CPU; needs no cloud settings.
# cloud (optional): private Modal GPU worker; requires VISION_CLOUD_URL + VISION_CLOUD_TOKEN. No fallback.
VISION_PROVIDER = os.getenv('VISION_PROVIDER', 'local')
VISION_PRELOAD = os.getenv('VISION_PRELOAD', '0').strip().lower() in ('1', 'true', 'yes')  # load model at startup
# Cloud vision worker (VISION_PROVIDER=cloud): HTTPS URL of the private GPU worker and its bearer token.
VISION_CLOUD_URL = os.getenv('VISION_CLOUD_URL', '')
VISION_CLOUD_TOKEN = os.getenv('VISION_CLOUD_TOKEN', '')
VISION_CLOUD_TIMEOUT_SECONDS = float(os.getenv('VISION_CLOUD_TIMEOUT_SECONDS', '120'))
# Worker side (backend/vision_worker): token the worker requires on every request.
VISION_WORKER_TOKEN = os.getenv('VISION_WORKER_TOKEN', '')
# Structured screening results kept in memory for explanations (no images).
VISION_RESULT_TTL_SECONDS = int(os.getenv('VISION_RESULT_TTL_SECONDS', '1800'))

# Text AI (explanations of structured vision results only)
TEXT_AI_PROVIDER = os.getenv('TEXT_AI_PROVIDER', 'ollama')  # ollama | omniroute
TEXT_AI_TIMEOUT_SECONDS = float(os.getenv('TEXT_AI_TIMEOUT_SECONDS', '90'))
OMNIROUTE_BASE_URL = os.getenv('OMNIROUTE_BASE_URL', '')  # OpenAI-compatible base, e.g. https://host/v1
OMNIROUTE_API_KEY = os.getenv('OMNIROUTE_API_KEY', '')
OMNIROUTE_MODEL = os.getenv('OMNIROUTE_MODEL', '')
VISION_WEIGHTS_PATH = os.getenv(
    'VISION_WEIGHTS_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'weights', 'densenet121-res224-all.pt'),
)
VISION_DEVICE = os.getenv('VISION_DEVICE', 'auto')  # auto | cuda | cpu
VISION_MAX_UPLOAD_BYTES = int(os.getenv('VISION_MAX_UPLOAD_BYTES', str(50 * 1024 * 1024)))
VISION_MAX_OVERLAY_SIDE = int(os.getenv('VISION_MAX_OVERLAY_SIDE', '1024'))

# Bulk DICOM import (Patient → Imaging → Import: DICOM files, a folder, or one ZIP archive).
# Every limit applies per import; each instance is also bound by the 50 MiB single-file limit.
IMPORT_MAX_ARCHIVE_BYTES = int(os.getenv('HOLOMED_IMPORT_MAX_ARCHIVE_BYTES', str(2 * 1024 ** 3)))    # ZIP as uploaded
IMPORT_MAX_EXTRACTED_BYTES = int(os.getenv('HOLOMED_IMPORT_MAX_EXTRACTED_BYTES', str(4 * 1024 ** 3)))  # all files, uncompressed
IMPORT_MAX_FILES = int(os.getenv('HOLOMED_IMPORT_MAX_FILES', '10000'))
# Largest uncompressed:compressed ratio accepted for a ZIP member (and the whole archive); DICOM
# rarely exceeds ~10:1, compression bombs reach thousands.
IMPORT_MAX_COMPRESSION_RATIO = float(os.getenv('HOLOMED_IMPORT_MAX_COMPRESSION_RATIO', '100'))
IMPORT_MAX_BATCH_FILES = int(os.getenv('HOLOMED_IMPORT_MAX_BATCH_FILES', '100'))  # files per upload request
IMPORT_JOB_TTL_SECONDS = int(os.getenv('HOLOMED_IMPORT_JOB_TTL_SECONDS', '3600'))  # idle/finished jobs are discarded after this
