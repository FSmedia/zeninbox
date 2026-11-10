import sys
import os
from pathlib import Path

# Ensure project root is on sys.path
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.insert(0, cwd)

from app.main import app
from starlette.types import ASGIApp, Scope, Receive, Send

class VercelPathFixMiddleware:
    def __init__(self, asgi_app: ASGIApp):
        self.asgi_app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            # Vercel sends the original requested path in x-matched-path
            matched_path = headers.get(b"x-matched-path")
            if matched_path:
                decoded = matched_path.decode("utf-8")
                clean_path = decoded.split("?")[0]
                scope["path"] = clean_path
                scope["raw_path"] = clean_path.encode("utf-8")
        await self.asgi_app(scope, receive, send)

# Register middleware on app
app.add_middleware(VercelPathFixMiddleware)
