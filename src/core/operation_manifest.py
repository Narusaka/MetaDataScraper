import json
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class OperationManifest:
    def __init__(self, task_id: Optional[str], manifest_dir: str = "logs/manifests"):
        self.task_id = task_id
        self.manifest_dir = Path(manifest_dir)
        self.operations: List[Dict[str, Any]] = []
        self.created_at = datetime.now(timezone.utc).isoformat()

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
        self.flush()

    def backup_file(self, path: Union[Path, str]) -> Optional[Path]:
        path = Path(path)
        backup_dir = self.backup_dir
        if not backup_dir or not path.exists() or not path.is_file():
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{len(self.operations):06d}-{path.name}"
        shutil.copy2(path, backup_path)
        return backup_path

    def flush(self) -> None:
        manifest_path = self.path
        if not manifest_path:
            return
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "task_id": self.task_id,
            "created_at": self.created_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "operations": self.operations,
        }
        tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(manifest_path)


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


def rollback_manifest(task_id: str, manifest_dir: str = "logs/manifests") -> Dict[str, Any]:
    manifest = get_manifest(task_id, manifest_dir)
    if not manifest:
        return {"task_id": task_id, "status": "not_found", "operations": []}

    results = []
    for operation in reversed(manifest.get("operations", [])):
        action = operation.get("action")
        source_raw = operation.get("source")
        source = Path(source_raw) if source_raw else None
        destination = Path(operation.get("destination", ""))
        result = {"action": action, "source": str(source) if source else None, "destination": str(destination), "status": "skipped"}

        try:
            if action == "move_file":
                if source and destination.exists() and not source.exists():
                    if _matches_recorded_fingerprint(destination, operation):
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(destination), str(source))
                        result["status"] = "rolled_back"
                    else:
                        result["status"] = "current_modified"
                elif source and source.exists():
                    result["status"] = "already_restored"
                else:
                    result["status"] = "missing_destination"
            elif action == "copy_file":
                if destination.exists():
                    if _matches_recorded_fingerprint(destination, operation):
                        destination.unlink()
                        result["status"] = "removed_copy"
                    else:
                        result["status"] = "current_modified"
                else:
                    result["status"] = "missing_destination"
            elif action == "rename_dir":
                if source and destination.exists() and not source.exists():
                    destination.rename(source)
                    result["status"] = "rolled_back"
                elif source and source.exists():
                    result["status"] = "already_restored"
                else:
                    result["status"] = "missing_destination"
            elif action == "create_file":
                if destination.exists():
                    if _matches_recorded_fingerprint(destination, operation):
                        destination.unlink()
                        result["status"] = "removed_created_file"
                    else:
                        result["status"] = "current_modified"
                else:
                    result["status"] = "missing_destination"
            elif action == "create_dir":
                if destination.exists():
                    try:
                        destination.rmdir()
                        result["status"] = "removed_created_dir"
                    except OSError:
                        result["status"] = "dir_not_empty"
                else:
                    result["status"] = "missing_destination"
            elif action == "overwrite_file":
                backup_raw = operation.get("backup_path")
                backup_path = Path(backup_raw) if backup_raw else None
                if backup_path and backup_path.exists():
                    if not destination.exists() or _matches_recorded_fingerprint(destination, operation):
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_path, destination)
                        result["backup_path"] = str(backup_path)
                        result["status"] = "restored_backup"
                    else:
                        result["status"] = "current_modified"
                else:
                    result["status"] = "missing_backup"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)

        results.append(result)

    failed = any(item["status"] == "failed" for item in results)
    incomplete = any(
        item["status"] in {"missing_backup", "dir_not_empty", "missing_destination", "current_modified"}
        for item in results
    )

    return {
        "task_id": task_id,
        "status": "failed" if failed else ("partial" if incomplete else "completed"),
        "operations": results,
    }
