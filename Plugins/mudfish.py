"""Mudfish adapter using the same HTTP endpoints as the site's ping form."""
from concurrent.futures import ThreadPoolExecutor
import math
import re
import socket
from urllib.parse import quote

from bs4 import BeautifulSoup
import requests

from Plugins.base import Base


class mudfish(Base):
    url = 'https://ping.mudfish.net'
    batch_size = 29

    def __init__(self, config):
        super().__init__(config)
        self.load()

    def prepare(self):
        return True

    def isComparable(self):
        return True

    def discover(self, html, country):
        soup = BeautifulSoup(html, 'html.parser')
        nodes = []
        locations = set()
        for node in soup.select('input[id^="checkbox_node_"]'):
            label = node.find_parent('label')
            location = node.get('location') or (label.get_text(' ', strip=True) if label else '')
            node_country = node.get('data-country') or location[:2]
            if node_country != country or node.has_attr('disabled'):
                continue
            match = re.search(r'\((.*?)\s-\s(.*?)\)', location)
            if not match:
                continue
            # Keep one representative per city/provider, as in the original plugin.
            city, provider = match.groups()
            if (city, provider) in locations:
                continue
            sid = node.get('value') or node['id'][len('checkbox_node_'):]
            if not sid.isdigit():
                continue
            locations.add((city, provider))
            nodes.append(sid)
        return nodes

    def measure(self, row, target):
        sid, ip, location = row
        if not sid.isdigit() or not self.validateIP(ip):
            return {}
        match = re.search(r'\((.*?)\s-\s(.*?)\)', location)
        if not match:
            return {}
        try:
            response = requests.get(f'{self.url}/ping/{sid}/{quote(ip, safe="")}/{quote(target, safe="")}', timeout=20)
            response.raise_for_status()
            avg = float(response.json()['rtt_avg'])
            if avg < 0 or not math.isfinite(avg):
                return {}
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            print(f'mudfish node {sid} failed: {exc}')
            return {}
        city, provider = match.groups()
        return {sid: {'provider': provider, 'city': city, 'ipv4': ip, 'avg': avg, 'source': self.__class__.__name__}}

    def engage(self, origin, target):
        print('Running mudfish')
        self.start()
        if not self.validateIP(target):
            target = socket.gethostbyname(target)
        results = {}
        with requests.Session() as session:
            response = session.get(self.url + '/', timeout=15)
            response.raise_for_status()
            nodes = self.discover(response.text, origin)
            if not nodes:
                print('Warning mudfish, No Probes found in Target Country')
                return {}
            for offset in range(0, len(nodes), self.batch_size):
                try:
                    response = session.post(f'{self.url}/ping/start/{quote(target, safe="")}', data={'nodes': ','.join(nodes[offset:offset + self.batch_size])}, timeout=20)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')
                    rows = [(row.get('data-sid', ''), row.get('data-ip', ''), row.select_one('td').get_text(' ', strip=True)) for row in soup.select('#ping_result_table tbody tr[data-sid][data-ip]') if row.select_one('td')]
                    if not rows:
                        print('mudfish returned no result rows; the service may have changed.')
                        continue
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        for measurement in pool.map(lambda row: self.measure(row, target), rows):
                            results.update(measurement)
                except requests.RequestException as exc:
                    print(f'mudfish batch failed: {exc}')
        print(f'Done mudfish in {self.diff()}s')
        return results
