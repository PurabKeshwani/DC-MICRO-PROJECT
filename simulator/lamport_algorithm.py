"""
Lamport's Distributed Mutual Exclusion Algorithm verification and rule logic.
Verifies safety invariants and provides formal protocol checks.
"""

from typing import List, Tuple, Dict, Any
from .models import ProcessState, RequestEntry
from .process import DistributedProcess


def verify_mutual_exclusion(processes: List[DistributedProcess]) -> Tuple[bool, List[int]]:
    """
    Formally verifies the fundamental safety invariant of Distributed Mutual Exclusion:
        number_of_processes_inside_critical_section <= 1

    Returns:
        (is_valid, pids_in_cs):
            is_valid: True if at most 1 process is in CS, False otherwise.
            pids_in_cs: List of process IDs currently inside the Critical Section.
    """
    pids_in_cs = [p.pid for p in processes if p.state == ProcessState.IN_CRITICAL_SECTION]
    is_valid = len(pids_in_cs) <= 1
    return is_valid, pids_in_cs


def is_queue_sorted(queue: List[RequestEntry]) -> bool:
    """
    Verifies that a request queue strictly respects Lamport's total order:
      (T_i, P_i) < (T_j, P_j) <=> (T_i < T_j) or (T_i == T_j and P_i < P_j)
    """
    for i in range(len(queue) - 1):
        r1, r2 = queue[i], queue[i + 1]
        if (r1.timestamp, r1.process_id) >= (r2.timestamp, r2.process_id):
            return False
    return True


def verify_lamport_conditions(process: DistributedProcess, total_processes: int) -> Tuple[bool, str]:
    """
    Validates Lamport's two entry conditions for a given process:
      L1: Request is at the head of process's local queue.
      L2: Process has received REPLY from all (N-1) other processes.
    """
    return process.can_enter_critical_section(total_processes)


def get_algorithm_stages() -> List[Dict[str, str]]:
    """
    Returns educational documentation of the 6 stages of Lamport's algorithm.
    """
    return [
        {
            "stage": 1,
            "title": "Stage 1: Request Creation",
            "description": "Process Pi wants to enter the Critical Section. It increments its local Lamport logical clock (C_i = C_i + 1), creates a timestamped request (C_i, Pi), and adds it to its own local queue."
        },
        {
            "stage": 2,
            "title": "Stage 2: Broadcast Request",
            "description": "Process Pi broadcasts a REQUEST(C_i, Pi) message to all other N-1 participating processes in the distributed system."
        },
        {
            "stage": 3,
            "title": "Stage 3: Queue Ordering & Reply",
            "description": "When any process Pj receives the REQUEST, Pj updates its logical clock using C_j = max(C_j, C_i) + 1, places Pi's request into its local queue sorted by (timestamp, PID), and immediately sends back a timestamped REPLY(C_j, Pj)."
        },
        {
            "stage": 4,
            "title": "Stage 4: Permission Verification",
            "description": "Process Pi waits until two strict conditions are met: (1) Its own request is at the head of its local queue; and (2) It has received REPLY messages from all N-1 other processes."
        },
        {
            "stage": 5,
            "title": "Stage 5: Critical Section Entry",
            "description": "With both conditions fulfilled, Process Pi safely enters the Critical Section. Mutual exclusion is guaranteed because no two processes can satisfy both conditions simultaneously."
        },
        {
            "stage": 6,
            "title": "Stage 6: Resource Release & Notification",
            "description": "Upon leaving the Critical Section, Pi removes its request from its local queue, increments its clock, and broadcasts RELEASE(C_i, Pi) to all peers. Peers remove Pi's request, allowing the next queued request to enter."
        }
    ]
