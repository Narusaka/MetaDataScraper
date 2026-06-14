import json
import os
import shutil
import hashlib
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class OperationManifest:
    def __init__(self, task_id: Optional[str], manifest_dir: str = "logs/manifests"):
        self.task_id = task_id
        self.manifest_dir = Path(manifest_dir)
        self.operations: List[Dict[str, Any]] = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self._lock = threading.RLock()

    @property
    def path(self) -> Optional[Path]:
        if not self.task_id:
            return None
        return self.manifest_dir / f"{self.task_id}.json"

    @property
    def backup_dir(self) -> Optional[Path]:
        if not self.task_id:
            return None
        return self.manifest_dir / f"{self.task_id}.backups"

    def record(self, action: str, source: Optional[Union[Path, str]], destination: Union[Path, str], status: str = "done", extra: Optional[Dict[str, Any]] = None) -> None:
        if not self.task_id:
            return
        with self._lock:
            payload_extra = dict(extra or {})
            destination_path = Path(destination)
            if action == "overwrite_file" and destination_path.exists() and "backup_path" not in payload_extra:
                backup_path = self.backup_file(destination_path)
                if backup_path:
                    payload_extra["backup_path"] = str(backup_path)
            fingerprint = _file_fingerprint(destination_path)
            if fingerprint and "destination_sha256" not in payload_extra:
                payload_extra.update(fingerprint)
            self.operations.append(
                {
                    "action": action,
                    "source": str(source) if source is not None else None,
                    "destination": str(destination),
                    "status": status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **payload_extra,
                }
            )
            self._flush_locked()

    def backup_file(self, path: Union[Path, str]) -> Optional[Path]:
        with self._lock:
            path = Path(path)
            backup_dir = self.backup_dir
            if not backup_dir or not path.exists() or not path.is_file():
                return None
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"{len(self.operations):06d}-{uuid.uuid4().hex}-{path.name}"
            shutil.copy2(path, backup_path)
            return backup_path

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        manifest_path = self.path
        if not manifest_path:
            return
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "task_id": self.task_id,
            "created_at": self.created_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "operations": list(self.operations),
        }
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            dir=str(manifest_path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            tmp_path.replace(manifest_path)
        except Exception:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise


def _file_fingerprint(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "destination_size": path.stat().st_size,
        "destination_sha256": digest.hexdigest(),
    }


def _matches_recorded_fingerprint(path: Path, operation: Dict[str, Any]) -> bool:
    expected_sha = operation.get("destination_sha256")
    expected_size = operation.get("destination_size")
    if not expected_sha:
        return True
    current = _file_fingerprint(path)
    return bool(
        current
        and current.get("destination_sha256") == expected_sha
        and (expected_size is None or current.get("destination_size") == expected_size)
    )


def get_manifest(task_id: str, manifest_dir: str = "logs/manifests") -> Optional[Dict[str, Any]]:
    path = Path(manifest_dir) / f"{task_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_manifest(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    operations = manifest.get("operations", []) if isinstance(manifest, dict) else []
    operations = [item for item in operations if isinstance(item, dict)]
    completed_operations = [item for item in operations if item.get("status", "done") == "done"]
    failed_operations = [item for item in operations if item.get("status", "done") == "failed"]
    reversible_actions = {"move_file", "copy_file", "rename_dir", "create_file", "create_dir", "overwrite_file", "replace_file"}
    action_counts: Dict[str, int] = {}
    reversible = 0
    for operation in completed_operations:
        action = str(operation.get("action") or "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
        if action in reversible_actions and operation.get("status", "done") == "done":
            reversible += 1
    return {
        "exists": isinstance(manifest, dict),
        "operation_count": len(completed_operations),
        "attempted_count": len(operations),
        "failed_count": len(failed_operations),
        "reversible_count": reversible,
        "action_counts": action_counts,
        "created_at": manifest.get("created_at") if isinstance(manifest, dict) else None,
        "updated_at": manifest.get("updated_at") if isinstance(manifest, dict) else None,
    }


def _rollback_status(status: str, apply: bool) -> str:
    if apply or status in {"missing_backup", "dir_not_empty", "missing_destination", "current_modified", "already_restored", "failed", "skipped"}:
        return status
    return f"would_{status}"


def _rollback_operation(operation: Dict[str, Any], apply: bool) -> Dict[str, Any]:
    action = operation.get("action")
    source_raw = operation.get("source")
    source = Path(source_raw) if source_raw else None
    destination = Path(operation.get("destination", ""))
    result = {
        "action": action,
        "source": str(source) if source else None,
        "destination": str(destination),
        "status": "skipped",
    }
    if operation.get("status", "done") != "done":
        result["status"] = "not_applied"
        if operation.get("error"):
            result["error"] = operation["error"]
        return result

    try:
        if action == "move_file":
            if source and destination.exists() and not source.exists():
                if _matches_recorded_fingerprint(destination, operation):
                    if apply:
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(destination), str(source))
                    result["status"] = _rollback_status("rolled_back", apply)
                else:
                    result["status"] = "current_modified"
            elif source and source.exists():
                result["status"] = "already_restored"
            else:
                result["status"] = "missing_destination"
        elif action == "copy_file":
            if destination.exists():
                if _matches_recorded_fingerprint(destination, operation):
                    if apply:
                        destination.unlink()
                    result["status"] = _rollback_status("removed_copy", apply)
                else:
                    result["status"] = "current_modified"
            else:
                result["status"] = "missing_destination"
        elif action == "rename_dir":
            if source and destination.exists() and not source.exists():
                if apply:
                    destination.rename(source)
                result["status"] = _rollback_status("rolled_back", apply)
            elif source and source.exists():
                result["status"] = "already_restored"
            else:
                result["status"] = "missing_destination"
        elif action == "create_file":
            if destination.exists():
                if _matches_recorded_fingerprint(destination, operation):
                    if apply:
                        destination.unlink()
                    result["status"] = _rollback_status("removed_created_file", apply)
                else:
                    result["status"] = "current_modified"
            else:
                result["status"] = "missing_destination"
        elif action == "create_dir":
            if destination.exists():
                if any(destination.iterdir()):
                    result["status"] = "dir_not_empty"
                else:
                    if apply:
                        destination.rmdir()
                    result["status"] = _rollback_status("removed_created_dir", apply)
            else:
                result["status"] = "missing_destination"
        elif action == "overwrite_file":
            backup_raw = operation.get("backup_path")
            backup_path = Path(backup_raw) if backup_raw else None
            if backup_path and backup_path.exists():
                if not destination.exists() or _matches_recorded_fingerprint(destination, operation):
                    if apply:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_path, destination)
                    result["backup_path"] = str(backup_path)
                    result["status"] = _rollback_status("restored_backup", apply)
                else:
                    result["status"] = "current_modified"
            else:
                result["status"] = "missing_backup"
        elif action == "replace_file":
            backup_raw = operation.get("backup_path")
            backup_path = Path(backup_raw) if backup_raw else None
            if not source:
                result["status"] = "missing_source"
            elif not backup_path or not backup_path.exists():
                result["status"] = "missing_backup"
            elif source.exists():
                result["status"] = "source_exists"
            elif not destination.exists():
                result["status"] = "missing_destination"
            elif not _matches_recorded_fingerprint(destination, operation):
                result["status"] = "current_modified"
            else:
                if apply:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(source))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_path, destination)
                result["backup_path"] = str(backup_path)
                result["status"] = _rollback_status("restored_replacement", apply)
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)

    return result


