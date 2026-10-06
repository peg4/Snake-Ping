from contextlib import redirect_stdout
import io
import os
import unittest
from unittest.mock import Mock, patch

import requests

import snake
from Plugins.globalping import globalping


def reply(data, status=200, headers=None):
    response = Mock(status_code=status, headers=headers or {})
    response.json.return_value = data
    return response


def result(avg=2, country='FI', status='finished', received=4):
    return {'probe': {'country': country, 'city': 'Helsinki', 'network': 'Example', 'asn': 64500},
            'result': {'status': status, 'resolvedAddress': '5.23.111.225', 'stats': {'avg': avg, 'rcv': received}}}


class GlobalpingTests(unittest.TestCase):
    def context(self, session):
        session.headers = {}
        return Mock(__enter__=Mock(return_value=session), __exit__=Mock(return_value=False))

    def plugin(self, config=None):
        plugin = globalping(config or {})
        with patch.dict(os.environ, {}, clear=True):
            plugin.prepare()
        return plugin

    def test_country_request_and_polling_after_response(self):
        plugin = self.plugin()
        session = Mock()
        session.post.return_value = reply({'id': 'test'}, 202)
        session.get.side_effect = [reply({'id': 'test', 'status': 'in-progress', 'results': [result(status='in-progress')]}),
                                   reply({'id': 'test', 'status': 'finished', 'results': [result()]})]
        with patch('Plugins.globalping.requests.Session', return_value=self.context(session)), patch('Plugins.globalping.time.sleep') as sleep, redirect_stdout(io.StringIO()):
            output = plugin.engage('FI', '5.23.111.225')
        self.assertEqual(output['test:0']['avg'], 2)
        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['locations'], [{'country': 'FI'}])
        self.assertEqual(payload['limit'], 5)
        self.assertEqual(payload['measurementOptions'], {'packets': 4})
        sleep.assert_called_once_with(0.5)
        session.post.assert_called_once()

    def test_worldwide_request_and_optional_token(self):
        plugin = self.plugin({'globalpingToken': 'test-token', 'globalpingLimit': 2})
        session = Mock()
        session.post.return_value = reply({'id': 'world'}, 202)
        session.get.return_value = reply({'id': 'world', 'status': 'finished', 'results': [result()]})
        with patch('Plugins.globalping.requests.Session', return_value=self.context(session)), redirect_stdout(io.StringIO()):
            plugin.engage('any', 'example.com')
        self.assertNotIn('locations', session.post.call_args.kwargs['json'])
        self.assertEqual(session.headers['Authorization'], 'Bearer test-token')
        self.assertTrue(plugin.canRunAny())
        self.assertFalse(plugin.isComparable())

    def test_failed_invalid_zero_received_and_wrong_country_results_excluded(self):
        items = [result(avg=0), result(avg=3), result(status='failed'), result(avg=None),
                 result(avg='nan'), result(avg=-1), result(received=0), result(country='US'), None]
        output = globalping.parse_results({'id': 'test', 'results': items}, 'FI')
        self.assertEqual(set(output), {'test:0', 'test:1'})
        self.assertNotIn('ipv4', output['test:0'])

    def test_poll_failure_keeps_completed_results(self):
        plugin = self.plugin()
        session = Mock()
        session.post.return_value = reply({'id': 'partial'}, 202)
        session.get.side_effect = [reply({'id': 'partial', 'status': 'in-progress', 'results': [result()]}), requests.Timeout('API timed out')]
        with patch('Plugins.globalping.requests.Session', return_value=self.context(session)), patch('Plugins.globalping.time.sleep'), redirect_stdout(io.StringIO()):
            output = plugin.engage('FI', '1.1.1.1')
        self.assertEqual(output['partial:0']['avg'], 2)

    def test_rate_limit_reported_without_retrying_creation(self):
        plugin = self.plugin()
        session = Mock()
        session.post.return_value = reply({}, 429, {'X-RateLimit-Remaining': '0', 'Retry-After': '60'})
        with patch('Plugins.globalping.requests.Session', return_value=self.context(session)), redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'Retry-After=60'):
            plugin.engage('FI', '1.1.1.1')
        session.post.assert_called_once()
        session.get.assert_not_called()

    def test_invalid_id_never_used_as_url(self):
        plugin = self.plugin()
        session = Mock()
        session.post.return_value = reply({'id': '../bad'}, 202)
        with patch('Plugins.globalping.requests.Session', return_value=self.context(session)), redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'measurement ID'):
            plugin.engage('FI', '1.1.1.1')
        session.get.assert_not_called()

    def test_client_deadline_keeps_finished_probes(self):
        plugin = self.plugin()
        session = Mock()
        session.post.return_value = reply({'id': 'partial'}, 202)
        session.get.return_value = reply({'id': 'partial', 'status': 'in-progress', 'results': [result()]})
        with patch('Plugins.globalping.requests.Session', return_value=self.context(session)), patch('Plugins.globalping.time.monotonic', side_effect=[0, 1, 2, 46]), patch('Plugins.globalping.time.sleep'), redirect_stdout(io.StringIO()):
            output = plugin.engage('FI', '1.1.1.1')
        self.assertEqual(len(output), 1)
        session.get.assert_called_once()

    def test_config_limit_and_environment_token(self):
        with patch.dict(os.environ, {}, clear=True):
            for value in [True, 0, '5', 51]:
                with self.assertRaises(ValueError):
                    globalping({'globalpingLimit': value}).prepare()
        with patch.dict(os.environ, {'GLOBALPING_TOKEN': 'test-env-token'}, clear=True):
            plugin = globalping({'globalpingLimit': 100})
            self.assertTrue(plugin.prepare())
            self.assertEqual(plugin.token, 'test-env-token')

    def test_plugin_is_discovered(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(snake.main(['--list-plugins']), 0)
        self.assertIn('globalping', output.getvalue().splitlines())


if __name__ == '__main__':
    unittest.main()
