"""ping.pe task start/poll/stop HTTP protocol; no browser."""
from collections import defaultdict
import json
import math
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
import requests

from Plugins.base import Base


class pingpe(Base):
    site = 'https://ping.pe'

    def __init__(self, config):
        super().__init__(config)
        self.load()

    def prepare(self):
        return True

    def canRunAny(self):
        return True

    def parse_nodes(self, html, origin):
        soup = BeautifulSoup(html, 'html.parser')
        nodes = {}
        for row in soup.select('tr[data-pinger-id][data-location]'):
            location = row['data-location'].split(', ')
            if origin != 'any' and self.GetAlpha2(location[0]) != origin:
                continue
            nodes[row['data-pinger-id']] = {'city': location[-1] if len(location) > 1 else 'n/a', 'provider': row.get('data-provider', 'n/a')}
        return nodes

    @staticmethod
    def add_samples(samples, seen, data, nodes):
        for item in data.get('data', []):
            if not isinstance(item, dict):
                continue
            node = item.get('node_id')
            if node not in nodes:
                continue
            identity = (node, item.get('timestamp_ms'))
            if identity in seen:
                continue
            try:
                value = float(item['result']) / 1000
            except (KeyError, TypeError, ValueError):
                continue
            if value >= 0 and math.isfinite(value):
                samples[node].append(value)
                seen.add(identity)

    def engage(self, origin, target):
        print('Running ping.pe')
        samples, seen, streams = defaultdict(list), set(), []
        page_url = self.site + '/' + quote(target, safe='')
        with requests.Session() as session:
            session.headers.update({'Origin': self.site, 'Referer': page_url})
            response = session.get(page_url, timeout=25)
            response.raise_for_status()
            # Follow the public page's cookie-and-redirect step, without executing JS.
            match = re.search(r'document.cookie="antiflood=([a-zA-Z0-9]+);', response.text)
            if match:
                session.cookies.set('antiflood', match.group(1), domain='ping.pe', path='/')
                response = session.get(page_url, params={'browsercheck': 'ok'}, timeout=25)
                response.raise_for_status()
            nodes = self.parse_nodes(response.text, origin)
            if not nodes:
                raise RuntimeError('ping.pe returned no nodes in selected country, or requires interactive verification')
            match = re.search(r'var taskStartToken\s*=\s*("[^"\n]*")', response.text)
            if not match:
                raise RuntimeError('ping.pe start token not found; the service page may have changed')
            token = json.loads(match.group(1))
            try:
                response = session.post(self.site + '/ajax_startTask_v1.php', data={'query': target, 'interval_s': '5', 'dense_mode': '0', 'start_token': token}, timeout=25)
                response.raise_for_status()
                payload = response.json()
                if not payload.get('ok'):
                    raise RuntimeError(str(payload.get('error', 'ping.pe task start rejected')))
                streams = [payload['data'][key] for key in ('stream_id', 'stream_id_mtr') if payload['data'].get(key)]
                if not payload['data'].get('stream_id'):
                    raise RuntimeError('ping.pe returned no stream ID')
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    time.sleep(min(5, max(0, deadline - time.monotonic())))
                    try:
                        response = session.get(self.site + '/ajax_getPingResults_v2.php', params={'stream_id': streams[0]}, timeout=15)
                        response.raise_for_status()
                        self.add_samples(samples, seen, response.json(), nodes)
                    except requests.RequestException as exc:
                        print(f'pingpe: polling failed; retaining received measurements ({type(exc).__name__})')
                        break
                    if all(len(samples[node]) >= 3 for node in nodes):
                        break
            finally:
                for stream in streams:
                    try:
                        session.get(self.site + '/ajax_stopTask.php', params={'stream_id': stream}, timeout=10)
                    except requests.RequestException:
                        print('pingpe: could not stop a task; the service will expire it')
        return {node: {**nodes[node], 'avg': sum(values) / len(values), 'source': 'pingpe'} for node, values in samples.items() if values}