def _summarize_rollback(task_id: str, results: List[Dict[str, Any]], preview: bool = False) -> Dict[str, Any]:
    failed = any(item["status"] == "failed" for item in results)
    incomplete = any(
        item["status"] in {
            "missing_backup",
            "missing_source",
            "source_exists",
            "dir_not_empty",
            "missing_destination",
            "current_modified",
        }
        for item in results
    )
    return {
        "task_id": task_id,
        "status": "failed" if failed else ("partial" if incomplete else "preview" if preview else "completed"),
        "preview": preview,
        "operations": results,
    }


def _preview_rollback_operations(operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Preview rollback in execution order while simulating removed outputs."""
    results: List[Dict[str, Any]] = []
    removed_paths: List[Path] = []
    removable_statuses = {
        "would_removed_copy",
        "would_removed_created_file",
        "would_removed_created_dir",
        "would_rolled_back",
    }

    def removed_by_prior_step(path: Path) -> bool:
        resolved = path.resolve(strict=False)
        return any(
            resolved == removed or removed in resolved.parents
            for removed in removed_paths
        )

    for operation in reversed(operations):
        result = _rollback_operation(operation, apply=False)
        destination = Path(operation.get("destination", ""))
        if operation.get("action") == "create_dir" and result["status"] == "dir_not_empty":
            remaining = [
                path
                for path in destination.rglob("*")
                if not removed_by_prior_step(path)
            ]
            if not remaining:
                result["status"] = "would_removed_created_dir"
        if result["status"] in removable_statuses:
            removed_paths.append(destination.resolve(strict=False))
        results.append(result)
    return results


def preview_rollback_manifest(task_id: str, manifest_dir: str = "logs/manifests") -> Dict[str, Any]:
    manifest = get_manifest(task_id, manifest_dir)
    if not manifest:
        return {"task_id": task_id, "status": "not_found", "preview": True, "operations": []}
    operations = [
        operation
        for operation in manifest.get("operations", [])
        if isinstance(operation, dict) and operation.get("status", "done") == "done"
    ]
    results = _preview_rollback_operations(operations)
    return _summarize_rollback(task_id, results, preview=True)


def rollback_manifest(task_id: str, manifest_dir: str = "logs/manifests") -> Dict[str, Any]:
    manifest = get_manifest(task_id, manifest_dir)
    if not manifest:
        return {"task_id": task_id, "status": "not_found", "preview": False, "operations": []}
    results = [
        _rollback_operation(operation, apply=True)
        for operation in reversed(manifest.get("operations", []))
        if isinstance(operation, dict) and operation.get("status", "done") == "done"
    ]
    return _summarize_rollback(task_id, results, preview=False)


def preview_recovery_manifest(task_id: str, manifest_dir: str = "logs/manifests") -> Dict[str, Any]:
    """Classify whether a failed task can be safely retried.

    Recovery never continues halfway through a mutation sequence. It either
    retries directly when nothing changed, or requires a clean rollback first.
    """
    manifest = get_manifest(task_id, manifest_dir)
    if not manifest:
        return {
            "task_id": task_id,
            "status": "ready",
            "strategy": "retry",
            "rollback_required": False,
            "reason": "No filesystem operations were recorded.",
            "operations": [],
        }

    operations = [
        item
        for item in manifest.get("operations", [])
        if isinstance(item, dict) and item.get("status", "done") == "done"
    ]
    if not operations:
        return {
            "task_id": task_id,
            "status": "ready",
            "strategy": "retry",
            "rollback_required": False,
            "reason": "The manifest contains no completed filesystem operations.",
            "operations": [],
        }

    rollback = preview_rollback_manifest(task_id, manifest_dir)
    review_statuses = {
        "missing_backup",
        "missing_source",
        "source_exists",
        "dir_not_empty",
        "missing_destination",
        "current_modified",
        "failed",
    }
    review = [
        operation
        for operation in rollback.get("operations", [])
        if operation.get("status") in review_statuses
    ]
    if review:
        return {
            "task_id": task_id,
            "status": "manual_review",
            "strategy": "manual_review",
            "rollback_required": True,
            "reason": "Recorded outputs changed or rollback evidence is incomplete.",
            "review_count": len(review),
            "operations": rollback.get("operations", []),
        }

    return {
        "task_id": task_id,
        "status": "ready",
        "strategy": "rollback_then_retry",
        "rollback_required": True,
        "reason": "Recorded changes can be rolled back cleanly before retrying.",
        "review_count": 0,
        "operations": rollback.get("operations", []),
    }
