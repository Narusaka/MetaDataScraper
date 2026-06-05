import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional


class DirectoryLockError(RuntimeError):
    def __init__(self, target_path: Path, lock_path: Path, owner: Optional[dict] = None):
        self.target_path = target_path
        self.lock_path = lock_path
        self.owner = owner or {}
        owner_label = self.owner.get("owner") or self.owner.get("task_id") or "another task"
        super().__init__(f"Target is locked by {owner_label}: {target_path}")


class DirectoryLock:
    """Small cross-process lock for media target paths."""

    def __init__(self, target_path: Path, owner: Optional[str] = None, stale_after_seconds: int = 12 * 60 * 60):
        self.target_path = Path(target_path)
        self.owner = owner or str(os.getpid())
        self.stale_after_seconds = stale_after_seconds
        self.token = uuid.uuid4().hex
        self.lock_path = self._lock_path_for(self.target_path)
        self.acquired = False

    @staticmethod
    def _lock_path_for(target_path: Path) -> Path:
        safe_name = target_path.name or "root"
        lock_dir = target_path.parent / ".metadata-scraper-locks"
        return lock_dir / f"{safe_name}.lock"

    def acquire(self) -> "DirectoryLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "target_path": str(self.target_path),
            "owner": self.owner,
            "pid": os.getpid(),
            "token": self.token,
            "created_at": time.time(),
        }

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(str(self.lock_path), flags, 0o644)
        except FileExistsError:
            existing = self._read_owner()
            if self._is_stale(existing):
                try:
                    self.lock_path.unlink()
                except FileNotFoundError:
                    pass
                return self.acquire()
            raise DirectoryLockError(self.target_path, self.lock_path, existing)

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())

        self.acquired = True
        return self

    def release(self) -> None:
        if not self.acquired:
            return

        existing = self._read_owner()
        if existing.get("token") == self.token:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
            try:
                self.lock_path.parent.rmdir()
            except OSError:
                pass
        self.acquired = False

    def _read_owner(self) -> dict:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _is_stale(self, owner: dict) -> bool:
        created_at = owner.get("created_at")
        if not isinstance(created_at, (int, float)):
            return False
        return time.time() - created_at > self.stale_after_seconds

    def __enter__(self) -> "DirectoryLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
