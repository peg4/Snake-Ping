# Verification

Date: 2026-10-06. Python: 3.12.

- `python -m unittest discover -s tests -v`: 64 tests passed.
- `git diff --check`: passed.
- Live command: `python snake.py NL 1.1.1.1 mudfish` exited with status 0
  and returned 11 measurements from Netherlands nodes in 38.48 seconds.

Observed averages (a single sample; they will change between runs):

| City | Provider | Average |
| --- | --- | --- |
| Amsterdam | DigitalOcean | 0.57 ms |
| Amsterdam | HostHatch | 0.96 ms |
| Amsterdam | Vultr 1 | 1.10 ms |
| Amsterdam | Vultr 3 | 1.30 ms |
| Amsterdam | G-Core Labs | 1.38 ms |
| Amsterdam | Vultr 2 | 1.40 ms |
| Amsterdam | Azure | 2.66 ms |
| Amsterdam | VPS2day | 2.78 ms |
| Amsterdam | RamNode | 3.24 ms |
| Amsterdam | Starry | 4.77 ms |
| Amsterdam | Google | 42.50 ms |

Country comparison was verified with mocked provider responses; a full live
comparison was not run. Chromium was absent and the attempted browser download
failed, so browser-dependent providers were not verified end to end. Several other provider homepages timed out during the first verification;
this does not establish whether those services are unavailable elsewhere.
LOOKING.HOUSE was investigated separately and updated for its current interface.

The original GitHub repository was not modified because the connected account
has read permission only. The archive contains all source files, dependencies,
instructions, and tests; install it as described in README.md.

## LOOKING.HOUSE update

The original plugin failed because it depended on Chromium and the old PHP
country/table/action interfaces. The current adapter uses HTTP country links,
server cards, and the `/action/looking-glass/network` form with `ping4`.
Pagination uses the site's `/action/looking-glass/search` POST action: GET URLs
with `?start=` repeat the first page. Country search reports success as the JSON
string `"0"`; the adapter accepts both string and numeric zero.

An initial live run against 1.1.1.1 returned measurements from all 20 nodes
on the first Netherlands page. The complete country listing contains 41 nodes.

Complete live command: `python snake.py NL 1.1.1.1 lookingHouse` exited with
status 0 and returned 40 measurements from the 41 discovered Netherlands nodes.
Done lookingHouse in 190.76s

```text
Snake-Ping
Running lookingHouse
lookingHouse: testing 41 nodes
lookingHouse node hostmayo-com/169-239-130-2 failed: Error when connecting to server
Done lookingHouse in 190.76s

Results
Latency Source       City          Provider
------- -------      -------       -------
0.90ms  lookingHouse Amsterdam     shockhosting-com
0.93ms  lookingHouse Doetinchem    profitserver-net
1.04ms  lookingHouse Amsterdam     incognet-io
1.07ms  lookingHouse Oude Meer     3v-host-com
1.09ms  lookingHouse Schiphol-Rijk ua-hosting-company
1.14ms  lookingHouse Oude Meer     zomro-com
1.15ms  lookingHouse Amsterdam     veesp-com
1.16ms  lookingHouse Amsterdam     hosthatch-com
1.17ms  lookingHouse Amsterdam     hostnamaste-com
1.24ms  lookingHouse Dronten       liteserver-nl
1.25ms  lookingHouse Amsterdam     black-host
1.34ms  lookingHouse Amsterdam     psychz-net
1.37ms  lookingHouse Amsterdam     chicagoservers-org
1.41ms  lookingHouse Schiphol-Rijk ouiheberg-com
1.42ms  lookingHouse Schiphol-Rijk hosteroid-uk
1.47ms  lookingHouse Roosendaal    hostsailor-com
1.55ms  lookingHouse Meppel        profitserver-net
1.74ms  lookingHouse Dronten       vps-one
1.77ms  lookingHouse Amsterdam     nktele-com
1.78ms  lookingHouse Dronten       itldc-com
2.03ms  lookingHouse Oude Meer     xserver-cloud
2.08ms  lookingHouse Amsterdam     cloudblast-io
2.22ms  lookingHouse Delft         zomro-com
2.31ms  lookingHouse Dronten       foxcloud-net
2.45ms  lookingHouse Naaldwijk     virterion-com
2.47ms  lookingHouse Hague         servinga-com
2.50ms  lookingHouse Amsterdam     altushost-com
2.66ms  lookingHouse Lelystad      freerangecloud-com
2.79ms  lookingHouse Doetinchem    virtua-cloud
3.06ms  lookingHouse Dronten       hyperhost-ua
3.12ms  lookingHouse Meppel        hostlife-net
3.22ms  lookingHouse Meppel        spacecore-pro
3.37ms  lookingHouse Amsterdam     flokinet-is
3.88ms  lookingHouse Eygelshoven   mlnl-host
3.89ms  lookingHouse Amsterdam     bluevps-com
4.25ms  lookingHouse Haarlem       kuroit-com
5.88ms  lookingHouse Eygelshoven   hostealo-com
7.11ms  lookingHouse Amsterdam     gozenhost-com
7.98ms  lookingHouse Amsterdam     hostzealot-com
19.87ms lookingHouse Amsterdam     profitserver-net
```

