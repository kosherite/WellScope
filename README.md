# WellScope

Open-data screening for oil and gas in the Western Canadian Sedimentary Basin. WellScope pulls every well and every month of reported production that Alberta, Saskatchewan, British Columbia and Manitoba publish for free, puts them in one format, and turns them into the numbers an analyst screens on: production and oil weighting, base decline, new-well type curves, PDP value at your own price deck, operator rankings and inactive-well liability.

It runs as a monthly GitHub Action and publishes a static website to GitHub Pages. No server and no database.

## What an analyst gets

| View | What it answers |
| --- | --- |
| **Overview** | Basin and province production (oil vs gas, boe/d), base decline, PDP value at your deck, new-well type curve, largest operators, drilling activity by year |
| **Map** | Township-sized areas shaded by production, oil weighting, decline, new wells or inactive wells. Tap one for its production history and forecast band, type curve (P10/P50/P90), operators and wells |
| **Operators** | Sortable league table, then a page per operator: production split, base decline, PDP forecast and value, type curve, where they produce, licensed wells and inactive-well cleanup estimate |
| **Price deck** | WTI, differential, FX, AECO, royalty, opex, transport, discount rate. Every value and netback on the site recalculates instantly |
| **Data & methods** | Sources and data dates, back-test accuracy, location accuracy, definitions and limits |

Conventions follow the sell-side primer *Energy Made Simple* (RBC Capital Markets): bbl/d and mcf/d per calendar day, boe at 6 mcf = 1 boe, field netback = price − royalties − operating − transportation, P10 = high case.

## Data sources

| Province | Wells | Production | Notes |
| --- | --- | --- | --- |
| Alberta | [AER ST37](https://www.aer.ca/data-and-performance-reports/statistical-reports/st37) Excel package, surveyed surface coordinates | [Petrinex Alberta public data](https://www.petrinex.ca/public-data/apd/), monthly Conventional Volumetric files | Battery rows name the producing well and its hours, so production is built well by well; confidential wells stay at facility level |
| Saskatchewan | [Petrinex Saskatchewan public data](https://www.petrinex.ca/public-data/spd/) Well Infrastructure | Petrinex Saskatchewan Conventional Volumetric files | The province's own well bundles are paid; locations come from the DLS UWI |
| British Columbia | [BC Energy Regulator data centre](https://www.bc-er.ca/data-reports/data-centre) well index | BCER all-well production download | Most NE BC wells use the NTS grid, converted to lat/lon |
| Manitoba | [Petroleum Branch reports](https://www.gov.mb.ca/iem/petroleum/reports/index.html) weekly UWI list | Well monthly production workbooks | Gas/GSD volumes in 1000 m³, other fluids m³ |

Every URL lives in `wellscope/config.py`. If a publisher moves or reshapes a file, `python -m wellscope probe` prints each source's columns so the adapter can be fixed in one place.

## Method

1. **Normalise.** Oil + condensate to bbl, gas to mcf, water to bbl; rates per calendar day. UWIs from AER (`00/06-06-001-01W4/0`), Petrinex (`ABWI100060600101W400`) and the standard form (`100/06-06-001-01W4/00`) all map to one key.
2. **Locate.** Surveyed coordinates where published. Otherwise DLS (AB, SK, MB, BC Peace River Block) or NTS (NE BC) legal locations are converted; the pipeline measures the formula's error against AER's surveyed coordinates on every run and reports it.
3. **Aggregate.** Areas are a basin-wide 0.1° × 0.15° grid (about one township) so the four provinces share one map.
4. **Decline.** Arps hyperbolic, q = qᵢ / (1 + b·Dᵢ·t)^(1/b), with a 6%/yr exponential tail. b is held at 0.3, 0.5, 0.8 and 1.0 because short public series can't pin it down, and every result is a range.
5. **Value.** The browser forecasts each fit and discounts monthly cash flow at your deck: pre-tax, producing wells only (wells online 12+ months), 30-year cap.
6. **Test.** Each area is refit without its last six months and compared with what was reported. The median error is on the Data & methods page.

## Run it

```bash
pip install -e ".[dev]"
pytest                                   # unit and end-to-end tests on fixtures
python -m wellscope probe                # check every source is reachable and print its columns
python -m wellscope run --provinces AB,SK,BC,MB --months 36 --out site/data
python -m http.server -d site 8000       # open http://localhost:8000
```

A full-basin run downloads a few GB and takes one to two hours. Downloads are cached in `data/raw/`, and the processed tables are written to `data/build/*.parquet` for your own analysis.

### On GitHub

* **`pipeline.yml`** runs on the 22nd of each month (or on demand from the Actions tab), builds the full dataset and deploys the site to GitHub Pages. Run it with *probe only* first to check every source.
* **`site.yml`** republishes front-end changes using the latest pipeline data, without a rebuild.
* **`ci.yml`** runs the tests on every push.

Turn on Pages once: **Settings → Pages → Source: GitHub Actions**.

The committed `site/data` is a pilot snapshot (real Petrinex data, Alberta around Whitecourt, battery level), so the site works before the first full run. `scripts/pilot_snapshot.py` rebuilds it.

## Limits

* Public volumes are gross; companies report working interest. Operator totals won't match their filings exactly, and the operator is the facility operator in Petrinex.
* Values are screening estimates, not reserves: pre-tax, no capital, no abandonment timing, no hedges.
* Inactive-well cleanup is a placeholder ($80k + $55 per metre of depth), not the AER's licensee capability assessment.
* Saskatchewan and Manitoba locations are approximate (legal location to lat/lon).
* Check each regulator's terms of use before redistributing the data commercially.

## Roadmap

* AER licensee capability assessment and orphan-fund data next to the liability estimate
* Formation and play names from Petrinex code reports, with type curves by play
* BCER frac and drilling data (lateral length, proppant per metre) to normalise type curves
* Well-level detail pages and CSV export
* `notebooks/wellscope_buyer.ipynb` is the original Colab notebook for the Whitecourt battery screen
