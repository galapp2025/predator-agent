"""Call Queue — תור שיחות (יוצאות + נכנסות מסומנות)"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("call-queue")


@dataclass
class QueueItem:
    priority: int
    session_id: str
    payload: dict
    item_type: str = "outbound"
    enqueued_at: str = field(default_factory=lambda: datetime.now().isoformat())
    attempts: int = 0


class CallQueue:
    """תור מאוחד. עדיפויות: whitelisted_inbound > inbound > outbound."""

    PRIORITY_WHITELISTED_INBOUND = 3
    PRIORITY_INBOUND = 2
    PRIORITY_OUTBOUND = 1

    def __init__(self, agent=None, max_size: int = 100):
        self.agent = agent
        self.max_size = max_size
        self._queue: deque[QueueItem] = deque()
        self._paused = False

    def _sort(self) -> None:
        # עדיפות גבוהה קודם, ואז FIFO בתוך אותה עדיפות
        self._queue = deque(
            sorted(self._queue, key=lambda x: (-x.priority, x.enqueued_at))
        )

    def enqueue(self, item: QueueItem) -> bool:
        if len(self._queue) >= self.max_size:
            logger.warning("Queue full, dropping item")
            return False
        self._queue.append(item)
        self._sort()
        logger.info(
            "[queue] enqueued %s priority=%s session=%s size=%s",
            item.item_type,
            item.priority,
            item.session_id,
            len(self._queue),
        )
        return True

    def enqueue_outbound(self, lead: dict) -> bool:
        phone = lead.get("phone", "unknown")
        return self.enqueue(
            QueueItem(
                priority=self.PRIORITY_OUTBOUND,
                session_id=f"out-{phone}",
                payload=lead,
                item_type="outbound",
            )
        )

    def enqueue_inbound(self, caller_phone: str, is_whitelisted: bool = False) -> bool:
        if is_whitelisted:
            priority = self.PRIORITY_WHITELISTED_INBOUND
            item_type = "whitelisted_inbound"
        else:
            priority = self.PRIORITY_INBOUND
            item_type = "inbound"

        return self.enqueue(
            QueueItem(
                priority=priority,
                session_id=f"in-{caller_phone}",
                payload={"caller_phone": caller_phone, "is_whitelisted": is_whitelisted},
                item_type=item_type,
            )
        )

    def dequeue(self) -> Optional[QueueItem]:
        if self._paused or not self._queue:
            return None
        item = self._queue.popleft()
        item.attempts += 1
        return item

    def pause(self) -> None:
        self._paused = True
        logger.info("Queue paused")

    def resume(self) -> None:
        self._paused = False
        logger.info("Queue resumed")

    def get_size(self) -> int:
        return len(self._queue)

    def stats(self) -> dict:
        return {
            "total": len(self._queue),
            "outbound": sum(1 for i in self._queue if i.item_type == "outbound"),
            "inbound": sum(
                1
                for i in self._queue
                if i.item_type in ("inbound", "whitelisted_inbound")
            ),
            "whitelisted_inbound": sum(
                1 for i in self._queue if i.item_type == "whitelisted_inbound"
            ),
            "paused": self._paused,
        }

    def inbound_first(self):
        inbounds = [
            i
            for i in self._queue
            if i.item_type in ("inbound", "whitelisted_inbound")
        ]
        outbounds = [i for i in self._queue if i.item_type == "outbound"]
        return inbounds, outbounds
