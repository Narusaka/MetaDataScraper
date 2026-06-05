
import os
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Literal
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path

# Import our customized modules
from src.server.logger_handler import log_broadcaster
from src.server.task_events import task_event_store
from src.server.job_manager import job_manager
from src.server.settings_manager import SettingsManager, SettingsValidationError

def _has_handler(root_logger: logging.Logger, marker: str) -> bool:
    return any(getattr(handler, marker, False) for handler in root_logger.handlers)


def configure_logging() -> Path:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"web_session_{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not _has_handler(root_logger, "_metadata_scraper_ws"):
        log_broadcaster._metadata_scraper_ws = True
        root_logger.addHandler(log_broadcaster)

    if not _has_handler(root_logger, "_metadata_scraper_file"):
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            file_handler._metadata_scraper_file = True
            root_logger.addHandler(file_handler)
        except OSError:
            print("⚠️ Server Log File creation failed (Disk Full likely). Continuing without file logs.")

    if not _has_handler(root_logger, "_metadata_scraper_console"):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        console_handler._metadata_scraper_console = True
        root_logger.addHandler(console_handler)

    logging.info(f"📝 Logging session to {log_file}")
    return log_file


configure_logging()

settings_manager = SettingsManager()

async def run_startup_maintenance():
    loop = asyncio.get_running_loop()
    log_broadcaster.set_loop(loop)
    task_event_store.set_loop(loop)

    try:
        logging.info("🧹 Performing System Cleanup...")
        from src.core.cache import CacheManager

        cm = CacheManager()
        cleared = cm.clear_expired(48)
        logging.info(f"   - Cleared {cleared} expired cache files.")

        log_path = Path("logs")
        if log_path.exists():
            import time

            now = time.time()
            cutoff = now - (7 * 86400)
            deleted_logs = 0
            for f in log_path.iterdir():
                if f.is_file() and f.suffix == ".log" and f.stat().st_mtime < cutoff:
                    try:
                        f.unlink()
                        deleted_logs += 1
                    except OSError:
                        logging.warning(f"Could not delete old log file: {f}")
            logging.info(f"   - Deleted {deleted_logs} old log files.")
        task_event_store.compact()
        logging.info("   - Compacted task event ledger.")
    except Exception as e:
        logging.error(f"Cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_startup_maintenance()
    yield


app = FastAPI(title="Media Metadata Scraper API", lifespan=lifespan)

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
    input_dir: str = Field(min_length=1)
    dry_run: bool = True
    inplace: bool = False
    copy_mode: bool = False
    output_dir: Optional[str] = None
    use_local_nfo: bool = False
    extra_images: bool = False
    workers: int = Field(default=4, ge=1, le=16)
    media_type: Optional[Literal["movie", "tv"]] = None
    tmdb_id: Optional[int] = Field(default=None, ge=0)
    search_mode: Literal["smart", "tmdb_only", "tavily_only"] = "smart"
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

# --- Endpoints ---

def _task_config_from_request(req: TaskStartRequest, tmdb_id: Optional[int]) -> dict:
    if req.copy_mode:
        strategy = "copy"
    elif req.dry_run:
        strategy = "audit"
    else:
        strategy = "organize" if req.inplace else "metadata"

    return {
        "dry_run": req.dry_run,
        "strategy": strategy,
        "workers": req.workers,
        "media_type": req.media_type,
        "tmdb_id": tmdb_id,
        "search_mode": req.search_mode,
        "multi_mode": req.multi_mode,
        "inplace": req.inplace,
        "copy_mode": req.copy_mode,
        "output_dir": req.output_dir,
        "use_local_nfo": req.use_local_nfo,
        "extra_images": req.extra_images,
        "fresh": req.fresh,
        "enable_fallback": req.enable_fallback,
        "enable_organize": req.enable_organize,
        "overwrite_images": req.overwrite_images,
        "rename_parent_dir": req.rename_parent_dir,
    }

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
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    try:
        entries = list(os.scandir(p))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    parent = p.parent
    items = []
    if p != p.parent:
        items.append({
            "name": "..",
            "path": str(parent),
            "is_dir": True,
            "has_children": True
        })

    for entry in entries:
        if entry.is_dir() and not entry.name.startswith('.'):
            items.append({
                "name": entry.name,
                "path": entry.path,
                "is_dir": True,
                "has_children": True
            })

    items.sort(key=lambda x: x["name"])

    return {
        "current": str(p),
        "items": items
    }

@app.get("/api/fs/check")
async def check_path(path: str):
    logging.info(f"🔍 Path check request: {path}")
    checked_path = Path(path).expanduser()
    return {
        "exists": checked_path.exists(),
        "is_dir": checked_path.is_dir(),
        "path": str(checked_path.resolve()) if checked_path.exists() else str(checked_path),
    }

@app.post("/api/tasks/start")
async def start_task(req: TaskStartRequest):
    input_path = Path(req.input_dir).expanduser()
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input path not found: {req.input_dir}")
    if req.copy_mode and not req.output_dir:
        raise HTTPException(status_code=400, detail="Output path is required for copy mode")
    if req.copy_mode and Path(req.output_dir).expanduser() == input_path:
        raise HTTPException(status_code=400, detail="Output path must be different from input path")

    tmdb_id = req.tmdb_id or None

    if not job_manager.reserve_start():
        raise HTTPException(status_code=400, detail="Task already running")

    try:
        task = task_event_store.create_task(
            req.input_dir,
            _task_config_from_request(req, tmdb_id),
        )
    except Exception:
        job_manager.release_reservation()
        raise
    
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
        tmdb_id=tmdb_id,
        search_mode=req.search_mode,
        enable_fallback=req.enable_fallback,
        multi_mode=req.multi_mode,
        fresh=req.fresh,
        enable_organize=req.enable_organize,
        overwrite_images=req.overwrite_images,
        rename_parent_dir=req.rename_parent_dir,
        task_id=task["id"],
        reserved=True
    ))
    
    return {"status": "started", "task_id": task["id"], "message": f"Scanning {req.input_dir}"}

