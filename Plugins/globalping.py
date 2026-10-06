"""Globalping public HTTP API adapter; no browser or CLI installation."""
import math
import os
import re
import time

import requests

from Plugins.base import Base


class globalping(Base):
    api = 'https://api.globalping.io/v1/measurements'

    def canRunAny(self):
        return True

    def prepare(self):
        self.limit = self.config.get('globalpingLimit', 10)
        self.token = os.environ.get('GLOBALPING_TOKEN') or self.config.get('globalpingToken', '')
        if not isinstance(self.token, str) or '\r' in self.token or '\n' in self.token:
            raise ValueError('globalping token must be a single-line string')
        maximum = 500 if self.token else 50
        if type(self.limit) is not int or not 1 <= self.limit <= maximum:
            raise ValueError(f'globalpingLimit must be an integer between 1 and {maximum}')
        return True

    @staticmethod
    def check_response(response):
        if response.status_code < 400:
            response.raise_for_status()
            return
        if response.status_code == 429:
            details = []
            for name in ('X-RateLimit-Remaining', 'X-RateLimit-Reset', 'Retry-After'):
                value = response.headers.get(name)
                if isinstance(value, str) and value.isdigit():
                    details.append(f'{name}={value}')
            suffix = '; ' + ', '.join(details) if details else ''
            raise RuntimeError('Globalping rate limit reached (HTTP 429)' + suffix)
        try:
            data = response.json()
            error = data.get('error', {}) if isinstance(data, dict) else {}
            message = error.get('message') if isinstance(error, dict) else None
        except ValueError:
            message = None
        raise RuntimeError(f'Globalping HTTP {response.status_code}' + (f': {message[:300]}' if isinstance(message, str) else ''))

    @staticmethod
    def parse_results(data, origin):
        output = {}
        items = data.get('results', [])
        if not isinstance(items, list):
            raise ValueError('Globalping results must be an array')
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            probe, result = item.get('probe'), item.get('result')
            if not isinstance(probe, dict) or not isinstance(result, dict) or result.get('status') != 'finished':
                continue
            if origin != 'any' and probe.get('country') != origin:
                continue
            stats = result.get('stats')
            if not isinstance(stats, dict):
                continue
            try:
                if type(stats.get('rcv')) is not int or stats['rcv'] <= 0 or isinstance(stats.get('avg'), bool):
                    continue
                avg = float(stats['avg'])
                if not math.isfinite(avg) or avg < 0:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            # Result indexes keep distinct probes with identical city/network.
            # resolvedAddress is the target, not the probe's source address.
            output[f"{data.get('id', 'measurement')}:{index}"] = {
                'avg': avg, 'source': 'globalping', 'city': probe.get('city') or 'n/a',
                'provider': probe.get('network') or 'n/a', 'country': probe.get('country'),
                'asn': probe.get('asn')}
        return output

    def engage(self, origin, target):
        print('Running globalping')
        self.start()
        payload = {'type': 'ping', 'target': target, 'limit': self.limit,
                   'timeout': 30, 'inProgressUpdates': False,
                   'measurementOptions': {'packets': 4}}
        if origin != 'any':
            payload['locations'] = [{'country': origin}]
        output = {}
        with requests.Session() as session:
            session.headers.update({'Accept': 'application/json', 'User-Agent': 'Snake-Ping/1.0'})
            if self.token:
                session.headers['Authorization'] = 'Bearer ' + self.token
            # Do not retry POST: retrying could create another charged measurement.
            response = session.post(self.api, json=payload, timeout=20)
            self.check_response(response)
            created = response.json()
            identifier = created.get('id') if isinstance(created, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier):
                raise RuntimeError('Globalping returned no valid measurement ID')
            print(f"globalping: requested up to {self.limit} probes; measurement {identifier}")
            # 30 seconds probe timeout + at least 10 seconds API finalization.
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    response = session.get(self.api + '/' + identifier,
                                           timeout=min(15, max(1, deadline - time.monotonic())))
                    self.check_response(response)
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(data.get('status'), str):
                        raise ValueError('Globalping returned an invalid measurement status')
                    output.update(self.parse_results(data, origin))
                    if data['status'] != 'in-progress':
                        break
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    print(f'globalping polling failed: {exc}')
                    break
                # API guidelines require 500 ms AFTER each response, not an interval.
                time.sleep(0.5)
            else:
                print('globalping: client deadline reached; returning completed results')
        if not output:
            print('globalping: no successful ping measurements received')
        print(f'Done globalping in {self.diff()}s')
        return output
