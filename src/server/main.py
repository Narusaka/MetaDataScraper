
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
from src.server.settings_manager import SettingsConflictError, SettingsManager, SettingsValidationError
from src.server.access_control import TrustedOriginMiddleware, TrustedOriginPolicy
from src.storage.match_memory import match_memory_store
from src.services.library_scan import LibraryScanService

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
        reconciliation = task_event_store.reconcile_interrupted_tasks()
        if reconciliation["count"]:
            logging.warning(
                "Reconciled %s task(s) interrupted by the previous process.",
                reconciliation["count"],
            )
    except Exception as exc:
        logging.error("Task restart reconciliation failed: %s", exc)

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

trusted_origin_policy = TrustedOriginPolicy.from_environment()

app.add_middleware(
    CORSMiddleware,
    allow_origins=trusted_origin_policy.cors_origins,
    allow_origin_regex=trusted_origin_policy.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(
    TrustedOriginMiddleware,
    policy=trusted_origin_policy,
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
    conflict_strategy: Optional[Literal["error", "skip", "suffix", "overwrite"]] = None
    operation_scope: Literal["full", "nfo_only", "artwork_only", "organize_only"] = "full"
    intended_strategy: Optional[Literal["audit", "organize", "copy"]] = None

class MatchReviewResolutionRequest(BaseModel):
    item_id: str = Field(min_length=1)
    action: Literal["audit", "execute", "ignored", "rejected"]
    tmdb_id: Optional[int] = Field(default=None, gt=0)
    media_type: Optional[Literal["movie", "tv"]] = None

class PlanExecuteRequest(BaseModel):
    item_id: str = Field(min_length=1)
    plan_digest: str = Field(min_length=64, max_length=64)

class LibraryScanRequest(BaseModel):
    path: str = Field(min_length=1)
    mode: Literal["auto", "single", "batch"] = "auto"
    use_local_nfo: bool = True

class FileSystemNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    children: Optional[List['FileSystemNode']] = None

# --- Endpoints ---

def _task_config_from_request(
    req: TaskStartRequest,
    tmdb_id: Optional[int],
    runtime_config: Optional[dict] = None,
) -> dict:
    if req.intended_strategy:
        strategy = req.intended_strategy
    elif req.copy_mode:
        strategy = "copy"
    elif req.inplace:
        strategy = "organize"
    elif req.dry_run:
        strategy = "audit"
    else:
        strategy = "metadata"

    scope_allows_organize = req.operation_scope in {"full", "organize_only"}
    scope_allows_artwork = req.operation_scope in {"full", "artwork_only"}
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
        "extra_images": req.extra_images and scope_allows_artwork,
        "fresh": req.fresh,
        "enable_fallback": req.enable_fallback,
        "enable_organize": req.enable_organize and scope_allows_organize,
        "overwrite_images": req.overwrite_images and scope_allows_artwork,
        "rename_parent_dir": req.rename_parent_dir and scope_allows_organize,
        "conflict_strategy": req.conflict_strategy or (runtime_config or settings_manager.get_effective_config()).get("output", {}).get("conflict_strategy", "error"),
        "operation_scope": req.operation_scope,
    }

@app.get("/api/status")
async def get_status():
    from src.server.stats_manager import stats_manager
    executor = getattr(job_manager, "executor", None)
    return {
        "running": job_manager.is_running,
        "workers": getattr(executor, "_max_workers", 1),
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

@app.post("/api/library/scan")
async def scan_library(req: LibraryScanRequest):
    root = Path(req.path).expanduser()
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    try:
        return await asyncio.to_thread(
            LibraryScanService().scan,
            root,
            req.mode,
            req.use_local_nfo,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

async def _start_task(
    req: TaskStartRequest,
    *,
    task_context: Optional[dict] = None,
    expected_plan_digest: Optional[str] = None,
    expected_settings_fingerprint: Optional[str] = None,
):
    input_path = Path(req.input_dir).expanduser()
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input path not found: {req.input_dir}")
    if req.copy_mode and not req.output_dir:
        raise HTTPException(status_code=400, detail="Output path is required for copy mode")
    if req.copy_mode:
        output_path = Path(req.output_dir).expanduser()
        if output_path == input_path:
            raise HTTPException(status_code=400, detail="Output path must be different from input path")
        if output_path.exists() and not output_path.is_dir():
            raise HTTPException(status_code=400, detail="Output path is not a directory")
        output_parent = output_path if output_path.exists() else output_path.parent
        if not output_parent.exists() or not output_parent.is_dir():
            raise HTTPException(status_code=400, detail="Output parent directory does not exist")
        if not os.access(output_parent, os.W_OK):
            raise HTTPException(status_code=403, detail="Output directory is not writable")

    runtime_context = settings_manager.get_runtime_context()
    if (
        expected_settings_fingerprint
        and runtime_context["fingerprint"] != expected_settings_fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Settings changed after audit; generate a new locked plan",
                "code": "SETTINGS_DRIFT",
                "expected_settings_fingerprint": expected_settings_fingerprint,
                "current_settings_fingerprint": runtime_context["fingerprint"],
            },
        )

    tmdb_id = req.tmdb_id or None
    effective_config = _task_config_from_request(req, tmdb_id, runtime_context["config"])
    effective_config.update({
        "settings_revision": runtime_context["revision"],
        "settings_fingerprint": runtime_context["fingerprint"],
    })
    if task_context:
        effective_config.update(task_context)

    if not job_manager.reserve_start():
        raise HTTPException(status_code=400, detail="Task already running")

    try:
        task = task_event_store.create_task(
            req.input_dir,
            effective_config,
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
        extra_images=effective_config["extra_images"],
        media_type=req.media_type,
        tmdb_id=tmdb_id,
        search_mode=req.search_mode,
        enable_fallback=req.enable_fallback,
        multi_mode=req.multi_mode,
        fresh=req.fresh,
        enable_organize=effective_config["enable_organize"],
        overwrite_images=effective_config["overwrite_images"],
        rename_parent_dir=effective_config["rename_parent_dir"],
        conflict_strategy=req.conflict_strategy,
        operation_scope=req.operation_scope,
        expected_plan_digest=expected_plan_digest,
        runtime_config=runtime_context["config"],
        task_id=task["id"],
        reserved=True
    ))
    
    return {"status": "started", "task_id": task["id"], "message": f"Scanning {req.input_dir}"}

@app.post("/api/tasks/start")
async def start_task(req: TaskStartRequest):
    if not req.dry_run:
        raise HTTPException(
            status_code=409,
            detail="Direct execution is disabled. Generate a plan and confirm that locked plan.",
        )
    return await _start_task(req)

@app.post("/api/tasks/plan")
async def plan_task(req: TaskStartRequest):
    if req.operation_scope == "organize_only" and req.intended_strategy == "audit":
        raise HTTPException(status_code=400, detail="Files-only scope requires organize or copy strategy")
    if req.operation_scope in {"nfo_only", "artwork_only"} and req.intended_strategy in {"organize", "copy"}:
        raise HTTPException(status_code=400, detail="NFO-only and artwork-only scopes require metadata strategy")
    payload = req.model_dump()
    payload["dry_run"] = True
    strategy = req.intended_strategy
    if strategy == "copy":
        payload["copy_mode"] = True
        payload["inplace"] = False
        payload["enable_organize"] = True
    elif strategy == "organize":
        payload["copy_mode"] = False
        payload["inplace"] = True
        payload["enable_organize"] = True
    elif strategy == "audit":
        payload["copy_mode"] = False
        payload["inplace"] = False
    planned_request = TaskStartRequest(**payload)
    result = await _start_task(planned_request)
    return {
        **result,
        "status": "planning",
        "strategy": _task_config_from_request(planned_request, planned_request.tmdb_id or None)["strategy"],
        "message": f"Generating a locked plan for {planned_request.input_dir}",
    }

@app.get("/api/tasks")
async def list_tasks(compact: bool = False):
    return {"tasks": task_event_store.list_tasks(compact=compact)}

def _match_review_records():
    reviews = []
    for task in task_event_store.list_tasks(compact=True):
        for item_id, item in (task.get("items") or {}).items():
            if not isinstance(item, dict):
                continue
            match = item.get("match") if isinstance(item.get("match"), dict) else {}
            review = item.get("review") if isinstance(item.get("review"), dict) else {}
            if review.get("status") == "resolved":
                continue
            confidence = str(match.get("confidence") or "").lower()
            review_required = bool(match.get("review_required")) or confidence in {"none", "low"}
            match_failure = item.get("error_code") == "MATCH_REVIEW_REQUIRED"
            if not review_required and not match_failure:
                continue
            reviews.append(
                {
                    "task_id": task.get("id"),
                    "task_status": task.get("status"),
                    "task_config": task.get("config") or {},
                    "item_id": item_id,
                    "item": item,
                }
            )
    reviews.sort(
        key=lambda review: (review.get("item") or {}).get("updated_at")
        or (review.get("item") or {}).get("created_at")
        or "",
        reverse=True,
    )
    return reviews

@app.get("/api/matches/review")
async def list_match_reviews():
    return {"reviews": _match_review_records()}

@app.post("/api/matches/review/{task_id}/resolve")
async def resolve_match_review(task_id: str, req: MatchReviewResolutionRequest):
    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    item = (task.get("items") or {}).get(req.item_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Task item not found")

    match = item.get("match") if isinstance(item.get("match"), dict) else {}
    confidence = str(match.get("confidence") or "").lower()
    is_reviewable = (
        bool(match.get("review_required"))
        or confidence in {"none", "low"}
        or item.get("error_code") == "MATCH_REVIEW_REQUIRED"
    )
    if not is_reviewable:
        raise HTTPException(status_code=409, detail="Task item does not require match review")
    if req.action != "ignored" and (req.tmdb_id is None or req.media_type is None):
        raise HTTPException(status_code=422, detail="TMDB ID and media type are required for this resolution")

    remembered_match = None
    rejected_match = None
    title = str(item.get("query") or item.get("name") or Path(req.item_id).name).strip()
    match_year = match.get("target_year")
    if not match_year:
        import re
        year_match = re.search(r"\((\d{4})\)", Path(req.item_id).name)
        match_year = int(year_match.group(1)) if year_match else None
    if req.action in {"audit", "execute"}:
        remembered_match = match_memory_store.remember(
            title=title,
            year=match_year,
            tmdb_id=req.tmdb_id,
            media_type=req.media_type,
            source_task_id=task_id,
            source_item_id=req.item_id,
        )
    elif req.action == "rejected":
        rejected_match = match_memory_store.reject(
            title=title,
            year=match_year,
            tmdb_id=req.tmdb_id,
            media_type=req.media_type,
            source_task_id=task_id,
            source_item_id=req.item_id,
        )

    event = task_event_store.emit(
        task_id,
        "item.review_resolved",
        {
            "action": req.action,
            "tmdb_id": req.tmdb_id,
            "media_type": req.media_type,
            "memory_id": remembered_match.get("id") if remembered_match else None,
            "rejection_id": rejected_match.get("id") if rejected_match else None,
        },
        item_id=req.item_id,
    )
    if not event:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "resolved", "task_id": task_id, "item_id": req.item_id, "review": event["payload"]}

@app.get("/api/matches/memory")
async def list_match_memory():
    return {"matches": match_memory_store.list_matches()}

@app.delete("/api/matches/memory/{match_id}")
async def delete_match_memory(match_id: int):
    if not match_memory_store.delete(match_id):
        raise HTTPException(status_code=404, detail="Saved match not found")
    return {"status": "deleted", "id": match_id}

@app.get("/api/matches/rejections")
async def list_match_rejections():
    return {"rejections": match_memory_store.list_rejections()}

@app.delete("/api/matches/rejections/{rejection_id}")
async def delete_match_rejection(rejection_id: int):
    if not match_memory_store.delete_rejection(rejection_id):
        raise HTTPException(status_code=404, detail="Rejected match not found")
    return {"status": "deleted", "id": rejection_id}

def _task_history_records():
    from src.core.operation_manifest import get_manifest, summarize_manifest

    finished_statuses = {
        "completed",
        "partial",
        "failed",
        "stopped",
        "cancelled",
        "interrupted",
    }
    history = []
    for task in task_event_store.list_tasks(compact=True):
        if task.get("status") not in finished_statuses:
            continue
        task_id = task.get("id")
        try:
            manifest = summarize_manifest(get_manifest(task_id)) if task_id else summarize_manifest(None)
        except (OSError, ValueError, TypeError) as exc:
            logging.warning("Failed to read manifest summary for task %s: %s", task_id, exc)
            manifest = summarize_manifest(None)
            manifest["error"] = str(exc)
        rollback_status = (task.get("rollback") or {}).get("status")
        task["manifest_summary"] = manifest
        task["rolled_back"] = rollback_status == "completed"
        task["rollback_available"] = manifest["reversible_count"] > 0 and rollback_status != "completed"
        history.append(task)
    return history

@app.get("/api/tasks/history")
async def list_task_history():
    return {"tasks": _task_history_records()}

def _history_cleanup_protection():
    protected = {}

    def protect(task_id, reason):
        if not task_id:
            return
        reasons = protected.setdefault(str(task_id), [])
        if reason not in reasons:
            reasons.append(reason)

    for review in _match_review_records():
        protect(review.get("task_id"), "match_review")
    for review in _plan_review_records_with_preflight():
        protect(review.get("task_id"), "plan_review")
    for task in _task_history_records():
        task_id = task.get("id")
        rollback_status = (task.get("rollback") or {}).get("status")
        if task.get("rollback_available"):
            protect(task_id, "rollback_available")
        if rollback_status in {"running", "partial", "failed"}:
            protect(task_id, "rollback_incomplete")
        if task.get("status") == "interrupted":
            protect(task_id, "recovery_available")

    return protected

@app.get("/api/tasks/history/cleanup-preview")
async def preview_completed_task_history_clear():
    return task_event_store.preview_finished_task_clear(
        _history_cleanup_protection(),
    )

@app.delete("/api/tasks/history/completed")
async def clear_completed_task_history():
    if job_manager.is_running:
        raise HTTPException(status_code=409, detail="Cannot clear task history while a task is running")
    return task_event_store.clear_finished_tasks(
        _history_cleanup_protection(),
    )

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

def _plan_review_records_with_preflight():
    from src.core.execution_preflight import assess_execution_preflight
    from src.core.plan_integrity import PlanIntegrityError

    plans = task_event_store.list_plan_reviews()
    current_settings = settings_manager.get_runtime_context()
    for record in plans:
        task_config = record.get("task_config") if isinstance(record.get("task_config"), dict) else {}
        audited_fingerprint = task_config.get("settings_fingerprint")
        if audited_fingerprint and audited_fingerprint != current_settings["fingerprint"]:
            record["review_status"] = "drifted"
            record["settings_drift"] = {
                "expected_revision": task_config.get("settings_revision"),
                "current_revision": current_settings["revision"],
                "expected_fingerprint": audited_fingerprint,
                "current_fingerprint": current_settings["fingerprint"],
            }
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        plan = item.get("plan") if isinstance(item.get("plan"), dict) else {}
        artifact_error = None
        try:
            artifact = task_event_store.read_plan_artifact(record["task_id"], record["item_id"])
            preflight_plan = artifact.get("plan") if isinstance(artifact.get("plan"), dict) else plan
            record["artifact_integrity"] = {
                "status": "verified",
                "version": artifact.get("version"),
                "artifact_digest": artifact.get("artifact_digest"),
            }
        except PlanIntegrityError as exc:
            preflight_plan = dict(plan)
            artifact_error = {
                "status": "invalid",
                "code": "PLAN_ARTIFACT_INVALID",
                "message": str(exc),
            }
        except (KeyError, FileNotFoundError, PermissionError) as exc:
            preflight_plan = dict(plan)
            artifact_error = {
                "status": "missing",
                "code": "PLAN_ARTIFACT_MISSING",
                "message": str(exc),
            }
        preflight_plan.setdefault("source_path", item.get("path") or record.get("item_id"))
        preflight_plan.setdefault("target_root", preflight_plan.get("source_path"))
        preflight = assess_execution_preflight(preflight_plan)
        if artifact_error:
            record["artifact_integrity"] = artifact_error
            preflight["checks"].insert(0, {
                "code": artifact_error["code"],
                "status": "blocked",
                "message": artifact_error["message"],
            })
            preflight["blocked"] = int(preflight.get("blocked") or 0) + 1
            preflight["status"] = "blocked"
        plan["preflight"] = preflight
        if preflight["status"] == "blocked" and record.get("review_status") == "ready":
            record["review_status"] = "blocked"
    return plans


@app.get("/api/plans/review")
async def get_plan_reviews():
    return {"plans": _plan_review_records_with_preflight()}

@app.get("/api/executions")
async def get_executions(limit: int = 50):
    return {"executions": task_event_store.list_executions(limit=limit)}

@app.get("/api/dashboard/summary")
async def get_dashboard_summary():
    from src.server.stats_manager import stats_manager

    def configured_secret(value):
        return bool(value and str(value).strip() not in {"EMPTY", "__KEEP_EXISTING__"})

    def compact_recent(task):
        return {
            key: task.get(key)
            for key in (
                "id",
                "input_dir",
                "status",
                "created_at",
                "updated_at",
                "summary",
                "rollback_available",
                "rolled_back",
            )
            if key in task
        }

    match_reviews = _match_review_records()
    plan_reviews = _plan_review_records_with_preflight()
    executions = task_event_store.list_executions(limit=50)
    history = _task_history_records()
    config = settings_manager.get_effective_config()
    plan_counts = {
        status: sum(1 for plan in plan_reviews if plan.get("review_status") == status)
        for status in ("ready", "blocked", "drifted")
    }
    execution_counts = {
        "running": sum(1 for task in executions if task.get("status") in {"created", "running", "cancel_requested"}),
        "issues": sum(
            1
            for task in executions
            if task.get("status") in {
                "failed",
                "partial",
                "stopped",
                "cancelled",
                "interrupted",
            }
        ),
    }
    history_counts = {
        "finished": len(history),
        "failed": sum(
            1
            for task in history
            if task.get("status") in {
                "failed",
                "partial",
                "stopped",
                "interrupted",
            }
        ),
        "rollback_ready": sum(1 for task in history if task.get("rollback_available")),
    }
    executor = getattr(job_manager, "executor", None)
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "worker": {
            "running": job_manager.is_running,
            "active_task_id": job_manager.active_task_id,
            "workers": getattr(executor, "_max_workers", 1),
        },
        "queues": {
            "match_reviews": len(match_reviews),
            "plan_reviews": {"total": len(plan_reviews), **plan_counts},
            "executions": {"total": len(executions), **execution_counts},
            "history": history_counts,
        },
        "services": {
            "tmdb": {"configured": configured_secret((config.get("tmdb") or {}).get("api_key"))},
            "tavily": {
                "configured": bool(
                    configured_secret((config.get("tavily") or {}).get("api_key"))
                    or (config.get("tavily") or {}).get("api_keys")
                )
            },
            "model": {"configured": configured_secret((config.get("model") or {}).get("api_key"))},
        },
        "stats": stats_manager.get_summary(),
        "recent": [compact_recent(task) for task in history[:5]],
    }

