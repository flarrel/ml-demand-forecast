"""Backtest and package a one-week-ahead unit-sales forecaster."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from forecast.data import SELECTION_WEEKS

FEATURES = ["lag_1", "lag_2", "lag_4", "mean_4", "std_4", "mean_8"]
BASELINES = {"last_week": "lag_1", "four_week_mean": "mean_4"}
MODEL = "gradient_boosting"
HOLDOUT_WEEKS = 8
REQUIRED_MAE_GAIN = 0.05
WEEK = pd.Timedelta(weeks=1)


def panel_digest(source):
    with source.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read_panel(source):
    panel = pd.read_csv(source, dtype={"sku": "string"}, parse_dates=["week"])
    if list(panel.columns) != ["week", "sku", "units"] or panel.isna().any().any():
        raise ValueError("Expected complete week, sku, and units columns")
    weeks = pd.DatetimeIndex(panel["week"].unique()).sort_values()
    if len(weeks) <= SELECTION_WEEKS + HOLDOUT_WEEKS:
        raise ValueError("Need separate training, validation, and holdout weeks")
    if not weeks.equals(pd.date_range(weeks[0], weeks[-1], freq="W-MON")):
        raise ValueError("Expected consecutive Monday week starts")
    if panel.duplicated(["week", "sku"]).any() or len(panel) != len(weeks) * panel["sku"].nunique():
        raise ValueError("Expected one row for every SKU and week")
    units = panel["units"].to_numpy(dtype=float)
    if not np.isfinite(units).all() or (units < 0).any() or (units % 1 != 0).any():
        raise ValueError("Expected finite, nonnegative integer units")
    return panel


def make_features(panel):
    frame = panel.sort_values(["sku", "week"]).copy()
    by_sku = frame.groupby("sku", sort=False)["units"]
    past = by_sku.shift(1).groupby(frame["sku"], sort=False)
    for lag in (1, 2, 4):
        frame[f"lag_{lag}"] = by_sku.shift(lag)
    frame["mean_4"] = past.transform(lambda series: series.rolling(4).mean())
    frame["std_4"] = past.transform(lambda series: series.rolling(4).std(ddof=0))
    frame["mean_8"] = past.transform(lambda series: series.rolling(8).mean())
    return frame.dropna(subset=FEATURES)


def predict_tree(model, frame):
    return np.maximum(0, model.predict(frame[FEATURES]))


def fit_tree(frame):
    model = HistGradientBoostingRegressor(
        max_iter=120, max_leaf_nodes=15, min_samples_leaf=15,
        l2_regularization=1.0, early_stopping=False, random_state=42,
    )
    with threadpool_limits(limits=1):
        return model.fit(frame[FEATURES], frame["units"])


def predict_period(frame, model):
    predictions = frame[["week", "sku", "units"]].copy()
    for name, feature in BASELINES.items():
        predictions[name] = frame[feature]
    with threadpool_limits(limits=1):
        predictions[MODEL] = predict_tree(model, frame)
    return predictions


def scores(predictions):
    actual = predictions["units"].to_numpy()
    volume = float(actual.sum())
    result = {}
    for name in (*BASELINES, MODEL):
        errors = np.abs(predictions[name].to_numpy() - actual)
        result[name] = {
            "mae": float(errors.mean()),
            "wape": float(errors.sum() / volume) if volume > 0 else None,
        }
    return result


def use_candidate(baseline_mae, candidate_mae):
    return baseline_mae > 0 and candidate_mae <= baseline_mae * (1 - REQUIRED_MAE_GAIN)


def evaluate(panel):
    weeks = pd.DatetimeIndex(panel["week"].unique()).sort_values()
    validation_weeks = weeks[SELECTION_WEEKS:-HOLDOUT_WEEKS]
    holdout_start = weeks[-HOLDOUT_WEEKS]
    frame = make_features(panel)
    validation_predictions = []
    for week in validation_weeks:
        model = fit_tree(frame[frame["week"] < week])
        validation_predictions.append(predict_period(frame[frame["week"] == week], model))
    validation = pd.concat(validation_predictions, ignore_index=True)
    validation_scores = scores(validation)
    baseline = min(BASELINES, key=lambda name: validation_scores[name]["mae"])

    model = fit_tree(frame[frame["week"] < holdout_start])
    holdout = predict_period(frame[frame["week"] >= holdout_start], model)
    holdout_scores = scores(holdout)
    baseline_mae = holdout_scores[baseline]["mae"]
    candidate_mae = holdout_scores[MODEL]["mae"]
    passed = use_candidate(baseline_mae, candidate_mae)
    selected = MODEL if passed else baseline

    selection = panel[panel["week"] <= weeks[SELECTION_WEEKS - 1]]
    volume = selection.groupby("sku")["units"].sum().sort_values(
        ascending=False, kind="stable"
    )
    top_skus = volume.head(max(1, len(volume) // 3)).index
    high = holdout["sku"].isin(top_skus)
    report = {
        "validation_start": str(validation_weeks[0].date()),
        "validation_end": str(validation_weeks[-1].date()),
        "validation_rows": len(validation),
        "validation": validation_scores,
        "holdout_start": str(holdout_start.date()),
        "holdout_end": str(weeks[-1].date()),
        "holdout_rows": len(holdout),
        "holdout": holdout_scores,
        "holdout_by_volume": {
            label: {"rows": len(rows), "scores": scores(rows)}
            for label, rows in (("higher_volume", holdout[high]), ("other", holdout[~high]))
            if not rows.empty
        },
        "release": {
            "validation_selected_baseline": baseline,
            "required_mae_reduction": REQUIRED_MAE_GAIN,
            "observed_mae_reduction": 1 - candidate_mae / baseline_mae if baseline_mae else None,
            "candidate_passed": passed,
            "selected": selected,
        },
    }
    artifact = {"schema": 1, "method": selected, "model": model if passed else None}
    return artifact, report, validation, holdout


def train(source, output):
    digest = panel_digest(source)
    panel = read_panel(source)
    artifact, report, validation, holdout = evaluate(panel)
    if panel_digest(source) != digest:
        raise ValueError("Weekly panel changed during evaluation")
    artifact["panel_sha256"] = digest
    # Stage each output before replacing a previous run's files.
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as directory:
        staging = Path(directory)
        joblib.dump(artifact, staging / "forecaster.joblib")
        (staging / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
        validation.to_csv(staging / "validation-predictions.csv", index=False)
        holdout.to_csv(staging / "holdout-predictions.csv", index=False)
        for name in ("validation-predictions.csv", "holdout-predictions.csv",
                     "evaluation.json", "forecaster.joblib"):
            (staging / name).replace(output / name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=Path("work/weekly.csv"))
    parser.add_argument("--output", type=Path, default=Path("work"))
    args = parser.parse_args()
    print(json.dumps(train(args.panel, args.output), indent=2))


if __name__ == "__main__":
    main()