@app.get("/api/tasks")
async def list_tasks():
    return {"tasks": task_event_store.list_tasks()}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

def _read_task_plan_artifact(task_id: str, item_id: str, store=None):
    store = store or task_event_store
    try:
        return store.read_plan_artifact(task_id, item_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read plan artifact: {exc}")

@app.get("/api/tasks/{task_id}/plan")
async def get_task_plan(task_id: str, item_id: str):
    return _read_task_plan_artifact(task_id, item_id)

@app.get("/api/tasks/{task_id}/manifest")
async def get_task_manifest(task_id: str):
    from src.core.operation_manifest import get_manifest

    manifest = get_manifest(task_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return manifest

@app.post("/api/tasks/{task_id}/rollback")
async def rollback_task(task_id: str):
    from src.core.operation_manifest import rollback_manifest

    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in {"created", "running"}:
        raise HTTPException(status_code=409, detail="Task is still running")

    result = rollback_manifest(task_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Manifest not found")
    task_event_store.emit(task_id, "task.rollback_completed", result)
    return result

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
        request_kwargs = {"proxies": proxies, "timeout": 5}
        if api_key and api_key.startswith("eyJ") and api_key.count(".") == 2:
            request_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        else:
            request_kwargs["params"] = {"api_key": api_key}
        r = await asyncio.to_thread(requests.get, "https://api.themoviedb.org/3/configuration", **request_kwargs)
        results["tmdb"] = {"status": "ok" if r.ok else "failed", "code": r.status_code}
        if not r.ok:
             try: results["tmdb"]["message"] = r.json().get("status_message", "Unknown error")
             except: results["tmdb"]["message"] = r.text
    except Exception as e:
        results["tmdb"] = {"status": "error", "message": str(e)}

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
    try:
        if settings_manager.save_settings(settings):
            return {"status": "saved", "config": settings_manager.get_settings()}
    except SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=500, detail="Failed to save settings")

# --- WebSocket ---
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    queue = await log_broadcaster.subscribe()

    try:
        while True:
            message = await queue.get()
            await websocket.send_text(message)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        log_broadcaster.unsubscribe(queue)

@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    queue = await task_event_store.subscribe()

    try:
        import json
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event, ensure_ascii=False))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        task_event_store.unsubscribe(queue)
