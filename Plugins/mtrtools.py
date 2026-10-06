"""Browserless adapter for MTR.Tools' public probe directory and WebSocket."""
from collections import deque
import json
import math
import re
import time
import uuid

import requests
import websocket

from Plugins.base import Base


class mtrtools(Base):
    directory_url = 'https://api.mtr.tools/probes.json'
    websocket_url = 'wss://api.mtr.tools/ws'
    region_aliases = {'eu': 'Europe', 'na': 'North America', 'sa': 'South America',
                      'as': 'Asia', 'af': 'Africa', 'oc': 'Oceania', 'me': 'Middle East'}

    def __init__(self, config):
        super().__init__(config)
        self.groups = []
        self.regions = []
        self.load()

    def canRunAny(self):
        return True

    def prepare(self):
        response = requests.get(self.directory_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError('mtrtools returned no probe regions')
        self.groups = [group for group in data if isinstance(group, dict)
                       and isinstance(group.get('name'), str)
                       and isinstance(group.get('servers'), list)]
        if not self.groups:
            raise RuntimeError('mtrtools returned an invalid probe directory')
        return True

    def region_names(self):
        return list(dict.fromkeys(group['name'] for group in self.groups))

    def selected_points(self, origin):
        names = {name.casefold(): name for name in self.region_names()}
        regions = set()
        for value in self.regions:
            value = self.region_aliases.get(value.strip().casefold(), value.strip())
            if value.casefold() not in names:
                raise ValueError(f'Unknown mtrtools region: {value}; use --list-regions')
            regions.add(names[value.casefold()])
        points = {}
        for group in self.groups:
            if regions and group['name'] not in regions:
                continue
            for probe in group['servers']:
                if not isinstance(probe, dict) or not isinstance(probe.get('id'), str):
                    continue
                caps = probe.get('caps', {})
                if not probe.get('status') or not isinstance(caps, dict) or not caps.get('ping'):
                    continue
                country = str(probe.get('unlocode', '')).split('-')[0].upper()
                if not self.GetAlpha2(country):
                    country = self.GetAlpha2(probe.get('country'))
                if origin != 'any' and country != origin:
                    continue
                points[probe['id']] = {'city': probe.get('city') or 'n/a',
                                       'provider': probe.get('provider') or 'n/a',
                                       'region': group['name'], 'country': country,
                                       'source': self.__class__.__name__}
        return points

    @staticmethod
    def average(text):
        match = re.search(r'(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*[0-9.]+/([0-9.]+)/', text)
        if not match:
            return None
        try:
            value = float(match.group(1))
        except ValueError:
            return None
        return value if math.isfinite(value) and value >= 0 else None

    def engage(self, origin, target):
        print('Running mtrtools')
        self.start()
        points = self.selected_points(origin)
        if not points:
            print('mtrtools: no online ping probes match the country and regions')
            return {}
        print(f'mtrtools: testing {len(points)} nodes')
        queue, pending, output = deque(points), {}, {}
        limit = min(4, self.config.get('workers', 4))
        connection = websocket.create_connection(self.websocket_url, origin='https://mtr.tools', timeout=20)
        try:
            connection.settimeout(1)
            while queue or pending:
                now = time.monotonic()
                for task_id, task in list(pending.items()):
                    if now - task['started'] >= 45:
                        print(f"mtrtools node {task['probe']} timed out")
                        del pending[task_id]
                while queue and len(pending) < limit:
                    probe = queue.popleft()
                    task_id = uuid.uuid4().hex
                    pending[task_id] = {'probe': probe, 'started': time.monotonic(), 'text': ''}
                    connection.send(json.dumps({'id': task_id, 'target': target, 'type': 'ping', 'probe': probe}))
                    time.sleep(0.1)
                if not pending:
                    continue
                try:
                    raw = connection.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    print('mtrtools: connection closed before all probes completed')
                    break
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(message, dict):
                    continue
                task_id = message.get('id')
                if not isinstance(task_id, str) or task_id not in pending:
                    continue
                task = pending[task_id]
                if message.get('error'):
                    print(f"mtrtools node {task['probe']} failed: {message['error']}")
                    del pending[task_id]
                    continue
                if message.get('type') == 'data' and isinstance(message.get('data'), str):
                    task['text'] = (task['text'] + message['data'])[-65536:]
                    avg = self.average(task['text'])
                    if avg is not None:
                        output[task['probe']] = {**points[task['probe']], 'avg': avg}
                elif message.get('type') == 'end':
                    if task['probe'] not in output:
                        print(f"mtrtools node {task['probe']}: no ping summary received")
                    del pending[task_id]
        except (websocket.WebSocketException, OSError) as exc:
            print(f'mtrtools connection failed: {exc}')
        finally:
            connection.close()
        print(f'Done mtrtools in {self.diff()}s')
        return output
