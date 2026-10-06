import asyncio
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import snake
from Plugins.base import Base
from Plugins.mudfish import mudfish
from Plugins.lookingHouse import lookingHouse
from Plugins.telephone import telephone
from Plugins.vultr import vultr


class CoreTests(unittest.TestCase):
    def test_country_aliases_and_exact_match(self):
        base = Base()
        for value, expected in [('uk', 'GB'), ('nld', 'NL'), ('Netherlands', 'NL'), ('UAE', 'AE')]:
            self.assertEqual(base.GetAlpha2(value), expected)
        self.assertFalse(base.GetAlpha2('ZZ'))
        self.assertFalse(base.GetAlpha2('lands'))

    def test_cli_works_outside_project(self):
        with tempfile.TemporaryDirectory(dir=snake.ROOT.parent) as temp:
            result = subprocess.run([sys.executable, str(snake.ROOT / 'snake.py'), '--list-plugins'], cwd=temp, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('mudfish', result.stdout)

    def test_invalid_cli_inputs_fail_before_network(self):
        for argv in [('ZZ', '1.1.1.1'), ('NL', 'https://example.com'), ('NL', 'compare'), ('NL', '1.1.1.1', 'missing')]:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                snake.main(argv)
            self.assertEqual(error.exception.code, 2)

    def test_worker_count_validation(self):
        with tempfile.TemporaryDirectory(dir=snake.ROOT.parent) as temp:
            path = Path(temp) / 'config.json'
            for workers in (0, -1, '6', True, 33):
                path.write_text(json.dumps({'workers': workers}))
                with self.assertRaises(ValueError):
                    snake.load_config(path)

    def test_one_plugin_failure_does_not_stop_others(self):
        class Broken(Base):
            def prepare(self):
                raise RuntimeError('provider offline')
        class Good(Base):
            def prepare(self):
                return True
            def engage(self, origin, target):
                return {'one': {'avg': 3, 'source': 'good'}}
        module = Mock(broken=Broken, good=Good)
        with patch('Plugins.base.importlib.import_module', return_value=module), redirect_stdout(io.StringIO()):
            results = snake.collect(Base({'workers': 2}), [{'plugin': p, 'origin': 'NL', 'target': '1.1.1.1'} for p in ('broken', 'good')])
        self.assertEqual(len(list(snake.valid_results(results))), 1)

    def test_results_keep_same_ids_and_sort(self):
        results = [{'id': {'avg': '20', 'source': 'a', 'city': 'A', 'provider': 'A'}}, {'id': {'avg': '3', 'source': 'b', 'city': 'B', 'provider': 'B'}}]
        output = io.StringIO()
        with patch('snake.collect', return_value=results), redirect_stdout(output):
            self.assertEqual(snake.main(['NL', '1.1.1.1']), 0)
        self.assertLess(output.getvalue().index('3.00ms'), output.getvalue().index('20.00ms'))

    def test_invalid_measurements_skipped(self):
        results = [{'x': {'avg': value}} for value in ('nan', 'inf', -1, None, 'timeout')]
        self.assertEqual(list(snake.valid_results(results)), [])

    def test_empty_results_have_failure_exit(self):
        with patch('snake.collect', return_value=[{}]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(snake.main(['NL', '1.1.1.1']), 1)

    def test_compare_preserves_sources_with_same_probe_id(self):
        initial = [{'id': {'avg': 1, 'ipv4': ip, 'source': source, 'city': 'London', 'provider': source}} for ip, source in [('192.0.2.1', 'a'), ('192.0.2.2', 'b')]]
        remote = [{'id': {'avg': 2, 'source': 'remote', 'city': 'Amsterdam', 'provider': 'remote'}}]
        with patch('snake.collect', side_effect=[initial, remote, remote]) as collect, redirect_stdout(io.StringIO()):
            self.assertEqual(snake.main(['UK,NL', 'compare']), 0)
        self.assertEqual([call.args[1][0]['target'] for call in collect.call_args_list[1:]], ['192.0.2.1', '192.0.2.2'])

    def test_unsupported_compare_skips_prepare(self):
        instance = Mock()
        instance.isComparable.return_value = False
        module = Mock(test=Mock(return_value=instance))
        with patch('Plugins.base.importlib.import_module', return_value=module):
            self.assertEqual(Base().run({'plugin': 'test', 'origin': 'GB,NL', 'target': 'compare'}), {})
        instance.prepare.assert_not_called()


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_failure_closes_pages_and_browser(self):
        page = Mock(goto=AsyncMock(side_effect=RuntimeError('offline')), close=AsyncMock())
        browser = Mock(newPage=AsyncMock(return_value=page), close=AsyncMock())
        base = Base()
        with patch.object(base, 'launchBrowser', AsyncMock(return_value=browser)):
            with self.assertRaisesRegex(RuntimeError, 'Could not load'):
                await base.browse('https://example.com', wait=1)
        self.assertEqual(page.close.await_count, 4)
        browser.close.assert_awaited_once()

    async def test_success_closes_browser(self):
        page = Mock(goto=AsyncMock(), waitForSelector=AsyncMock(), content=AsyncMock(return_value='<html/>'), close=AsyncMock())
        browser = Mock(newPage=AsyncMock(return_value=page), close=AsyncMock())
        base = Base()
        with patch.object(base, 'launchBrowser', AsyncMock(return_value=browser)):
            self.assertEqual(await base.browse('https://example.com', wait=0, element='#ready'), '<html/>')
        page.close.assert_awaited_once()
        browser.close.assert_awaited_once()



class ProviderTests(unittest.TestCase):
    def test_mudfish_current_markup_and_legacy(self):
        html = '<label><input id="checkbox_node_383" value="383" data-country="NL"><span>NL Europe (Amsterdam - Azure)</span></label>'
        html += '<input id="checkbox_node_4" location="NL Europe (Rotterdam - Provider)">'
        html += '<label><input id="checkbox_node_9" value="9" data-country="GB"><span>GB Europe (London - Azure)</span></label>'
        self.assertEqual(mudfish({}).discover(html, 'NL'), ['383', '4'])

    def test_mudfish_all_60_nodes_are_measured(self):
        nodes = ''.join(f'<label><input id="checkbox_node_{i}" value="{i}" data-country="NL"><span>NL Europe (City{i} - Provider)</span></label>' for i in range(60))
        session = Mock()
        session.get.return_value = Mock(text=nodes)
        def start(url, data, timeout):
            rows = ''.join(f'<tr data-sid="{sid}" data-ip="192.0.2.1"><td>NL Europe (City{sid} - Provider)</td></tr>' for sid in data['nodes'].split(','))
            return Mock(text=f'<table id="ping_result_table"><tbody>{rows}</tbody></table>')
        session.post.side_effect = start
        context = Mock()
        context.__enter__ = Mock(return_value=session)
        context.__exit__ = Mock(return_value=False)
        plugin = mudfish({})
        def measure(row, target):
            return {row[0]: {'avg': 1}}
        with patch('Plugins.mudfish.requests.Session', return_value=context), patch.object(plugin, 'measure', side_effect=measure), redirect_stdout(io.StringIO()):
            self.assertEqual(len(plugin.engage('NL', '1.1.1.1')), 60)
        self.assertEqual([len(call.kwargs['data']['nodes'].split(',')) for call in session.post.call_args_list], [29, 29, 2])

    def test_mudfish_current_json_result(self):
        response = Mock()
        response.json.return_value = {'result': 'UP', 'rtt_avg': '2.67'}
        with patch('Plugins.mudfish.requests.get', return_value=response):
            result = mudfish({}).measure(('383', '168.63.103.13', 'NL Europe (Amsterdam - Azure)'), '1.1.1.1')
        self.assertEqual(result['383']['avg'], 2.67)
        self.assertEqual(result['383']['ipv4'], '168.63.103.13')

    def test_mudfish_failed_node_is_skipped(self):
        response = Mock()
        response.json.return_value = {'result': 'DOWN', 'rtt_avg': None}
        with patch('Plugins.mudfish.requests.get', return_value=response), redirect_stdout(io.StringIO()):
            self.assertEqual(mudfish({}).measure(('383', '168.63.103.13', 'NL Europe (Amsterdam - Azure)'), '1.1.1.1'), {})

    def test_failed_http_preparation_returns_false(self):
        response = Mock(status_code=503)
        with patch('Plugins.telephone.requests.get', return_value=response), patch.object(telephone, 'snapshot', snake.ROOT / 'tests' / 'missing-directory.json'), redirect_stdout(io.StringIO()):
            self.assertFalse(telephone({}).prepare())
        with patch('Plugins.vultr.requests.post', return_value=response):
            self.assertFalse(vultr({}).prepare())

    def house_card(self, item='192-0-2-1', ip='192.0.2.1', city='Amsterdam', company='provider'):
        return f"<div class='card'><a href='/companies/{company}/looking-glass/{item}'>{city}, Netherlands</a><input id='IPv4Input-{item}' value='{ip}'><button onclick=\"StartNetworkTest('{company}', '{item}', 'ping4');\">ping4</button></div>"

    def test_lookinghouse_keeps_each_probe_ip(self):
        cards = ''.join(self.house_card(f'192-0-2-{i}', f'192.0.2.{i}', f'City{i}') for i in (1, 2))
        html = f'<div id="LookingGlassServers">{cards}</div>'
        plugin = lookingHouse({})
        plugin.mapping = {'NL': '/looking-glass/countries/netherlands'}
        with patch.object(plugin, 'get_html', return_value=html), patch.object(plugin, 'run', side_effect=lambda point: {**point[1], 'avg': 1}), redirect_stdout(io.StringIO()):
            results = plugin.engage('NL', '1.1.1.1')
        self.assertEqual({r['ipv4'] for r in results.values()}, {'192.0.2.1', '192.0.2.2'})

    def test_lookinghouse_country_links_use_codes(self):
        html = '<a href="/looking-glass/countries/netherlands" data-bs-target="#LookingGlassNav-15"><span class="country-icons country-nl"></span>Netherlands 51</a>'
        html += '<a href="/looking-glass/countries/netherlands/amsterdam">Amsterdam</a>'
        plugin = lookingHouse({})
        with patch.object(plugin, 'get_html', return_value=html):
            self.assertTrue(plugin.prepare())
        self.assertEqual(plugin.mapping, {'NL': '/looking-glass/countries/netherlands'})
        self.assertEqual(plugin.country_ids, {'/looking-glass/countries/netherlands': '15'})

    def test_lookinghouse_all_pagination_pages_are_used(self):
        path = '/looking-glass/countries/netherlands'
        html = f'<div id="LookingGlassServers">{self.house_card()}</div><div class="pagination"><a href="{path}?start=20">2</a></div>'
        second = f'<div id="LookingGlassServers">{self.house_card("192-0-2-2", "192.0.2.2")}</div><div class="pagination"><a href="{path}?start=20">2</a></div>'
        plugin = lookingHouse({})
        plugin.mapping = {'NL': path}
        with patch.object(plugin, 'get_html', side_effect=[html, second]) as get_html, patch.object(plugin, 'run', side_effect=lambda point: {**point[1], 'avg': 1}), redirect_stdout(io.StringIO()):
            self.assertEqual(len(plugin.engage('NL', '1.1.1.1')), 2)
        self.assertEqual(get_html.call_count, 2)

    def test_lookinghouse_pagination_uses_search_action(self):
        plugin = lookingHouse({})
        path = '/looking-glass/countries/netherlands'
        plugin.country_ids = {path: '15'}
        response = Mock()
        response.json.return_value = {'Error': '0', 'Templates': {'looking_glass': self.house_card('192-0-2-2', '192.0.2.2')}}
        with patch('Plugins.lookingHouse.requests.post', return_value=response) as post, patch('Plugins.lookingHouse.requests.get') as get:
            html = plugin.get_html(path + '?start=20')
        get.assert_not_called()
        self.assertEqual(post.call_args.kwargs['data'], {'country': '15', 'city': 0, 'ipv6': 2, 'start': 20})
        self.assertEqual(len(plugin.parse_points(html)), 1)

    def test_lookinghouse_current_network_action(self):
        response = Mock()
        response.json.return_value = {'Error': 0, 'Template': '<pre>rtt min/avg/max/mdev = 1.179/1.735/2.354/0.511 ms</pre>'}
        plugin = lookingHouse({})
        plugin.target = '1.1.1.1'
        point = ('provider/item', {'company': 'provider', 'item': 'item', 'ipv4': '192.0.2.1'})
        with patch('Plugins.lookingHouse.requests.post', return_value=response) as post:
            result = plugin.run(point)
        self.assertEqual(result['avg'], 1.735)
        self.assertEqual(post.call_args.kwargs['data'], {'url': 'provider', 'item': 'item', 'network': 'ping4', 'input': '1.1.1.1'})
        self.assertTrue(post.call_args.args[0].endswith('/action/looking-glass/network'))

    def test_lookinghouse_failed_response_is_skipped(self):
        plugin = lookingHouse({})
        plugin.target = '1.1.1.1'
        point = ('provider/item', {'company': 'provider', 'item': 'item'})
        for payload in ({'Error': 'offline'}, {'Error': 0, 'Template': 'No data'}, {'Error': 0}, []):
            response = Mock()
            response.json.return_value = payload
            with patch('Plugins.lookingHouse.requests.post', return_value=response), redirect_stdout(io.StringIO()):
                self.assertEqual(plugin.run(point), {})

    def test_lookinghouse_malformed_card_skipped(self):
        html = '<div id="LookingGlassServers"><div class="card"><input id="IPv4Input-bad" value="invalid"></div>' + self.house_card() + '</div>'
        self.assertEqual(len(lookingHouse({}).parse_points(html)), 1)


if __name__ == '__main__':
    unittest.main()
