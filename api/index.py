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
from fastapi import Request

@app.get("/api/test-route")
def test_route(request: Request):
    return {
        "status": "ok",
        "url_path": request.url.path,
        "scope_path": request.scope.get("path"),
        "headers": dict(request.headers),
    }

@app.get("/api/index.py")
def handle_direct_index(request: Request):
    return {
        "status": "ok",
        "msg": "Reached /api/index.py directly",
        "headers": dict(request.headers),
    }
