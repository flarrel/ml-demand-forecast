"""Serve versioned forecasts for the week after the loaded sales snapshot."""

from contextlib import asynccontextmanager
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from forecast.model import MODEL, ROLLING_METHODS, WEEK, make_features, predict_tree, read_panel

Sku = Annotated[str, StringConstraints(pattern=r"^[0-9]{5}[A-Z]{0,2}$")]
Method = Literal["last_week", "four_week_mean", "gradient_boosting", "robust_rolling"]


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forecast_week: date
    skus: list[Sku] = Field(min_length=1, max_length=25)


class Snapshot(BaseModel):
    history_through_week: date
    forecast_week: date
    model_version: str
    method: Method


class Catalog(Snapshot):
    skus: list[Sku]


class ForecastItem(BaseModel):
    sku: Sku
    units: float = Field(ge=0, allow_inf_nan=False)


class ForecastResponse(Snapshot):
    forecasts: list[ForecastItem]


def create_app(workdir=Path("work")):
    @asynccontextmanager
    async def lifespan(app):
        artifact_bytes = (workdir / "forecaster.joblib").read_bytes()
        # Joblib artifacts must come from our own local training run.
        artifact = joblib.load(BytesIO(artifact_bytes))
        if artifact.get("schema") != 1 or artifact.get("method") not in (*ROLLING_METHODS, MODEL):
            raise ValueError("Unsupported forecaster artifact")
        if artifact["method"] == MODEL and artifact.get("model") is None:
            raise ValueError("Boosted forecaster is missing its trained model")
        panel_bytes = (workdir / "weekly.csv").read_bytes()
        if sha256(panel_bytes).hexdigest() != artifact.get("panel_sha256"):
            raise ValueError("Forecast artifact and sales panel do not match. Run training again.")
        panel = read_panel(BytesIO(panel_bytes))
        through = panel["week"].max()
        target = through + WEEK
        future = panel.loc[panel["week"] == through, ["sku"]].assign(week=target, units=np.nan)
        frame = make_features(pd.concat([panel, future], ignore_index=True))
        app.state.features = frame.loc[frame["week"] == target].set_index("sku")
        app.state.model = artifact["model"]
        app.state.snapshot = Snapshot(
            history_through_week=through.date(),
            forecast_week=target.date(),
            model_version=sha256(artifact_bytes).hexdigest()[:16],
            method=artifact["method"],
        )
        yield

    app = FastAPI(title="Weekly Sales Forecast", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    def ready():
        return {"status": "ready", "model_version": app.state.snapshot.model_version}

    @app.get("/v1/catalog", response_model=Catalog)
    def catalog():
        return Catalog(**app.state.snapshot.model_dump(), skus=app.state.features.index.tolist())

    @app.post("/v1/forecasts", response_model=ForecastResponse)
    def forecast(payload: ForecastRequest):
        snapshot = app.state.snapshot
        if payload.forecast_week != snapshot.forecast_week:
            raise HTTPException(
                status_code=422,
                detail=f"Available forecast week is {snapshot.forecast_week.isoformat()}",
            )
        if len(set(payload.skus)) != len(payload.skus):
            raise HTTPException(status_code=422, detail="SKUs must be unique")
        features = app.state.features
        unknown = sorted(set(payload.skus) - set(features.index))
        if unknown:
            raise HTTPException(status_code=422, detail={"unknown_skus": unknown})
        batch = features.loc[payload.skus]
        if snapshot.method == MODEL:
            units = predict_tree(app.state.model, batch)
        else:
            units = batch[ROLLING_METHODS[snapshot.method]].to_numpy()
        return ForecastResponse(
            **snapshot.model_dump(),
            forecasts=[ForecastItem(sku=sku, units=value)
                       for sku, value in zip(payload.skus, units, strict=True)],
        )

    return app


app = create_app()