def _read_task_plan_artifact(task_id: str, item_id: str, store=None):
    from src.core.plan_integrity import PlanIntegrityError

    store = store or task_event_store
    try:
        return store.read_plan_artifact(task_id, item_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PlanIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PLAN_ARTIFACT_INVALID",
                "message": str(exc),
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read plan artifact: {exc}")

@app.get("/api/tasks/{task_id}/plan")
async def get_task_plan(task_id: str, item_id: str):
    return _read_task_plan_artifact(task_id, item_id)

@app.post("/api/tasks/{task_id}/execute")
async def execute_task_plan(task_id: str, req: PlanExecuteRequest):
    from src.core.execution_preflight import assess_execution_preflight
    from src.core.plan_integrity import detect_plan_drift

    source_task = task_event_store.get_task(task_id)
    if not source_task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not bool((source_task.get("config") or {}).get("dry_run")):
        raise HTTPException(status_code=409, detail="Only audited tasks can be confirmed for execution")

    item = (source_task.get("items") or {}).get(req.item_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Task item not found")
    if item.get("status") != "audit_completed":
        raise HTTPException(status_code=409, detail="Task item is not awaiting execution confirmation")

    artifact = _read_task_plan_artifact(task_id, req.item_id)
    stored_digest = artifact.get("plan_digest")
    if not stored_digest or stored_digest != req.plan_digest:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Plan confirmation is stale",
                "expected_plan_digest": stored_digest,
                "received_plan_digest": req.plan_digest,
            },
        )

    plan = artifact.get("plan") or {}
    summary = plan.get("summary") or {}
    if int(summary.get("conflicts") or 0) > 0 or int(summary.get("blocked") or 0) > 0:
        raise HTTPException(status_code=409, detail="Execution plan contains blockers")

    drift = detect_plan_drift(artifact.get("baseline") or [])
    if drift:
        task_event_store.emit(
            task_id,
            "item.plan_drifted",
            {"plan_digest": stored_digest, "drift": drift},
            item_id=req.item_id,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Filesystem changed after audit; run a new audit",
                "code": "PLAN_DRIFT",
                "drift": drift,
            },
        )

    preflight = assess_execution_preflight(plan)
    if preflight["status"] == "blocked":
        task_event_store.emit(
            task_id,
            "item.preflight_failed",
            {"plan_digest": stored_digest, "preflight": preflight},
            item_id=req.item_id,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Execution preflight failed",
                "code": "EXECUTION_PREFLIGHT_FAILED",
                "preflight": preflight,
            },
        )

    config = source_task.get("config") or {}
    audited_settings_fingerprint = config.get("settings_fingerprint")
    current_settings = settings_manager.get_runtime_context()
    if (
        audited_settings_fingerprint
        and audited_settings_fingerprint != current_settings["fingerprint"]
    ):
        task_event_store.emit(
            task_id,
            "item.settings_drifted",
            {
                "expected_revision": config.get("settings_revision"),
                "current_revision": current_settings["revision"],
                "expected_settings_fingerprint": audited_settings_fingerprint,
                "current_settings_fingerprint": current_settings["fingerprint"],
            },
            item_id=req.item_id,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Settings changed after audit; generate a new locked plan",
                "code": "SETTINGS_DRIFT",
                "expected_revision": config.get("settings_revision"),
                "current_revision": current_settings["revision"],
            },
        )
    candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
    tmdb_id = candidate.get("tmdb_id") or item.get("tmdb_id") or config.get("tmdb_id")
    media_type = candidate.get("media_type") or item.get("media_type") or config.get("media_type")
    execution_request = TaskStartRequest(
        input_dir=str(plan.get("source_path") or item.get("path") or req.item_id),
        dry_run=False,
        inplace=bool(config.get("inplace", False)),
        copy_mode=bool(config.get("copy_mode", False)),
        output_dir=config.get("output_dir"),
        use_local_nfo=bool(config.get("use_local_nfo", False)),
        extra_images=bool(config.get("extra_images", False)),
        workers=int(config.get("workers") or 4),
        media_type=media_type,
        tmdb_id=tmdb_id,
        search_mode=config.get("search_mode") or "smart",
        enable_fallback=bool(config.get("enable_fallback", True)),
        multi_mode=False,
        fresh=bool(config.get("fresh", False)),
        enable_organize=bool(config.get("enable_organize", False)),
        overwrite_images=bool(config.get("overwrite_images", False)),
        rename_parent_dir=bool(config.get("rename_parent_dir", False)),
        conflict_strategy=config.get("conflict_strategy"),
        operation_scope=config.get("operation_scope") or "full",
        intended_strategy=config.get("strategy") if config.get("strategy") in {"audit", "organize", "copy"} else None,
    )

    started = await _start_task(
        execution_request,
        task_context={
            "source_plan_task_id": task_id,
            "source_plan_item_id": req.item_id,
            "plan_digest": stored_digest,
        },
        expected_plan_digest=stored_digest,
        expected_settings_fingerprint=audited_settings_fingerprint,
    )
    task_event_store.emit(
        task_id,
        "item.execution_confirmed",
        {"plan_digest": stored_digest, "execution_task_id": started["task_id"]},
        item_id=req.item_id,
    )
    task_event_store.emit(
        task_id,
        "item.execution_started",
        {"plan_digest": stored_digest, "execution_task_id": started["task_id"]},
        item_id=req.item_id,
    )
    return {
        **started,
        "source_plan_task_id": task_id,
        "source_plan_item_id": req.item_id,
        "plan_digest": stored_digest,
    }

