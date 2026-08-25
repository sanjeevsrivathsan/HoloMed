import sys
import os
# Ensure the project root is in sys.path for imports
project_root = os.path.abspath(os.path.dirname(__file__))
# Ensure test environment variable is set
os.environ.setdefault("ENV", "test")
# Set a default JWT secret for tests
os.environ.setdefault("JWT_SECRET", "testsecret")
