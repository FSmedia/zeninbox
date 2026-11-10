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
