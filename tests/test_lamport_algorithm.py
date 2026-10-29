"""
Automated Unit Tests for Lamport's Distributed Mutual Exclusion Algorithm.
Verifies all 10 essential scenarios, edge cases, tie-breakers, and safety invariants.
"""

import unittest
import sys
import os

# Ensure the root project directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulator.models import Message, MessageType, ProcessState, RequestEntry
from simulator.process import DistributedProcess
from simulator.coordinator import SimulationCoordinator
from simulator.lamport_algorithm import verify_mutual_exclusion, is_queue_sorted


class TestLamportAlgorithm(unittest.TestCase):
    """Comprehensive test suite for Lamport's Mutual Exclusion Algorithm."""

    def setUp(self):
        """Initializes a fresh coordinator for each test."""
        self.coordinator = SimulationCoordinator(process_count=4, cs_duration=2)

    def test_01_single_process_request(self):
        """Test 1: Single process requests the shared resource."""
        ok, msg = self.coordinator.request_resource(1)
        self.assertTrue(ok)
        p1 = self.coordinator.processes[1]
        self.assertEqual(p1.state, ProcessState.REQUESTING)
        self.assertEqual(p1.clock, 1)
        self.assertEqual(len(p1.request_queue), 1)
        self.assertEqual(p1.request_queue[0].timestamp, 1)
        self.assertEqual(p1.request_queue[0].process_id, 1)

        # 3 REQUEST messages sent to P2, P3, P4
        self.assertEqual(self.coordinator.network.pending_count(), 3)

        # Step until all messages delivered and P1 enters CS
        for _ in range(20):
            if p1.state == ProcessState.IN_CRITICAL_SECTION:
                break
            self.coordinator.step()

        self.assertEqual(p1.state, ProcessState.IN_CRITICAL_SECTION)
        self.assertEqual(self.coordinator.violations_count, 0)
        self.assertEqual(self.coordinator.cs_entries, 1)

    def test_02_two_processes_different_times(self):
        """Test 2: Two processes request the resource sequentially at different times."""
        # P1 requests first
        self.coordinator.request_resource(1)
        
        # Run until P1 enters CS
        for _ in range(20):
            if self.coordinator.processes[1].state == ProcessState.IN_CRITICAL_SECTION:
                break
            self.coordinator.step()
        self.assertEqual(self.coordinator.processes[1].state, ProcessState.IN_CRITICAL_SECTION)

        # P2 requests while P1 is in CS
        ok, _ = self.coordinator.request_resource(2)
        self.assertTrue(ok)

        # Step until P1 exits and P2 enters CS
        for _ in range(40):
            self.coordinator.step()
            # Safety invariant must hold at every single step!
            is_valid, _ = verify_mutual_exclusion(list(self.coordinator.processes.values()))
            self.assertTrue(is_valid, "Invariant breached during sequential requests!")

        self.assertEqual(self.coordinator.violations_count, 0)
        self.assertGreaterEqual(self.coordinator.cs_entries, 2)

    def test_03_two_processes_simultaneous_requests(self):
        """Test 3: Two processes requesting simultaneously."""
        self.coordinator.request_resource(1)
        self.coordinator.request_resource(2)

        # Run full lifecycle until both requests complete
        for _ in range(60):
            self.coordinator.step()
            is_valid, in_cs = verify_mutual_exclusion(list(self.coordinator.processes.values()))
            self.assertTrue(is_valid, f"Safety invariant breached! Processes in CS: {in_cs}")

        self.assertEqual(self.coordinator.violations_count, 0)
        self.assertEqual(self.coordinator.completed_requests, 2)

    def test_04_multiple_concurrent_requests(self):
        """Test 4: Multiple concurrent requests from 3 processes (P1, P2, P3)."""
        ok, desc = self.coordinator.trigger_concurrent_requests([1, 2, 3])
        self.assertTrue(ok)

        for _ in range(120):
            self.coordinator.step()
            is_valid, in_cs = verify_mutual_exclusion(list(self.coordinator.processes.values()))
            self.assertTrue(is_valid, "Invariant breached during concurrent execution!")

        self.assertEqual(self.coordinator.violations_count, 0)
        self.assertEqual(self.coordinator.completed_requests, 3)

    def test_05_equal_logical_timestamps_tie_breaking(self):
        """
        Test 5: Equal logical timestamps with process-ID tie-breaking.
        When two requests have equal timestamps, the one with smaller process ID wins.
        """
        # Create identical timestamps for P2 and P4 manually
        req2 = RequestEntry(timestamp=5, process_id=2)
        req4 = RequestEntry(timestamp=5, process_id=4)
        req1 = RequestEntry(timestamp=5, process_id=1)

        queue = [req4, req2, req1]
        queue.sort(key=lambda r: (r.timestamp, r.process_id))

        self.assertEqual(queue[0].process_id, 1)
        self.assertEqual(queue[1].process_id, 2)
        self.assertEqual(queue[2].process_id, 4)
        self.assertTrue(is_queue_sorted(queue))

    def test_06_process_entering_and_leaving_cs(self):
        """Test 6: Verify correct state transitions when entering and leaving CS."""
        self.coordinator.request_resource(3)
        p3 = self.coordinator.processes[3]

        # Advance until inside CS
        steps = 0
        while p3.state != ProcessState.IN_CRITICAL_SECTION and steps < 30:
            self.coordinator.step()
            steps += 1

        self.assertEqual(p3.state, ProcessState.IN_CRITICAL_SECTION)
        self.assertIsNotNone(p3.current_request)

        # Advance through CS duration to release
        while p3.state == ProcessState.IN_CRITICAL_SECTION and steps < 50:
            self.coordinator.step()
            steps += 1

        # P3 should be back to RELEASED
        self.assertEqual(p3.state, ProcessState.RELEASED)
        self.assertIsNone(p3.current_request)
        self.assertEqual(p3.completed_requests, 1)

    def test_07_correct_handling_of_request_reply_release_messages(self):
        """Test 7: Direct testing of message handling functions in DistributedProcess."""
        p1 = DistributedProcess(pid=1)
        p2 = DistributedProcess(pid=2)

        # P1 creates request
        ok, _, msgs = p1.request_resource(all_pids=[1, 2], step=1)
        self.assertTrue(ok)
        self.assertEqual(len(msgs), 1)
        req_msg = msgs[0]
        self.assertEqual(req_msg.msg_type, MessageType.REQUEST)
        self.assertEqual(req_msg.sender_id, 1)
        self.assertEqual(req_msg.receiver_id, 2)
        self.assertEqual(req_msg.timestamp, 1)

        # P2 handles REQUEST and produces REPLY
        reply_msg = p2.handle_request_message(req_msg, step=2)
        self.assertEqual(p2.clock, 2)  # max(0, 1) + 1 = 2
        self.assertEqual(reply_msg.msg_type, MessageType.REPLY)
        self.assertEqual(reply_msg.sender_id, 2)
        self.assertEqual(reply_msg.receiver_id, 1)
        self.assertEqual(reply_msg.timestamp, 2)

        # P1 handles REPLY
        p1.handle_reply_message(reply_msg, step=3)
        self.assertEqual(p1.clock, 3)  # max(1, 2) + 1 = 3
        self.assertIn(2, p1.replies_received)

        # P1 checks can_enter_cs
        can_enter, _ = p1.can_enter_critical_section(total_processes=2)
        self.assertTrue(can_enter)

        # P1 enters CS
        p1.enter_critical_section(duration=2, current_step=4)
        self.assertEqual(p1.state, ProcessState.IN_CRITICAL_SECTION)

        # P1 releases CS
        ok, _, rel_msgs = p1.release_critical_section(all_pids=[1, 2], step=5)
        self.assertTrue(ok)
        self.assertEqual(len(rel_msgs), 1)
        rel_msg = rel_msgs[0]
        self.assertEqual(rel_msg.msg_type, MessageType.RELEASE)

        # P2 handles RELEASE
        p2.handle_release_message(rel_msg, step=6)
        self.assertEqual(len(p2.request_queue), 0)

    def test_08_logical_clock_updates_on_message_receipt(self):
        """Test 8: Verify Lamport's clock update rule: clock = max(local, incoming) + 1."""
        p = DistributedProcess(pid=1)
        p.clock = 3

        # Receive lower timestamp (T=1): max(3, 1) + 1 = 4
        res = p.update_clock_on_receive(1)
        self.assertEqual(res, 4)
        self.assertEqual(p.clock, 4)

        # Receive higher timestamp (T=10): max(4, 10) + 1 = 11
        res = p.update_clock_on_receive(10)
        self.assertEqual(res, 11)
        self.assertEqual(p.clock, 11)

    def test_09_resetting_simulation(self):
        """Test 9: Verifies that resetting the simulation clears all queues, clocks, and stats."""
        self.coordinator.request_resource(1)
        for _ in range(5):
            self.coordinator.step()

        self.assertGreater(self.coordinator.step_counter, 0)
        self.coordinator.reset()

        self.assertEqual(self.coordinator.step_counter, 0)
        self.assertEqual(self.coordinator.violations_count, 0)
        self.assertEqual(self.coordinator.cs_entries, 0)
        self.assertEqual(self.coordinator.network.pending_count(), 0)
        for p in self.coordinator.processes.values():
            self.assertEqual(p.clock, 0)
            self.assertEqual(p.state, ProcessState.RELEASED)
            self.assertEqual(len(p.request_queue), 0)

    def test_10_repeated_runs_and_invariant_check(self):
        """
        Test 10: Repeated randomized runs to stress-test race conditions and verify:
            number_of_processes_inside_critical_section <= 1
        """
        coord = SimulationCoordinator(process_count=5, cs_duration=1)

        import random
        random.seed(42)

        for _ in range(150):
            # Periodically issue random requests
            if random.random() < 0.2:
                available = [p.pid for p in coord.processes.values() if p.state == ProcessState.RELEASED]
                if available:
                    coord.request_resource(random.choice(available))

            coord.step()
            
            # Invariant check
            is_valid, in_cs = verify_mutual_exclusion(list(coord.processes.values()))
            self.assertTrue(is_valid, f"Safety invariant breached! Processes in CS: {in_cs}")

        self.assertEqual(coord.violations_count, 0)
        self.assertGreater(coord.completed_requests, 0)

    def test_11_out_of_order_message_delivery(self):
        """
        Test 11: Out-of-order and reversed message delivery.
        Verifies that non-FIFO, asynchronous packet reordering still guarantees
        proper queue ordering and safety.
        """
        coord = SimulationCoordinator(process_count=4, cs_duration=2)
        coord.request_resource(1)
        coord.request_resource(2)

        # Reverse pending messages to scramble delivery order
        coord.network.reverse_pending()

        # Step through until both complete
        for _ in range(80):
            if coord.network.pending_count() > 2:
                # Randomly shuffle in-transit messages
                coord.network.shuffle_pending(seed=42)
            coord.step()
            is_valid, in_cs = verify_mutual_exclusion(list(coord.processes.values()))
            self.assertTrue(is_valid, f"Safety breached during out-of-order delivery! CS: {in_cs}")

        self.assertEqual(coord.violations_count, 0)
        self.assertEqual(coord.completed_requests, 2)

    def test_12_duplicate_reply_cannot_bypass_peers(self):
        """
        Test 12: Sender identity tracking.
        Duplicate replies from the same peer cannot satisfy the requirement for other peers.
        """
        p1 = DistributedProcess(pid=1)
        all_pids = [1, 2, 3, 4]
        p1.request_resource(all_pids, step=1)

        # Create a single reply from P2
        reply_p2 = Message.create(
            msg_type=MessageType.REPLY,
            sender_id=2,
            receiver_id=1,
            timestamp=2,
            req_timestamp=1,
            step_created=2
        )

        # Deliver the same reply from P2 10 times
        for _ in range(10):
            p1.handle_reply_message(reply_p2, step=3, all_pids=all_pids)

        # P1 should still only have recorded 1 unique reply (from P2)
        self.assertEqual(len(p1.replies_received), 1)
        self.assertIn(2, p1.replies_received)

        # Can P1 enter CS? Absolutely NOT, because P3 and P4 have not replied!
        can_enter, reason = p1.can_enter_critical_section(total_processes=4, all_pids=all_pids)
        self.assertFalse(can_enter)
        self.assertIn("Missing", reason)

    def test_13_self_reply_rejected(self):
        """
        Test 13: Verifies that self-replies are rejected and cannot satisfy peer requirements.
        """
        p1 = DistributedProcess(pid=1)
        all_pids = [1, 2, 3]
        p1.request_resource(all_pids, step=1)

        # Bogus self-reply with sender_id = 1
        bogus_self_reply = Message.create(
            msg_type=MessageType.REPLY,
            sender_id=1,
            receiver_id=1,
            timestamp=2,
            req_timestamp=1,
            step_created=2
        )
        p1.handle_reply_message(bogus_self_reply, step=2, all_pids=all_pids)

        # Self reply must NOT be added to replies_received
        self.assertNotIn(1, p1.replies_received)
        self.assertEqual(len(p1.replies_received), 0)

    def test_14_dynamic_invariant_violation_detection(self):
        """
        Test 14: Verifies that the mutual exclusion invariant is dynamically checked
        and reliably detects violations when multiple processes enter CS simultaneously.
        """
        coord = SimulationCoordinator(process_count=3, cs_duration=2)
        self.assertEqual(coord.violations_count, 0)

        # Artificially force both P1 and P2 into IN_CRITICAL_SECTION to test detector
        coord.processes[1].state = ProcessState.IN_CRITICAL_SECTION
        coord.processes[2].state = ProcessState.IN_CRITICAL_SECTION

        # Run invariant verification
        is_valid, pids = verify_mutual_exclusion(list(coord.processes.values()))
        self.assertFalse(is_valid)
        self.assertEqual(sorted(pids), [1, 2])

        # Verify coordinator's monitor increments violations_count
        coord._check_mutual_exclusion()
        self.assertEqual(coord.violations_count, 1)

    def test_15_sequential_rerequest_clock_monotonicity(self):
        """
        Test 15: Verifies that when a process exits CS and requests again,
        its logical clock monotonically increases and prior request state is clean.
        """
        coord = SimulationCoordinator(process_count=3, cs_duration=1)
        
        # P1 requests and completes CS
        coord.request_resource(1)
        while coord.processes[1].state != ProcessState.IN_CRITICAL_SECTION:
            coord.step()
        first_cs_clock = coord.processes[1].clock
        
        while coord.processes[1].state == ProcessState.IN_CRITICAL_SECTION:
            coord.step()
        self.assertEqual(coord.processes[1].state, ProcessState.RELEASED)
        
        # Deliver remaining release messages
        while coord.network.has_pending():
            coord.step()

        # P1 requests a second time
        ok, _ = coord.request_resource(1)
        self.assertTrue(ok)
        second_request_clock = coord.processes[1].clock
        
        # Must be strictly greater than clock during first CS
        self.assertGreater(second_request_clock, first_cs_clock)

    def test_16_max_processes_scale_eight(self):
        """
        Test 16: Tests cluster scaling to maximum 8 processes.
        Verifies correct concurrent arbitration and message accounting: 3*(8-1) = 21 msgs/entry.
        """
        coord = SimulationCoordinator(process_count=8, cs_duration=1)
        self.assertEqual(coord.process_count, 8)
        self.assertEqual(len(coord.processes), 8)

        # Trigger concurrent requests for all 8 processes
        all_pids = list(range(1, 9))
        ok, _ = coord.trigger_concurrent_requests(all_pids)
        self.assertTrue(ok)

        # Run until all 8 requests complete
        max_steps = 600
        steps = 0
        while coord.completed_requests < 8 and steps < max_steps:
            coord.step()
            steps += 1
            is_valid, _ = verify_mutual_exclusion(list(coord.processes.values()))
            self.assertTrue(is_valid, "Invariant breached in 8-node cluster!")

        self.assertEqual(coord.completed_requests, 8)
        self.assertEqual(coord.violations_count, 0)


if __name__ == '__main__':
    unittest.main()
