"""Call Queue — תור שיחות (יוצאות + נכנסות מסומנות)"""
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..agent.predator import PredatorAgent

logger = logging.getLogger("call-queue")


@dataclass
class QueueItem:
    priority: int
    session_id: str
    payload: dict
    item_type: str = "outbound"  # outbound | inbound | whitelisted_inbound
    enqueued_at: str = field(default_factory=lambda: datetime.now().isoformat())
    attempts: int = 0


class CallQueue:
    """
    תור מאוחד לכל סוגי השיחות.
    סדר עדיפויות:
      1. whitelisted_inbound (בוחר שסומן מראש שמחזיר שיחה)
      2. inbound (כל שיחה נכנסת)
      3. outbound (חיוג יוצא לפי leads.csv)
    """

    PRIORITY_WHITELISTED_INBOUND = 3
    PRIORITY_INBOUND = 2
    PRIORITY_OUTBOUND = 1

    def __init__(self, agent: PredatorAgent, max_size: int = 100):
        self.agent = agent
        self.max_size = max_size
        self._queue: deque = deque()
        self._paused = False
        self._processing = False

    def enqueue(self, item: QueueItem) -> bool:
        if len(self._queue) >= self.max_size:
            logger.warning("Queue full, dropping item")
            return False
        self._queue.append(item)
        self._queue = deque(
            sorted(self._queue, key=lambda x: (-x.priority, x.enqueued_at))
        )
        logger.info(
            f"[queue] enqueued {item.item_type} priority={item.priority} "
            f"session={item.session_id} size={len(self._queue)}"
        )
        return True

    def enqueue_outbound(self, lead: dict) -> bool:
        return self.enqueue(QueueItem(
            priority=self.PRIORITY_OUTBOUND,
            session_id=f"out-{lead.get('phone', 'unknown')}",
            payload=lead,
            item_type="outbound",
        ))

    def enqueue_inbound(self, caller_phone: str, is_whitelisted: bool = False) -> bool:
        priority = (
            self.PRIORITY_WHITELISTED_INBOUND if is_whitelisted else self.PRIORITY_INBOUND
        )
        item_type = "whitelisted_inbound" if is_whitelisted else "inbound"
        return self.enqueue(QueueItem(
            priority=priority,
            session_id=f"in-{caller_phone}",
            payload={"caller_phone": caller_phone},
            item_type=item_type,
        ))

    def dequeue(self) -> Optional[QueueItem]:
        if self._paused or not self._queue:
            return None
        item = self._queue.popleft()
        item.attempts += 1
        return item

    def pause(self):
        self._paused = True
        logger.info("Queue paused")

    def resume(self):
        self._paused = False
        logger.info("Queue resumed")

    def get_size(self) -> int:
        return len(self._queue)

    def stats(self) -> dict:
        inbounds = sum(1 for i in self._queue if i.item_type in ("inbound", "whitelisted_inbound"))
        outbounds = sum(1 for i in self._queue if i.item_type == "outbound")
        whitelisted = sum(1 for i in self._queue if i.item_type == "whitelisted_inbound")
        return {
            "total": len(self._queue),
            "outbound": outbounds,
            "inbound": inbounds,
            "whitelisted_inbound": whitelisted,
            "paused": self._paused,
        }

    def inbound_first(self):
        inbounds = [i for i in self._queue if i.item_type in ("inbound", "whitelisted_inbound")]
        outbounds = [i for i in self._queue if i.item_type == "outbound"]
        return inbounds, outbounds
