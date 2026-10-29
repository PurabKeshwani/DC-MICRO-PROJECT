"""Ricart–Agrawala: local priority comparisons and deferred REPLY messages."""

from typing import Dict, List, Optional, Tuple
from .models import Message, MessageType, ProcessState, RequestEntry
from .process import DistributedProcess


class RicartAgrawalaProcess(DistributedProcess):
    # Reuse clocks, request broadcasts, reply tracking, and CS accounting.
    # This protocol does not maintain Lamport's replicated request queue.
    uses_request_queue = False

    def __init__(self, pid: int):
        super().__init__(pid)
        self.deferred_replies: Dict[int, RequestEntry] = {}

    def to_dict(self):
        return {
            **super().to_dict(),
            "deferred_replies": [request.to_dict() for request in sorted(self.deferred_replies.values())],
        }

    def reset(self) -> None:
        super().reset()
        self.deferred_replies.clear()

    def handle_request_message(self, msg: Message, step: int) -> Optional[Message]:
        self.messages_received += 1
        self.update_clock_on_receive(msg.timestamp)
        incoming = RequestEntry(msg.req_timestamp, msg.sender_id)
        # Compare the fixed request timestamp, never the clock after receipt.
        own_request_first = self.current_request is not None and self.current_request < incoming
        if self.state == ProcessState.IN_CRITICAL_SECTION or own_request_first:
            self.deferred_replies[msg.sender_id] = incoming
            return None

        self.messages_sent += 1
        return Message.create(
            MessageType.REPLY, self.pid, msg.sender_id,
            self.clock, msg.req_timestamp, step_created=step,
        )

    def can_enter_critical_section(
        self, total_processes: int, all_pids: Optional[List[int]] = None,
    ) -> Tuple[bool, str]:
        if self.state not in (ProcessState.REQUESTING, ProcessState.WAITING) or self.current_request is None:
            return False, "No active request waiting to enter."
        if all_pids is not None:
            missing = set(all_pids) - {self.pid} - self.replies_received
            if missing:
                return False, f"Missing required replies from peers: {sorted(missing)}."
        elif len(self.replies_received) < total_processes - 1:
            return False, f"Received {len(self.replies_received)}/{total_processes - 1} required replies."
        return True, "Received REPLY from every other process."

    def release_critical_section(self, all_pids: List[int], step: int):
        if self.state != ProcessState.IN_CRITICAL_SECTION:
            return False, f"P{self.pid} is not inside the critical section.", []
        self.state = ProcessState.RELEASED
        self.completed_requests += 1
        self.current_request = None
        self.replies_received.clear()
        self.cs_ticks_remaining = 0
        self.request_submitted_step = None
        self.tick_clock()
        messages = [
            Message.create(
                MessageType.REPLY, self.pid, request.process_id,
                self.clock, request.timestamp, step_created=step,
            )
            for request in sorted(self.deferred_replies.values())
        ]
        self.deferred_replies.clear()
        self.messages_sent += len(messages)
        return True, f"P{self.pid} exited and sent {len(messages)} deferred REPLY messages.", messages


def get_ricart_agrawala_stages():
    return [
        {"stage": 1, "title": "Stage 1: Create a request", "description": "Increment the local logical clock and save the request's timestamp. This timestamp stays fixed while waiting."},
        {"stage": 2, "title": "Stage 2: Broadcast REQUEST", "description": "Send REQUEST(timestamp, PID) to every other process. Each receiver updates its logical clock."},
        {"stage": 3, "title": "Stage 3: Reply now or defer", "description": "An idle process replies immediately. A process inside CS defers. A requesting process defers only if its own (timestamp, PID) is smaller than the incoming request."},
        {"stage": 4, "title": "Stage 4: Collect peer replies", "description": "Track one REPLY from each of the N − 1 other processes for the current request. Deferred replies arrive after the holder exits."},
        {"stage": 5, "title": "Stage 5: Enter the critical section", "description": "Enter after receiving every peer's REPLY. There is no replicated request queue or queue-head condition."},
        {"stage": 6, "title": "Stage 6: Send deferred replies", "description": "On exit, send a REPLY to every process whose request was deferred, then clear the deferred list. No RELEASE message is broadcast."},
    ]