@app.get("/api/tasks/{task_id}/manifest")
async def get_task_manifest(task_id: str):
    from src.core.operation_manifest import get_manifest

    manifest = get_manifest(task_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found")
    return manifest

@app.get("/api/tasks/{task_id}/rollback/preview")
async def preview_task_rollback(task_id: str):
    from src.core.operation_manifest import preview_rollback_manifest

    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in {"created", "running"}:
        raise HTTPException(status_code=409, detail="Task is still running")

    result = preview_rollback_manifest(task_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Manifest not found")
    return result

@app.get("/api/tasks/{task_id}/recovery/preview")
async def preview_task_recovery(task_id: str):
    from src.core.operation_manifest import preview_recovery_manifest

    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in {"created", "running", "cancel_requested"}:
        raise HTTPException(status_code=409, detail="Task is still running")
    if task.get("status") == "completed":
        raise HTTPException(status_code=409, detail="Completed tasks do not require recovery")
    return preview_recovery_manifest(task_id)

def _emit_rollback_result(task_id: str, result: dict):
    status = result.get("status")
    event_type = {
        "completed": "task.rollback_completed",
        "partial": "task.rollback_partial",
        "failed": "task.rollback_failed",
    }.get(status, "task.rollback_failed")
    payload = result if status in {"completed", "partial", "failed"} else {
        **result,
        "status": "failed",
        "reason": status or "unknown",
        "error": result.get("error") or "Rollback did not produce a valid result",
    }
    task_event_store.emit(task_id, event_type, payload)
    return payload

@app.post("/api/tasks/{task_id}/recover")
async def recover_task(task_id: str):
    from src.core.operation_manifest import preview_recovery_manifest, rollback_manifest

    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in {"created", "running", "cancel_requested"}:
        raise HTTPException(status_code=409, detail="Task is still running")
    if task.get("status") == "completed":
        raise HTTPException(status_code=409, detail="Completed tasks do not require recovery")

    preview = preview_recovery_manifest(task_id)
    if preview.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Recovery requires manual review",
                "recovery": preview,
            },
        )

    task_event_store.emit(task_id, "task.recovery_started", {"strategy": preview.get("strategy")})
    rollback = None
    if preview.get("rollback_required"):
        task_event_store.emit(task_id, "task.rollback_started", {"reason": "recovery"})
        rollback = rollback_manifest(task_id)
        _emit_rollback_result(task_id, rollback)
        if rollback.get("status") != "completed":
            task_event_store.emit(
                task_id,
                "task.recovery_failed",
                {"error": "Rollback did not complete cleanly", "rollback": rollback},
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Rollback did not complete cleanly",
                    "rollback": rollback,
                },
            )
    config = task.get("config") or {}
    retry_request = TaskStartRequest(
        input_dir=task.get("input_dir") or "",
        dry_run=bool(config.get("dry_run", True)),
        inplace=bool(config.get("inplace", False)),
        copy_mode=bool(config.get("copy_mode", False)),
        output_dir=config.get("output_dir"),
        use_local_nfo=bool(config.get("use_local_nfo", False)),
        extra_images=bool(config.get("extra_images", False)),
        workers=int(config.get("workers") or 4),
        media_type=config.get("media_type"),
        tmdb_id=config.get("tmdb_id"),
        search_mode=config.get("search_mode") or "smart",
        enable_fallback=bool(config.get("enable_fallback", True)),
        multi_mode=config.get("multi_mode"),
        fresh=bool(config.get("fresh", False)),
        enable_organize=bool(config.get("enable_organize", False)),
        overwrite_images=bool(config.get("overwrite_images", False)),
        rename_parent_dir=bool(config.get("rename_parent_dir", False)),
        conflict_strategy=config.get("conflict_strategy"),
        operation_scope=config.get("operation_scope") or "full",
    )
    retry = await _start_task(retry_request)
    task_event_store.emit(
        task_id,
        "task.recovery_completed",
        {
            "strategy": preview.get("strategy"),
            "rollback": rollback,
            "retry_task_id": retry.get("task_id"),
        },
    )
    return {
        "status": "restarted",
        "source_task_id": task_id,
        "task_id": retry.get("task_id"),
        "strategy": preview.get("strategy"),
        "rollback": rollback,
    }