## Browserless dnstools and pingpe

The adapters were rewritten to use the site's current network protocols:

- DNS Tools: current worker directory in its public application bundle, followed
  by SignalR JSON streaming over negotiated HTTP long polling. JavaScript is
  parsed as a literal configuration string, not executed.
- ping.pe: public page/session setup, page-provided task token, task start,
  polling, microsecond-to-millisecond conversion, timestamp deduplication,
  and stopping both ping and MTR streams. No CAPTCHA solving is implemented.

The default requirements no longer include pyppeteer. All enabled plugins can
run without a Chrome/Chromium executable. The disabled legacy mtrsh adapter
retains its optional browser requirement.

Live DNS Tools CLI: `python snake.py NL 1.1.1.1 dnstools` exited with status 0,
returning Amsterdam/WebHorizon at 4.10 ms. An earlier attempt received a proxy
403; the ordinary retry succeeded without changes to proxy settings.

Live ping.pe CLI: `python snake.py NL 1.1.1.1 pingpe` exited with status 0 and
returned 9 Netherlands measurements.

```text
Snake-Ping
Running dnstools.ws

Results
Latency Source   City      Provider
------- -------  -------   -------
4.10ms  dnstools Amsterdam WebHorizon
```

```text
Snake-Ping
Running ping.pe

Results
Latency Source  City        Provider
------- ------- -------     -------
0.44ms  pingpe  Amsterdam   ZetNet
0.90ms  pingpe  Amsterdam   Nexonhost
1.26ms  pingpe  Amsterdam   Hybula
1.42ms  pingpe  Amsterdam   Online.net
2.96ms  pingpe  Amsterdam   Interhost
2.98ms  pingpe  Steenbergen NFOrce
3.97ms  pingpe  Eygelshoven Evolushost
5.31ms  pingpe  Eygelshoven PipeHost
14.58ms pingpe  Eindhoven   YottaSrc
```

## MTR.Tools and LOOKING.CENTER update

Removed the pingsx adapter and its protocol tests. Replaced the disabled browser
mtrtools adapter with a browserless implementation using the current public
`https://api.mtr.tools/probes.json` directory and `wss://api.mtr.tools/ws` stream.
Region selection comes from the directory; `--list-regions` lists current names.
`--region` can be repeated and intersects with the selected country. Offline
probes and probes without ping capability are excluded. Tests are queued with
at most four concurrent tasks and a 45-second deadline per task.

Live CLI: `python snake.py NL 1.1.1.1 mtrtools --region Europe` exited with status
0 and returned all 13 selected Netherlands probes in 21.56 seconds. Observed
averages ranged from 0.95 ms (ParadoxNetworks, Amsterdam) to 4.02 ms
(Atomic Networks, Eygelshoven).

LOOKING.CENTER reuses the HTTP country/card/search/network adapter with its own
base URL, diagnostic name, and result source. It supports country selection and
comparison; its requests never use looking.house.

