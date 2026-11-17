# GTA VI Twitch CCU Forecast — make.fun entry

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Tiannuryadins/makefun-gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Tiannuryadins/makefun-gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts Grand Theft Auto VI's launch-day Twitch concurrent viewers hour by
hour: for each of hours 2–24 of the release day (UTC 2026-11-19), five
quantiles (5%, 25%, 50%, 75%, 95%) of that hour's CCU in the "Grand Theft
Auto VI" Twitch category.

Competition: **gta6-twitch-ccu-forecast-01** ($250, escrowed, free entry).
Score: mean pinball loss on the log scale; lower is better. A prize needs a
loss strictly below the best house entry (a persistence baseline, practice
loss 0.387, and a house model forecast).

## Model

A comparable-shape ensemble, fitted only on the case's own data, offline:

- **Shape library.** Each comparable launch contributes its release-day
  log-ratio curve r_h = ln(viewers_h / viewers_hour1), h = 2..24. Launch-day
  curves share a shape driven by the unlock waves (overnight dip, US unlocks
  at hours 6 and 9, prime-time peak around hours 19–21, late decay), but the
  shape depends strongly on the launch regime — so each comparable is
  weighted by similarity to the target:
  - **Hour-1 scale** — Gaussian kernel on ln(hour-1 viewers), bandwidth 1.5.
    A launch whose hour 1 already holds a big audience behaves nothing like
    one whose hour 1 is near-empty before a single global unlock.
  - **Console-only ×5** — GTA VI is a console-only launch; comparables with
    no PC/Stadia release get five times the weight.
  - **Rolling midnight ×2** — comparables whose unlock rolled at midnight
    local get twice the weight; GTA VI unlocks that way.
  - **Tier labels respected** — launches the house labelled
    "early-access-contaminated" (their release day is not a real launch day)
    or "weak" (free-to-play, slow-burn) are dropped. The target's own
    pre-release history comparable is not a launch and is dropped too.
- **Median.** Similarity-weighted median of r_h per hour;
  q50 = hour1 × exp(median r_h).
- **Spread.** Parametric — the similarity-weighted standard deviation of r_h
  per hour, floored at 0.08·√(h−1), with Gaussian quantiles at the case's
  levels. The cross-launch dispersion is the honest uncertainty: launches
  genuinely differ.
- **Fallbacks.** Empty library → the house persistence baseline. Missing
  hour-1 print → last history point. The program never crashes on a
  malformed case.

Stdlib only, deterministic, no network, no wall clock. ~0.08 s per case
(limit 8 s).

## Validation

On the kit's four practice cases, with release-day answers fetched once from
SullyGnome's public API (hour-1 values match the cases' known prints exactly,
all four):

| case | this entry | house baseline |
|------|-----------|----------------|
| p00 Wolverine | 0.309 | 0.744 |
| p01 Red Dead Redemption 2 | 0.142 | 0.287 |
| p02 God of War Ragnarök | 0.131 | 0.215 |
| p03 Spider-Man 2 | 0.182 | 0.303 |
| **mean** | **0.191** | **0.387** |

50.7% better than the baseline, better on every case. 90% coverage 0.957;
typical median miss 36% (baseline 90%). Leave-one-out over the 37
comparables of p00 (each launch forecast from the other 36): 0.407 overall,
0.214 on the 8 console-only launches. The final case's library is strictly
better than the practice libraries — it includes all four practice launches
as comparables.

Ideas tested and rejected (see BUILD-TRANSCRIPT.md): pre-release surge-ratio
similarity (hurt everywhere), a weight floor for huge hour-1 prints (hurt),
trimmed-mean medians (hurt), empirical-quantile spreads (worse than
parametric), equal-weight median (0.336 — the similarity weighting is what
makes the ensemble work).

## Files

- `main.py` — the entry. Reads `$MAKEFUN_INPUT_DIR` (else `/input`),
  writes `$MAKEFUN_OUTPUT_DIR` (else `/output`).
- `tests/test_main.py` — 16 tests: output schema on all practice cases,
  beats-baseline on every case, determinism (in-process and end-to-end),
  edge cases (empty library, missing hour-1 print, minimal case), and unit
  tests for the helpers.
- `tests/fixtures/` — the kit's four practice cases plus `answers.json`
  (SullyGnome release-day answers).
- `LICENSE` — MIT.

## Run

```sh
python3 -m unittest discover -s tests
MAKEFUN_INPUT_DIR=tests/fixtures MAKEFUN_OUTPUT_DIR=/tmp/out python3 main.py
```
