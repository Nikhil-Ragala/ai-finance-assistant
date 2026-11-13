"""Spending forecast: simple Linear Regression over monthly expense totals."""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LinearRegression

MIN_MONTHS = 3  # below this we do not fit a model (SRS 9.6: handle insufficient data gracefully)


def forecast_next(monthly_totals: list[float]) -> dict:
    """Estimate next month's spending from a chronological list of monthly totals."""
    n = len(monthly_totals)
    if n == 0:
        return {"status": "insufficient_data", "estimate": None, "method": None,
                "message": "Add some expenses first - no history to forecast from yet."}
    if n < MIN_MONTHS:
        avg = float(np.mean(monthly_totals))
        return {"status": "insufficient_data", "estimate": round(avg, 2), "method": "average",
                "message": f"Only {n} month(s) of data, so this is a simple average, not a trained forecast."}
    X = np.arange(n).reshape(-1, 1)
    y = np.array(monthly_totals, dtype=float)
    model = LinearRegression().fit(X, y)
    est = float(model.predict([[n]])[0])
    est = max(est, 0.0)
    return {"status": "ok", "estimate": round(est, 2), "method": "linear_regression",
            "message": "Estimate based on your monthly trend. It is not a guaranteed value."}
