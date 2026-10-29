"""
DistributedProcess implementation for Lamport's Mutual Exclusion Algorithm.
Maintains local Lamport logical clock, local request queue, state, and message accounting.
"""

from typing import List, Set, Optional, Tuple, Dict, Any
from .models import Message, MessageType, ProcessState, RequestEntry


class DistributedProcess:
    """
    Represents an independent distributed process participating in mutual exclusion.
    
    Each process maintains:
      - A Lamport logical clock (monotonically non-decreasing integer).
      - A private local request queue ordered by (timestamp, process_id).
      - Its current state: RELEASED, REQUESTING, WAITING, or IN_CRITICAL_SECTION.
      - A set of replies received for its active resource request.
    """

    uses_request_queue = True

    def __init__(self, pid: int):
        self.pid: int = pid
        self.clock: int = 0
        self.state: ProcessState = ProcessState.RELEASED
        self.request_queue: List[RequestEntry] = []
        self.replies_received: Set[int] = set()
        self.current_request: Optional[RequestEntry] = None
        
        # Performance & accounting statistics
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.cs_entry_count: int = 0
        self.cs_ticks_remaining: int = 0
        self.request_submitted_step: Optional[int] = None
        self.total_wait_steps: int = 0
        self.completed_requests: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the process state for API and frontend visualization."""
        return {
            "pid": self.pid,
            "name": f"P{self.pid}",
            "clock": self.clock,
            "state": self.state.value,
            "request_queue": [entry.to_dict() for entry in self.request_queue],
            "replies_received": sorted(list(self.replies_received)),
            "replies_count": len(self.replies_received),
            "current_request": self.current_request.to_dict() if self.current_request else None,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "cs_entry_count": self.cs_entry_count,
            "cs_ticks_remaining": self.cs_ticks_remaining,
            "request_submitted_step": self.request_submitted_step,
            "total_wait_steps": self.total_wait_steps,
            "completed_requests": self.completed_requests,
        }

    def reset(self) -> None:
        """Resets the process to initial state."""
        self.clock = 0
        self.state = ProcessState.RELEASED
        self.request_queue.clear()
        self.replies_received.clear()
        self.current_request = None
        self.messages_sent = 0
        self.messages_received = 0
        self.cs_entry_count = 0
        self.cs_ticks_remaining = 0
        self.request_submitted_step = None
        self.total_wait_steps = 0
        self.completed_requests = 0

    def tick_clock(self) -> int:
        """
        Increments the local clock for an internal event.
        Returns the updated clock value.
        """
        self.clock += 1
        return self.clock

    def update_clock_on_receive(self, incoming_timestamp: int) -> int:
        """
        Standard Lamport Logical Clock update rule on receiving a message with timestamp T:
        clock = max(local_clock, T) + 1
        """
        self.clock = max(self.clock, incoming_timestamp) + 1
        return self.clock

    def _insert_into_queue(self, entry: RequestEntry) -> None:
        """
        Inserts a request entry into the local request queue in ascending order:
          1. Smaller timestamp first.
          2. Smaller process ID if timestamps are equal.
        Avoids duplicate entries for the same process.
        """
        # Remove any existing entry for this process ID to avoid stale requests
        self.request_queue = [e for e in self.request_queue if e.process_id != entry.process_id]
        self.request_queue.append(entry)
        # Sort queue by (timestamp, process_id)
        self.request_queue.sort(key=lambda req: (req.timestamp, req.process_id))

    def _remove_from_queue(self, process_id: int) -> bool:
        """Removes the request for the given process ID from the local queue."""
        initial_len = len(self.request_queue)
        self.request_queue = [e for e in self.request_queue if e.process_id != process_id]
        return len(self.request_queue) < initial_len

    def request_resource(self, all_pids: List[int], step: int) -> Tuple[bool, str, List[Message]]:
        """
        Initiates a request for the shared resource (Critical Section).
        
        Algorithm Steps:
          1. Increment local logical clock: C = C + 1
          2. Create timestamped request: (C, pid)
          3. Insert request into local request queue
          4. Broadcast REQUEST(C, pid) to all other active processes
        """
        if self.state != ProcessState.RELEASED:
            return False, f"Process P{self.pid} is already {self.state.value} and cannot request again.", []

        # 1. Increment local logical clock
        self.tick_clock()

        # 2. Create request entry
        req_entry = RequestEntry(timestamp=self.clock, process_id=self.pid)
        self.current_request = req_entry
        self.request_submitted_step = step

        # 3. Insert into local queue
        if self.uses_request_queue:
            self._insert_into_queue(req_entry)

        # 4. Update state and clear replies
        self.state = ProcessState.REQUESTING
        self.replies_received.clear()

        # 5. Broadcast REQUEST messages to all other processes
        messages: List[Message] = []
        for peer_id in all_pids:
            if peer_id != self.pid:
                msg = Message.create(
                    msg_type=MessageType.REQUEST,
                    sender_id=self.pid,
                    receiver_id=peer_id,
                    timestamp=self.clock,
                    req_timestamp=self.clock,
                    step_created=step
                )
                messages.append(msg)

        self.messages_sent += len(messages)
        return True, f"Process P{self.pid} created request at timestamp {self.clock} and broadcasted REQUEST to {len(messages)} peers.", messages

    def handle_request_message(self, msg: Message, step: int) -> Message:
        """
        Handles an incoming REQUEST message from another process.
        
        Algorithm Steps:
          1. Update local logical clock: clock = max(clock, msg.timestamp) + 1
          2. Insert received request (req_timestamp, sender_id) into local queue
          3. Send a timestamped REPLY message back to the requesting process
        """
        self.messages_received += 1
        
        # 1. Update clock
        self.update_clock_on_receive(msg.timestamp)

        # 2. Insert sender's request into local queue
        incoming_req = RequestEntry(timestamp=msg.req_timestamp, process_id=msg.sender_id)
        self._insert_into_queue(incoming_req)

        # 3. Create REPLY message with updated clock
        reply_msg = Message.create(
            msg_type=MessageType.REPLY,
            sender_id=self.pid,
            receiver_id=msg.sender_id,
            timestamp=self.clock,
            req_timestamp=msg.req_timestamp,
            step_created=step
        )
        self.messages_sent += 1
        return reply_msg

    def handle_reply_message(
        self,
        msg: Message,
        step: int,
        total_processes: Optional[int] = None,
        all_pids: Optional[List[int]] = None
    ) -> None:
        """
        Handles an incoming REPLY message from a peer.
        
        Algorithm Steps:
          1. Update local logical clock: clock = max(clock, msg.timestamp) + 1
          2. Reject self-replies or stale replies for older requests.
          3. Record reply in self.replies_received by peer PID.
          4. If all required replies are collected, transition to WAITING state.
        """
        self.messages_received += 1
        
        # 1. Update clock
        self.update_clock_on_receive(msg.timestamp)

        # 2. Reject self-reply to guarantee Point 6: sender identity tracking
        if msg.sender_id == self.pid:
            return

        # 3. Record reply if we have an active request matching the request timestamp
        if self.current_request is not None and msg.req_timestamp == self.current_request.timestamp:
            self.replies_received.add(msg.sender_id)
            
            # 4. Check if all replies gathered; if so and still waiting for queue head, set WAITING
            needed_count = len(all_pids) - 1 if all_pids else (total_processes - 1 if total_processes else None)
            if needed_count is not None and len(self.replies_received) >= needed_count:
                if self.state == ProcessState.REQUESTING:
                    self.state = ProcessState.WAITING

    def handle_release_message(self, msg: Message, step: int) -> None:
        """
        Handles an incoming RELEASE message.
        
        Algorithm Steps:
          1. Update local logical clock: clock = max(clock, msg.timestamp) + 1
          2. Remove the sender's request from local request queue
        """
        self.messages_received += 1
        
        # 1. Update clock
        self.update_clock_on_receive(msg.timestamp)

        # 2. Remove sender's request from local queue
        self._remove_from_queue(msg.sender_id)

    def can_enter_critical_section(
        self,
        total_processes: int,
        all_pids: Optional[List[int]] = None
    ) -> Tuple[bool, str]:
        """
        Checks Lamport's two necessary and sufficient conditions for entering Critical Section:
        
        Condition 1: Process's own request (T, pid) is at the HEAD of its local request queue.
        Condition 2: Process has received REPLY messages from ALL other (N-1) active processes.
                     Tracked by exact sender PID to prevent duplicates or phantom replies.
        """
        if self.state not in (ProcessState.REQUESTING, ProcessState.WAITING):
            return False, f"Process P{self.pid} is in state {self.state.value}, not waiting for CS."

        if self.current_request is None:
            return False, f"Process P{self.pid} has no active request."

        if not self.request_queue:
            return False, f"Process P{self.pid}'s request queue is empty."

        head_entry = self.request_queue[0]
        is_at_head = (head_entry.process_id == self.pid and head_entry.timestamp == self.current_request.timestamp)
        if not is_at_head:
            return False, f"Request {self.current_request} is not at head of queue (Head is {head_entry})."

        # Verify replies by sender identity
        if all_pids is not None:
            expected_peers = {p for p in all_pids if p != self.pid}
            missing = expected_peers - self.replies_received
            if missing:
                return False, f"Missing required replies from peers: {sorted(list(missing))}."
        else:
            required_replies = total_processes - 1
            if len(self.replies_received) < required_replies:
                return False, f"Received {len(self.replies_received)}/{required_replies} required replies."

        return True, "Both Lamport conditions satisfied: at head of queue and received all required replies."

    def enter_critical_section(self, duration: int, current_step: int) -> None:
        """Transitions the process into the Critical Section."""
        self.state = ProcessState.IN_CRITICAL_SECTION
        self.cs_ticks_remaining = max(1, duration)
        self.cs_entry_count += 1
        if self.request_submitted_step is not None:
            self.total_wait_steps += max(0, current_step - self.request_submitted_step)

    def decrement_cs_tick(self) -> int:
        """Decrements remaining Critical Section duration. Returns remaining ticks."""
        if self.state == ProcessState.IN_CRITICAL_SECTION and self.cs_ticks_remaining > 0:
            self.cs_ticks_remaining -= 1
        return self.cs_ticks_remaining

    def release_critical_section(self, all_pids: List[int], step: int) -> Tuple[bool, str, List[Message]]:
        """
        Releases the Critical Section and broadcasts RELEASE messages.
        
        Algorithm Steps:
          1. Set state to RELEASED
          2. Remove own request from local request queue
          3. Clear current request and received replies
          4. Increment local logical clock: C = C + 1
          5. Broadcast RELEASE(C, pid) to all other active processes
        """
        if self.state != ProcessState.IN_CRITICAL_SECTION:
            return False, f"Process P{self.pid} is not in Critical Section (current state: {self.state.value}).", []

        # 1. State change
        self.state = ProcessState.RELEASED
        self.completed_requests += 1

        # 2. Remove own request from queue
        self._remove_from_queue(self.pid)
        self.current_request = None
        self.replies_received.clear()
        self.cs_ticks_remaining = 0
        self.request_submitted_step = None

        # 3. Increment clock
        self.tick_clock()

        # 4. Broadcast RELEASE messages
        messages: List[Message] = []
        for peer_id in all_pids:
            if peer_id != self.pid:
                msg = Message.create(
                    msg_type=MessageType.RELEASE,
                    sender_id=self.pid,
                    receiver_id=peer_id,
                    timestamp=self.clock,
                    req_timestamp=self.clock,
                    step_created=step
                )
                messages.append(msg)

        self.messages_sent += len(messages)
        return True, f"Process P{self.pid} exited Critical Section and broadcasted RELEASE to {len(messages)} peers.", messages
