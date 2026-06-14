import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


class PlanIntegrityError(RuntimeError):
    pass


READY_ACTION_TYPES = {
    "copy_file",
    "create_dir",
    "create_file",
    "download_image",
    "move_file",
    "overwrite_file",
    "rename_dir",
    "replace_file",
}


def plan_digest(plan: Dict[str, Any]) -> str:
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_artifact_digest(artifact: Dict[str, Any]) -> str:
    protected = {
        key: artifact.get(key)
        for key in (
            "version",
            "task_id",
            "item_id",
            "generated_at",
            "plan_digest",
            "baseline",
            "plan",
        )
    }
    canonical = json.dumps(protected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_plan_artifact_integrity(artifact: Dict[str, Any]) -> None:
    if int(artifact.get("version") or 0) < 3:
        raise PlanIntegrityError("Plan artifact predates envelope integrity checks; run a new audit.")
    expected = str(artifact.get("artifact_digest") or "")
    actual = plan_artifact_digest(artifact)
    if not expected or actual != expected:
        raise PlanIntegrityError("Plan artifact integrity check failed; run a new audit.")
    assert_plan_digest(artifact.get("plan") or {}, str(artifact.get("plan_digest") or ""))


def _plan_paths(plan: Dict[str, Any]) -> Iterable[str]:
    seen = set()
    for raw_path in (plan.get("source_path"), plan.get("target_root")):
        if raw_path and raw_path not in seen:
            seen.add(raw_path)
            yield str(raw_path)
    for action in plan.get("actions") or []:
        if not isinstance(action, dict):
            continue
        for key in ("source", "destination", "original_destination"):
            raw_path = action.get(key)
            if raw_path and raw_path not in seen:
                seen.add(raw_path)
                yield str(raw_path)


def _directory_digest(path: Path) -> str:
    entries: List[str] = []
    try:
        for child in sorted(path.rglob("*"), key=lambda item: str(item)):
            try:
                stat = child.stat()
                relative = child.relative_to(path)
                kind = "dir" if child.is_dir() else "file"
                entries.append(f"{relative}\0{kind}\0{stat.st_size}\0{stat.st_mtime_ns}")
            except OSError as exc:
                entries.append(f"{child}\0error\0{type(exc).__name__}")
    except OSError as exc:
        entries.append(f".\0error\0{type(exc).__name__}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def snapshot_path(raw_path: str) -> Dict[str, Any]:
    path = Path(raw_path).expanduser()
    snapshot: Dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not snapshot["exists"]:
        return snapshot
    try:
        stat = path.stat()
        snapshot.update(
            {
                "kind": "directory" if path.is_dir() else "file",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
        if path.is_dir():
            snapshot["tree_digest"] = _directory_digest(path)
    except OSError as exc:
        snapshot["error"] = type(exc).__name__
    return snapshot


def build_plan_baseline(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [snapshot_path(path) for path in _plan_paths(plan)]


def detect_plan_drift(baseline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    drift = []
    for expected in baseline:
        current = snapshot_path(str(expected.get("path") or ""))
        if current != expected:
            drift.append(
                {
                    "path": expected.get("path"),
                    "expected": expected,
                    "current": current,
                }
            )
    return drift


def assert_plan_digest(plan: Dict[str, Any], expected_digest: str) -> None:
    actual_digest = plan_digest(plan)
    if actual_digest != expected_digest:
        raise PlanIntegrityError(
            f"Execution plan changed after confirmation (expected {expected_digest[:12]}, got {actual_digest[:12]})."
        )


def assess_plan_path_safety(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Prove that ready actions stay inside the plan's declared roots."""
    checks: List[Dict[str, Any]] = []
    source_root = _absolute_resolved_path(plan.get("source_path"))
    target_root = _absolute_resolved_path(plan.get("target_root"))

    if source_root is None:
        checks.append(_path_check("source_root_invalid", "blocked", "Plan source path must be absolute."))
    if target_root is None:
        checks.append(_path_check("target_root_invalid", "blocked", "Plan target root must be absolute."))
    if source_root is None or target_root is None:
        return _path_safety_result(checks)

    checked_actions = 0
    for index, action in enumerate(plan.get("actions") or []):
        if not isinstance(action, dict) or action.get("status", "ready") != "ready":
            continue
        checked_actions += 1
        action_type = str(action.get("type") or "")
        if action_type not in READY_ACTION_TYPES:
            checks.append(_path_check(
                "unsupported_ready_action",
                "blocked",
                f"Ready action {index + 1} has an unsupported type: {action_type or '(missing)'}.",
                action_index=index,
                action_type=action_type,
            ))
            continue

        source = _absolute_resolved_path(action.get("source")) if action.get("source") else None
        destination = _absolute_resolved_path(action.get("destination"))
        original_destination = (
            _absolute_resolved_path(action.get("original_destination"))
            if action.get("original_destination")
            else None
        )

        if action.get("source") and source is None:
            checks.append(_path_check(
                "action_source_invalid",
                "blocked",
                f"Action {index + 1} source path must be absolute.",
                action_index=index,
                action_type=action_type,
                path=action.get("source"),
            ))
        elif source is not None and not _is_within(source, source_root):
            checks.append(_path_check(
                "action_source_outside_root",
                "blocked",
                f"Action {index + 1} source escapes the declared source root.",
                action_index=index,
                action_type=action_type,
                path=str(source),
                root=str(source_root),
            ))

        if destination is None:
            checks.append(_path_check(
                "action_destination_invalid",
                "blocked",
                f"Action {index + 1} destination path must be absolute.",
                action_index=index,
                action_type=action_type,
                path=action.get("destination"),
            ))
        elif not _is_within(destination, target_root):
            checks.append(_path_check(
                "action_destination_outside_root",
                "blocked",
                f"Action {index + 1} destination escapes the declared target root.",
                action_index=index,
                action_type=action_type,
                path=str(destination),
                root=str(target_root),
            ))

        if action.get("original_destination") and original_destination is None:
            checks.append(_path_check(
                "original_destination_invalid",
                "blocked",
                f"Action {index + 1} original destination must be absolute.",
                action_index=index,
                action_type=action_type,
                path=action.get("original_destination"),
            ))
        elif original_destination is not None and not _is_within(original_destination, target_root):
            checks.append(_path_check(
                "original_destination_outside_root",
                "blocked",
                f"Action {index + 1} original destination escapes the declared target root.",
                action_index=index,
                action_type=action_type,
                path=str(original_destination),
                root=str(target_root),
            ))

    if not checks:
        checks.append(_path_check(
            "plan_paths_confined",
            "passed",
            f"{checked_actions} ready action(s) are confined to the declared source and target roots.",
            checked_actions=checked_actions,
            source_root=str(source_root),
            target_root=str(target_root),
        ))
    return _path_safety_result(checks)


def _absolute_resolved_path(raw_path: Any) -> Any:
    if raw_path is None:
        return None
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        return None
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path_check(code: str, status: str, message: str, **details: Any) -> Dict[str, Any]:
    return {"code": code, "status": status, "message": message, **details}


def _path_safety_result(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    blocked = sum(1 for check in checks if check["status"] == "blocked")
    return {
        "status": "blocked" if blocked else "ready",
        "blocked": blocked,
        "checks": checks,
    }
