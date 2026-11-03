# Versions

| Name | Where | What it is |
| --- | --- | --- |
| **WellScope V1** | branch [`v1`](https://github.com/kosherite/WellScope/tree/v1) (commit `a480a7f`) | The map of every WCSB well reviewed on 2026-10-28: 764,733 wells in AB, SK, BC and MB, standard well symbols, horizontal laterals, search by UWI / licence / legal location / operator, township grid calibrated to AER surveyed wells (median 0.15 km), well panel with 36-month production. Data through Aug 2026 (pipeline run 40790843432). |

`v1` is a fixed reference: nothing is committed to it. To run V1 again, check out the branch and run the pipeline,
or compare any later change against it with `git diff v1 main`.

## Test area (staging)

- **Live:** https://kosherite.github.io/WellScope/ is the `main` branch.
- **Test:** https://kosherite.github.io/WellScope/staging/ is the `staging` branch. It shows a yellow TEST tag and is hidden from search engines.

Both use the same map data. Website changes go to `staging` first. Once they look right there, `staging` is merged into `main` to put them live.
Data-pipeline changes are tried on the `pipeline-test` branch (a full build with screenshots, no publish) before they reach `main`.
