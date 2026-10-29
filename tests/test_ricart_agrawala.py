"""Protocol tests for deferred replies, priority, safety, and message accounting."""
import unittest

from simulator.coordinator import SimulationCoordinator
from simulator.models import Message, MessageType, ProcessState
from simulator.ricart_agrawala import RicartAgrawalaProcess


class TestRicartAgrawala(unittest.TestCase):
    def drain(self, coordinator, expected):
        for _ in range(600):
            coordinator.step()
            inside = [p for p in coordinator.processes.values() if p.state == ProcessState.IN_CRITICAL_SECTION]
            self.assertLessEqual(len(inside), 1)
            if coordinator.completed_requests == expected and not coordinator.network.has_pending():
                break
        self.assertEqual(coordinator.completed_requests, expected)
        self.assertEqual(coordinator.violations_count, 0)

    def test_single_request_uses_only_request_and_reply(self):
        coordinator = SimulationCoordinator(4, 2, algorithm='ricart_agrawala')
        coordinator.request_resource(1)
        self.drain(coordinator, 1)
        self.assertEqual(coordinator.network.total_messages_count(), 6)
        self.assertEqual({m['msg_type'] for m in coordinator.network.get_history()}, {'REQUEST', 'REPLY'})
        self.assertTrue(all(not p.request_queue for p in coordinator.processes.values()))

    def test_all_process_counts_resolve_equal_timestamps_by_pid(self):
        for count in range(3, 9):
            with self.subTest(count=count):
                coordinator = SimulationCoordinator(count, 1, algorithm='ricart_agrawala')
                coordinator.trigger_concurrent_requests(list(range(count, 0, -1)))
                self.drain(coordinator, count)
                order = [event.process_id for event in coordinator.events if event.event_type == 'CS_ENTRY']
                self.assertEqual(order, list(range(1, count + 1)))
                self.assertEqual(coordinator.network.total_messages_count(), 2 * count * (count - 1))
                self.assertTrue(all(not p.deferred_replies for p in coordinator.processes.values()))

    def test_comparison_uses_fixed_request_timestamp(self):
        process = RicartAgrawalaProcess(1)
        process.request_resource([1, 2, 3], 0)
        process.clock = 20
        message = Message.create(MessageType.REQUEST, 2, 1, 2, 2)
        self.assertIsNone(process.handle_request_message(message, 1))
        self.assertEqual(process.clock, 21)
        self.assertEqual(process.current_request.timestamp, 1)
        self.assertEqual(process.deferred_replies[2].timestamp, 2)

    def test_higher_priority_peer_gets_immediate_reply(self):
        process = RicartAgrawalaProcess(3)
        process.clock = 4
        process.request_resource([1, 2, 3], 0)
        reply = process.handle_request_message(Message.create(MessageType.REQUEST, 2, 3, 1, 1), 1)
        self.assertEqual(reply.msg_type, MessageType.REPLY)
        self.assertEqual(reply.req_timestamp, 1)
        self.assertEqual(process.deferred_replies, {})

    def test_inside_cs_holds_reply_and_sends_it_on_exit(self):
        process = RicartAgrawalaProcess(1)
        process.clock = 4
        process.request_resource([1, 2, 3], 0)
        process.enter_critical_section(1, 1)
        # While inside, defer even an incoming request with a lower tuple.
        self.assertIsNone(process.handle_request_message(Message.create(MessageType.REQUEST, 2, 1, 1, 1), 2))
        ok, _, messages = process.release_critical_section([1, 2, 3], 3)
        self.assertTrue(ok)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].msg_type, MessageType.REPLY)
        self.assertEqual(messages[0].receiver_id, 2)
        self.assertEqual(messages[0].req_timestamp, 1)
        self.assertEqual(process.deferred_replies, {})
        self.assertIsNone(process.current_request)
        self.assertEqual(process.state, ProcessState.RELEASED)

    def test_reply_identity_and_request_matching_are_required(self):
        process = RicartAgrawalaProcess(1)
        peers = [1, 2, 3]
        process.request_resource(peers, 0)
        reply = Message.create(MessageType.REPLY, 2, 1, 2, 1)
        for _ in range(5):
            process.handle_reply_message(reply, 1, all_pids=peers)
        process.handle_reply_message(Message.create(MessageType.REPLY, 1, 1, 2, 1), 2, all_pids=peers)
        process.handle_reply_message(Message.create(MessageType.REPLY, 3, 1, 2, 0), 3, all_pids=peers)
        self.assertEqual(process.replies_received, {2})
        self.assertFalse(process.can_enter_critical_section(3, peers)[0])
        process.handle_reply_message(Message.create(MessageType.REPLY, 3, 1, 3, 1), 4, all_pids=peers)
        self.assertTrue(process.can_enter_critical_section(3, peers)[0])
        self.assertEqual(process.request_queue, [])

    def test_reordered_delivery_preserves_safety_and_completion(self):
        coordinator = SimulationCoordinator(4, 1, algorithm='ricart_agrawala')
        coordinator.trigger_concurrent_requests([4, 2, 1, 3])
        for step in range(300):
            coordinator.network.shuffle_pending(seed=step)
            coordinator.step()
            self.assertLessEqual(sum(p.state == ProcessState.IN_CRITICAL_SECTION for p in coordinator.processes.values()), 1)
            if coordinator.completed_requests == 4 and not coordinator.network.has_pending():
                break
        self.assertEqual(coordinator.completed_requests, 4)
        self.assertEqual(coordinator.violations_count, 0)

    def test_repeated_rounds_clear_deferred_state(self):
        coordinator = SimulationCoordinator(3, 1, algorithm='ricart_agrawala')
        coordinator.trigger_concurrent_requests([1, 2])
        self.drain(coordinator, 2)
        first_clock = coordinator.processes[1].clock
        coordinator.trigger_concurrent_requests([2, 1])
        self.assertGreater(coordinator.processes[1].current_request.timestamp, first_clock)
        self.drain(coordinator, 4)
        self.assertEqual(coordinator.network.total_messages_count(), 16)
        self.assertTrue(all(not p.deferred_replies for p in coordinator.processes.values()))

    def test_deferred_reply_has_clear_live_explanation(self):
        coordinator = SimulationCoordinator(4, 1, algorithm='ricart_agrawala')
        coordinator.trigger_concurrent_requests([1, 2])
        for _ in range(4):
            coordinator.step()
        event = coordinator.get_state()['live_event']
        self.assertEqual(event['event_type'], 'REQUEST')
        self.assertTrue(event['details']['deferred'])
        self.assertIn('priority', event['educational_note'])
        self.assertEqual(coordinator.processes[1].deferred_replies[2].timestamp, 1)


if __name__ == '__main__':
    unittest.main()
