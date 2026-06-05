import asyncio
import hashlib
import json
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional


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
        storage_path: Optional[str] = "logs/task_events.json",
        max_tasks: int = 50,
    ):
        self.max_events_per_task = max_events_per_task
        self.max_tasks = max_tasks
        self.storage_path = Path(storage_path) if storage_path else None
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._subscribers: List[asyncio.Queue] = []
        self._lock = RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._load()

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
            self._persist_locked()
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
            self._prune_tasks_locked()
            self._persist_locked()
            snapshot_event = deepcopy(event)

        self._broadcast(snapshot_event)
        return snapshot_event

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                self._without_events(task)
                for task in sorted(
                    self._tasks.values(),
                    key=lambda item: item.get("created_at", ""),
                    reverse=True,
                )
            ]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return deepcopy(task) if task else None

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
        return json.loads(resolved_plan_path.read_text(encoding="utf-8"))

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

    def _apply_event(self, task: Dict[str, Any], event: Dict[str, Any]) -> None:
        event_type = event["type"]
        payload = event.get("payload", {})
        item_id = event.get("item_id")

        if event_type in {"task.started", "task.scan.started"}:
            task["status"] = "running"
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
        elif event_type == "task.rollback_completed":
            task["rollback"] = payload
            task["status"] = "stopped"
            rollback_status = payload.get("status") or "partial"
            rollback_result = "已回滚" if rollback_status == "completed" else f"回滚{rollback_status}"
            for item in task.get("items", {}).values():
                item["status"] = "stopped"
                item["result"] = rollback_result
                item["rollback"] = payload
                item["updated_at"] = event["timestamp"]

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
                plan_path = self._write_plan_artifact(task["id"], item_id, full_plan, event["timestamp"])
                compact_plan = self._compact_plan(full_plan)
                item["plan"] = compact_plan
                if plan_path:
                    payload["plan_path"] = str(plan_path)
                    item["plan_path"] = str(plan_path)
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
            elif event_type == "item.completed":
                item.update(payload)
                item["status"] = "completed"
                task["summary"]["completed"] = self._count_items(task, {"completed", "audit_completed"})
            elif event_type == "item.failed":
                item.update(payload)
                item["status"] = "failed"
                task["summary"]["failed"] = self._count_items(task, {"failed"})
            elif event_type == "item.skipped":
                item.update(payload)
                item["status"] = "skipped"
                task["summary"]["completed"] = self._count_items(task, {"completed", "audit_completed", "skipped"})

    def _count_items(self, task: Dict[str, Any], statuses: set) -> int:
        return sum(1 for item in task.get("items", {}).values() if item.get("status") in statuses)

    def _write_plan_artifact(self, task_id: str, item_id: str, plan: Dict[str, Any], generated_at: str) -> Optional[Path]:
        plan_root = self.plan_root
        if not plan_root:
            return None
        try:
            item_hash = hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:16]
            plan_dir = plan_root / task_id
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_path = plan_dir / f"{item_hash}.json"
            payload = {
                "version": 1,
                "task_id": task_id,
                "item_id": item_id,
                "generated_at": generated_at,
                "plan": plan,
            }
            tmp_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            tmp_path.replace(plan_path)
            return plan_path
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
            for key in ("media_type", "title", "year", "source_path", "target_root", "mode", "rollback_available", "artwork", "summary")
            if key in plan
        }
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

    def _prune_tasks_locked(self) -> None:
        if self.max_tasks <= 0 or len(self._tasks) <= self.max_tasks:
            return
        sorted_items = sorted(
            self._tasks.items(),
            key=lambda item: item[1].get("updated_at") or item[1].get("created_at", ""),
            reverse=True,
        )
        self._tasks = dict(sorted_items[:self.max_tasks])

    def _load(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
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
            logging.warning("Failed to load task event store from %s: %s", self.storage_path, exc)

    def _persist_locked(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
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
