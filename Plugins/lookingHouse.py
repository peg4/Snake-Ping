"""Adapter for LOOKING.HOUSE's current country pages and network action."""
from concurrent.futures import ThreadPoolExecutor
import math
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import requests

from Plugins.base import Base


class lookingHouse(Base):
    url = 'https://looking.house'

    def __init__(self, config):
        super().__init__(config)
        self.load()
        self.mapping = {}
        self.country_ids = {}

    def get_html(self, path):
        url = urlsplit(path)
        start = parse_qs(url.query).get('start', [None])[0]
        if start is not None:
            country_id = self.country_ids.get(url.path)
            if not country_id or not start.isdigit():
                raise ValueError(f'Invalid {self.__class__.__name__} pagination request')
            response = requests.post(self.url + '/action/looking-glass/search',
                data={'country': country_id, 'city': 0, 'ipv6': 2, 'start': int(start)}, timeout=30)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get('Error') not in (0, '0'):
                raise RuntimeError(f'{self.__class__.__name__} country search failed')
            templates = data.get('Templates')
            template = templates.get('looking_glass') if isinstance(templates, dict) else None
            if not isinstance(template, str):
                raise RuntimeError(f'{self.__class__.__name__} search returned no cards')
            return '<div id="LookingGlassServers">' + template + '</div>'
        response = requests.get(self.url + path, timeout=30)
        response.raise_for_status()
        return response.text

    def prepare(self):
        soup = BeautifulSoup(self.get_html('/looking-glass'), 'html.parser')
        self.mapping = {}
        self.country_ids = {}
        for link in soup.select('a[href^="/looking-glass/countries/"]'):
            path = urlsplit(link['href']).path
            if not re.fullmatch(r'/looking-glass/countries/[a-z0-9-]+', path):
                continue
            icon = link.select_one('[class*="country-"]')
            if not icon:
                continue
            code = next((name[8:].upper() for name in icon.get('class', []) if re.fullmatch(r'country-[a-z]{2}', name)), None)
            if code:
                self.mapping[code] = path
                target = link.get('data-bs-target', '')
                match = re.fullmatch(r'#LookingGlassNav-([0-9]+)', target)
                if match:
                    self.country_ids[path] = match.group(1)
        if not self.mapping:
            raise RuntimeError(f'{self.__class__.__name__} returned no country links; the site may have changed.')
        return True

    def isComparable(self):
        return True

    def parse_points(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        points = {}
        for card in soup.select('#LookingGlassServers > .card'):
            address = card.select_one('input[id^="IPv4Input-"]')
            if not address or not self.validateIP(address.get('value')):
                continue
            link = card.select_one('a[href*="/looking-glass/"]')
            if not link:
                continue
            match = re.fullmatch(r'/companies/([a-z0-9-]+)/looking-glass/([a-z0-9-]+)', urlsplit(link['href']).path)
            if not match:
                continue
            company, item = match.groups()
            if not any(re.search(r"(?:StartNetworkTest|ShowNetworkOffcanvas)\([^)]*['\"]ping4['\"]", button.get('onclick', '')) and not button.has_attr('disabled') for button in card.select('button')):
                continue
            location = link.get_text(' ', strip=True)
            city = location.rsplit(',', 1)[0].strip() if ',' in location else location
            points[f'{company}/{item}'] = {'company': company, 'item': item, 'provider': company, 'city': city or 'n/a', 'location': location, 'ipv4': address['value']}
        return points

    def pagination(self, html, country_path):
        soup = BeautifulSoup(html, 'html.parser')
        paths = set()
        for link in soup.select('.pagination a[href]'):
            url = urlsplit(link['href'])
            start = parse_qs(url.query).get('start', [''])[0]
            if not url.scheme and not url.netloc and url.path == country_path and start.isdigit():
                if int(start) > 0:
                    paths.add(f'{country_path}?start={int(start)}')
        return sorted(paths, key=lambda path: int(path.rsplit('=', 1)[1]))

    def run(self, point):
        key, details = point
        try:
            response = requests.post(self.url + '/action/looking-glass/network',
                data={'url': details['company'], 'item': details['item'], 'network': 'ping4', 'input': self.target},
                headers={'Origin': self.url, 'Referer': self.url + f"/companies/{details['company']}/looking-glass/{details['item']}", 'X-Requested-With': 'XMLHttpRequest'}, timeout=35)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get('Error') not in (0, '0'):
                message = data.get('Error', 'invalid response') if isinstance(data, dict) else 'invalid response'
                print(f'{self.__class__.__name__} node {key} failed: {message}')
                return {}
            template = data.get('Template')
            if not isinstance(template, str):
                return {}
            soup = BeautifulSoup(template, 'html.parser')
            text = '\n'.join(pre.get_text() for pre in soup.select('pre'))
            match = re.search(r'(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*[0-9.]+/([0-9.]+)/', text)
            if not match:
                print(f'{self.__class__.__name__} node {key}: no ping summary received')
                return {}
            avg = float(match.group(1))
            if not math.isfinite(avg) or avg < 0:
                return {}
            return {**details, 'avg': avg}
        except (requests.RequestException, ValueError, TypeError) as exc:
            print(f'{self.__class__.__name__} node {key} failed: {exc}')
            return {}

    def engage(self, origin, target):
        print(f'Running {self.__class__.__name__}')
        self.start()
        code = self.GetAlpha2(origin)
        country_path = self.mapping.get(code)
        if not country_path:
            print(f'Warning {self.__class__.__name__}, No Probes found in Target Country')
            return {}
        points = {}
        pending, visited = [country_path], set()
        while pending:
            path = pending.pop(0)
            if path in visited:
                continue
            visited.add(path)
            try:
                html = self.get_html(path)
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                print(f'{self.__class__.__name__} page {path} failed: {exc}')
                continue
            points.update(self.parse_points(html))
            pending.extend(path for path in self.pagination(html, country_path) if path not in visited and path not in pending)
        if not points:
            print(f'{self.__class__.__name__}: no IPv4 ping nodes found in country pages.')
            return {}
        print(f'{self.__class__.__name__}: testing {len(points)} nodes')
        self.target = target
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.run, points.items()))
        output = {f"{details['company']}/{details['item']}": {**details, 'source': self.__class__.__name__} for details in results if 'avg' in details}
        print(f'Done {self.__class__.__name__} in {self.diff()}s')
        return output
