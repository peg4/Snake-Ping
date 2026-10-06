from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock, patch

import websocket

import snake
from Plugins.base import Base
from Plugins.lookingCenter import lookingCenter
from Plugins.mtrtools import mtrtools


def probe(identifier, country='NL', **extra):
    return {'id': identifier, 'unlocode': country + '-AMS', 'country': 'Netherlands',
            'city': 'Amsterdam', 'provider': 'Example', 'status': True,
            'caps': {'ping': True}, **extra}


class NewProviderTests(unittest.TestCase):
    def test_regions_and_countries_intersect_with_capabilities(self):
        plugin = mtrtools({})
        plugin.groups = [{'name': 'Europe', 'servers': [probe('nl'), probe('gb', 'GB'),
                           probe('offline', status=False), probe('no-ping', caps={'ping': False}), None]},
                         {'name': 'Asia', 'servers': [probe('jp', 'JP')]}]
        plugin.regions = ['eu']
        self.assertEqual(set(plugin.selected_points('NL')), {'nl'})
        self.assertEqual(set(plugin.selected_points('any')), {'nl', 'gb'})
        plugin.regions = ['EU', 'asia']
        self.assertEqual(set(plugin.selected_points('any')), {'nl', 'gb', 'jp'})
        plugin.regions = ['Atlantis']
        with self.assertRaisesRegex(ValueError, 'Unknown mtrtools region'):
            plugin.selected_points('any')

    def test_mtr_stream_split_summary_unknown_ids_and_cleanup(self):
        plugin = mtrtools({})
        plugin.groups = [{'name': 'Europe', 'servers': [probe('nl')]}]
        connection = Mock()
        connection.recv.side_effect = [
            '{"id":"unrelated","type":"end"}',
            json.dumps({'id': 'task', 'type': 'data', 'data': 'rtt min/avg/max/mdev = 1/'}),
            json.dumps({'id': 'task', 'type': 'data', 'data': '2.5/4/0.1 ms\n'}),
            '{"id":"task","type":"end"}']
        with patch('Plugins.mtrtools.uuid.uuid4', return_value=Mock(hex='task')), patch('Plugins.mtrtools.time.sleep'), patch('Plugins.mtrtools.websocket.create_connection', return_value=connection), redirect_stdout(io.StringIO()):
            result = plugin.engage('NL', '1.1.1.1')
        self.assertEqual(result['nl']['avg'], 2.5)
        self.assertEqual(json.loads(connection.send.call_args.args[0]), {'id': 'task', 'target': '1.1.1.1', 'type': 'ping', 'probe': 'nl'})
        connection.close.assert_called_once()

    def test_mtr_queue_continues_after_node_errors(self):
        plugin = mtrtools({'workers': 1})
        plugin.groups = [{'name': 'Europe', 'servers': [probe('bad'), probe('good')]}]
        connection = Mock()
        connection.recv.side_effect = ['{"id":"first","error":"probe unavailable"}',
            '{"id":"second","type":"data","data":"round-trip min/avg/max/stddev = 1/3/4/1 ms"}',
            '{"id":"second","type":"end"}']
        with patch('Plugins.mtrtools.uuid.uuid4', side_effect=[Mock(hex='first'), Mock(hex='second')]), patch('Plugins.mtrtools.time.sleep'), patch('Plugins.mtrtools.websocket.create_connection', return_value=connection), redirect_stdout(io.StringIO()):
            result = plugin.engage('NL', 'example.com')
        self.assertEqual(set(result), {'good'})
        self.assertEqual(connection.send.call_count, 2)
        connection.close.assert_called_once()

    def test_mtr_disconnect_keeps_finished_measurement(self):
        plugin = mtrtools({})
        plugin.groups = [{'name': 'Europe', 'servers': [probe('nl')]}]
        connection = Mock()
        connection.recv.side_effect = ['{"id":"task","type":"data","data":"rtt min/avg/max/mdev = 1/2/3/1 ms"}', websocket.WebSocketConnectionClosedException()]
        with patch('Plugins.mtrtools.uuid.uuid4', return_value=Mock(hex='task')), patch('Plugins.mtrtools.time.sleep'), patch('Plugins.mtrtools.websocket.create_connection', return_value=connection), redirect_stdout(io.StringIO()):
            result = plugin.engage('NL', '1.1.1.1')
        self.assertEqual(result['nl']['avg'], 2)
        connection.close.assert_called_once()

    def test_cli_region_selects_only_mtrtools(self):
        result = [{'id': {'avg': 1}}]
        with patch('snake.collect', return_value=result) as collect, redirect_stdout(io.StringIO()):
            self.assertEqual(snake.main(['any', '1.1.1.1', '--region', 'Europe', '--region', 'Asia']), 0)
        self.assertEqual(collect.call_args.args[1], [{'plugin': 'mtrtools', 'origin': 'any', 'target': '1.1.1.1', 'regions': ['Europe', 'Asia']}])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            snake.main(['NL', '1.1.1.1', 'mudfish', '--region', 'Europe'])

    def test_mtr_silent_probe_deadline_closes_connection(self):
        plugin = mtrtools({})
        plugin.groups = [{'name': 'Europe', 'servers': [probe('nl')]}]
        connection = Mock()
        connection.recv.side_effect = websocket.WebSocketTimeoutException()
        with patch('Plugins.mtrtools.time.monotonic', side_effect=[0, 0, 46]), patch('Plugins.mtrtools.time.sleep'), patch('Plugins.mtrtools.websocket.create_connection', return_value=connection), redirect_stdout(io.StringIO()):
            result = plugin.engage('NL', '1.1.1.1')
        self.assertEqual(result, {})
        connection.recv.assert_called_once()
        connection.close.assert_called_once()

    def test_list_regions_uses_current_directory(self):
        response = Mock()
        response.json.return_value = [{'name': 'Europe', 'servers': []}, {'name': 'Asia', 'servers': []}]
        output = io.StringIO()
        with patch('Plugins.mtrtools.requests.get', return_value=response), redirect_stdout(output):
            self.assertEqual(snake.main(['--list-regions']), 0)
        self.assertEqual(output.getvalue(), 'Europe\nAsia\n')

    def test_pingsx_removed_from_discovery(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(snake.main(['--list-plugins']), 0)
        self.assertNotIn('pingsx', output.getvalue())
        self.assertIn('mtrtools', output.getvalue())
        self.assertIn('lookingCenter', output.getvalue())

    def test_lookingcenter_country_links_search_and_network_use_own_domain(self):
        plugin = lookingCenter({})
        page = '<a href="/looking-glass/countries/netherlands" data-bs-target="#LookingGlassNav-15"><span class="country-nl"></span></a>'
        response = Mock(text=page)
        with patch('Plugins.lookingHouse.requests.get', return_value=response) as get:
            self.assertTrue(plugin.prepare())
        self.assertEqual(get.call_args.args[0], 'https://looking.center/looking-glass')
        self.assertEqual(plugin.mapping['NL'], '/looking-glass/countries/netherlands')
        response.json.return_value = {'Error': '0', 'Templates': {'looking_glass': '<div class="card"></div>'}}
        with patch('Plugins.lookingHouse.requests.post', return_value=response) as post:
            plugin.get_html('/looking-glass/countries/netherlands?start=20')
        self.assertEqual(post.call_args.args[0], 'https://looking.center/action/looking-glass/search')
        response.json.return_value = {'Error': '0', 'Template': '<pre>rtt min/avg/max/mdev = 1/2/3/1 ms</pre>'}
        plugin.target = '1.1.1.1'
        point = {'company': 'example', 'item': '192-0-2-1', 'ipv4': '192.0.2.1'}
        with patch('Plugins.lookingHouse.requests.post', return_value=response) as post:
            measured = plugin.run(('example/192-0-2-1', point))
        self.assertEqual(post.call_args.args[0], 'https://looking.center/action/looking-glass/network')
        self.assertEqual(post.call_args.kwargs['headers']['Origin'], 'https://looking.center')
        self.assertEqual(measured['ipv4'], '192.0.2.1')
        self.assertEqual(measured['avg'], 2)
        self.assertTrue(plugin.isComparable())


if __name__ == '__main__':
    unittest.main()
