from threading import Event
from typing import Optional


class OperationCancelled(RuntimeError):
    def __init__(self, stage: str = "unknown"):
        self.stage = stage
        super().__init__(f"Operation cancelled during {stage}")


def raise_if_cancelled(cancel_event: Optional[Event], stage: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled(stage)