@app.post("/api/tasks/{task_id}/rollback")
async def rollback_task(task_id: str):
    from src.core.operation_manifest import rollback_manifest

    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") in {"created", "running"}:
        raise HTTPException(status_code=409, detail="Task is still running")

    task_event_store.emit(task_id, "task.rollback_started", {"reason": "user_request"})
    result = rollback_manifest(task_id)
    if result["status"] == "not_found":
        _emit_rollback_result(task_id, result)
        raise HTTPException(status_code=404, detail="Manifest not found")
    _emit_rollback_result(task_id, result)
    return result

@app.post("/api/tasks/stop")
async def stop_task():
    job_manager.stop_task()
    return {"status": "cancel_requested", "message": "Cancellation requested"}

@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    task = task_event_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("status") not in {"created", "running", "cancel_requested"}:
        raise HTTPException(status_code=409, detail="Task is not running")
    if not job_manager.stop_task(task_id):
        raise HTTPException(status_code=409, detail="Another task is currently active")
    return {"status": "cancel_requested", "task_id": task_id}

async def _test_connectivity():
    import requests
    results = {"checked_at": datetime.utcnow().isoformat() + "Z"}
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
        if not api_key:
            results["tmdb"] = {"status": "skipped", "message": "No TMDB API key configured"}
        else:
            request_kwargs = {"proxies": proxies, "timeout": 5}
            if api_key.startswith("eyJ") and api_key.count(".") == 2:
                request_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
            else:
                request_kwargs["params"] = {"api_key": api_key}
            r = await asyncio.to_thread(requests.get, "https://api.themoviedb.org/3/configuration", **request_kwargs)
            results["tmdb"] = {"status": "ok" if r.ok else "failed", "code": r.status_code, "message": "Configuration endpoint reachable" if r.ok else "TMDB request failed"}
            if not r.ok:
                 try: results["tmdb"]["message"] = r.json().get("status_message", "Unknown error")
                 except Exception: results["tmdb"]["message"] = r.text
    except Exception as e:
        results["tmdb"] = {"status": "error", "message": str(e)}

    # Test Tavily
    try:
        # Collect all potential keys
        t_keys = []
        tavily_config = config.get("tavily", {}) if isinstance(config.get("tavily"), dict) else {}
        if tavily_config.get("api_key"):
            t_keys.append(tavily_config.get("api_key"))
        if isinstance(tavily_config.get("api_keys"), list):
            t_keys.extend(tavily_config.get("api_keys"))
        for env_name in ("TAVILY_API_KEY", "TAVILY_API_KEY_2", "TAVILY_API_KEY_3"):
            if os.getenv(env_name):
                t_keys.append(os.getenv(env_name))
        
        # Deduplicate
        t_keys = list(dict.fromkeys([str(k).strip() for k in t_keys if str(k or "").strip()]))
        
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
                results["tavily"] = {"status": "ok", "code": 200, "checked_keys": len(t_keys), "message": "Search endpoint reachable"}
            else:
                results["tavily"] = {"status": "failed", "checked_keys": len(t_keys), "message": f"All {len(t_keys)} keys failed. Last error: {last_error}"}
        else:
            results["tavily"] = {"status": "skipped", "checked_keys": 0, "message": "No Tavily API keys configured"}
            
    except Exception as e:
        results["tavily"] = {"status": "error", "message": str(e)}
        
    return results

@app.get("/api/connectivity")
async def get_connectivity():
    return await _test_connectivity()

@app.get("/api/test_connectivity")
async def test_connectivity():
    return await _test_connectivity()

@app.get("/api/settings")
async def get_settings():
    return settings_manager.get_settings()

@app.post("/api/settings")
async def save_settings(settings: dict):
    try:
        if settings_manager.save_settings(settings, actor="web"):
            return {
                "status": "saved",
                "config": settings_manager.get_settings(),
                "revision": settings_manager.last_revision,
            }
    except SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SettingsConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=500, detail="Failed to save settings")

@app.get("/api/settings/history")
async def get_settings_history(limit: int = 20):
    return {"revisions": settings_manager.get_revision_history(limit)}

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
