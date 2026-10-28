# WellScope

A free, open map of every oil and gas well in Western Canada. Search any well and see what's at a location, who holds the licence, whether it's producing and what it has made.

Every licensed well in Alberta, Saskatchewan, British Columbia and Manitoba (about 740,000), rebuilt monthly from the regulators' public files and served as a static site. No account, no server.

## What it does

| Feature | Details |
| --- | --- |
| **Every well on the map** | Producing, suspended, abandoned, dry and abandoned, injection/disposal, and licensed or drilling, drawn with standard well symbols. Light dots when zoomed out, full symbols from zoom 9 |
| **Horizontal laterals** | Drawn from surface to bottom hole wherever bottom-hole coordinates are published (Alberta ST37) |
| **One search box** | A UWI in any common format (`100/06-06-001-01W4/00`, `00/06-06-001-01W4/0`, `ABWI100060600101W400`, BC `200/D-080-H/092-G-03/00`, Manitoba `100.14-14-009-29W1.00`), a licence or BC well authorization number, a legal location (`06-06-001-01W4`, `06-001-01W4`, `060-12W5`, `T60 R12 W5`) or an operator name |
| **Township grid** | Township and range lines from zoom 7.5, sections from 11, LSDs from 13.5, with labels |
| **Well panel** | UWI, name, licence, licensee, regulator status and date, fluid, spud or rig-release date, total depth, field, pool, horizontal or not, surface and bottom-hole coordinates, current oil/gas/water rates and a 36-month production chart |
| **Operator view** | Pick an operator to show only their wells and zoom to their footprint |
| **Field use** | Satellite and topo base maps, "locate me", Google/Apple Maps directions to the lease, copy UWI, copy a shareable link (`#well=100/06-06-001-01W4/00`) |
| **Layer controls** | Toggle each well status, the grid and laterals |

## Data sources

| Province | Wells | Production |
| --- | --- | --- |
| Alberta | [AER ST37](https://www.aer.ca/data-and-performance-reports/statistical-reports/st37): surveyed surface and bottom-hole coordinates | [Petrinex Alberta public data](https://www.petrinex.ca/public-data/apd/), well by well |
| Saskatchewan | [Petrinex Saskatchewan](https://www.petrinex.ca/public-data/spd/) Well Infrastructure | Petrinex Saskatchewan volumes |
| British Columbia | [BC Energy Regulator](https://www.bc-er.ca/data-reports/data-centre) well index | BCER all-well production |
| Manitoba | [Petroleum Branch](https://www.gov.mb.ca/iem/petroleum/reports/index.html) weekly UWI list | Well monthly production workbooks |

Wells without published coordinates (SK, BC, MB) are placed from their legal location (DLS or NTS), which can be a few hundred metres off. The grid is drawn from the same survey formula. Production is gross and per calendar day. Check each regulator's terms before reusing the data commercially.

## How it's built

```
regulator files ─► wellscope/sources/*  (one adapter per province)
                ─► wellscope/schema.py  (one well format; every UWI style matched to one key)
                ─► wellscope/mapdata.py ─► wells.geojsonl ─► tippecanoe ─► site/data/wells.pmtiles
                                        ─► site/data/twp/<township>.json   (well details + production)
                                        ─► site/data/lic/<xx>.json         (licence search)
                                        ─► site/data/operators.json, meta.json
site/  MapLibre GL + PMTiles (range requests, so GitHub Pages works with no server)
```

* **`pipeline.yml`** runs on the 22nd of each month (or from the Actions tab): downloads everything, builds the tiles, deploys to GitHub Pages and pushes screenshots of the result to the `ci-screenshots` branch. Pushing to `pipeline-test` runs a full build without deploying.
* **`site.yml`** republishes front-end changes with the latest pipeline data.
* **`ci.yml`** runs the tests.

### Run locally

```bash
pip install -e ".[dev]"
pytest
python -m wellscope probe                       # check every source and print its columns
TIPPECANOE=/path/to/tippecanoe python -m wellscope run --out site/data
python scripts/rangeserve.py site 8000          # PMTiles needs range requests; plain http.server won't do
```

## Parked

The earlier valuation screener (decline fits, PDP value at a price deck, type curves, back-tests) is still in `wellscope/analytics.py` and `wellscope/model.py`. `python -m wellscope run --valuation` builds its data into `site/data/valuation/`, but the site doesn't use it. The plan is to bring it back later as a "screen this area" layer on top of the map.

## Next

* Facilities (batteries, plants) and pipelines as layers
* Exact township grid from official survey data instead of the formula
* CSV export of the wells in view
