import os
import sys
from contextlib import suppress

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Absolute path to AI_engine directory
ENGINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../AI_engine"))

# Ensure AI_engine is first in sys.path
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

# Load PyTorch before the rest of the app to avoid Windows CUDA DLL load-order failures.
with suppress(ImportError, OSError):
    import torch  # noqa: F401

# This import must follow the sys.path bootstrap above when this file runs directly.
from app.main import app  # noqa: E402

# Resolve the absolute path to the static frontend files directory
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))

# Mount the static directory to serve assets (CSS, JS, images)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Route to serve the index.html frontend page at the root URL path
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


# Allow direct execution with `python API/main.py`
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
