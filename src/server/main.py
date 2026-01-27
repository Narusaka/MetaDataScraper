
import os
import logging
import asyncio
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

# Import our customized modules
from src.server.logger_handler import log_broadcaster
from src.server.job_manager import job_manager
from src.server.settings_manager import SettingsManager

# --- Logging Setup ---
# Ensure logs directory exists
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
session_timestamp = logging.Formatter().converter(None) # just a placeholder
from datetime import datetime
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = log_dir / f"web_session_{timestamp}.log"

# Attach handlers to the root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 1. WebSocket Broadcaster
root_logger.addHandler(log_broadcaster)

# 2. Local File Logger for the web session
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
root_logger.addHandler(file_handler)

# 3. Console Output
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
root_logger.addHandler(console_handler)

logging.info(f"📝 Logging session to {log_file}")

settings_manager = SettingsManager()

app = FastAPI(title="Media Metadata Scraper API")

@app.on_event("startup")
async def startup_event():
    # Set the loop for the log broadcaster so it can send logs to WebSockets
    log_broadcaster.set_loop(asyncio.get_running_loop())
    logging.info("🚀 Server started, log broadcaster ready.")

# Allow CORS for frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---
class TaskStartRequest(BaseModel):
    input_dir: str
    dry_run: bool = True
    inplace: bool = False
    copy_mode: bool = False
    output_dir: Optional[str] = None
    use_local_nfo: bool = False
    extra_images: bool = False
    workers: int = 4
    media_type: Optional[str] = None
    tmdb_id: Optional[int] = None
    search_mode: str = "smart" # smart, tmdb_only
    enable_fallback: bool = True
    multi_mode: Optional[bool] = None  # None = Auto-detect

class FileSystemNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    children: Optional[List['FileSystemNode']] = None

# --- Events ---
@app.on_event("startup")
async def startup_event():
    # Pass the running loop to the logger so it can schedule broadcasts
    loop = asyncio.get_running_loop()
    log_broadcaster.set_loop(loop)

# --- Endpoints ---

@app.get("/api/status")
async def get_status():
    from src.server.stats_manager import stats_manager
    return {
        "running": job_manager.is_running,
        "workers": job_manager.executor._max_workers,
        "stats": stats_manager.get_summary()
    }

@app.get("/api/filesystem")
def browse_filesystem(path: str = "."):
    """
    Simple file browser to select directories.
    Defaults to current directory.
    """
    try:
        p = Path(path).resolve()
        if not p.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        
        # Parent nav
        parent = p.parent
        
        items = []
        # Add parent directory entry
        if p != p.parent:
            items.append({
                "name": "..",
                "path": str(parent),
                "is_dir": True,
                "has_children": True
            })

        for entry in os.scandir(p):
            # Only show directories for now as we scan folders
            if entry.is_dir() and not entry.name.startswith('.'):
                 items.append({
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": True,
                    "has_children": True # Simplified
                })
        
        # Sort by name
        items.sort(key=lambda x: x["name"])
        
        return {
            "current": str(p),
            "items": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tasks/start")
async def start_task(req: TaskStartRequest):
    if job_manager.is_running:
         raise HTTPException(status_code=400, detail="Task already running")
    
    # Fire and forget (task runs in background)
    asyncio.create_task(job_manager.start_batch_scan(
        input_dir=req.input_dir,
        dry_run=req.dry_run,
        inplace=req.inplace,
        workers=req.workers,
        copy=req.copy_mode,
        output_dir=req.output_dir,
        use_local_nfo=req.use_local_nfo,
        extra_images=req.extra_images,
        media_type=req.media_type,
        tmdb_id=req.tmdb_id,
        search_mode=req.search_mode,
        enable_fallback=req.enable_fallback,
        multi_mode=req.multi_mode
    ))
    
    return {"status": "started", "message": f"Scanning {req.input_dir}"}

@app.post("/api/tasks/stop")
async def stop_task():
    job_manager.stop_task()
    return {"status": "stopping", "message": "Stop signal sent (best effort)"}

@app.get("/api/test_connectivity")
async def test_connectivity():
    import requests
    results = {}
    config = settings_manager.get_effective_config()
    proxies = None
    if config.get("proxy"):
        p = config["proxy"]
        proxies = {"http": p, "https": p}
    
    # Test TMDB
    try:
        r = await asyncio.to_thread(requests.get, "https://api.themoviedb.org/3/status", proxies=proxies, timeout=5)
        results["tmdb"] = {"status": "ok" if r.ok else "failed", "code": r.status_code}
    except Exception as e:
        results["tmdb"] = {"status": "error", "message": str(e)}

    # Test Google
    try:
        r = await asyncio.to_thread(requests.get, "https://www.google.com", proxies=proxies, timeout=5)
        results["google"] = {"status": "ok" if r.ok else "failed", "code": r.status_code}
    except Exception as e:
        results["google"] = {"status": "error", "message": str(e)}
        
    return results

@app.get("/api/settings")
async def get_settings():
    return settings_manager.get_settings()

@app.post("/api/settings")
async def save_settings(settings: dict):
    # Basic validation could go here
    if settings_manager.save_settings(settings):
        return {"status": "saved", "config": settings}
    else:
        raise HTTPException(status_code=500, detail="Failed to save settings")

# --- WebSocket ---
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    queue = await log_broadcaster.subscribe()
    
    try:
        while True:
            # Wait for log message
            message = await queue.get()
            await websocket.send_text(message)
    except WebSocketDisconnect:
        log_broadcaster.unsubscribe(queue)
