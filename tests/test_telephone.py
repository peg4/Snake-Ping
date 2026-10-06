from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup

from Plugins.telephone import telephone


class TelephoneTests(unittest.TestCase):
    directory = {'example.com': {'http://lg.example.com/speedtest/': {'ipv4': ['192.0.2.1']},
                                'https://lg.example.com/speedtest': {'ipv4': ['192.0.2.1']}}}
    geography = {'example.com': {'https://lg.example.com/speedtest/': {'ipv4': {'192.0.2.1': 'Amsterdam, The Netherlands'}}}}

    def test_current_directory_joins_geography_deduplicates_and_prefers_https(self):
        result = telephone({}).parse_directory(self.directory, self.geography)
        points = list(result['NL'].values())
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]['url'], 'https://lg.example.com/speedtest/')
        self.assertEqual(points[0]['city'], 'Amsterdam')

    def test_ambiguous_country_frontend_and_malformed_entries_skipped(self):
        directory = {'example.com': {'https://lg.example.com/': {'ipv4': ['192.0.2.1', '192.0.2.2']}, 'invalid': None}}
        geography = {'example.com': {'https://lg.example.com/': {'ipv4': {'192.0.2.1': 'Amsterdam, The Netherlands', '192.0.2.2': 'London, United Kingdom'}}}}
        self.assertEqual(telephone({}).parse_directory(directory, geography), {})
        self.assertIsNone(telephone.endpoint('https://user:password@example.com/'))
        self.assertIsNone(telephone.endpoint('ftp://example.com/'))

    def test_prepare_uses_current_data_paths(self):
        directory, geography = Mock(), Mock()
        directory.json.return_value = self.directory
        geography.json.return_value = self.geography
        def get(url, **kwargs):
            return geography if url.endswith('/everything.json') else directory
        plugin = telephone({})
        with patch('Plugins.telephone.requests.get', side_effect=get) as request:
            self.assertTrue(plugin.prepare())
        self.assertEqual({c.args[0] for c in request.call_args_list}, {plugin.catalog_root + 'lg.json', plugin.catalog_root + 'everything.json'})
        self.assertIn('NL', plugin.locations)

    def test_network_failure_uses_bundled_snapshot(self):
        plugin = telephone({})
        with patch('Plugins.telephone.requests.get', side_effect=requests.Timeout('directory timed out')), redirect_stdout(io.StringIO()) as output:
            self.assertTrue(plugin.prepare())
        self.assertIn('using bundled directory', output.getvalue())
        self.assertTrue(plugin.locations['NL'])

    def session_context(self, session):
        return Mock(__enter__=Mock(return_value=session), __exit__=Mock(return_value=False))

    def test_legacy_ajax_keeps_subdirectory_and_encodes_target(self):
        plugin = telephone({})
        plugin.target = 'example.com'
        session = Mock()
        session.get.return_value = Mock(text='<html>Telephone Looking Glass</html>', url='https://lg.example.com/speedtest/')
        session.post.return_value = Mock(text='rtt min/avg/max/mdev = 1/2.5/4/1 ms')
        point = {'url': 'https://lg.example.com/speedtest/', 'provider': 'Example', 'city': 'Amsterdam'}
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)):
            result = plugin.run(('node', point))
        self.assertEqual(result['avg'], 2.5)
        self.assertEqual(session.post.call_args.args[0], 'https://lg.example.com/speedtest/ajax.php')
        self.assertEqual(session.post.call_args.kwargs['params'], {'cmd': 'ping', 'host': 'example.com'})

    def test_hybula_csrf_session_form_then_backend(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        form = '<form action="/"><input type="hidden" name="csrfToken" value="test-token"><input name="targetHost"><select name="backendMethod"><option value="ping"></option></select></form>'
        session.get.side_effect = [Mock(text=form, url='https://lg.example.com/'), Mock(text='round-trip min/avg/max/stddev = 1/3/4/1 ms')]
        session.post.return_value = Mock(text='<script>callBackend(); function callBackend() { xhr.open("GET", "backend.php"); }</script>')
        point = {'url': 'https://lg.example.com/', 'provider': 'Example'}
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)):
            result = plugin.run(('node', point))
        self.assertEqual(result['avg'], 3)
        self.assertEqual(session.post.call_args.kwargs['data'], {'csrfToken': 'test-token', 'targetHost': '1.1.1.1', 'backendMethod': 'ping', 'submitForm': ''})
        self.assertEqual(session.get.call_args.args[0], 'https://lg.example.com/backend.php')

    def test_hybula_rejected_form_does_not_request_backend(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        session.get.return_value = Mock(text='<form><input name="csrfToken"><input name="targetHost"><select name="backendMethod"><option value="ping"></option></select></form>', url='https://lg.example.com/')
        session.post.return_value = Mock(text='CSRF validation failed <script>function callBackend() { xhr.open("GET", "backend.php"); }</script>')
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)), redirect_stdout(io.StringIO()):
            self.assertEqual(plugin.run(('node', {'url': 'https://lg.example.com/'})), {})
        self.assertEqual(session.get.call_count, 1)

    def test_node_timeout_isolated_and_no_failed_measurements(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        session.get.side_effect = requests.Timeout('node offline')
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)), redirect_stdout(io.StringIO()):
            self.assertEqual(plugin.run(('node', {'url': 'https://lg.example.com/'})), {})
        self.assertIsNone(plugin.average('100% packet loss'))

    def test_new_hybula_refresh_and_fetch_backend(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        form = '<form><input name="csrfToken" type="hidden" value="token"><input name="targetHost"><select name="backendMethod"><option value="ping"></option></select></form>'
        session.get.side_effect = [Mock(text=form, url='https://lg.example.com/'),
            Mock(text="<script>fetch('backend.php')</script>"),
            Mock(text='rtt min/avg/max/mdev = 1/2/3/1 ms')]
        session.post.return_value = Mock(text='', headers={'Refresh': '0'})
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)):
            result = plugin.run(('node', {'url': 'https://lg.example.com/'}))
        self.assertEqual(result['avg'], 2)
        self.assertEqual([c.args[0] for c in session.get.call_args_list], ['https://lg.example.com/', 'https://lg.example.com/', 'https://lg.example.com/backend.php'])

    def test_refresh_error_does_not_start_backend(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        form = '<form><input name="csrfToken"><input name="targetHost"><select name="backendMethod"><option value="ping"></option></select></form>'
        session.get.side_effect = [Mock(text=form, url='https://lg.example.com/'), Mock(text='<div class="alert-danger">Missing or incorrect CSRF token.</div>')]
        session.post.return_value = Mock(text='', headers={'Refresh': '0'})
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(plugin.run(('node', {'url': 'https://lg.example.com/'})), {})
        self.assertIn('Missing or incorrect CSRF token', output.getvalue())
        self.assertEqual(session.get.call_count, 2)

    def test_bacloud_get_and_three_value_freebsd_summary(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        page = '<p>Server Location: Lithuania, EU Other Location: Chicago, USA Test IPv4: 192.0.2.1</p><form id="networktest"><input name="host"><select name="cmd"><option value="ping"></option></select></form>'
        session.get.side_effect = [Mock(text=page, url='https://lg-lt.example.com/'), Mock(text='round-trip min/avg/max = 6.952/7.022/7.084 ms')]
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)):
            result = plugin.run(('node', {'url': 'https://lg-lt.example.com/', 'country': 'LT'}))
        self.assertEqual(result['avg'], 7.022)
        self.assertEqual(result['country'], 'LT')
        session.post.assert_not_called()
        self.assertEqual(session.get.call_args.kwargs['params'], {'cmd': 'ping', 'host': '1.1.1.1'})

    def test_hostname_countries_override_bad_ip_geolocation(self):
        plugin = telephone({})
        directory = {'bacloud.com': {url: {'ipv4': ['192.0.2.1']} for url in ['https://lg-uk-eu.bacloud.com/', 'https://lg-chi-us.bacloud.com/']}}
        geography = {'bacloud.com': {url: {'ipv4': {'192.0.2.1': 'Lithuania'}} for url in directory['bacloud.com']}}
        points = plugin.parse_directory(directory, geography)
        self.assertNotIn('LT', points)
        self.assertEqual(set(points), {'GB', 'US'})
        self.assertEqual(plugin.hostname_country('https://lg-chicago.serverhub.com/', 'serverhub.com'), 'US')
        self.assertEqual(plugin.hostname_country('https://sgp.lg.vebble.com/', 'vebble.com'), 'SG')
        self.assertEqual(plugin.page_location(BeautifulSoup('Server Location: Chicago, USA Other Location: Lithuania, EU Test IPv4: 192.0.2.1', 'html.parser')), ('US', 'Chicago'))

    def test_provider_tld_is_not_a_country_hint(self):
        self.assertIsNone(telephone({}).hostname_country('https://lg.example.de/', 'example.de'))

    def test_actual_page_country_mismatch_prevents_ping(self):
        plugin = telephone({})
        session = Mock()
        session.get.return_value = Mock(text='<input readonly value="Chicago, USA">', url='https://lg.example.com/')
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)), redirect_stdout(io.StringIO()):
            self.assertEqual(plugin.run(('node', {'url': 'https://lg.example.com/', 'country': 'DE'})), {})
        session.post.assert_not_called()
        self.assertEqual(session.get.call_count, 1)

    def test_terms_are_not_accepted_implicitly(self):
        plugin = telephone({})
        plugin.target = '1.1.1.1'
        session = Mock()
        session.get.return_value = Mock(text='<form><input name="csrfToken"><input name="targetHost"><input name="checkTerms" type="checkbox"><select name="backendMethod"><option value="ping"></option></select></form>', url='https://lg.example.com/')
        with patch('Plugins.telephone.requests.Session', return_value=self.session_context(session)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(plugin.run(('node', {'url': 'https://lg.example.com/'})), {})
        self.assertIn('telephoneAcceptTerms', output.getvalue())
        session.post.assert_not_called()

    def test_finland_extra_points_are_added_to_live_directory(self):
        plugin = telephone({})
        plugin.add_extra_points()
        self.assertEqual(len(plugin.locations['FI']), 2)


if __name__ == '__main__':
    unittest.main()
