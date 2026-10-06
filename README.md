# Snake-Ping

Measure latency to an IP address or hostname from remote looking-glass nodes.
Results are sorted by average latency. Country comparison ranks measured routes
between remote nodes in two countries.

## Install

Use Python 3.8 or newer (tested with Python 3.12). A virtual environment is recommended:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

All enabled plugins work without Chrome or Chromium. Mudfish, lookingHouse, lookingCenter,
telephone, vultr, and pingpe use HTTP. DNS Tools uses SignalR JSON over HTTP
long polling. mtrtools uses a WebSocket connection.

On Windows activate the environment with `.venv\Scripts\activate`. The
configuration file is optional; copy `config.example.json` to `config.json`
to adjust `workers`. Old `executablePath` settings can be left in place; enabled
plugins do not use them.

The disabled legacy mtrsh adapter still requires a browser and the
optional `requirements-browser.txt`. It is not selected by normal runs.

## Run

A quick start:

```sh
python snake.py NL 1.1.1.1 mudfish
```

Run all compatible plugins, list available plugins, or select one:

```sh
python snake.py NL 1.1.1.1
python snake.py --list-plugins
python snake.py NL example.com mudfish
python snake.py NL 1.1.1.1 lookingHouse
python snake.py NL 1.1.1.1 dnstools
python snake.py NL 1.1.1.1 pingpe
python snake.py NL 1.1.1.1 telephone
python snake.py NL 1.1.1.1 lookingCenter
python snake.py NL 1.1.1.1 mtrtools
```

Country codes and names are case insensitive. `UK` is accepted as an alias for
`GB`, and `UAE` for `AE`.

Select MTR.Tools regions using their current names or aliases. `--region`
automatically selects mtrtools; a country filters nodes within those regions,
and `any` selects all online ping nodes in the selected regions. Repeat the
option to select several regions. Without this option, mtrtools searches all
regions for the requested country.

```sh
python snake.py --list-regions
python snake.py any 1.1.1.1 mtrtools --region Europe
python snake.py NL 1.1.1.1 mtrtools --region EU
python snake.py any 1.1.1.1 --region Europe --region "North America"
```

Current region aliases: `EU` (Europe), `NA` (North America), `SA` (South America),
`AS` (Asia), `AF` (Africa), `OC` (Oceania), and `ME` (Middle East). Region aliases
are used only with `--region`, so country code `NA` still means Namibia.

```sh
python snake.py any 1.1.1.1
python snake.py UK,NL compare mudfish
```

`any` runs only plugins that explicitly support worldwide probing; it is disabled
for Mudfish and some other providers to limit the number of requests. Comparison
uses only compatible plugins (Mudfish, lookingHouse, and lookingCenter). A comparison result
reports the measured direction: **Origin** is the country after the comma, and
**Destination** is the country before it. `UK,NL compare` measures NL → UK.

The script can be invoked by its full path from another directory. Resources and
default configuration are located relative to the script. Use `--config PATH`
to select another configuration file.

## Service failures

These are external public services: availability, nodes, rate limits, and page
formats can change. One failed plugin is reported and does not discard results
from the others. Exit status is `0` when measurements were collected, `1` if none
were received, or `2` for invalid arguments/configuration. Failed and nonnumeric
measurements are excluded from sorting.

HTTP requests, polling loops, and WebSocket reads have bounded timeouts.
Connections are closed after use. ping.pe's ping and MTR tasks are stopped
after samples have been collected. Negative values/timeouts are not counted as
latency measurements; duplicate ping.pe timestamps are not counted twice.
MTR.Tools selects online nodes with ping capability and runs at most four tests
at a time. Each test has a 45-second deadline; a failed node does not discard
completed measurements.

A service may reject connections or request interactive verification. Such
errors are reported explicitly; removing the browser dependency does not remove
service or network restrictions. MTR.Tools requires outbound secure WebSockets to
`api.mtr.tools`. DNS Tools requires HTTPS access to
`api.dnstools.ws`. Browserless adapters do not solve CAPTCHAs.

## Telephone looking glasses

`telephone` uses the current Looking-Glass-2 `data/lg.json` probe directory
and `data/everything.json` location metadata. The old root-level `lg.json` URL
returns 404 and is no longer used. HTTP/HTTPS and trailing-slash duplicates
are merged, preferring HTTPS. A front end with probes in several countries is
excluded when the adapter cannot choose the corresponding server reliably.
IP geolocation can describe the provider's registered network rather than the
actual probe. Explicit location tokens in subdomains take precedence over it;
the current location on a Hybula or BaCloud page is checked before running ping.
An explicit page country that differs from the requested country skips the node.
Two additional Finland nodes are maintained in `Plugins/data/telephone-extra.json`
and are merged into both downloaded and bundled catalogs.

If downloading or parsing the directory fails, a bundled snapshot is used
with an explicit date in the diagnostic output. The snapshot is a directory,
not saved ping results; every reported latency is measured again. Public nodes
can disappear or change software. A failed node is reported independently.

The adapter supports Telephone's POST `ajax.php` interface, BaCloud's GET
`ajax.php` interface, and Hybula's CSRF form/session plus `backend.php` interface
without Chrome. New Hybula versions return an empty POST body with `Refresh: 0`;
the adapter reloads the form in the same session and recognizes both legacy
`callBackend()` and current `fetch('backend.php')` startup scripts. FreeBSD ping
summaries with just min/avg/max are supported. Other interfaces are skipped
when they return no valid ping summary.

Sites displaying a Terms of Use checkbox are skipped by default. If you have
reviewed and accepted those sites' terms, add `"telephoneAcceptTerms": true` to
`config.json` to submit the checkbox. TLS validation remains enabled: expired
certificates and unavailable sites are reported as node failures.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests do not contact external services. They cover the CLI, country validation,
plugin failure isolation, sorting, country comparison, browser cleanup, Mudfish's
current markup/JSON, batching more than 29 nodes, and correct per-probe addresses
in lookingHouse, including its current country links, cards, network action,
and pagination. Additional tests cover DNS Tools framing/worker metadata,
mtrtools region/country filtering, streamed summaries, queue continuation after
node failures, lookingCenter's domain and actions, ping.pe units/deduplication,
rejected requests, and connection/task cleanup.

This version is based on upstream commit
`4a3abdddc01ce4bd1067fe26632865b2b6bd7363`.
