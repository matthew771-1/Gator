import sys
from pathlib import Path

# Add parent directory to path so we can import backend_api
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend_api import app
