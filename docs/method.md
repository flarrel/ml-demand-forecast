# Forecasting method

## Data

Daqing Chen's Online Retail dataset contains 541,909 transaction lines from a
UK-based online retailer. The ingestion command verifies a pinned SHA-256 for the
UCI download and checks the workbook schema before parsing. Customer identifiers
and descriptions are excluded from all products of the pipeline. [UCI Online Retail, CC BY 4.0](https://archive.ics.uci.edu/dataset/352/online%2Bretail)

The transaction filter removes cancellations, non-merchandise stock codes,
missing invoice IDs or dates, nonpositive or invalid prices, and nonpositive or
non-integer quantities. Repeated invoice lines contribute to the total. The
source does not provide a unique line ID that would let the pipeline distinguish
a true duplicate from repeated sales on the same invoice. Both calendar weeks
at the dataset boundaries are dropped. The data report accounts for every input
line exactly once.

The output sums positive sales by SKU and Monday-start week. SKU eligibility uses
the highest unit volumes from the first 26 complete weeks. Missing SKU-week rows
for eligible products are filled with zero observed sales. The resulting panel
contains 1,300 rows across 25 SKUs and 52 weeks, with 55 zero-sales rows.

## Forecast and evaluation

The target is next-week units sold for an eligible SKU. The candidate is a single
histogram gradient-boosted regression model shared by all SKUs. It uses lagged
units from one, two, and four weeks prior, an eight-week mean, and a four-week
mean and standard deviation. Each feature ends before the forecast week starts.
The two baselines carry the previous week's units forward or average the previous
four weeks.

Development uses 18 rolling weekly origins. At each origin, the candidate fits
only on earlier weeks and forecasts all 25 SKUs. The lower-MAE baseline from
these origins becomes the release comparator. For the final eight weeks, the
candidate is fitted once on the pre-holdout portion. Previously observed sales
can update lag features as the holdout window advances. The held-out results
are compared after the feature definitions, estimator, and release rule
are fixed.

MAE measures the typical error in units per SKU-week. WAPE divides total absolute
error by total realized sales volume and is undefined when realized sales are
zero across the evaluation group. We also report errors for the top third of
SKUs by selection-period volume and for the remaining SKUs. The baseline is
served whenever the candidate misses the 5% relative MAE improvement target.

## Research and retail context

The M5 Accuracy study found that models trained across aligned product series
were common among the strongest submissions. Its findings on cross-learning,
benchmarks, and temporal validation motivated the pooled boosted candidate and
explicit comparisons against simple weekly methods. The project tests that
idea at one retailer and one aggregation level. [Makridakis et al., M5 Accuracy results](https://www.sciencedirect.com/science/article/pii/S0169207021001874)

A follow-up compared the characteristics of Walmart's M5 series with two other
retailers. Differences in demand patterns and aggregation are reasons to test
transfer on the source at hand. Here, the baseline beat the pooled candidate
across both evaluated SKU-volume groups. [Theodorou et al., M5 representativeness](https://arxiv.org/html/2103.02941)

Walmart's forecasting discussion treats accuracy and uncertainty as inputs to
operational decisions. Its separate demand-sensing case illustrates the use of
in-week updates. This service supplies week-ahead point estimates over a fixed
retail snapshot. The data lacks stock balances, lead times, and reliable
future promotion schedules, so the forecast cannot establish safety stock,
unmet demand, or ordering quantities. [Walmart discussion of M5](https://www.sciencedirect.com/science/article/pii/S0169207021001023) · [Walmart Labs demand-sensing case](https://www.youtube.com/watch?v=yK163J2ZI9U)
