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
VISION_WEIGHTS_PATH = os.getenv(
    'VISION_WEIGHTS_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'weights', 'densenet121-res224-all.pt'),
)
VISION_DEVICE = os.getenv('VISION_DEVICE', 'auto')  # auto | cuda | cpu
VISION_MAX_UPLOAD_BYTES = int(os.getenv('VISION_MAX_UPLOAD_BYTES', str(50 * 1024 * 1024)))
VISION_MAX_OVERLAY_SIDE = int(os.getenv('VISION_MAX_OVERLAY_SIDE', '1024'))