Live CLI: `python snake.py NL 1.1.1.1 lookingCenter` exited with status 0 and
returned 21 measurements from 22 discovered Netherlands nodes in 87.47 seconds.
The mgnhost-ru/193-0-178-164 node reported a server connection error. Observed
averages ranged from 0.73 ms (profitserver-ru, Doetinchem) to 57.48 ms
(senko-digital, Amsterdam). The country has more than 20 nodes, so this run also
verified the second page through LOOKING.CENTER's country search action.

Live `--list-regions` returned Europe, North America, Asia, South America,
Africa, Oceania, and Middle East. No Chrome/Chromium executable was used.

Live region-only CLI: `python snake.py any 1.1.1.1 mtrtools --region ME`
exited with status 0 and returned all 5 Middle East probes in 20.73 seconds:
Dubai/ServerWala (0.47 ms), Istanbul/Datapacket (2.18 ms),
Istanbul/Talido A.S (2.48 ms), Tel Aviv/OneProvider (2.49 ms), and
Fujairah/Melbicom (2.71 ms). This verifies selection across several countries
within a single region.

## Telephone directory and HTTP interfaces

The old `https://raw.githubusercontent.com/Ne00n/Looking-Glass-2/master/lg.json`
returns HTTP 404. The current catalog is at `data/lg.json`, grouped by provider
and endpoint rather than `telephone` and country. It is joined with
`data/everything.json` for location metadata. HTTP/HTTPS/trailing-slash variants
are deduplicated. Multi-country front ends are excluded when the matching
server cannot be selected reliably. A dated snapshot of 266 endpoints in 34
countries is bundled for directory download/parsing failures; latencies are
always measured live.

Telephone's legacy `ajax.php` and Hybula's CSRF/session/form/`backend.php`
interfaces are supported. Each node has its own session, targets are passed
as encoded parameters, and failures are isolated and reported explicitly.
Chrome is not used.

Live CLI: `python snake.py NL 1.1.1.1 telephone` exited with status 0 and
returned 7 measurements from 24 discovered Netherlands endpoints in 130.21
seconds. The other 17 endpoints returned connection errors, HTTP 403/404/502,
failed backend startup, or no supported ping summary. This confirms directory
preparation and live measurements; it does not imply all catalog entries
remain available or run a supported interface.

| City | Provider | Average |
| --- | --- | --- |
| Almere Stad | alexhost.com | 0.89 ms |
| Amsterdam | psychz.net | 1.21 ms |
| Haarlem | ultravps.eu | 1.45 ms |
| Dronten | liteserver.nl | 1.72 ms |
| Meppel | isplevel.com | 2.00 ms |
| Netherlands | hostio.solutions | 2.16 ms |
| Eygelshoven | atomicnetworks.co | 4.33 ms |

New offline tests cover the current directory paths and schema, location joins,
deduplication, ambiguous countries, bundled fallback, subdirectory AJAX calls,
CSRF session setup, rejected forms, and node failure isolation. All 47 tests
pass, and `git diff --check` passes.

## Telephone follow-up: Hybula refresh, BaCloud, and countries

The previous adapter mistook Hybula's empty POST response with `Refresh: 0` for
a failed ping startup. Current Hybula source (`index.php` and `bootstrap.php`)
confirms that the response asks the browser to reload the page. The adapter
now follows that zero-delay refresh in the same cookie session and recognizes
both `callBackend()` and the newer `fetch('backend.php')` script. Rejected forms
are reported using the error displayed on the refreshed page.

BaCloud's current public JavaScript uses GET, not POST, for `ajax.php`. Its
FreeBSD ping prints `round-trip min/avg/max`, without mdev/stddev. Both differences
are now supported. BaCloud's explicit page location was checked: the UK endpoint
reports United Kingdom, and the LT endpoint reports Lithuania.

