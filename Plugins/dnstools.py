"""DNS Tools SignalR JSON streaming over HTTP long polling; no browser."""
import ast
from collections import defaultdict
import json
import math
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from Plugins.base import Base


class dnstools(Base):
    site = 'https://dnstools.ws'
    hub = 'https://api.dnstools.ws/hub'
    separator = '\x1e'

    def __init__(self, config):
        super().__init__(config)
        self.load()
        self.workers = []

    @staticmethod
    def parse_workers(bundle):
        match = re.search(r"e\.exports=JSON\.parse\('((?:\\.|[^'\\])*)'\)", bundle)
        if not match:
            raise RuntimeError('DNS Tools worker configuration not found')
        # Decode a literal string, never execute the downloaded JavaScript.
        config = json.loads(ast.literal_eval("'" + match.group(1) + "'"))
        workers = config.get('workers')
        if not isinstance(workers, list):
            raise RuntimeError('Invalid DNS Tools worker directory')
        return [w for w in workers if isinstance(w, dict) and all(isinstance(w.get(key), str) for key in ('id', 'country', 'city'))]

    def prepare(self):
        response = requests.get(self.site + '/', timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup.select('script[src]'):
            path = script['src']
            if re.fullmatch(r'/static/js/main\.[a-zA-Z0-9]+\.chunk\.js', path):
                response = requests.get(urljoin(self.site, path), timeout=20)
                response.raise_for_status()
                self.workers = self.parse_workers(response.text)
                return bool(self.workers)
        raise RuntimeError('DNS Tools application bundle not found')

    def canRunAny(self):
        return True

    @staticmethod
    def parse_frames(buffer, chunk):
        parts = (buffer + chunk).split('\x1e')
        return [json.loads(part) for part in parts[:-1] if part.strip()], parts[-1]

    def engage(self, origin, target):
        print('Running dnstools.ws')
        workers = {w['id']: w for w in self.workers if origin == 'any' or w['country'].upper() == origin}
        if not workers:
            print('dnstools: no workers in selected country')
            return {}
        samples = defaultdict(list)
        with requests.Session() as session:
            response = session.post(self.hub + '/negotiate', params={'negotiateVersion': 1}, timeout=20)
            response.raise_for_status()
            negotiation = response.json()
            if not any(t.get('transport') == 'LongPolling' for t in negotiation.get('availableTransports', [])):
                raise RuntimeError('DNS Tools does not offer HTTP long polling')
            params = {'id': negotiation['connectionToken']}
            def send(message):
                response = session.post(self.hub, params=params, data=json.dumps(message) + self.separator,
                    headers={'Content-Type': 'text/plain;charset=UTF-8'}, timeout=15)
                response.raise_for_status()
            try:
                response = session.get(self.hub, params=params, timeout=20)
                response.raise_for_status()
                send({'protocol': 'json', 'version': 1})
                response = session.get(self.hub, params=params, timeout=20)
                response.raise_for_status()
                handshake, buffer = self.parse_frames('', response.text)
                if not handshake or handshake[0].get('error'):
                    raise RuntimeError('DNS Tools handshake failed')
                send({'type': 4, 'invocationId': '1', 'target': 'ping',
                    'arguments': [{'host': target, 'protocol': 0, 'workers': list(workers)}]})
                deadline = time.monotonic() + 45
                complete = False
                while time.monotonic() < deadline and not complete:
                    try:
                        response = session.get(self.hub, params=params, timeout=max(1, min(25, deadline - time.monotonic())))
                        response.raise_for_status()
                    except requests.RequestException as exc:
                        print(f'dnstools: stream interrupted; retaining received measurements ({type(exc).__name__})')
                        break
                    if response.status_code == 204:
                        break
                    messages, buffer = self.parse_frames(buffer, response.text)
                    for message in messages:
                        if message.get('type') == 7:
                            print('dnstools: stream closed by service')
                            complete = True
                        if message.get('invocationId') != '1':
                            continue
                        if message.get('type') == 3:
                            complete = True
                            if message.get('error'):
                                print('dnstools: ' + str(message['error']))
                        elif message.get('type') == 2:
                            item = message.get('item', {})
                            worker = item.get('workerId')
                            result = item.get('response', {})
                            if worker not in workers:
                                continue
                            if isinstance(result.get('error'), dict):
                                print(f"dnstools worker {worker}: {result['error'].get('message', 'failed')}")
                            reply = result.get('reply')
                            if isinstance(reply, dict):
                                try:
                                    avg = float(reply['rtt'])
                                    if math.isfinite(avg) and avg >= 0:
                                        samples[worker].append(avg)
                                except (KeyError, ValueError, TypeError):
                                    continue
                if not complete:
                    print('dnstools: measurement stream incomplete')
            finally:
                try:
                    send({'type': 5, 'invocationId': '1'})
                except requests.RequestException:
                    pass
                try:
                    session.delete(self.hub, params=params, timeout=10)
                except requests.RequestException:
                    pass
        return {key: {'avg': sum(values) / len(values), 'city': workers[key]['city'],
            'provider': workers[key].get('providerName', 'n/a'), 'source': 'dnstools'} for key, values in samples.items() if values}
