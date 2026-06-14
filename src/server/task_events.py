import asyncio
import hashlib
import json
import logging
import shutil
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

from src.core.plan_integrity import (
    assert_plan_artifact_integrity,
    build_plan_baseline,
    plan_artifact_digest,
    plan_digest,
)
from src.storage.task_ledger import SQLiteTaskLedger


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskEventStore:
    """Task ledger used by the web server and worker threads.

    Snapshots are kept in memory for fast reads and persisted as a compact JSON
    file so the UI can recover task history after a server restart.
    """

    def __init__(
        self,
        max_events_per_task: int = 500,
        storage_path: Optional[str] = "logs/task_events.db",
        max_tasks: int = 1000,
        legacy_storage_path: Optional[str] = None,
    ):
        self.max_events_per_task = max_events_per_task
        self.max_tasks = max_tasks
        self.storage_path = Path(storage_path) if storage_path else None
        self.legacy_storage_path = Path(legacy_storage_path) if legacy_storage_path else self._default_legacy_path()
        self._sqlite_ledger = (
            SQLiteTaskLedger(self.storage_path)
            if self.storage_path and self.storage_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
            else None
        )
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._subscribers: List[asyncio.Queue] = []
        self._lock = RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._load()

    def _default_legacy_path(self) -> Optional[Path]:
        if not self.storage_path or self.storage_path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            return None
        return self.storage_path.with_name("task_events.json")

    @property
    def plan_root(self) -> Optional[Path]:
        if not self.storage_path:
            return None
        return self.storage_path.parent / "plans"

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def create_task(self, input_dir: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex
        now = _utc_now()
        snapshot = {
            "id": task_id,
            "input_dir": input_dir,
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "config": config or {},
            "summary": {"total": 0, "completed": 0, "failed": 0},
            "items": {},
            "events": [],
        }
        with self._lock:
            self._tasks[task_id] = snapshot
            self._persist_task_locked(snapshot)
        self.emit(task_id, "task.created", {"input_dir": input_dir, "config": config or {}})
        return self.get_task(task_id) or snapshot

    def emit(
        self,
        task_id: Optional[str],
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not task_id:
            return None

        payload = payload or {}
        event = {
            "id": uuid.uuid4().hex,
            "task_id": task_id,
            "type": event_type,
            "timestamp": _utc_now(),
            "payload": payload,
        }
        if item_id:
            event["item_id"] = item_id

        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            self._apply_event(task, event)
            task["events"].append(event)
            task["events"] = task["events"][-self.max_events_per_task:]
            task["updated_at"] = event["timestamp"]
            pruned = self._prune_tasks_locked()
            self._persist_task_locked(task)
            if pruned and self._sqlite_ledger:
                self._sqlite_ledger.retain_tasks(self._tasks.keys())
            snapshot_event = deepcopy(event)

        self._broadcast(snapshot_event)
        return snapshot_event

    def list_tasks(self, compact: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                self._compact_task_snapshot(task) if compact else self._without_events(task)
                for task in sorted(
                    self._tasks.values(),
                    key=lambda item: item.get("created_at", ""),
                    reverse=True,
                )
            ]

    def list_plan_reviews(self) -> List[Dict[str, Any]]:
        """Return locked audit plans that still require a user decision."""
        reviews = []
        seen_sources = set()
        with self._lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda item: item.get("updated_at") or item.get("created_at", ""),
                reverse=True,
            )
            for task in tasks:
                if not bool((task.get("config") or {}).get("dry_run")):
                    continue
                for item_id, item in (task.get("items") or {}).items():
                    if not isinstance(item, dict):
                        continue
                    if not item.get("plan_digest") or not item.get("plan_path"):
                        continue
                    source_key = str(item.get("path") or item_id)
                    if source_key in seen_sources:
                        continue
                    seen_sources.add(source_key)
                    if item.get("status") != "audit_completed":
                        continue
                    confirmation = item.get("plan_confirmation") or {}
                    confirmation_status = confirmation.get("status")
                    if confirmation_status in {"confirmed", "executing"}:
                        continue

                    plan = item.get("plan") or {}
                    summary = plan.get("summary") or item.get("plan_summary") or {}
                    blockers = int(summary.get("conflicts") or 0) + int(summary.get("blocked") or 0)
                    review_status = (
                        "drifted"
                        if confirmation_status in {"drifted", "settings_drifted"}
                        else "blocked"
                        if blockers > 0
                        else "ready"
                    )
                    reviews.append({
                        "task_id": task["id"],
                        "task_status": task.get("status"),
                        "task_created_at": task.get("created_at"),
                        "task_updated_at": task.get("updated_at"),
                        "task_config": deepcopy(task.get("config") or {}),
                        "item_id": item_id,
                        "review_status": review_status,
                        "item": self._compact_item_snapshot(item),
                    })
        return reviews

    def list_executions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return real execution tasks with a compact, structured timeline."""
        with self._lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda item: item.get("updated_at") or item.get("created_at", ""),
                reverse=True,
            )
            executions = []
            for task in tasks:
                config = task.get("config") or {}
                if bool(config.get("dry_run", True)):
                    continue
                snapshot = self._compact_task_snapshot(task)
                snapshot["phase"] = task.get("phase") or self._execution_phase(task)
                snapshot["progress"] = deepcopy(task.get("progress") or self._execution_progress(task))
                snapshot["timeline"] = [
                    self._compact_execution_event(event)
                    for event in (task.get("events") or [])[-40:]
                    if event.get("type") != "task.created"
                ]
                executions.append(snapshot)
                if len(executions) >= max(1, min(limit, 200)):
                    break
            return executions

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

    def clear_finished_tasks(
        self,
        protected_task_ids: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        preview = self.preview_finished_task_clear(protected_task_ids)
        removed_ids = preview["task_ids"]
        with self._lock:
            if removed_ids:
                for task_id in removed_ids:
                    self._tasks.pop(task_id, None)
                self._persist_locked()

        cleanup_errors = []
        plan_root = self.plan_root
        if plan_root:
            for task_id in removed_ids:
                plan_dir = plan_root / task_id
                if not plan_dir.exists():
                    continue
                try:
                    shutil.rmtree(plan_dir)
                except OSError as exc:
                    cleanup_errors.append({
                        "task_id": task_id,
                        "artifact": str(plan_dir),
                        "error": str(exc),
                    })

        return {
            "removed": len(removed_ids),
            "task_ids": removed_ids,
            "retained": preview["retained"],
            "retained_count": preview["retained_count"],
            "plan_cleanup_errors": cleanup_errors,
        }

    def preview_finished_task_clear(
        self,
        protected_task_ids: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        removable_statuses = {
            "completed",
            "failed",
            "partial",
            "stopped",
            "cancelled",
            "interrupted",
        }
        protected = protected_task_ids or {}
        with self._lock:
            removed_ids = [
                task_id
                for task_id, task in self._tasks.items()
                if task.get("status") in removable_statuses and task_id not in protected
            ]
            retained = [
                {
                    "task_id": task_id,
                    "reasons": list(protected.get(task_id) or []),
                }
                for task_id, task in self._tasks.items()
                if task.get("status") in removable_statuses and task_id in protected
            ]
        return {
            "eligible_count": len(removed_ids),
            "task_ids": removed_ids,
            "retained": retained,
            "retained_count": len(retained),
        }

    def reconcile_interrupted_tasks(self, reason: str = "process_restart") -> Dict[str, Any]:
        """Move persisted non-terminal tasks into an explicit recovery state.

        A freshly started process cannot own workers from the previous process,
        so retaining ``running`` or ``cancel_requested`` would make the API lie
        about active work and would block rollback/recovery indefinitely.
        """
        active_statuses = {"created", "running", "cancel_requested"}
        with self._lock:
            interrupted = [
                {
                    "task_id": task_id,
                    "previous_status": str(task.get("status") or "created"),
                    "previous_phase": task.get("phase"),
                    "last_updated_at": task.get("updated_at"),
                }
                for task_id, task in self._tasks.items()
                if task.get("status") in active_statuses
            ]

        for record in interrupted:
            self.emit(
                record["task_id"],
                "task.interrupted",
                {
                    "reason": reason,
                    "previous_status": record["previous_status"],
                    "previous_phase": record["previous_phase"],
                    "last_updated_at": record["last_updated_at"],
                    "recoverable": True,
                    "error": "Task was interrupted before the worker reported a terminal result",
                    "error_code": "PROCESS_INTERRUPTED",
                },
            )

        return {
            "count": len(interrupted),
            "task_ids": [record["task_id"] for record in interrupted],
        }

    def compact(self) -> None:
        """Rewrite the ledger using the current retention and compact-plan rules."""
        with self._lock:
            self._tasks = {
                task_id: self._compact_loaded_task(task)
                for task_id, task in self._tasks.items()
            }
            self._prune_tasks_locked()
            self._persist_locked()

    def read_plan_artifact(self, task_id: str, item_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id)
        if not task:
            raise KeyError("Task not found")

        item = task.get("items", {}).get(item_id)
        if not item:
            raise KeyError("Task item not found")

        plan_path_raw = item.get("plan_path")
        if not plan_path_raw:
            raise FileNotFoundError("Plan artifact not found")

        plan_root = self.plan_root
        if not plan_root:
            raise FileNotFoundError("Plan storage unavailable")

        plan_path = Path(plan_path_raw)
        resolved_plan_path = plan_path.resolve()
        resolved_plan_root = plan_root.resolve()
        try:
            resolved_plan_path.relative_to(resolved_plan_root)
        except ValueError:
            raise PermissionError("Plan artifact path is outside plan storage")

        if not resolved_plan_path.exists():
            raise FileNotFoundError("Plan artifact file not found")
        artifact = json.loads(resolved_plan_path.read_text(encoding="utf-8"))
        assert_plan_artifact_integrity(artifact)
        artifact["integrity_status"] = "verified"
        return artifact

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def _without_events(self, task: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = deepcopy(task)
        snapshot.pop("events", None)
        return snapshot

    def _compact_task_snapshot(self, task: Dict[str, Any]) -> Dict[str, Any]:
        snapshot = {
            key: deepcopy(task.get(key))
            for key in (
                "id",
                "input_dir",
                "status",
                "created_at",
                "updated_at",
                "config",
                "summary",
                "mode",
                "error",
                "error_code",
                "cancel",
                "recovery",
                "interruption",
                "phase",
                "progress",
            )
            if key in task
        }
        if "rollback" in task:
            snapshot["rollback"] = self._compact_rollback(task.get("rollback") or {})
        snapshot["items"] = {
            item_id: self._compact_item_snapshot(item)
            for item_id, item in (task.get("items") or {}).items()
            if isinstance(item, dict)
        }
        snapshot["compact"] = True
        return snapshot

    def _compact_item_snapshot(self, item: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            key: deepcopy(item.get(key))
            for key in (
                "id",
                "status",
                "name",
                "path",
                "kind",
                "media_type",
                "query",
                "result",
                "reason",
                "error",
                "error_code",
                "dry_run",
                "tmdb_id",
                "video_count",
                "parse",
                "parse_confidence",
                "created_at",
                "updated_at",
                "plan_path",
                "plan_digest",
                "plan_summary",
                "output_path",
                "review",
                "plan_confirmation",
                "phase",
                "operation",
                "current_operation",
                "latest_operation",
                "operation_summary",
            )
            if key in item
        }
        if "operation_history" in item:
            compact["operation_history"] = deepcopy((item.get("operation_history") or [])[-20:])
        if "candidate" in item:
            compact["candidate"] = self._compact_candidate(item.get("candidate") or {})
        if "match" in item:
            compact["match"] = self._compact_match(item.get("match") or {})
        if "plan" in item:
            compact["plan"] = self._compact_plan_for_list(item.get("plan") or {})
        if "artwork" in item:
            compact["artwork"] = self._compact_artwork(item.get("artwork") or {})
        if "verification" in item:
            compact["verification"] = self._compact_verification(item.get("verification") or {})
        if "nfo_outputs" in item:
            compact["nfo_outputs"] = deepcopy((item.get("nfo_outputs") or [])[-10:])
        if "lock" in item:
            compact["lock"] = deepcopy(item.get("lock"))
        if "issue" in item:
            compact["issue"] = deepcopy(item.get("issue"))
        return compact

    def _compact_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            key: deepcopy(candidate.get(key))
            for key in ("title", "tmdb_id", "media_type", "poster_path", "poster_url")
            if key in candidate
        }
        if "tmdb_id" not in compact and candidate.get("id") is not None:
            compact["tmdb_id"] = deepcopy(candidate.get("id"))
        if "title" not in compact:
            title = candidate.get("name") or candidate.get("original_title") or candidate.get("original_name")
            if title:
                compact["title"] = deepcopy(title)
        if "match" in candidate:
            compact["match"] = self._compact_match(candidate.get("match") or {})
        return compact

    def _compact_match(self, match: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            key: deepcopy(match.get(key))
            for key in (
                "provider",
                "confidence",
                "reason",
                "score",
                "title_similarity",
                "token_overlap",
                "selected_id",
                "external_id",
                "selected_title",
                "matched_title",
                "matched_field",
                "target_year",
                "review_required",
                "review_reason",
            )
            if key in match
        }
        if isinstance(match.get("evidence"), dict):
            compact["evidence"] = self._compact_match_evidence(match["evidence"])
        candidates = match.get("candidates") or []
        selected_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)][:3]
        compact["candidates"] = [
            {
                key: deepcopy(candidate.get(key))
                for key in (
                    "id",
                    "title",
                    "media_type",
                    "year",
                    "score",
                    "title_similarity",
                    "token_overlap",
                    "decision",
                    "matched_title",
                    "matched_field",
                )
                if isinstance(candidate, dict) and key in candidate
            }
            for candidate in selected_candidates
        ]
        for compact_candidate, candidate in zip(compact["candidates"], selected_candidates):
            if isinstance(candidate.get("evidence"), dict):
                compact_candidate["evidence"] = self._compact_match_evidence(candidate["evidence"])
        return compact

    def _compact_match_evidence(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        dimensions = evidence.get("dimensions") if isinstance(evidence.get("dimensions"), dict) else {}
        compact_dimensions = {}
        for name in ("title_similarity", "token_overlap", "year", "media_type", "script", "external_evidence"):
            dimension = dimensions.get(name)
            if not isinstance(dimension, dict):
                continue
            compact_dimensions[name] = {
                key: deepcopy(dimension.get(key))
                for key in ("score", "weight", "status", "target", "candidate", "expected", "provider")
                if key in dimension
            }
        return {
            "schema_version": evidence.get("schema_version", 1),
            "composite_score": evidence.get("composite_score"),
            "title_similarity": evidence.get("title_similarity"),
            "token_overlap": evidence.get("token_overlap"),
            "dimensions": compact_dimensions,
            "hard_blockers": deepcopy((evidence.get("hard_blockers") or [])[:5]),
            "warnings": deepcopy((evidence.get("warnings") or [])[:5]),
        }

    def _compact_plan_for_list(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            key: deepcopy(plan.get(key))
            for key in ("media_type", "title", "year", "source_path", "target_root", "mode", "operation_scope", "conflict_strategy", "rollback_available", "artwork", "nfo", "summary", "review", "diagnostics", "compact", "full_plan_available")
            if key in plan
        }
        compact.setdefault("compact", True)
        compact["preview_omitted"] = True
        return compact

    def _compact_artwork(self, artwork: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: deepcopy(artwork.get(key))
            for key in ("status", "total", "counts", "manifest_path", "error")
            if key in artwork
        }

    def _compact_verification(self, verification: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            key: deepcopy(verification.get(key))
            for key in ("status", "verified_at", "checked", "passed", "failed", "warnings", "skipped", "failure_codes", "warning_codes")
            if key in verification
        }
        compact["checks"] = deepcopy((verification.get("checks") or [])[:10])
        omitted = max(0, len(verification.get("checks") or []) - len(compact["checks"]))
        if omitted:
            compact["omitted_checks"] = omitted
        return compact

    def _compact_rollback(self, rollback: Dict[str, Any]) -> Dict[str, Any]:
        compact = {
            key: deepcopy(rollback.get(key))
            for key in ("status", "task_id", "error")
            if key in rollback
        }
        operations = rollback.get("operations") or []
        compact["operations"] = deepcopy(operations[:5])
        if len(operations) > 5:
            compact["omitted_operations"] = len(operations) - 5
        return compact

    def _apply_event(self, task: Dict[str, Any], event: Dict[str, Any]) -> None:
        event_type = event["type"]
        payload = event.get("payload", {})
        item_id = event.get("item_id")

        if event_type in {"task.started", "task.scan.started"}:
            task["status"] = "running"
            task["phase"] = "scanning"
        elif event_type == "task.progress":
            task["progress"] = deepcopy(payload)
        elif event_type == "task.cancel_requested":
            task["status"] = "cancel_requested"
            task["cancel"] = payload
        elif event_type == "task.cancelled":
            task["status"] = "cancelled"
            task["cancel"] = payload
            task["summary"].update(payload.get("summary", {}))
            for item in task.get("items", {}).values():
                if item.get("status") in {"created", "planned", "processing", "fetching"}:
                    item["status"] = "cancelled"
                    item["result"] = "Cancelled"
                    item["updated_at"] = event["timestamp"]
        elif event_type == "task.interrupted":
            task["status"] = "interrupted"
            task["phase"] = "interrupted"
            task["error"] = payload.get("error")
            task["error_code"] = payload.get("error_code") or "PROCESS_INTERRUPTED"
            task["interruption"] = deepcopy(payload)
            interrupted_items = 0
            for item in task.get("items", {}).values():
                if item.get("status") in {
                    "created",
                    "planned",
                    "processing",
                    "fetching",
                    "verifying",
                }:
                    item["status"] = "interrupted"
                    item["error"] = task["error"]
                    item["error_code"] = task["error_code"]
                    item["updated_at"] = event["timestamp"]
                    interrupted_items += 1
            task["summary"]["interrupted"] = interrupted_items
        elif event_type == "task.recovery_started":
            task["recovery"] = {**payload, "status": "running"}
        elif event_type == "task.recovery_completed":
            task["recovery"] = {**payload, "status": "restarted"}
        elif event_type == "task.recovery_failed":
            task["recovery"] = {**payload, "status": "failed"}
        elif event_type == "task.mode_detected":
            task["mode"] = payload.get("mode")
        elif event_type == "task.scan.completed":
            task["summary"]["total"] = payload.get("total", task["summary"].get("total", 0))
        elif event_type == "task.completed":
            task["status"] = "completed"
            task["summary"].update(payload.get("summary", payload))
        elif event_type == "task.partial":
            task["status"] = "partial"
            task["summary"].update(payload.get("summary", payload))
        elif event_type == "task.failed":
            task["status"] = "failed"
            task["error"] = payload.get("error")
            task["summary"].update(payload.get("summary", {}))
        elif event_type == "task.stopped":
            task["status"] = "stopped"
            task["summary"].update(payload.get("summary", {}))
        elif event_type == "task.rollback_started":
            task["rollback"] = {**payload, "status": "running"}
        elif event_type in {"task.rollback_completed", "task.rollback_partial", "task.rollback_failed"}:
            default_status = {
                "task.rollback_completed": "completed",
                "task.rollback_partial": "partial",
                "task.rollback_failed": "failed",
            }[event_type]
            task["rollback"] = {**payload, "status": payload.get("status") or default_status}

        if item_id:
            items = task.setdefault("items", {})
            item = items.setdefault(
                item_id,
                {
                    "id": item_id,
                    "status": "created",
                    "logs": [],
                    "created_at": event["timestamp"],
                },
            )
            item["updated_at"] = event["timestamp"]

            if event_type == "item.started":
                item.update(payload)
                item["status"] = "processing"
            elif event_type == "item.planned":
                item.update(payload)
                item["status"] = "planned"
            elif event_type == "item.plan_ready":
                full_plan = payload.get("plan", payload)
                artifact = self._write_plan_artifact(task["id"], item_id, full_plan, event["timestamp"])
                compact_plan = self._compact_plan(full_plan)
                item["plan"] = compact_plan
                if artifact:
                    payload["plan_path"] = str(artifact["path"])
                    payload["plan_digest"] = artifact["digest"]
                    item["plan_path"] = str(artifact["path"])
                    item["plan_digest"] = artifact["digest"]
                payload["plan"] = compact_plan
                item["plan_summary"] = item["plan"].get("summary", {})
            elif event_type == "candidate.selected":
                item["candidate"] = payload
                if "match" in payload:
                    item["match"] = payload.get("match")
                item["status"] = "fetching"
            elif event_type == "item.audit_completed":
                item.update(payload)
                item["status"] = "audit_completed"
                task["summary"]["completed"] = self._count_items(task, {"completed", "audit_completed"})
            elif event_type == "item.plan_drifted":
                item["plan_confirmation"] = {**payload, "status": "drifted"}
            elif event_type == "item.settings_drifted":
                item["plan_confirmation"] = {**payload, "status": "settings_drifted"}
            elif event_type == "item.preflight_failed":
                item["plan_confirmation"] = {**payload, "status": "preflight_failed"}
            elif event_type == "item.execution_confirmed":
                item["plan_confirmation"] = {**payload, "status": "confirmed"}
            elif event_type == "item.execution_started":
                item["plan_confirmation"] = {**payload, "status": "executing"}
            elif event_type == "item.execution_phase":
                phase = payload.get("phase")
                if phase:
                    item["phase"] = phase
                    task["phase"] = phase
            elif event_type == "item.verification_started":
                item.update(payload)
                item["status"] = "verifying"
                item["phase"] = "verifying"
                task["phase"] = "verifying"
            elif event_type == "item.verification_completed":
                item["verification"] = payload.get("verification", payload)
            elif event_type == "item.completed":
                item.update(payload)
                item["status"] = "completed"
                task["summary"]["completed"] = self._count_items(task, {"completed", "audit_completed"})
            elif event_type == "item.partial":
                item.update(payload)
                item["status"] = "partial"
                task["summary"]["partial"] = self._count_items(task, {"partial"})
            elif event_type == "item.failed":
                item.update(payload)
                item["status"] = "failed"
                task["summary"]["failed"] = self._count_items(task, {"failed"})
            elif event_type == "item.skipped":
                item.update(payload)
                item["status"] = "skipped"
                task["summary"]["completed"] = self._count_items(task, {"completed", "audit_completed", "skipped"})
            elif event_type == "item.cancelled":
                item.update(payload)
                item["status"] = "cancelled"
                item["result"] = "Cancelled"
                task["summary"]["cancelled"] = self._count_items(task, {"cancelled"})
            elif event_type == "item.quarantined":
                item.update(payload)
                item["status"] = "quarantined"
                task["summary"]["quarantined"] = self._count_items(task, {"quarantined"})
            elif event_type in {"operation.started", "operation.completed", "operation.failed", "operation.skipped"}:
                operation = deepcopy(payload.get("operation") or {})
                operation_status = event_type.rsplit(".", 1)[-1]
                operation["status"] = operation_status
                operation["timestamp"] = event["timestamp"]
                summary = item.setdefault(
                    "operation_summary",
                    {"started": 0, "completed": 0, "failed": 0, "skipped": 0},
                )
                summary[operation_status] = int(summary.get(operation_status) or 0) + 1
                if event_type == "operation.started":
                    item["current_operation"] = operation
                    item["phase"] = "organizing"
                    task["phase"] = "organizing"
                else:
                    current = item.get("current_operation") or {}
                    if (
                        current.get("action") == operation.get("action")
                        and current.get("destination") == operation.get("destination")
                    ):
                        item.pop("current_operation", None)
                    item["latest_operation"] = operation
                    history = item.setdefault("operation_history", [])
                    history.append(operation)
                    item["operation_history"] = history[-50:]
            elif event_type == "item.review_resolved":
                item["review"] = {
                    **payload,
                    "status": "resolved",
                    "resolved_at": event["timestamp"],
                }
            elif event_type == "nfo.written":
                outputs = item.setdefault("nfo_outputs", [])
                outputs.append({**payload, "written_at": event["timestamp"]})
                item["nfo_outputs"] = outputs[-100:]

    def _execution_phase(self, task: Dict[str, Any]) -> str:
        status = str(task.get("status") or "")
        if status == "created":
            return "queued"
        if status == "cancel_requested":
            return "cancelling"
        if status == "cancelled":
            return "cancelled"
        if status in {"completed", "partial", "failed", "stopped", "interrupted"}:
            return status
        for event in reversed(task.get("events") or []):
            event_type = event.get("type")
            payload = event.get("payload") or {}
            if event_type == "item.execution_phase" and payload.get("phase"):
                return str(payload["phase"])
            if event_type == "item.verification_started":
                return "verifying"
            if event_type in {"item.lock_acquired", "item.plan_ready"}:
                return "organizing"
            if event_type in {"candidate.selected", "item.started"}:
                return "metadata"
            if event_type in {"task.scan.started", "task.started"}:
                return "scanning"
        return "queued"

    def _execution_progress(self, task: Dict[str, Any]) -> Dict[str, Any]:
        items = list((task.get("items") or {}).values())
        total = int((task.get("summary") or {}).get("total") or len(items))
        completed_statuses = {"completed", "partial", "failed", "skipped", "cancelled", "quarantined"}
        processed = sum(1 for item in items if item.get("status") in completed_statuses)
        return {
            "total": total,
            "processed": processed,
            "completed": self._count_items(task, {"completed", "skipped"}),
            "partial": self._count_items(task, {"partial"}),
            "failed": self._count_items(task, {"failed"}),
            "cancelled": self._count_items(task, {"cancelled"}),
        }

    def _compact_execution_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        payload = event.get("payload") or {}
        keep = (
            "phase",
            "name",
            "path",
            "stage",
            "error",
            "error_code",
            "result",
            "reason",
            "processed",
            "total",
            "completed",
            "partial",
            "failed",
            "cancelled",
            "target_path",
            "operation",
        )
        compact = {
            "id": event.get("id"),
            "type": event.get("type"),
            "timestamp": event.get("timestamp"),
            "payload": {key: deepcopy(payload.get(key)) for key in keep if key in payload},
        }
        if event.get("item_id"):
            compact["item_id"] = event["item_id"]
        return compact

    def _count_items(self, task: Dict[str, Any], statuses: set) -> int:
        return sum(1 for item in task.get("items", {}).values() if item.get("status") in statuses)

    def _write_plan_artifact(self, task_id: str, item_id: str, plan: Dict[str, Any], generated_at: str) -> Optional[Dict[str, Any]]:
        plan_root = self.plan_root
        if not plan_root:
            return None
        try:
            item_hash = hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:16]
            plan_dir = plan_root / task_id
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_path = plan_dir / f"{item_hash}.json"
            payload = {
                "version": 3,
                "task_id": task_id,
                "item_id": item_id,
                "generated_at": generated_at,
                "plan_digest": plan_digest(plan),
                "baseline": build_plan_baseline(plan),
                "plan": plan,
            }
            payload["artifact_digest"] = plan_artifact_digest(payload)
            tmp_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(plan_path)
            return {"path": plan_path, "digest": payload["plan_digest"]}
        except Exception as exc:
            logging.warning("Failed to write plan artifact for task %s item %s: %s", task_id, item_id, exc)
            return None

    def _compact_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Keep task snapshots light while preserving a useful UI preview.

        The complete plan is written as an artifact before this compact version
        is stored in the task ledger.
        """
        if not isinstance(plan, dict):
            return {}
        compact = {
            key: deepcopy(plan.get(key))
            for key in ("media_type", "title", "year", "source_path", "target_root", "mode", "operation_scope", "conflict_strategy", "rollback_available", "artwork", "nfo", "summary", "review")
            if key in plan
        }
        compact["diagnostics"] = deepcopy((plan.get("diagnostics") or [])[:10])
        compact["actions"] = deepcopy((plan.get("actions") or [])[:5])
        compact["conflicts"] = deepcopy((plan.get("conflicts") or [])[:5])
        compact["risks"] = deepcopy((plan.get("risks") or [])[:5])
        compact["missing_episodes"] = deepcopy((plan.get("missing_episodes") or [])[:20])
        compact["compact"] = True
        compact["full_plan_available"] = True
        return compact

    def _compact_loaded_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task = deepcopy(task)
        task["events"] = task.get("events", [])[-self.max_events_per_task:]
        for event in task.get("events", []):
            payload = event.get("payload")
            if isinstance(payload, dict) and "plan" in payload:
                payload["plan"] = self._compact_plan(payload.get("plan") or {})
        for item in task.get("items", {}).values():
            if isinstance(item, dict) and "plan" in item:
                item["plan"] = self._compact_plan(item.get("plan") or {})
        return task

    def _prune_tasks_locked(self) -> bool:
        if self.max_tasks <= 0 or len(self._tasks) <= self.max_tasks:
            return False
        sorted_items = sorted(
            self._tasks.items(),
            key=lambda item: item[1].get("updated_at") or item[1].get("created_at", ""),
            reverse=True,
        )
        self._tasks = dict(sorted_items[:self.max_tasks])
        return True

    def _load(self) -> None:
        if not self.storage_path:
            return
        if self._sqlite_ledger:
            try:
                self._tasks = {
                    task_id: self._compact_loaded_task(task)
                    for task_id, task in self._sqlite_ledger.load_tasks(self.max_events_per_task).items()
                }
                if not self._tasks:
                    self._load_legacy_json()
                    if self._tasks:
                        with self._lock:
                            self._prune_tasks_locked()
                            self._persist_locked()
                else:
                    with self._lock:
                        self._prune_tasks_locked()
                return
            except Exception as exc:
                logging.warning("Failed to load SQLite task event store from %s: %s", self.storage_path, exc)
                return
        if not self.storage_path.exists():
            return
        self._load_json(self.storage_path)

    def _load_legacy_json(self) -> None:
        if self.legacy_storage_path and self.legacy_storage_path.exists():
            self._load_json(self.legacy_storage_path)

    def _load_json(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tasks = data.get("tasks", {})
            if isinstance(tasks, dict):
                self._tasks = {
                    str(task_id): self._compact_loaded_task(task)
                    for task_id, task in tasks.items()
                    if isinstance(task, dict)
                }
                with self._lock:
                    self._prune_tasks_locked()
        except Exception as exc:
            logging.warning("Failed to load task event store from %s: %s", path, exc)

    def _persist_locked(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if self._sqlite_ledger:
                self._sqlite_ledger.persist_tasks(self._tasks.values())
                return
            payload = {
                "version": 1,
                "updated_at": _utc_now(),
                "tasks": self._tasks,
            }
            tmp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp_path.replace(self.storage_path)
        except Exception as exc:
            logging.warning("Failed to persist task event store to %s: %s", self.storage_path, exc)

    def _persist_task_locked(self, task: Dict[str, Any]) -> None:
        if not self.storage_path:
            return
        if self._sqlite_ledger:
            try:
                self._sqlite_ledger.persist_task(task)
            except Exception as exc:
                logging.warning("Failed to persist task %s to %s: %s", task.get("id"), self.storage_path, exc)
            return
        self._persist_locked()

    def _broadcast(self, event: Dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        if not subscribers:
            return

        def send() -> None:
            for queue in subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(send)
        else:
            send()


task_event_store = TaskEventStore()
