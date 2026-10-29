"""
Simulated distributed message passing layer.
Maintains in-transit message queues and message history.
Modular design allows substituting with actual socket/network transport.
"""

from typing import List, Optional, Dict, Any
from collections import deque
import threading
from .models import Message


class MessageNetwork:
    """
    Simulates asynchronous network transmission of messages between distributed processes.
    Provides thread-safe enqueuing, step-by-step dequeueing, and delivery history tracking.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._in_transit: deque[Message] = deque()
        self._history: List[Message] = []

    def send(self, message: Message) -> None:
        """Enqueues a message for in-transit transmission."""
        with self._lock:
            self._in_transit.append(message)
            self._history.append(message)

    def send_batch(self, messages: List[Message]) -> None:
        """Enqueues multiple messages for in-transit transmission."""
        with self._lock:
            for msg in messages:
                self.send(msg)

    def pop_next(self) -> Optional[Message]:
        """Pops the next pending message to be delivered."""
        with self._lock:
            if self._in_transit:
                return self._in_transit.popleft()
            return None

    def peek_next(self) -> Optional[Message]:
        """Peeks at the next message in queue without popping it."""
        with self._lock:
            if self._in_transit:
                return self._in_transit[0]
            return None

    def has_pending(self) -> bool:
        """Returns True if there are messages waiting in transit."""
        with self._lock:
            return len(self._in_transit) > 0

    def pending_count(self) -> int:
        """Returns the number of messages currently in transit."""
        with self._lock:
            return len(self._in_transit)

    def reverse_pending(self) -> None:
        """Reverses the order of in-transit messages to simulate reverse arrival."""
        with self._lock:
            self._in_transit.reverse()

    def shuffle_pending(self, seed: Optional[int] = None) -> None:
        """Shuffles in-transit messages to simulate non-deterministic network delays."""
        import random
        with self._lock:
            rng = random.Random(seed) if seed is not None else random
            msg_list = list(self._in_transit)
            rng.shuffle(msg_list)
            self._in_transit = deque(msg_list)

    def pop_specific(self, msg_id: str) -> Optional[Message]:
        """Pops a specific message by ID to simulate targeted out-of-order delivery."""
        with self._lock:
            for i, msg in enumerate(self._in_transit):
                if msg.id == msg_id:
                    del self._in_transit[i]
                    return msg
            return None

    def mark_delivered(self, message: Message, step: int) -> None:
        """Marks a message as delivered with the delivery step."""
        with self._lock:
            message.status = "delivered"
            message.step_delivered = step

    def get_in_transit(self) -> List[Dict[str, Any]]:
        """Returns list of currently pending in-transit messages."""
        with self._lock:
            return [m.to_dict() for m in self._in_transit]

    def get_history(self, limit: int = 150) -> List[Dict[str, Any]]:
        """Returns reverse-chronological list of messages."""
        with self._lock:
            items = list(self._history)
            if limit > 0:
                items = items[-limit:]
            return [m.to_dict() for m in reversed(items)]

    def total_messages_count(self) -> int:
        """Returns the total number of messages sent since initialization."""
        with self._lock:
            return len(self._history)

    def clear(self) -> None:
        """Resets the network queues."""
        with self._lock:
            self._in_transit.clear()
            self._history.clear()
