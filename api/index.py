import sys
from pathlib import Path

# Add project root to path so we can import backend_api when running as a Vercel function
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend_api import app as fastapi_app


# Vercel routes /api/* to this function. The FastAPI app defines routes like /health,
# so we strip the /api prefix here before dispatching.
async def app(scope, receive, send):
    if scope.get("type") in ("http", "websocket"):
        path = scope.get("path") or ""
        if path == "/api":
            path = "/"
        elif path.startswith("/api/"):
            path = path[4:]  # remove leading "/api"

        if path != scope.get("path"):
            scope = dict(scope)
            scope["path"] = path

    await fastapi_app(scope, receive, send)
