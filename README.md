# Weekly Sales Forecast

Weekly Sales Forecast gives a replenishment batch job a one-week-ahead unit-sales
forecast for 25 selected products. It turns public retail transactions into a
weekly panel, compares candidate and baseline forecasters, and serves the method
selected by the release rule through a local HTTP API.

## Run locally

From the repository root, use Python 3.12 and curl.

```sh
mkdir -p .cache work
python3 -m venv .venv
. .venv/bin/activate
export TMPDIR="$PWD/.cache"
export OMP_NUM_THREADS=1 LOKY_MAX_CPU_COUNT=1
python -m pip --cache-dir .cache/pip --disable-pip-version-check install -r requirements.txt

curl -fL --retry 2 'https://archive.ics.uci.edu/static/public/352/online+retail.zip' \
  -o work/online-retail.zip
python -m forecast.data
python -m forecast.data --sku-offset 25 --output work/confirmation
python -m forecast.model
python -m unittest discover -s tests -v
python -m uvicorn forecast.service:app --host 127.0.0.1 --port 8000
```

In another terminal, from the repository root:

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/catalog
.venv/bin/python -m forecast.batch --week 2011-12-05 85123A 84879
```

The service uses a historical snapshot ending in the week of November 28, 2011.
December 5, 2011 is the start of the forecast week in this demonstration. The source also
contains a partial week beginning December 5, which is excluded from training and
scoring. See the [batch integration guide](docs/integration.md) for the contract,
sample output, and failure scenarios.

## Evaluation

The release compares the robust rolling forecast with the four-week average,
the baseline selected during development. Each evaluation below covers eight
weeks and 200 SKU-week forecasts.

- **Original period replay:** MAE fell from 293.35 to 271.11 units (**7.58%**).
  WAPE fell from 52.43% to 48.45%.
- **25 additional SKUs:** MAE fell from 173.19 to 149.34 units (**13.77%**).
  WAPE fell from 62.20% to 53.64%. These SKUs were excluded from candidate
  selection and are from the same retailer and dates.

The robust rolling forecast exceeded the 5% MAE improvement target on both
checks and is the method served by the API. Gradient boosting remains in the
evaluation as a comparator.

The model command generates a release artifact, validation and holdout metrics,
and row-level predictions in `work/`. You can compare a run with the committed
[example evaluation](docs/example-evaluation.json) and
[data report](docs/example-data-report.json). The [forecasting method](docs/method.md)
explains the cleaning, time splits, research, and limitations.
