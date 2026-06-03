import json
import shutil
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

    def record(self, action: str, source: Optional[Union[Path, str]], destination: Union[Path, str], status: str = "done", extra: Optional[Dict[str, Any]] = None) -> None:
        if not self.task_id:
            return
        self.operations.append(
            {
                "action": action,
                "source": str(source) if source is not None else None,
                "destination": str(destination),
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **(extra or {}),
            }
        )
        self.flush()

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
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(source))
                    result["status"] = "rolled_back"
                elif source and source.exists():
                    result["status"] = "already_restored"
                else:
                    result["status"] = "missing_destination"
            elif action == "copy_file":
                if destination.exists():
                    destination.unlink()
                    result["status"] = "removed_copy"
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
                    destination.unlink()
                    result["status"] = "removed_created_file"
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
                result["status"] = "not_reversible"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)

        results.append(result)

    failed = any(item["status"] == "failed" for item in results)
    incomplete = any(
        item["status"] in {"not_reversible", "dir_not_empty", "missing_destination"}
        for item in results
    )

    return {
        "task_id": task_id,
        "status": "failed" if failed else ("partial" if incomplete else "completed"),
        "operations": results,
    }
