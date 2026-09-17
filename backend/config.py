import os
from dotenv import load_dotenv

# Load .env if present
if os.path.exists('.env'):
    load_dotenv()

# Environment variables with defaults
CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', '')
DATABASE_URL = os.getenv('DATABASE_URL', f"sqlite:///./data/holomed.db")
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')

# Vision AI service (chest radiograph screening model, local checkpoint only)
VISION_PROVIDER = os.getenv('VISION_PROVIDER', 'local')  # local | cloud (cloud: reserved, not implemented)
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
