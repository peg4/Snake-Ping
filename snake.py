"""Collect remote ping results from independent provider plugins."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import math
from pathlib import Path
import re
import sys

from Plugins.base import Base

ROOT = Path(__file__).resolve().parent


def load_config(path):
    config = {"workers": 6, "executablePath": "", "timeout": 30000}
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            supplied = json.load(handle)
        if not isinstance(supplied, dict):
            raise ValueError("config must be a JSON object")
        config.update(supplied)
    if type(config['workers']) is not int or not 1 <= config['workers'] <= 32:
        raise ValueError("workers must be an integer between 1 and 32")
    if type(config['timeout']) is not int or config['timeout'] <= 0:
        raise ValueError("timeout must be a positive integer in milliseconds")
    return config


def normalize_country(value):
    base = Base()
    base.load()
    country = base.GetAlpha2(value.strip())
    if not country:
        raise ValueError(f"Unknown country: {value}")
    return country


def validate_target(value):
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    hostname = value.rstrip('.').encode('idna').decode('ascii')
    if len(hostname) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in hostname.split('.')):
        raise ValueError("target must be an IP address or hostname")
    return hostname


def collect(base, jobs):
    with ThreadPoolExecutor(max_workers=base.config['workers']) as pool:
        return list(pool.map(base.run, jobs))


def valid_results(results):
    for result in results:
        if not isinstance(result, dict):
            continue
        for probe, details in result.items():
            try:
                avg = float(details['avg'])
                if avg < 0 or not math.isfinite(avg):
                    continue
                yield probe, {**details, 'avg': avg}
            except (KeyError, TypeError, ValueError):
                continue


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin', nargs='?', help='country code/name, any, or UK,NL for compare')
    parser.add_argument('target', nargs='?', help='IP address, hostname, or compare')
    parser.add_argument('plugin', nargs='?', help='use only this plugin')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--list-plugins', action='store_true')
    parser.add_argument('--region', action='append', help='mtrtools region name; repeat to select several regions')
    parser.add_argument('--list-regions', action='store_true', help='list current mtrtools regions')
    args = parser.parse_args(argv)
    plugins = sorted(p.stem for p in (ROOT / 'Plugins').glob('*.py') if p.stem not in ('base', '__init__'))
    if args.list_plugins:
        print('\n'.join(plugins))
        return 0
    if args.list_regions:
        from Plugins.mtrtools import mtrtools
        try:
            provider = mtrtools(load_config(args.config))
            provider.prepare()
            print('\n'.join(provider.region_names()))
            return 0
        except (OSError, ValueError, RuntimeError) as exc:
            print(f'Cannot list mtrtools regions: {exc}', file=sys.stderr)
            return 1
    if args.origin is None or args.target is None:
        parser.error('origin and target are required, e.g. NL 1.1.1.1')
    try:
        config = load_config(args.config)
        if args.region:
            if args.plugin not in (None, 'mtrtools') or args.target == 'compare':
                raise ValueError('--region is supported only for mtrtools ping measurements')
            args.plugin = 'mtrtools'
        if args.target == 'compare':
            countries = args.origin.split(',')
            if len(countries) != 2:
                raise ValueError('compare requires two countries, e.g. UK,NL compare')
            origin, destination = map(normalize_country, countries)
            origin = f'{origin},{destination}'
        else:
            origin = 'any' if args.origin.lower() == 'any' else normalize_country(args.origin)
            args.target = validate_target(args.target)
        if args.plugin:
            if args.plugin not in plugins:
                raise ValueError(f'Unknown plugin: {args.plugin}; use --list-plugins')
            plugins = [args.plugin]
    except (OSError, ValueError, UnicodeError) as exc:
        parser.error(str(exc))
    print('Snake-Ping')
    base = Base(config)
    jobs = [{'plugin': plugin, 'origin': origin, 'target': args.target} for plugin in plugins]
    if args.region:
        for job in jobs:
            job['regions'] = args.region
    results = collect(base, jobs)
    rows = []
    if args.target == 'compare':
        for probe, details in valid_results(results):
            address = details.get('ipv4')
            if not base.validateIP(address):
                continue
            target_jobs = [{**job, 'origin': destination, 'target': address} for job in jobs]
            for _, remote in valid_results(collect(base, target_jobs)):
                rows.append((remote['avg'], remote.get('source', '?'), f"{remote.get('city', '?')} {remote.get('provider', '?')}", f"{details.get('city', '?')} {details.get('provider', '?')}"))
        header = 'Latency\tSource\tOrigin\tDestination'
    else:
        for _, details in valid_results(results):
            rows.append((details['avg'], details.get('source', '?'), details.get('city', '?'), details.get('provider', '?')))
        header = 'Latency\tSource\tCity\tProvider'
    output = [header, '-------\t-------\t-------\t-------']
    output.extend(f'{avg:.2f}ms\t{source}\t{city}\t{provider}' for avg, source, city, provider in sorted(rows, key=lambda row: row[0]))
    print('\nResults')
    print(base.formatTable(output))
    if not rows:
        print('No measurements received. Check provider diagnostics above.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
