"""Persistent repositories used by the metadata service."""

from src.storage.task_ledger import SQLiteTaskLedger

__all__ = ["SQLiteTaskLedger"]
