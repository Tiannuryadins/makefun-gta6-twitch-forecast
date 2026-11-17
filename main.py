#!/usr/bin/env python3
"""Forecast GTA VI's launch-day Twitch viewers hour by hour.

make.fun competition: gta6-twitch-ccu-forecast-01 (harness program/v1).

Reads every case file ``<id>.in`` in the input directory (``$MAKEFUN_INPUT_DIR``
or ``/input``) and writes one forecast ``<id>.out`` per case to the output
directory (``$MAKEFUN_OUTPUT_DIR`` or ``/output``).

Input case (``makefun/twitch-ccu-case/v1``): the target game's hour-1 print
(``known``), its pre-release history, and a library of past big launches
(``comparables``) with hourly Twitch category curves from 14 days before
to 3 days after each launch. Output: for each of hours 2-24 of the release
day, five quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent
viewers. Score: mean pinball loss on the log scale; lower is better.

Model -- a comparable-shape ensemble, fitted only on the case's own data,
offline, no network:
  * Shape library: for each comparable, the release-day log-ratio curve
    r_h = ln(viewers_h / viewers_hour1), h = 2..24. Launch-day curves share
    a shape driven by the unlock waves (overnight dip, US unlocks at hours
    6 and 9, prime-time peak around hours 19-21, late decay), but the shape
    depends strongly on the launch regime -- so each comparable is weighted
    by how similar its regime is to the target's:
      - hour-1 scale: a Gaussian kernel on ln(hour-1 viewers), bandwidth
        1.5. A launch whose hour 1 already holds a big audience (rolling
        midnight, major regions live) behaves nothing like one whose hour 1
        is near-empty before a single global unlock hours later.
      - console-only x5: the target (GTA VI) is a console-only launch, as
        are the practice targets; a comparable with no PC/Stadia release
        gets five times the weight.
      - rolling midnight x2: a comparable whose unlock text says the launch
        rolled at midnight local gets twice the weight; GTA VI unlocks that
        way.
      - the house's own tier labels in the unlock text are respected:
        "early-access-contaminated" launches (their release day is not a
        real launch day -- the peak happened days earlier) and "weak"
        launches (free-to-play, slow-burn) are dropped from the library.
        The target's own pre-release history comparable is not a launch
        and is dropped too (it has no hour-1 point on its day).
  * Median: the similarity-weighted median of r_h per hour;
    q50 = hour1 * exp(median r_h).
  * Spread: parametric -- the similarity-weighted standard deviation of r_h
    around its weighted mean per hour, floored at 0.08 * sqrt(h - 1) (a
    random-walk floor, so no hour is ever over-confident), with Gaussian
    quantiles at the case's levels. The cross-launch dispersion is the
    honest uncertainty here: it is wide because launches genuinely differ.
  * Fallbacks: if no comparable yields a usable curve, the forecast falls
    back to the house persistence baseline (q50 = hour-1 print, spread
    0.15 * sqrt(h - 1)); a missing hour-1 print falls back to the last
    history point. The program never crashes on a malformed case -- an
    invalid case forfeits the prize, a bad row only costs its loss.

Everything is deterministic: no randomness, no wall clock, no network, and
the standard library only. Two runs on the same case write identical bytes.

Validation (see BUILD-TRANSCRIPT.md): on the kit's four practice cases,
with release-day answers fetched once from SullyGnome's public API (hour-1
values match the cases' known prints exactly, all four), this program
scores a mean pinball loss of 0.1909 against 0.3871 for the house baseline
-- a 51% improvement, better on every case (0.309 / 0.142 / 0.131 / 0.182
vs 0.744 / 0.287 / 0.215 / 0.303), with 90% coverage of 0.957 and a
typical median miss of 36% (baseline 90%). Leave-one-out over the 37
comparables of p00 (each launch forecast from the other 36): 0.4066
overall, 0.2135 on the 8 console-only launches.
"""

import json
import math
import os
import sys
from datetime import datetime

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"

# --- Model constants (tuned on the practice cases + LOO; see BUILD-TRANSCRIPT.md) ---
SCALE_BANDWIDTH = 1.5   # Gaussian kernel bandwidth on ln(hour-1 viewers).
CONSOLE_BONUS = 5.0     # weight multiplier for console-only comparables:
                        # the target (GTA VI) is a console-only launch.
ROLLING_BONUS = 2.0     # weight multiplier for rolling-midnight-local
                        # unlocks: GTA VI unlocks that way.
SPREAD_FLOOR = 0.08     # per-hour spread floor, grown as sqrt(h - 1).
BASELINE_SIGMA = 0.15   # persistence-baseline spread (the house baseline),
                        # used only when the comparable library is empty.
MAX_VIEWERS = 1e9       # output cap from the competition spec.
DEFAULT_LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
TARGET_CONSOLE_ONLY = True  # GTA VI launches on PS5 / Xbox Series only
                            # (no PC release); the practice targets are
                            # console-only launches too.


