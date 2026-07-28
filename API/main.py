import sys
import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Absolute path to AI_engine directory
ENGINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../AI_engine"))

# Ensure AI_engine is first in sys.path
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

# Import the main FastAPI application instance from AI_engine/app/main.py
from app.main import app

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
