import os
from dotenv import load_dotenv

# Load .env if present
if os.path.exists('.env'):
    # Explicit path: a bare load_dotenv() searches from this file's directory and would pick
    # backend/.env instead of the .env in the working directory (repository root).
    load_dotenv('.env')

# Environment variables with defaults
CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',')
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
# lax (default; frontend and API on the same site) | strict | none (cross-site; requires Secure)
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
