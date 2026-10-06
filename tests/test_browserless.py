from collections import defaultdict
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock, patch

import requests

from Plugins.dnstools import dnstools
from Plugins.pingpe import pingpe


class BrowserlessTests(unittest.TestCase):
    def test_dns_worker_literal_is_decoded_safely(self):
        bundle = r'''e.exports=JSON.parse('{"workers":[{"id":"cl","country":"CL","city":"Valdivia","providerName":"Gullo\'s Los R\xedos"}]}')'''
        workers = dnstools.parse_workers(bundle)
        self.assertEqual(workers[0]['providerName'], "Gullo's Los Ríos")
        with self.assertRaises(RuntimeError):
            dnstools.parse_workers('arbitrary JavaScript')

    def test_signalr_frames_can_span_responses(self):
        messages, pending = dnstools.parse_frames('', '{"type":2')
        self.assertEqual(messages, [])
        messages, pending = dnstools.parse_frames(pending, '}\x1e{"type":3}\x1e')
        self.assertEqual(messages, [{'type': 2}, {'type': 3}])
        self.assertEqual(pending, '')

    def test_dns_http_stream_and_cleanup_without_browser(self):
        plugin = dnstools({})
        plugin.workers = [{'id': 'nl', 'country': 'NL', 'city': 'Amsterdam', 'providerName': 'WebHorizon'}]
        session = Mock()
        negotiate = Mock()
        negotiate.json.return_value = {'connectionToken': 'test-connection', 'availableTransports': [{'transport': 'LongPolling'}]}
        session.post.side_effect = [negotiate, Mock(), Mock(), Mock()]
        reply = lambda rtt: json.dumps({'type': 2, 'invocationId': '1', 'item': {'workerId': 'nl', 'response': {'reply': {'rtt': rtt}}}}) + '\x1e'
        session.get.side_effect = [Mock(text=''), Mock(text='{}\x1e'), Mock(text=reply(2) + reply(4) + '{"type":3,"invocationId":"1"}\x1e')]
        context = Mock(__enter__=Mock(return_value=session), __exit__=Mock(return_value=False))
        with patch('Plugins.dnstools.requests.Session', return_value=context), redirect_stdout(io.StringIO()):
            result = plugin.engage('NL', '1.1.1.1')
        self.assertEqual(result['nl']['avg'], 3)
        invocation = json.loads(session.post.call_args_list[2].kwargs['data'].rstrip('\x1e'))
        self.assertEqual(invocation['arguments'][0]['workers'], ['nl'])
        session.delete.assert_called_once()

    def test_pingpe_nodes_use_current_metadata(self):
        html = '<tr data-pinger-id="NL_1" data-location="Netherlands, Amsterdam" data-provider="Example"></tr><tr data-pinger-id="US_1" data-location="USA, CA, Los Angeles"></tr>'
        self.assertEqual(pingpe({}).parse_nodes(html, 'NL'), {'NL_1': {'city': 'Amsterdam', 'provider': 'Example'}})

    def test_pingpe_microseconds_dedup_and_failed_samples(self):
        samples, seen = defaultdict(list), set()
        items = [{'node_id': 'nl', 'timestamp_ms': 1, 'result': 2500}, {'node_id': 'nl', 'timestamp_ms': 2, 'result': -2000}, {'node_id': 'nl', 'timestamp_ms': 3, 'result': 'nan'}, None]
        for _ in range(2):
            pingpe.add_samples(samples, seen, {'data': items}, {'nl': {}})
        self.assertEqual(samples['nl'], [2.5])

    def test_pingpe_stops_ping_and_mtr_when_polling_fails(self):
        plugin = pingpe({})
        session = Mock()
        html = '<tr data-pinger-id="NL_1" data-location="Netherlands, Amsterdam"></tr><script>var taskStartToken = "test-token";</script>'
        session.get.side_effect = [Mock(text=html), requests.Timeout('poll timeout'), Mock(), Mock()]
        start = Mock()
        start.json.return_value = {'ok': True, 'data': {'stream_id': 'ping', 'stream_id_mtr': 'mtr'}}
        session.post.return_value = start
        context = Mock(__enter__=Mock(return_value=session), __exit__=Mock(return_value=False))
        with patch('Plugins.pingpe.requests.Session', return_value=context), patch('Plugins.pingpe.time.sleep'), redirect_stdout(io.StringIO()):
            self.assertEqual(plugin.engage('NL', '1.1.1.1'), {})
        stopped = [call.kwargs['params']['stream_id'] for call in session.get.call_args_list if call.args[0].endswith('/ajax_stopTask.php')]
        self.assertEqual(stopped, ['ping', 'mtr'])


if __name__ == '__main__':
    unittest.main()
