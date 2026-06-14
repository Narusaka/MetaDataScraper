import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from src.core.plan_integrity import assess_plan_path_safety


COPY_ACTIONS = {"copy_file"}
MOVE_ACTIONS = {"move_file", "replace_file"}
WRITE_ACTIONS = {"create_file", "overwrite_file", "download_image"}
DEFAULT_WRITE_RESERVE = 64 * 1024 * 1024


def _nearest_existing_parent(path: Path) -> Optional[Path]:
    current = path.expanduser()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current if current.exists() else None


def _ready_actions(plan: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for action in plan.get("actions") or []:
        if isinstance(action, dict) and action.get("status", "ready") == "ready":
            yield action


def _file_size(path: Optional[Path]) -> int:
    if not path:
        return 0
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def estimate_required_bytes(plan: Dict[str, Any]) -> int:
    required = 0
    has_unknown_writes = False
    for action in _ready_actions(plan):
        action_type = str(action.get("type") or action.get("action") or "")
        source = Path(str(action["source"])).expanduser() if action.get("source") else None
        destination = Path(str(action["destination"])).expanduser() if action.get("destination") else None
        if action_type in COPY_ACTIONS:
            required += _file_size(source)
        elif action_type in MOVE_ACTIONS and source and destination:
            source_parent = _nearest_existing_parent(source)
            destination_parent = _nearest_existing_parent(destination.parent)
            try:
                if source_parent and destination_parent and source_parent.stat().st_dev != destination_parent.stat().st_dev:
                    required += _file_size(source)
            except OSError:
                required += _file_size(source)
        elif action_type in WRITE_ACTIONS:
            has_unknown_writes = True

        if action_type in {"overwrite_file", "replace_file"}:
            required += _file_size(destination)

    if has_unknown_writes:
        required += DEFAULT_WRITE_RESERVE
    return required


def assess_execution_preflight(plan: Dict[str, Any]) -> Dict[str, Any]:
    path_safety = assess_plan_path_safety(plan)
    checks = list(path_safety["checks"])
    source = Path(str(plan.get("source_path") or "")).expanduser()
    if not plan.get("source_path"):
        checks.append(_check("source_path_missing", "blocked", "Execution plan has no source path."))
    elif not source.exists():
        checks.append(_check("source_missing", "blocked", f"Source path no longer exists: {source}", path=source))
    elif not os.access(source, os.R_OK):
        checks.append(_check("source_not_readable", "blocked", f"Source path is not readable: {source}", path=source))
    else:
        checks.append(_check("source_readable", "passed", "Source path is readable.", path=source))

    action_sources = {
        Path(str(action["source"])).expanduser()
        for action in _ready_actions(plan)
        if action.get("source") and bool(action.get("required", True))
    }
    missing_sources = sorted(str(path) for path in action_sources if not path.exists())
    unreadable_sources = sorted(
        str(path)
        for path in action_sources
        if path.exists() and not os.access(path, os.R_OK)
    )
    if missing_sources:
        checks.append(_check(
            "planned_sources_missing",
            "blocked",
            f"{len(missing_sources)} required planned source files are missing.",
            paths=missing_sources[:20],
        ))
    elif unreadable_sources:
        checks.append(_check(
            "planned_sources_not_readable",
            "blocked",
            f"{len(unreadable_sources)} required planned source files are not readable.",
            paths=unreadable_sources[:20],
        ))
    elif action_sources:
        checks.append(_check(
            "planned_sources_readable",
            "passed",
            f"{len(action_sources)} required planned source files are readable.",
        ))

    target = Path(str(plan.get("target_root") or source)).expanduser()
    target_parent = _nearest_existing_parent(target if target.exists() else target.parent)
    if not target_parent or not target_parent.is_dir():
        checks.append(_check("target_parent_missing", "blocked", f"No existing target parent for: {target}", path=target))
    elif not os.access(target_parent, os.W_OK):
        checks.append(_check("target_not_writable", "blocked", f"Target location is not writable: {target_parent}", path=target_parent))
    else:
        checks.append(_check("target_writable", "passed", "Target location is writable.", path=target_parent))

    required_bytes = estimate_required_bytes(plan)
    free_bytes = None
    if target_parent and target_parent.is_dir():
        try:
            free_bytes = shutil.disk_usage(target_parent).free
            if free_bytes < required_bytes:
                checks.append(_check(
                    "insufficient_disk_space",
                    "blocked",
                    f"Target has {_format_bytes(free_bytes)} free but the plan requires at least {_format_bytes(required_bytes)}.",
                    path=target_parent,
                    required_bytes=required_bytes,
                    free_bytes=free_bytes,
                ))
            else:
                checks.append(_check(
                    "disk_space_available",
                    "passed",
                    "Target has enough free space for the planned operations.",
                    path=target_parent,
                    required_bytes=required_bytes,
                    free_bytes=free_bytes,
                ))
        except OSError as exc:
            checks.append(_check(
                "disk_space_unknown",
                "warning",
                f"Could not inspect free space: {exc}",
                path=target_parent,
                required_bytes=required_bytes,
            ))

    blocked = sum(1 for check in checks if check["status"] == "blocked")
    warnings = sum(1 for check in checks if check["status"] == "warning")
    return {
        "status": "blocked" if blocked else "warning" if warnings else "ready",
        "blocked": blocked,
        "warnings": warnings,
        "required_bytes": required_bytes,
        "free_bytes": free_bytes,
        "checks": checks,
    }


def _check(code: str, status: str, message: str, path: Optional[Path] = None, **details: Any) -> Dict[str, Any]:
    result = {"code": code, "status": status, "message": message}
    if path is not None:
        result["path"] = str(path)
    result.update(details)
    return result


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
