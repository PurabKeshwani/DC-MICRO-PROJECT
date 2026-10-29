"""
SimulationCoordinator manages distributed processes, message passing,
event logs, automatic execution, step-by-step stepping, and invariant verification.
"""

from typing import Dict, List, Optional, Any, Tuple
import threading
import time
import random

from .models import Message, MessageType, ProcessState, RequestEntry, Event
from .process import DistributedProcess
from .message_network import MessageNetwork
from .lamport_algorithm import verify_mutual_exclusion, get_algorithm_stages
from .ricart_agrawala import RicartAgrawalaProcess, get_ricart_agrawala_stages

ALGORITHM_NAMES = {"lamport": "Lamport", "ricart_agrawala": "Ricart–Agrawala"}


class SimulationCoordinator:
    """
    Central controller managing all distributed processes and message traffic.
    Maintains concurrency control, safety invariant checking, and real-time statistics.
    """

    def __init__(self, process_count: int = 4, cs_duration: int = 3, algorithm: str = "lamport"):
        if algorithm not in ALGORITHM_NAMES:
            raise ValueError("Unknown algorithm.")
        self.algorithm = algorithm
        self._lock = threading.RLock()
        self.process_count: int = max(3, min(8, process_count))
        self.cs_duration: int = max(1, cs_duration)
        self.network = MessageNetwork()
        self.processes: Dict[int, DistributedProcess] = {}
        
        self.step_counter: int = 0
        self.event_counter: int = 0
        self.events: List[Event] = []
        self.live_events: List[Event] = []
        
        # Invariant and statistics tracking
        self.violations_count: int = 0
        self.requests_created: int = 0
        self.cs_entries: int = 0
        self.completed_requests: int = 0
        
        # Automatic simulation controls
        self.is_running: bool = False
        self.speed_ms: int = 1200  # readable default delay between auto steps
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._init_processes()
        self._log_event(
            event_type="SYSTEM",
            process_id=None,
            description=f"Initialized distributed system with {self.process_count} processes (P1 to P{self.process_count}).",
            educational_note=("Every process starts with clock 0 and no deferred replies."
                              if self.algorithm == "ricart_agrawala" else
                              "Every process has an initial Lamport logical clock of 0 and an empty request queue.")
        )

    def _init_processes(self) -> None:
        """Initializes processes P1 through P_n."""
        self.processes.clear()
        process_class = RicartAgrawalaProcess if self.algorithm == "ricart_agrawala" else DistributedProcess
        for pid in range(1, self.process_count + 1):
            self.processes[pid] = process_class(pid=pid)

    def get_algorithm_stages(self):
        return get_ricart_agrawala_stages() if self.algorithm == "ricart_agrawala" else get_algorithm_stages()

    def set_algorithm(self, algorithm: str) -> None:
        if algorithm not in ALGORITHM_NAMES:
            raise ValueError("Choose Lamport or Ricart–Agrawala.")
        with self._lock:
            if algorithm != self.algorithm:
                self.algorithm = algorithm
                self.reset()

    def _log_event(
        self,
        event_type: str,
        process_id: Optional[int],
        description: str,
        educational_note: str,
        details: Optional[Dict[str, Any]] = None
    ) -> Event:
        """Records an event with educational explanation."""
        self.event_counter += 1
        ev = Event(
            id=self.event_counter,
            step=self.step_counter,
            event_type=event_type,
            process_id=process_id,
            description=description,
            educational_note=educational_note,
            details=details or {}
        )
        self.events.append(ev)
        self.live_events.append(ev)
        return ev

    def _check_mutual_exclusion(self) -> None:
        """
        Safety Invariant Check:
        number_of_processes_inside_critical_section <= 1
        """
        is_valid, pids_in_cs = verify_mutual_exclusion(list(self.processes.values()))
        if not is_valid:
            self.violations_count += 1
            self._log_event(
                event_type="SYSTEM",
                process_id=None,
                description=f"CRITICAL SAFETY VIOLATION! Multiple processes in CS simultaneously: {pids_in_cs}",
                educational_note="Safety invariant breached: the selected algorithm must prevent simultaneous CS access."
            )

    def request_resource(self, pid: int) -> Tuple[bool, str]:
        """
        Triggers a resource request from process `pid`.
        Thread-safe entry point.
        """
        with self._lock:
            if pid not in self.processes:
                return False, f"Process P{pid} does not exist."

            proc = self.processes[pid]
            if proc.state != ProcessState.RELEASED:
                return False, f"Process P{pid} already has a request in progress."
            self.live_events.clear()
            clock_before = proc.clock
            all_pids = list(self.processes.keys())
            success, msg_desc, messages = proc.request_resource(all_pids, self.step_counter)
            
            if not success:
                return False, msg_desc

            self.requests_created += 1
            self.network.send_batch(messages)

            self._log_event(
                event_type="REQUEST",
                process_id=pid,
                description=f"P{pid} requested shared resource with timestamp T={proc.clock}.",
                educational_note=(
                    f"Process P{pid} incremented its Lamport clock to {proc.clock}, "
                    + (f"saved its request (T={proc.clock}, P{pid}) and broadcast REQUEST to {len(messages)} peers."
                       if self.algorithm == "ricart_agrawala" else
                       f"queued (T={proc.clock}, P{pid}) locally, and broadcasted REQUEST to {len(messages)} peers.")
                ),
                details={"clock_before": clock_before, "clock_after": proc.clock}
            )

            # Check if this process can enter immediately (only possible in 1-node trivial setup)
            self._evaluate_cs_entries()
            return True, msg_desc

    def trigger_concurrent_requests(self, pids: Optional[List[int]] = None) -> Tuple[bool, str]:
        """
        Triggers resource requests from multiple processes concurrently or in rapid succession.
        Demonstrates Lamport timestamp ordering and tie-breaking by Process ID.
        """
        with self._lock:
            if not pids:
                # Default: pick first two idle processes or P1 and P2
                available = [p.pid for p in self.processes.values() if p.state == ProcessState.RELEASED]
                if len(available) >= 2:
                    pids = available[:2]
                elif len(available) == 1:
                    pids = available
                else:
                    return False, "No processes currently in RELEASED state to issue requests."

            successes = []
            for pid in pids:
                ok, desc = self.request_resource(pid)
                if ok:
                    successes.append(f"P{pid}")

            if successes:
                self._log_event(
                    event_type="SYSTEM",
                    process_id=None,
                    description=f"Concurrent requests initiated for processes: {', '.join(successes)}.",
                    educational_note=(
                        "Concurrent requests are ordered by Lamport timestamp. "
                        "If timestamps are identical, the smaller Process ID wins the tie-breaker."
                    )
                )
                return True, f"Triggered concurrent requests for: {', '.join(successes)}"
            return False, "Failed to issue concurrent requests."

    def _evaluate_cs_entries(self) -> None:
        """
        Each process checks the selected protocol's local entry conditions.
        The coordinator only schedules events and monitors mutual exclusion.
        """
        total_n = len(self.processes)
        all_pids = list(self.processes.keys())

        # Each process checks its own queue and peer replies. The observer view
        # and iteration order do not grant permission to enter.
        for proc in self.processes.values():
            can_enter, reason = proc.can_enter_critical_section(total_n, all_pids)
            if can_enter:
                proc.enter_critical_section(self.cs_duration, self.step_counter)
                self.cs_entries += 1

                self._log_event(
                    event_type="CS_ENTRY",
                    process_id=proc.pid,
                    description=f"P{proc.pid} entered the critical section.",
                    educational_note=(
                        f"P{proc.pid} has received REPLY from all {total_n - 1} peers. It can now enter."
                        if self.algorithm == "ricart_agrawala" else
                        f"Lamport Conditions satisfied for P{proc.pid}: "
                        f"(1) Its request {proc.current_request} is at the head of its queue; and "
                        f"(2) Received REPLY messages from all {total_n - 1} peers."
                    )
                )

        # Monitor the outcome; this check does not grant or deny entry.
        self._check_mutual_exclusion()

    def step(self) -> Dict[str, Any]:
        """
        Advances the simulation by one discrete event:
          Case A: Deliver one pending in-transit message from the network.
          Case B: If no messages, advance critical section execution tick for the active process.
          Case C: Process CS exit and release broadcasting when duration expires.
        """
        with self._lock:
            self.live_events.clear()
            self.step_counter += 1
            step_action = "IDLE"
            action_detail = "System idle. No active messages or processes in Critical Section."

            # Find if any process is currently inside Critical Section
            proc_in_cs: Optional[DistributedProcess] = None
            for p in self.processes.values():
                if p.state == ProcessState.IN_CRITICAL_SECTION:
                    proc_in_cs = p
                    break

            # Prioritize message delivery if messages are pending
            if self.network.has_pending():
                msg = self.network.pop_next()
                if msg:
                    self.network.mark_delivered(msg, self.step_counter)
                    step_action = f"DELIVER_{msg.msg_type.value}"
                    receiver = self.processes.get(msg.receiver_id)

                    if receiver:
                        delivery_details = {
                            "message": msg.to_dict(),
                            "clock_before": receiver.clock,
                        }
                        if msg.msg_type == MessageType.REQUEST:
                            reply_msg = receiver.handle_request_message(msg, self.step_counter)
                            if reply_msg is not None:
                                self.network.send(reply_msg)
                            if self.algorithm == "ricart_agrawala":
                                deferred = reply_msg is None
                                if deferred:
                                    if receiver.state == ProcessState.IN_CRITICAL_SECTION:
                                        reason = f"P{receiver.pid} is inside the critical section."
                                    elif receiver.current_request.timestamp == msg.req_timestamp:
                                        reason = f"Both requests have T={msg.req_timestamp}; lower PID P{receiver.pid} has priority."
                                    else:
                                        reason = f"Its own request {receiver.current_request} has priority over (T={msg.req_timestamp}, P{msg.sender_id})."
                                    note = f"{reason} It holds the reply for P{msg.sender_id} until it exits."
                                else:
                                    note = (
                                        f"P{receiver.pid} has no active request. It sends a REPLY immediately."
                                        if receiver.current_request is None else
                                        f"P{msg.sender_id}'s request (T={msg.req_timestamp}, P{msg.sender_id}) comes before its own {receiver.current_request}. It sends a REPLY immediately."
                                    )
                                action_detail = f"P{receiver.pid} received P{msg.sender_id}'s REQUEST and " + ("deferred its REPLY." if deferred else "sent a REPLY.")
                                self._log_event(
                                    event_type="REQUEST", process_id=receiver.pid,
                                    description=action_detail, educational_note=note,
                                    details={**delivery_details, "clock_after": receiver.clock, "deferred": deferred},
                                )
                            else:
                                action_detail = f"P{receiver.pid} received P{msg.sender_id}'s REQUEST and sent a REPLY."
                                self._log_event(
                                    event_type="REQUEST", process_id=receiver.pid,
                                    description=action_detail,
                                    educational_note=(
                                        f"P{receiver.pid} adds (T={msg.req_timestamp}, P{msg.sender_id}) to its own sorted queue. "
                                        "The REPLY acknowledges the request; it does not give exclusive access."
                                    ),
                                    details={**delivery_details, "clock_after": receiver.clock},
                                )

                        elif msg.msg_type == MessageType.REPLY:
                            receiver.handle_reply_message(
                                msg,
                                self.step_counter,
                                total_processes=len(self.processes),
                                all_pids=list(self.processes.keys())
                            )
                            action_detail = (
                                f"P{receiver.pid} received REPLY from P{msg.sender_id}. "
                                f"Replies collected: {len(receiver.replies_received)}/{len(self.processes) - 1}."
                            )
                            self._log_event(
                                event_type="REPLY",
                                process_id=receiver.pid,
                                description=f"P{receiver.pid} received REPLY from P{msg.sender_id}.",
                                educational_note=(
                                    f"Process P{receiver.pid} recorded reply from P{msg.sender_id}. "
                                    f"Total replies for active request: {len(receiver.replies_received)}/{len(self.processes) - 1}. "
                                    + ("It can enter once all peers have replied." if self.algorithm == "ricart_agrawala" else
                                       "It must also be first in its own queue before entering.")
                                ),
                                details={**delivery_details, "clock_after": receiver.clock}
                            )

                        elif msg.msg_type == MessageType.RELEASE:
                            receiver.handle_release_message(msg, self.step_counter)
                            action_detail = (
                                f"P{receiver.pid} received RELEASE from P{msg.sender_id}. "
                                f"Removed P{msg.sender_id} from local queue."
                            )
                            self._log_event(
                                event_type="RELEASE",
                                process_id=receiver.pid,
                                description=f"P{receiver.pid} received RELEASE from P{msg.sender_id}.",
                                educational_note=(
                                    f"Lamport Rule 4: Process P{receiver.pid} removes P{msg.sender_id}'s request "
                                    "from its local queue, potentially advancing its own request to the head."
                                ),
                                details={**delivery_details, "clock_after": receiver.clock}
                            )

                    # Check if any process can enter CS now that message was processed
                    self._evaluate_cs_entries()

            elif proc_in_cs is not None:
                # No messages pending, but a process is inside Critical Section
                remaining = proc_in_cs.decrement_cs_tick()
                if remaining > 0:
                    step_action = "CS_PROGRESS"
                    action_detail = f"P{proc_in_cs.pid} executing inside Critical Section. Remaining ticks: {remaining}."
                    self._log_event(
                        event_type="CS_PROGRESS", process_id=proc_in_cs.pid,
                        description=f"P{proc_in_cs.pid} is using the critical section. {remaining} ticks remain.",
                        educational_note="Only this process is inside. A CS tick models work duration; it does not advance the Lamport clock."
                    )
                else:
                    # CS duration reached zero -> Release resource
                    step_action = "CS_RELEASE"
                    all_pids = list(self.processes.keys())
                    clock_before = proc_in_cs.clock
                    success, desc, release_msgs = proc_in_cs.release_critical_section(all_pids, self.step_counter)
                    self.completed_requests += 1
                    self.network.send_batch(release_msgs)
                    ricart = self.algorithm == "ricart_agrawala"
                    if ricart:
                        step_action = "CS_EXIT"
                    action_detail = (f"P{proc_in_cs.pid} exited and sent {len(release_msgs)} deferred {'reply' if len(release_msgs) == 1 else 'replies'}."
                                     if ricart else f"P{proc_in_cs.pid} exited the critical section and sent RELEASE to every peer.")

                    self._log_event(
                        event_type="CS_EXIT",
                        process_id=proc_in_cs.pid,
                        description=action_detail,
                        educational_note=(
                            f"It sends the replies it held for other processes and clears its deferred list. No RELEASE broadcast is needed."
                            if ricart else f"Lamport Rule 3: Process P{proc_in_cs.pid} completed CS execution, "
                            f"removed its request from its local queue, incremented its clock to {proc_in_cs.clock}, "
                            f"and broadcasted RELEASE messages to all {len(release_msgs)} peers."
                        ),
                        details={"clock_before": clock_before, "clock_after": proc_in_cs.clock}
                    )

                    # Check if another process can enter CS
                    self._evaluate_cs_entries()

            else:
                # No messages and no process in CS; evaluate if any waiting process can enter
                self._evaluate_cs_entries()
                self._log_event(
                    event_type="SYSTEM", process_id=None,
                    description="The system is idle. Choose a process to request the resource.",
                    educational_note="A request starts with a local clock increment, then a REQUEST broadcast to every peer."
                )

            # Safety check after every single step
            self._check_mutual_exclusion()

            return {
                "step": self.step_counter,
                "action": step_action,
                "detail": action_detail,
                "in_cs": [p.pid for p in self.processes.values() if p.state == ProcessState.IN_CRITICAL_SECTION],
                "pending_messages": self.network.pending_count(),
                "violations_count": self.violations_count
            }

    def _auto_run_worker(self) -> None:
        """Background thread executing automatic simulation."""
        idle_ticks = 0
        while not self._stop_event.is_set():
            if not self.is_running:
                time.sleep(0.1)
                continue

            with self._lock:
                has_messages = self.network.has_pending()
                any_in_cs = any(p.state == ProcessState.IN_CRITICAL_SECTION for p in self.processes.values())
                any_requesting = any(p.state in (ProcessState.REQUESTING, ProcessState.WAITING) for p in self.processes.values())

                if not has_messages and not any_in_cs and not any_requesting:
                    idle_ticks += 1
                    # After brief idle period, randomly pick an available process to issue a request
                    if idle_ticks >= 2:
                        available = [p.pid for p in self.processes.values() if p.state == ProcessState.RELEASED]
                        if available:
                            chosen_pid = random.choice(available)
                            self.request_resource(chosen_pid)
                        idle_ticks = 0
                else:
                    idle_ticks = 0
                    self.step()

            # Sleep according to configured simulation speed
            sleep_sec = max(0.05, self.speed_ms / 1000.0)
            time.sleep(sleep_sec)

    def start_auto(self) -> None:
        """Starts automatic continuous simulation."""
        with self._lock:
            self.is_running = True
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._stop_event.clear()
                self._worker_thread = threading.Thread(target=self._auto_run_worker, daemon=True)
                self._worker_thread.start()

    def pause_auto(self) -> None:
        """Pauses automatic continuous simulation."""
        with self._lock:
            self.is_running = False

    def set_speed(self, speed_ms: int) -> None:
        """Sets the simulation speed in milliseconds per step (100ms - 2000ms)."""
        with self._lock:
            self.speed_ms = max(50, min(3000, speed_ms))

    def set_cs_duration(self, duration: int) -> None:
        """Sets how many simulation ticks a process spends inside the Critical Section."""
        with self._lock:
            self.cs_duration = max(1, min(20, duration))

    def set_process_count(self, count: int) -> bool:
        """Reconfigures the number of participating processes (3 to 8). Resets simulation."""
        with self._lock:
            count = max(3, min(8, count))
            if count == self.process_count:
                return True
            self.process_count = count
            self.reset()
            return True

    def reset(self) -> None:
        """Resets the entire simulation to clean initial state."""
        with self._lock:
            self.is_running = False
            self.step_counter = 0
            self.event_counter = 0
            self.events.clear()
            self.live_events.clear()
            self.network.clear()
            self.violations_count = 0
            self.requests_created = 0
            self.cs_entries = 0
            self.completed_requests = 0

            self._init_processes()
            self._log_event(
                event_type="SYSTEM",
                process_id=None,
                description=f"{ALGORITHM_NAMES[self.algorithm]} ready with {self.process_count} processes.",
                educational_note="All logical clocks start at 0. Choose a process to request the resource."
            )

    def get_state(self, event_filter: Optional[str] = None, event_limit: int = 40) -> Dict[str, Any]:
        """Returns a complete snapshot of the simulation state for the frontend."""
        with self._lock:
            # Determine shared resource status
            procs_in_cs = [p for p in self.processes.values() if p.state == ProcessState.IN_CRITICAL_SECTION]
            if len(procs_in_cs) > 0:
                resource_status = "IN_USE"
                active_process = procs_in_cs[0].pid
            else:
                resource_status = "AVAILABLE"
                active_process = None

            # Calculate average waiting time
            total_wait = sum(p.total_wait_steps for p in self.processes.values())
            avg_wait = round(total_wait / max(1, self.cs_entries), 2)

            # Filter events
            filtered_events = self.events
            if event_filter and event_filter.upper() != "ALL":
                ef_upper = event_filter.upper()
                if ef_upper == "CRITICAL_SECTION":
                    filtered_events = [e for e in self.events if e.event_type in ("CS_ENTRY", "CS_PROGRESS", "CS_EXIT")]
                else:
                    filtered_events = [e for e in self.events if e.event_type == ef_upper]

            recent_events = [e.to_dict() for e in reversed(filtered_events[-event_limit:])]

            # Collect global view of outstanding requests across all local queues
            # Ordered according to Lamport's ordering rule
            all_requests_dict: Dict[Tuple[int, int], Dict[str, Any]] = {}
            for proc in self.processes.values():
                for req in proc.request_queue:
                    all_requests_dict[(req.timestamp, req.process_id)] = {
                        "timestamp": req.timestamp,
                        "process_id": req.process_id,
                        "display": f"(T={req.timestamp}, P{req.process_id})",
                        "is_in_cs": (self.processes[req.process_id].state == ProcessState.IN_CRITICAL_SECTION
                                     and self.processes[req.process_id].current_request == req),
                        "is_active": self.processes[req.process_id].current_request == req,
                    }
            
            sorted_global_requests = sorted(
                all_requests_dict.values(),
                key=lambda r: (r["timestamp"], r["process_id"])
            )

            if self.algorithm == "ricart_agrawala":
                sorted_global_requests = [
                    {**proc.current_request.to_dict(), "is_active": True,
                     "is_in_cs": proc.state == ProcessState.IN_CRITICAL_SECTION}
                    for proc in self.processes.values() if proc.current_request is not None
                ]
                sorted_global_requests.sort(key=lambda request: (request["timestamp"], request["process_id"]))

            return {
                "algorithm": self.algorithm,
                "algorithm_name": ALGORITHM_NAMES[self.algorithm],
                "algorithm_stages": self.get_algorithm_stages(),
                "step": self.step_counter,
                "is_running": self.is_running,
                "process_count": self.process_count,
                "speed_ms": self.speed_ms,
                "cs_duration": self.cs_duration,
                "shared_resource": {
                    "status": resource_status,
                    "current_process_id": active_process,
                    "total_cs_entries": self.cs_entries,
                    "violations_count": self.violations_count,
                    "is_safe": self.violations_count == 0
                },
                "processes": [p.to_dict() for p in self.processes.values()],
                "in_transit_messages": self.network.get_in_transit(),
                "message_timeline": self.network.get_history(limit=50),
                "global_request_queue": sorted_global_requests,
                "events": recent_events,
                # Live commentary is independent of the event-log filter.
                "live_event": self.events[-1].to_dict() if self.events else None,
                "live_events": [e.to_dict() for e in self.live_events],
                "stats": {
                    "total_messages": self.network.total_messages_count(),
                    "requests_created": self.requests_created,
                    "cs_entries": self.cs_entries,
                    "completed_requests": self.completed_requests,
                    "average_wait_steps": avg_wait,
                    "violations_count": self.violations_count
                }
            }
