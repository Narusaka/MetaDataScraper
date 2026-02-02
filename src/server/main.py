
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
try:
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(file_handler)
except OSError:
    print(f"⚠️ Server Log File creation failed (Disk Full likely). Continuing without file logs.")

# 3. Console Output
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
root_logger.addHandler(console_handler)

logging.info(f"📝 Logging session to {log_file}")

settings_manager = SettingsManager()

app = FastAPI(title="Media Metadata Scraper API")

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
    fresh: bool = False # If True, overwrite existing metadata. If False, skip if exists.
    enable_organize: bool = False # If True, allow moving/renaming files.
    overwrite_images: bool = False # If True, redownload images even if exist.
    rename_parent_dir: bool = False # If True, rename parent directory to Title (Year).

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
    
    # --- System Cleanup ---
    try:
        logging.info("🧹 Performing System Cleanup...")
        # Clean Cache
        from src.core.cache import CacheManager
        cm = CacheManager()
        cleared = cm.clear_expired(48) # 48 hours
        logging.info(f"   - Cleared {cleared} expired cache files.")
        
        # Clean Logs
        log_path = Path("logs")
        if log_path.exists():
             import time
             now = time.time()
             cutoff = now - (7 * 86400) # 7 days
             deleted_logs = 0
             for f in log_path.iterdir():
                 if f.is_file() and f.suffix == ".log" and f.stat().st_mtime < cutoff:
                     try:
                        f.unlink()
                        deleted_logs += 1
                     except: pass
             logging.info(f"   - Deleted {deleted_logs} old log files.")
    except Exception as e:
        logging.error(f"Cleanup failed: {e}")

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

@app.get("/api/fs/check")
async def check_path(path: str):
    logging.info(f"🔍 Path check request: {path}")
    return {"exists": os.path.exists(path), "path": path}

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
        multi_mode=req.multi_mode,
        fresh=req.fresh,
        enable_organize=req.enable_organize,
        overwrite_images=req.overwrite_images,
        rename_parent_dir=req.rename_parent_dir
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
        if isinstance(p, dict):
             proxies = p
        else:
             proxies = {"http": p, "https": p}
    
    # Test TMDB
    try:
        api_key = config.get("tmdb", {}).get("api_key")
        r = await asyncio.to_thread(requests.get, f"https://api.themoviedb.org/3/configuration?api_key={api_key}", proxies=proxies, timeout=5)
        results["tmdb"] = {"status": "ok" if r.ok else "failed", "code": r.status_code}
        if not r.ok:
             try: results["tmdb"]["message"] = r.json().get("status_message", "Unknown error")
             except: results["tmdb"]["message"] = r.text
    except Exception as e:
        results["tmdb"] = {"status": "error", "message": str(e)}

    # Test Google
    try:
        r = await asyncio.to_thread(requests.get, "https://www.google.com", proxies=proxies, timeout=5)
        results["google"] = {"status": "ok" if r.ok else "failed", "code": r.status_code}
    except Exception as e:
        results["google"] = {"status": "error", "message": str(e)}

    # Test Tavily
    try:
        # Collect all potential keys
        t_keys = []
        if config.get("tavily", {}).get("api_key"): t_keys.append(config.get("tavily", {}).get("api_key"))
        if os.getenv("TAVILY_API_KEY"): t_keys.append(os.getenv("TAVILY_API_KEY"))
        if os.getenv("TAVILY_API_KEY_2"): t_keys.append(os.getenv("TAVILY_API_KEY_2"))
        if os.getenv("TAVILY_API_KEY_3"): t_keys.append(os.getenv("TAVILY_API_KEY_3"))
        
        # Deduplicate
        t_keys = list(set([k for k in t_keys if k]))
        
        if t_keys:
            any_valid = False
            last_error = "Unknown"
            
            for key in t_keys:
                try:
                    payload = {"api_key": key, "query": "test", "max_results": 1}
                    r = await asyncio.to_thread(requests.post, "https://api.tavily.com/search", json=payload, proxies=proxies, timeout=5)
                    if r.status_code == 200:
                        any_valid = True
                        break # Found a working key
                    else:
                        try: last_error = r.json().get("detail", {}).get("error", r.text)
                        except: last_error = f"Status {r.status_code}"
                except Exception as ex:
                    last_error = str(ex)
            
            if any_valid:
                results["tavily"] = {"status": "ok", "code": 200}
            else:
                results["tavily"] = {"status": "failed", "message": f"All {len(t_keys)} keys failed. Last error: {last_error}"}
        else:
            results["tavily"] = {"status": "skipped", "message": "No API Keys found"}
            
    except Exception as e:
        results["tavily"] = {"status": "error", "message": str(e)}
        
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
