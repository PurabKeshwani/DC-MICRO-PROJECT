"""
Integration and API tests for Flask server and REST endpoints.
Verifies all buttons, controls, and endpoints are fully functional.
"""

import unittest
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, coordinator


class TestFlaskAPI(unittest.TestCase):
    """Test suite for Flask API routes."""

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True
        coordinator.set_algorithm('lamport')
        coordinator.reset()

    def test_01_index_page(self):
        """Test GET / renders dashboard HTML."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Distributed Mutual Exclusion Simulator", response.data)
        self.assertIn(b"Lamport's Algorithm", response.data)

    def test_02_api_state(self):
        """Test GET /api/state returns valid initial snapshot."""
        response = self.client.get('/api/state')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['processes']), 4)
        self.assertEqual(data['data']['shared_resource']['status'], 'AVAILABLE')
        self.assertEqual(data['data']['shared_resource']['violations_count'], 0)

    def test_03_api_request(self):
        """Test POST /api/request triggers resource request for P1."""
        response = self.client.post(
            '/api/request',
            data=json.dumps({'pid': 1}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        p1 = [p for p in data['data']['processes'] if p['pid'] == 1][0]
        self.assertEqual(p1['state'], 'REQUESTING')
        self.assertEqual(p1['clock'], 1)

    def test_04_api_concurrent(self):
        """Test POST /api/concurrent triggers multiple requests."""
        response = self.client.post(
            '/api/concurrent',
            data=json.dumps({'pids': [1, 2]}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        p1 = [p for p in data['data']['processes'] if p['pid'] == 1][0]
        p2 = [p for p in data['data']['processes'] if p['pid'] == 2][0]
        self.assertEqual(p1['state'], 'REQUESTING')
        self.assertEqual(p2['state'], 'REQUESTING')

    def test_05_api_step(self):
        """Test POST /api/step executes one step."""
        # Request P1
        self.client.post('/api/request', data=json.dumps({'pid': 1}), content_type='application/json')
        # Step once
        response = self.client.post('/api/step')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertIn('step_result', data)
        self.assertEqual(data['step_result']['step'], 1)

    def test_06_api_start_pause(self):
        """Test POST /api/start and /api/pause."""
        res_start = self.client.post('/api/start')
        self.assertEqual(res_start.status_code, 200)
        self.assertTrue(json.loads(res_start.data)['is_running'])

        res_pause = self.client.post('/api/pause')
        self.assertEqual(res_pause.status_code, 200)
        self.assertFalse(json.loads(res_pause.data)['is_running'])

    def test_07_api_config(self):
        """Test POST /api/config reconfigures process count, speed, and CS duration."""
        response = self.client.post(
            '/api/config',
            data=json.dumps({
                'process_count': 6,
                'speed_ms': 700,
                'cs_duration': 4
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['process_count'], 6)
        self.assertEqual(len(data['data']['processes']), 6)
        self.assertEqual(data['data']['speed_ms'], 700)
        self.assertEqual(data['data']['cs_duration'], 4)

    def test_08_api_reset(self):
        """Test POST /api/reset resets the state."""
        self.client.post('/api/request', data=json.dumps({'pid': 1}), content_type='application/json')
        self.client.post('/api/step')
        response = self.client.post('/api/reset')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['step'], 0)
        self.assertEqual(data['data']['stats']['requests_created'], 0)

    def test_09_api_algorithm(self):
        """Test GET /api/algorithm returns educational stages."""
        response = self.client.get('/api/algorithm')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertEqual(len(data['stages']), 6)

    def test_10_live_explanation_is_independent_of_log_filter(self):
        self.client.post('/api/request', json={'pid': 1})
        self.client.post('/api/step')
        unfiltered = self.client.get('/api/state').get_json()['data']
        filtered = self.client.get('/api/state?filter=RELEASE').get_json()['data']
        self.assertEqual(filtered['events'], [])
        self.assertEqual(filtered['live_event'], unfiltered['live_event'])
        self.assertEqual(filtered['live_events'], unfiltered['live_events'])

    def test_11_delivery_explains_the_actual_clock_values(self):
        self.client.post('/api/request', json={'pid': 1})
        state = self.client.post('/api/step').get_json()['data']
        event = state['live_event']
        self.assertEqual(event['event_type'], 'REQUEST')
        details = event['details']
        self.assertEqual(details['clock_before'], 0)
        self.assertEqual(details['message']['timestamp'], 1)
        self.assertEqual(details['clock_after'], 2)
        self.assertEqual(details['message']['receiver_id'], 2)

    def test_12_observer_distinguishes_release_cleanup(self):
        self.client.post('/api/request', json={'pid': 1})
        for _ in range(30):
            state = self.client.post('/api/step').get_json()['data']
            if state['stats']['completed_requests']:
                break
        self.assertEqual(state['stats']['completed_requests'], 1)
        self.assertEqual(len(state['global_request_queue']), 1)
        request = state['global_request_queue'][0]
        self.assertFalse(request['is_active'])
        self.assertFalse(request['is_in_cs'])

    def test_13_each_action_has_its_own_live_details(self):
        self.client.post('/api/request', json={'pid': 1})
        self.client.post('/api/step')
        state = self.client.post('/api/request', json={'pid': 3}).get_json()['data']
        self.assertEqual(len(state['live_events']), 1)
        self.assertEqual(state['live_events'][0]['process_id'], 3)
        self.assertNotIn('message', state['live_events'][0]['details'])

    def test_14_cs_progress_and_reset_have_current_commentary(self):
        self.client.post('/api/request', json={'pid': 1})
        for _ in range(20):
            state = self.client.post('/api/step').get_json()['data']
            if state['live_event']['event_type'] == 'CS_PROGRESS':
                break
        self.assertEqual(state['live_event']['event_type'], 'CS_PROGRESS')
        self.assertEqual(state['live_event']['step'], state['step'])
        coordinator.start_auto()
        reset = self.client.post('/api/reset').get_json()['data']
        self.assertFalse(reset['is_running'])
        self.assertEqual(reset['step'], 0)
        self.assertEqual(len(reset['live_events']), 1)

    def test_15_switch_algorithm_resets_to_paused_clean_run(self):
        self.client.post('/api/concurrent', json={})
        self.client.post('/api/start')
        switched = self.client.post('/api/config', json={'algorithm': 'ricart_agrawala'}).get_json()['data']
        self.assertEqual(switched['algorithm'], 'ricart_agrawala')
        self.assertFalse(switched['is_running'])
        self.assertEqual(switched['step'], 0)
        self.assertEqual(switched['stats']['total_messages'], 0)
        self.assertTrue(all(not p['deferred_replies'] for p in switched['processes']))
        self.client.post('/api/concurrent', json={})
        for _ in range(4):
            self.client.post('/api/step')
        restored = self.client.post('/api/config', json={'algorithm': 'lamport'}).get_json()['data']
        self.assertEqual(restored['algorithm'], 'lamport')
        self.assertEqual(restored['stats']['total_messages'], 0)
        self.assertTrue(all(not p['request_queue'] for p in restored['processes']))

    def test_16_unknown_algorithm_is_rejected(self):
        for algorithm in ['unknown', None, []]:
            response = self.client.post('/api/config', json={'algorithm': algorithm})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(coordinator.algorithm, 'lamport')

    def test_17_ricart_reference_matches_selected_algorithm(self):
        self.client.post('/api/config', json={'algorithm': 'ricart_agrawala'})
        response = self.client.get('/api/algorithm').get_json()
        self.assertEqual(response['algorithm'], 'ricart_agrawala')
        self.assertEqual(len(response['stages']), 6)
        self.assertIn('deferred', response['stages'][-1]['description'])


if __name__ == '__main__':
    unittest.main()
