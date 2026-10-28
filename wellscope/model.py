"""Decline-curve engine. Arps hyperbolic with a 6%/yr terminal exponential tail.

b (the hyperbolic exponent) is poorly constrained by short, noisy public series, so it is held fixed at
several values and results are reported as a range. The website re-runs the economics in the browser
with the viewer's own price deck using these parameters.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit

B_GRID = (0.3, 0.5, 0.8, 1.0)
D_MIN = 0.06


def arps(t, qi, di, b):
    """q(t) = qi / (1 + b*di*t)^(1/b); t in years, di nominal per year."""
    return qi / np.power(1.0 + b * di * t, 1.0 / b)


def fit_fixed_b(rates, b, min_points=9):
    """Fit qi, di for a fixed b from the peak onward. Returns None when there is too little signal."""
    y = np.asarray(rates, float)
    if len(y) < min_points or y[-3:].min() <= 0:
        return None
    y = y[int(np.argmax(y)):]
    if len(y) < min_points:
        return None
    t = np.arange(len(y)) / 12.0
    m = y > 0
    try:
        p, _ = curve_fit(lambda t, qi, di: arps(t, qi, di, b), t[m], y[m], p0=[y[0], 0.3],
                         bounds=([0, 0.0], [y.max() * 3, 5.0]), maxfev=4000)
    except (RuntimeError, ValueError):
        return None
    pred = arps(t[m], p[0], p[1], b)
    ss_tot = float(np.sum((y[m] - y[m].mean()) ** 2)) or 1.0
    r2 = 1 - float(np.sum((y[m] - pred) ** 2)) / ss_tot
    tn = (len(y) - 1) / 12.0
    return {"qi": float(p[0]), "di": float(p[1]), "b": b, "r2": r2, "t_now": tn,
            "q_now": float(arps(tn, p[0], p[1], b))}


def fit_range(rates):
    """Fits at every b in B_GRID. Returns compact params for the website, or None."""
    fits = [fit_fixed_b(rates, b) for b in B_GRID]
    fits = [f for f in fits if f]
    if len(fits) < len(B_GRID):
        return None
    r2 = float(np.mean([f["r2"] for f in fits]))
    mid = fits[1]
    return {
        "q": round(float(np.median([f["q_now"] for f in fits])), 2),
        "fits": [[f["b"], round(f["di"], 4), round(f["q_now"], 3), round(f["t_now"], 3)] for f in fits],
        "decl": round((1 - np.exp(-mid["di"] / (1 + mid["b"] * mid["di"] * mid["t_now"]))) * 100, 1),
        "r2": round(r2, 2),
    }


def forecast(q_now, di, b, t_now, months=360, q_limit=0.0):
    """Monthly rates going forward from q_now, switching to D_MIN exponential once decline falls to it."""
    out, q_term, m0 = [], None, 0
    qi = q_now * np.power(1 + b * di * t_now, 1 / b)
    for m in range(1, months + 1):
        t = t_now + m / 12.0
        if q_term is None and di / (1 + b * di * t) <= D_MIN:
            q_term, m0 = arps(t, qi, di, b), m
        q = q_term * np.exp(-D_MIN * (m - m0) / 12.0) if q_term is not None else arps(t, qi, di, b)
        if q < q_limit:
            break
        out.append(q)
    return np.array(out)


def backtest(rates, hold=6):
    """Fit on all but the last ``hold`` months (b=0.5), return (predicted - actual) / actual for their mean."""
    y = np.asarray(rates, float)
    if len(y) < 18 + hold:
        return None
    f = fit_fixed_b(y[:-hold], 0.5)
    if not f:
        return None
    act = y[-hold:].mean()
    if act <= 0:
        return None
    pred = forecast(f["q_now"], f["di"], 0.5, f["t_now"], months=hold).mean()
    return float((pred - act) / act)
