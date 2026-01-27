import logging
import asyncio
from typing import List

class LogBroadcaster(logging.Handler):
    """
    A custom logging handler that broadcasts log records to connected WebSocket clients.
    """
    def __init__(self):
        super().__init__()
        self.queues: List[asyncio.Queue] = []
        self.loop = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def emit(self, record: logging.LogRecord):
        if not self.queues or not self.loop:
            return
        
        try:
            log_entry = self.format(record)
            # Use call_soon_threadsafe to interact with asyncio loop from sync logging
            self.loop.call_soon_threadsafe(self._broadcast, log_entry)
        except Exception:
            self.handleError(record)

    def _broadcast(self, message: str):
        for q in self.queues:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass # Drop logs if client is too slow

    async def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=1000)
        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.queues:
            self.queues.remove(q)

# Global Instance
log_broadcaster = LogBroadcaster()
formatter = logging.Formatter('%(asctime)s [%(threadName)s] %(levelname)s - %(message)s')
log_broadcaster.setFormatter(formatter)