The raw IP geolocation catalog sometimes assigns the provider's registered
country to a probe in a different country. Location-shaped subdomain tokens
now override that metadata (without treating the provider's TLD as a location).
Page location, when provided by Hybula or BaCloud, is checked before sending the
ping: an explicit conflicting country skips the node. This moves BaCloud UK
and Chicago to GB and US and the Chicago ServerHub and SGP Vebble endpoints
out of DE. Unknown page location remains dependent on the catalog's accuracy.

Added two Finland nodes whose provider pages were inspected directly:
`https://fi-lg.mynymbox.io/` and `https://ping-fi.4vps.su/lg/`. They are merged
into downloaded and fallback catalogs. No browser or disabled TLS validation
was used. Nodes requiring a Terms of Use checkbox are skipped unless the user
sets `telephoneAcceptTerms` after reviewing and accepting those terms.

Live CLI: `python snake.py FI 5.23.111.225 telephone` exited with status 0 and
returned both selected Helsinki nodes in 15.15 seconds: 4vps.su at 20.77 ms and
mynymbox.io at 42.45 ms.

Live CLI: `python snake.py LT 5.23.111.225 telephone` exited with status 0 and
returned all six selected LT nodes in 57.77 seconds: time4vps.eu (25.35 ms),
time4vps.com (25.39 ms), hostens.com (25.56 ms), bacloud.com (36.88 ms),
serveroffer.net (43.42 ms), and ultravps.eu (46.60 ms). BaCloud UK/Chicago
were not queried as LT nodes.

Separate live checks against the same target returned prohosting24.de at
41.223 ms and harmony-solutions.de at 43.025 ms after the Hybula refresh fix.
ServerHub's backend returned an empty response even after successful startup;
no measurement was invented. SSL certificate/handshake failures, connection
failures, HTTP 502, packet loss, and unavailable public backends can still occur.

All 55 tests pass. Regression cases cover zero-delay refresh, modern fetch
startup, refreshed form errors, BaCloud GET, three-value ping summaries,
country correction, rejecting explicit page-country mismatches, additional
FI nodes, and explicit terms opt-in.

Full DE live CLI: `python snake.py DE 5.23.111.225 telephone` exited with
status 0 and returned 8 measurements from 15 selected nodes in 88.44 seconds.
The previous falsely DE-tagged Chicago ServerHub, SGP Vebble, and NL Hostshield
endpoints were absent from the DE job list. Newly working Hybula nodes included
prohosting24.de at 38.42 ms and harmony-solutions.de at 43.25 ms. Four nodes
returned HTTP 502 or timed out, two returned no supported summary, and
lowhosting.com required Terms of Use acceptance. TLS verification stayed enabled.

## Globalping plugin

Added `Plugins/globalping.py` using the official public HTTP API and its current
OpenAPI specification (`https://api.globalping.io/v1/spec.yaml`, with schemas
and examples from `jsdelivr/globalping/public/v1/components`). It creates one
ping measurement, requests up to five probes by default, sends four packets
per probe, and polls no faster than once per 500 ms after each response.
The probe timeout is 30 seconds and the client allows 45 seconds for execution
and API finalization. The optional API token is read from `GLOBALPING_TOKEN` or
`globalpingToken`; no browser or external Globalping CLI is used.

Country requests use the normalized ISO alpha-2 country field; `any` omits
location filters. Completed results use API `stats.avg` in milliseconds. Failed
results, zero received packets, invalid averages, and unexpected countries are
excluded. Result indexes preserve distinct probes with identical location or
network names. The resolved target address is not misrepresented as a source
probe address, so country comparison is unsupported. Poll failures and client
deadlines preserve already completed results. HTTP 429 produces an explicit
rate-limit diagnostic without retrying the measurement-creation POST.

Live CLI: `python snake.py FI 5.23.111.225 globalping` exited with status 0 and
returned five Finnish probes in 11.52 seconds without a token:

| City | Network | Average |
| --- | --- | --- |
| Helsinki | Hetzner Online | 18.26 ms |
| Helsinki | Baykov Ilya Sergeevich | 18.58 ms |
| Helsinki | HOSTKEY | 26.14 ms |
| Helsinki | H2NEXUS CLOUD SERVICES - FZCO | 33.38 ms |
| Helsinki | Inios | 51.79 ms |

All 64 offline tests pass. Globalping tests cover country/worldwide requests,
optional authentication, configuration limits, polling intervals, failure and
country filtering, duplicate-looking probes, preserving partial results on
errors/deadlines, rate limits, rejecting invalid IDs, and plugin discovery.
`git diff --check` passes.