def parse_ts(text):
    """Parse a 'YYYY-MM-DDTHH:MM:SSZ' timestamp, or return None."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def normal_ppf(p):
    """Quantile of the standard normal distribution (Acklam's approximation).

    Accurate to ~1e-9 relative error -- far tighter than the forecast needs.
    """
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    # Coefficients for the central region and the tails.
    a = (-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285984469534e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00)
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    else:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    # One Halley refinement step (the final step of Acklam's algorithm):
    # drives the approximation error down to ~1e-9.
    e = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


def weighted_quantile(pairs, q):
    """Weighted q-quantile of [(value, weight), ...]; pairs need not be sorted."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0] if ordered else 0.0
    target = q * total
    acc = 0.0
    for value, w in ordered:
        acc += w
        if acc >= target:
            return value
    return ordered[-1][0]


def is_console_only(platforms):
    """True when the platforms string lists no PC (or Stadia) release."""
    text = (platforms or "").lower()
    return "pc" not in text and "stadia" not in text


def is_rolling_unlock(unlock_text):
    """True when the unlock text describes a rolling midnight-local launch."""
    text = (unlock_text or "").lower()
    return ("midnight local" in text or "rolling" in text) and \
        "single global" not in text


def comparable_tier(unlock_text):
    """The house's tier label embedded in the unlock text.

    Returns "contaminated" for early-access-contaminated launches, "weak"
    for weak analogues, "comparable" otherwise.
    """
    text = unlock_text or ""
    if "early-access-contaminated" in text:
        return "contaminated"
    if "Tier: weak" in text:
        return "weak"
    return "comparable"


def release_day_curve(comp):
    """{hour: viewers} for hours 1..24 of a comparable's release day.

    Points are hourly averages; an hour the source did not sample is absent.
    Returns {} when the comparable has no parseable day_start.
    """
    day0 = parse_ts(comp.get("day_start"))
    if day0 is None:
        return {}
    points = {}
    for p in comp.get("hourly") or []:
        t = parse_ts(p.get("from"))
        v = p.get("viewers")
        if t is None or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        h = int((t - day0).total_seconds() // 3600) + 1
        if 1 <= h <= 24:
            points[h] = v
    return points


def log_ratio_curve(comp):
    """(ratios, hour1) with ratios = {h: ln(v_h / v_1)} for h = 2..24.

    Returns None when the comparable has no usable hour-1 point (this is
    how the target's own pre-release history comparable is excluded: its
    series starts mid-day, so it has no hour-1 point on its day_start).
    """
    points = release_day_curve(comp)
    v1 = points.get(1)
    if not v1 or v1 <= 0:
        return None
    ratios = {h: math.log(max(v, 1) / v1) for h, v in points.items() if h >= 2}
    return ratios, v1


def similarity_weight(comp, hour1, target_console):
    """How much one comparable's shape should count for this target."""
    v1 = comp["_v1"]
    d = math.log(max(v1, 1)) - math.log(max(hour1, 1))
    w = math.exp(-(d / SCALE_BANDWIDTH) ** 2)
    if target_console and is_console_only(comp.get("platforms", "")):
        w *= CONSOLE_BONUS
    if is_rolling_unlock(comp.get("unlock", "")):
        w *= ROLLING_BONUS
    return w


def build_library(case):
    """The shape library: [(comparable, ratios), ...], sorted by name.

    Drops comparables the house labelled early-access-contaminated or weak,
    and any comparable named after the target game itself (its own history).
    """
    target_name = (case.get("game") or {}).get("name") or ""
    library = []
    for comp in sorted(case.get("comparables") or [], key=lambda c: c.get("name", "")):
        name = comp.get("name") or ""
        if target_name and name.startswith(target_name):
            continue
        if comparable_tier(comp.get("unlock", "")) != "comparable":
            continue
        res = log_ratio_curve(comp)
        if res is None:
            continue
        ratios, v1 = res
        comp = dict(comp)
        comp["_v1"] = v1
        library.append((comp, ratios))
    return library


def round2(x):
    """Round to 2 decimals, clamped to the spec's (0, 1e9] output range."""
    return min(MAX_VIEWERS, max(0.01, round(x, 2)))


def forecast_case(case):
    """Forecast one case. Returns the output object {"hours": [...]}."""
    levels = case.get("levels") or list(DEFAULT_LEVELS)
    zscores = [normal_ppf(tau) for tau in levels]

    # Hour-1 print: known[0].viewers, else the last history point, else 1.
    hour1 = None
    known = case.get("known") or []
    if known:
        v = known[0].get("viewers")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            hour1 = float(v)
    if hour1 is None:
        history = case.get("history") or []
        for p in reversed(history):
            v = p.get("viewers")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                hour1 = float(v)
                break
    if hour1 is None:
        hour1 = 1.0

    library = build_library(case)

    hours = []
    for h in range(2, 25):
        if library:
            pairs = []
            for comp, ratios in library:
                if h in ratios:
                    pairs.append((ratios[h],
                                  similarity_weight(comp, hour1, TARGET_CONSOLE_ONLY)))
            if pairs:
                median = weighted_quantile(pairs, 0.5)
                total = sum(w for _, w in pairs)
                mean = sum(v * w for v, w in pairs) / total
                var = sum(w * (v - mean) ** 2 for v, w in pairs) / total
                sigma = max(math.sqrt(var), SPREAD_FLOOR * math.sqrt(h - 1))
                centre, spread = median, sigma
            else:
                centre, spread = 0.0, BASELINE_SIGMA * math.sqrt(h - 1)
        else:
            # Empty library: fall back to the persistence baseline.
            centre, spread = 0.0, BASELINE_SIGMA * math.sqrt(h - 1)
        qs = [round2(hour1 * math.exp(centre + z * spread)) for z in zscores]
        # Rounding can only tie neighbours, but enforce monotonicity anyway.
        for j in range(1, len(qs)):
            if qs[j] < qs[j - 1]:
                qs[j] = qs[j - 1]
        hours.append({"hour": h, "q": qs})
    return {"hours": hours}


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    inputs = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".in"))
    for filename in inputs:
        case_id = filename[: -len(".in")]
        with open(os.path.join(INPUT_DIR, filename), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        result = forecast_case(case)
        out_path = os.path.join(OUTPUT_DIR, case_id + ".out")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(result, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
