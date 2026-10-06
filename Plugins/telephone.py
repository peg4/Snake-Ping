"""HTTP adapter for Telephone looking glasses and their Hybula successors."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
import requests

from Plugins.base import Base


class telephone(Base):
    catalog_root = 'https://raw.githubusercontent.com/Ne00n/Looking-Glass-2/master/data/'
    snapshot = Path(__file__).resolve().parent / 'data' / 'telephone.json'
    extra_catalog = Path(__file__).resolve().parent / 'data' / 'telephone-extra.json'
    country_aliases = {'south korea': 'KR', 'vietnam': 'VN', 'turkiye': 'TR',
                       'czech republic': 'CZ', 'bolivia': 'BO', 'laos': 'LA', 'deutschland': 'DE'}

    def location(self, value):
        city, separator, country = value.rpartition(',')
        country = (country if separator else value).strip()
        if country.lower().startswith('the '):
            country = country[4:]
        code = self.country_aliases.get(country.casefold()) or self.GetAlpha2(country)
        if not code:
            match = re.search(r'\(([A-Z]{2})\)$', country)
            code = self.GetAlpha2(match.group(1)) if match else False
        return code, re.sub(r'^\W+', '', city.strip() if separator else country)

    def hostname_country(self, endpoint, provider):
        hostname = urlsplit(endpoint).hostname
        prefix = hostname[:-len(provider)-1] if hostname.endswith('.' + provider) else ''
        tokens = re.split(r'[.-]', prefix.lower())
        aliases = {'uk': 'GB', 'frankfurt': 'DE', 'chicago': 'US', 'sgp': 'SG', 'helsinki': 'FI'}
        # Only location-shaped subdomain tokens, never the provider's TLD.
        safe = {'de','nl','lt','fi','gb','us','sg','ru','ca','fr','se','no','dk','es','it','au','jp','hk','ch','cz','pl','ro','bg'}
        countries = {aliases.get(token) or token.upper() for token in tokens if token in aliases or token in safe}
        return next(iter(countries)) if len(countries) == 1 else None

    def page_location(self, soup):
        # Hybula's first readonly field is the current location. Other location
        # links and the visitor's IP must not be treated as the probe location.
        field = soup.select_one('input[readonly][value]')
        if field:
            code, city = self.location(field['value'])
            if code:
                return code, city
        text = soup.get_text(' ', strip=True)
        match = re.search(r'Server Location:\s*(.*?)\s*(?:Other Location:|Test IPv4:)', text)
        if match:
            value = match.group(1).strip()
            code, city = self.location(value)
            if not code:
                code, city = self.location(value.rsplit(',', 1)[0].strip())
            if code:
                return code, city
        return None

    def __init__(self, config):
        super().__init__(config)
        self.load()
        self.locations = {}

    @staticmethod
    def endpoint(value):
        if not isinstance(value, str):
            return None
        url = urlsplit(value if '://' in value else 'https://' + value)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            return None
        return urlunsplit((url.scheme, url.netloc.lower(), url.path.rstrip('/') + '/', '', ''))

    def parse_directory(self, directory, geography):
        if not isinstance(directory, dict) or not isinstance(geography, dict):
            raise ValueError('telephone directory must contain JSON objects')
        points = {}
        for provider, endpoints in directory.items():
            if not isinstance(endpoints, dict):
                continue
            geo = geography.get(provider, {})
            if not isinstance(geo, dict):
                continue
            index = {urlsplit(normalized).netloc + urlsplit(normalized).path: data
                     for value, data in geo.items() if (normalized := self.endpoint(value)) and isinstance(data, dict)}
            for value, addresses in endpoints.items():
                endpoint = self.endpoint(value)
                if not endpoint or not isinstance(addresses, dict) or not isinstance(addresses.get('ipv4'), list):
                    continue
                parsed = urlsplit(endpoint)
                key = parsed.netloc + parsed.path
                metadata = index.get(key, {}).get('ipv4', {})
                if not isinstance(metadata, dict):
                    continue
                locations = []
                for address in addresses['ipv4']:
                    location = metadata.get(address)
                    if not self.validateIP(address) or not isinstance(location, str):
                        continue
                    code, city = self.location(location)
                    if code:
                        locations.append((code, city, address))
                # A multi-country front end needs a separate server selector;
                # do not mislabel its default probe as a selected country.
                if not locations or len({location[0] for location in locations}) != 1:
                    continue
                code, city, address = locations[0]
                hint = self.hostname_country(endpoint, provider)
                if hint and hint != code:
                    code, city = hint, self.getCountry(hint)
                identity = provider + '/' + key
                point = {'url': endpoint, 'provider': provider, 'city': city, 'country': code, 'ipv4': address}
                if identity not in points or parsed.scheme == 'https':
                    points[identity] = point
        locations = {}
        for key, point in points.items():
            locations.setdefault(point['country'], {})[key] = point
        return locations

    def fetch_json(self, filename):
        response = requests.get(self.catalog_root + filename, timeout=20)
        response.raise_for_status()
        return response.json()

    def prepare(self):
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                directory, geography = list(pool.map(self.fetch_json, ['lg.json', 'everything.json']))
            self.locations = self.parse_directory(directory, geography)
            if not self.locations:
                raise ValueError('telephone current directory contains no located IPv4 probes')
            self.add_extra_points()
            return True
        except (requests.RequestException, ValueError, TypeError) as exc:
            print(f'telephone directory unavailable: {exc}')
        try:
            with self.snapshot.open(encoding='utf-8') as handle:
                cached = json.load(handle)
            self.locations = cached['locations']
            if not isinstance(self.locations, dict) or not self.locations:
                raise ValueError('empty snapshot')
            print(f"telephone: using bundled directory dated {cached['date']}; nodes may have changed")
            self.add_extra_points()
            return True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'telephone has no usable directory: {exc}')
            self.locations = {}
            return False

    def add_extra_points(self):
        with self.extra_catalog.open(encoding='utf-8') as handle:
            extras = json.load(handle)
        for point in extras['points']:
            key = point['provider'] + '/' + urlsplit(point['url']).netloc + urlsplit(point['url']).path
            self.locations.setdefault(point['country'], {})[key] = point

    @staticmethod
    def average(html):
        text = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)
        match = re.search(r'(?:rtt|round-trip)\s+min/avg/max(?:/(?:mdev|stddev))?\s*=\s*[0-9.]+/([0-9.]+)/', text)
        if not match:
            return None
        try:
            avg = float(match.group(1))
        except ValueError:
            return None
        return avg if math.isfinite(avg) and avg >= 0 else None

    def run(self, data):
        key, point = data
        try:
            # Each node needs its own cookie/CSRF session.
            with requests.Session() as session:
                session.headers.update({'User-Agent': 'Snake-Ping/1.0', 'Referer': point['url']})
                page = session.get(point['url'], timeout=15)
                page.raise_for_status()
                soup = BeautifulSoup(page.text, 'html.parser')
                current = self.page_location(soup)
                if current:
                    code, city = current
                    if code != point.get('country', code):
                        print(f"telephone node {key}: page reports {code}, skipping requested {point['country']}")
                        return {}
                    point = {**point, 'city': city, 'country': code}
                form = soup.select_one('form:has(input[name="csrfToken"]):has(input[name="targetHost"])')
                if form:
                    endpoint = urljoin(page.url, form.get('action') or page.url)
                    if urlsplit(endpoint).netloc != urlsplit(page.url).netloc:
                        raise ValueError('cross-origin looking glass form')
                    method = form.select_one('select[name="backendMethod"] option[value="ping"]')
                    if not method:
                        raise ValueError('looking glass does not offer IPv4 ping')
                    payload = {item['name']: item.get('value', '') for item in form.select('input[type="hidden"][name]')}
                    payload.update(targetHost=self.target, backendMethod='ping', submitForm='')
                    if form.select_one('input[name="checkTerms"]'):
                        if self.config.get('telephoneAcceptTerms', False) is not True:
                            raise ValueError('site requires Terms of Use; review them before setting telephoneAcceptTerms=true')
                        payload['checkTerms'] = 'on'
                    submitted = session.post(endpoint, data=payload, timeout=20)
                    submitted.raise_for_status()
                    if re.fullmatch(r'\s*0\s*;?\s*', str(submitted.headers.get('Refresh', ''))):
                        submitted = session.get(endpoint, timeout=20)
                        submitted.raise_for_status()
                    old_backend = re.search(r'(?<!function )callBackend\s*\(\s*\)\s*;', submitted.text)
                    new_backend = re.search(r'fetch\(\s*[\'"]backend\.php[\'"]\s*\)', submitted.text)
                    if 'backend.php' not in submitted.text or not (old_backend or new_backend):
                        errors = BeautifulSoup(submitted.text, 'html.parser').select('.alert-danger')
                        message = '; '.join(error.get_text(' ', strip=True) for error in errors)
                        raise ValueError(message or 'looking glass did not start the ping backend')
                    response = session.get(urljoin(page.url, 'backend.php'), timeout=30)
                else:
                    # Follow the current page's base directory after redirects.
                    if soup.select_one('form#networktest input[name="host"]'):
                        response = session.get(urljoin(page.url, 'ajax.php'), params={'cmd': 'ping', 'host': self.target}, timeout=30)
                    else:
                        response = session.post(urljoin(page.url, 'ajax.php'), params={'cmd': 'ping', 'host': self.target}, timeout=30)
                response.raise_for_status()
                avg = self.average(response.text)
                if avg is None:
                    print(f'telephone node {key}: no ping summary; unsupported interface, rejected request, or packet loss')
                    return {}
                return {**point, 'avg': avg, 'source': self.__class__.__name__}
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            print(f'telephone node {key} failed: {exc}')
            return {}

    def engage(self, origin, target):
        print('Running telephone')
        self.start()
        points = self.locations.get(origin, {})
        if not points:
            print('telephone: no IPv4 probes found in target country')
            return {}
        self.target = target
        print(f'telephone: testing {len(points)} nodes')
        with ThreadPoolExecutor(max_workers=min(3, self.config.get('workers', 3))) as pool:
            results = list(pool.map(self.run, points.items()))
        output = {point['url']: point for point in results if 'avg' in point}
        print(f'Done telephone in {self.diff()}s')
        return output
