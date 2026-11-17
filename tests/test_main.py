#!/usr/bin/env python3
"""Tests for the GTA VI Twitch CCU forecast entry.

Run from the repository root: python3 -m unittest discover -s tests

Fixtures: the kit's four practice cases (p00-p03.in) plus the release-day
answers (answers.json), fetched once from SullyGnome's public API; the
hour-1 value of each answer matches its case's known print exactly.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, ROOT)

import main  # noqa: E402

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# House baseline practice losses (computed with the same scorer; the mean
# 0.3871 matches the documented practice result for the starter).
BASELINE_LOSS = {"p00": 0.743671, "p01": 0.286813,
                 "p02": 0.214579, "p03": 0.303324}


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def load_answers():
    raw = load_fixture("answers.json")
    return {cid: {int(h): v for h, v in ans.items()}
            for cid, ans in raw.items()}


def pinball_loss(forecast, answers):
    items = []
    for row in forecast["hours"]:
        y = answers.get(row["hour"])
        if y is None:
            continue
        y = max(1, y)
        for tau, q in zip(LEVELS, row["q"]):
            d = math.log(y) - math.log(max(q, 1e-9))
            items.append(2 * max(tau * d, (tau - 1) * d))
    return sum(items) / len(items)


def assert_valid_output(test, result):
    """The output schema from competition.yaml, exactly."""
    test.assertEqual(set(result.keys()), {"hours"})
    test.assertEqual(len(result["hours"]), 23)
    seen = set()
    for row in result["hours"]:
        test.assertEqual(set(row.keys()), {"hour", "q"})
        test.assertIn(row["hour"], range(2, 25))
        test.assertNotIn(row["hour"], seen)
        seen.add(row["hour"])
        test.assertEqual(len(row["q"]), 5)
        for q in row["q"]:
            test.assertIsInstance(q, (int, float))
            test.assertTrue(math.isfinite(q))
            test.assertGreater(q, 0)
            test.assertLessEqual(q, 1e9)
        test.assertEqual(row["q"], sorted(row["q"]))
    test.assertEqual(seen, set(range(2, 25)))
    test.assertLessEqual(
        len(json.dumps(result, separators=(",", ":"))), 65536)


class TestForecast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.answers = load_answers()
        cls.cases = {cid: load_fixture(cid + ".in")
                     for cid in ("p00", "p01", "p02", "p03")}
        cls.forecasts = {cid: main.forecast_case(case)
                         for cid, case in cls.cases.items()}

    def test_output_schema_all_practice_cases(self):
        for cid, forecast in self.forecasts.items():
            with self.subTest(case=cid):
                assert_valid_output(self, forecast)

    def test_beats_baseline_on_every_practice_case(self):
        for cid, forecast in self.forecasts.items():
            with self.subTest(case=cid):
                loss = pinball_loss(forecast, self.answers[cid])
                self.assertLess(loss, BASELINE_LOSS[cid],
                                f"{cid} loss {loss:.4f} not below baseline "
                                f"{BASELINE_LOSS[cid]:.4f}")

    def test_mean_practice_loss(self):
        losses = [pinball_loss(f, self.answers[cid])
                  for cid, f in self.forecasts.items()]
        mean_loss = sum(losses) / len(losses)
        # Documented validation result is 0.1909; allow a small margin.
        self.assertLess(mean_loss, 0.30)
        self.assertLess(mean_loss, 0.3871)

    def test_median_shape_dips_then_rises(self):
        # The launch-day shape: an overnight dip after hour 1, then a rise
        # into the US unlocks and prime time. p02's median must dip below
        # the hour-1 print early and exceed it by the evening peak.
        forecast = self.forecasts["p02"]
        p1 = self.cases["p02"]["known"][0]["viewers"]
        med = {row["hour"]: row["q"][2] for row in forecast["hours"]}
        self.assertLess(med[4], p1)
        self.assertGreater(med[20], p1)
        self.assertGreater(med[20], med[4])

    def test_deterministic(self):
        first = main.forecast_case(self.cases["p01"])
        second = main.forecast_case(self.cases["p01"])
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))


class TestEndToEnd(unittest.TestCase):
    def test_cli_writes_one_out_per_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = os.path.join(tmp, "in")
            out_dir = os.path.join(tmp, "out")
            os.makedirs(in_dir)
            for cid in ("p00", "p02"):
                with open(os.path.join(FIXTURES, cid + ".in"), "rb") as src, \
                        open(os.path.join(in_dir, cid + ".in"), "wb") as dst:
                    dst.write(src.read())
            env = dict(os.environ, MAKEFUN_INPUT_DIR=in_dir,
                       MAKEFUN_OUTPUT_DIR=out_dir)
            proc = subprocess.run(
                [sys.executable, "-P", "-s",
                 os.path.join(ROOT, "main.py")],
                env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            for cid in ("p00", "p02"):
                with open(os.path.join(out_dir, cid + ".out")) as fh:
                    assert_valid_output(self, json.load(fh))
            # Byte-identical across two runs.
            first = {}
            for cid in ("p00", "p02"):
                with open(os.path.join(out_dir, cid + ".out"), "rb") as fh:
                    first[cid] = fh.read()
            proc = subprocess.run(
                [sys.executable, "-P", "-s",
                 os.path.join(ROOT, "main.py")],
                env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for cid in ("p00", "p02"):
                with open(os.path.join(out_dir, cid + ".out"), "rb") as fh:
                    self.assertEqual(fh.read(), first[cid])


class TestEdgeCases(unittest.TestCase):
    def test_empty_library_falls_back_to_persistence(self):
        case = {"game": {"name": "X", "twitch_id": "1"},
                "day_start": "2026-11-19T00:00:00Z",
                "levels": [0.05, 0.25, 0.5, 0.75, 0.95],
                "known": [{"hour": 1, "viewers": 1000}],
                "forecast": [], "history": [], "comparables": []}
        result = main.forecast_case(case)
        assert_valid_output(self, result)
        # Persistence: every median equals the hour-1 print.
        for row in result["hours"]:
            self.assertEqual(row["q"][2], 1000)

    def test_missing_known_uses_last_history_point(self):
        case = {"game": {"name": "X", "twitch_id": "1"},
                "day_start": "2026-11-19T00:00:00Z",
                "levels": [0.05, 0.25, 0.5, 0.75, 0.95],
                "known": [],
                "history": [{"at": "2026-11-19T00:00:00Z", "viewers": 500,
                             "channels": 10}],
                "comparables": []}
        result = main.forecast_case(case)
        assert_valid_output(self, result)
        for row in result["hours"]:
            self.assertEqual(row["q"][2], 500)

    def test_minimal_case_never_crashes(self):
        result = main.forecast_case({})
        assert_valid_output(self, result)

    def test_tiny_hour1_stays_valid(self):
        case = {"game": {"name": "X", "twitch_id": "1"},
                "day_start": "2026-11-19T00:00:00Z",
                "levels": [0.05, 0.25, 0.5, 0.75, 0.95],
                "known": [{"hour": 1, "viewers": 1}],
                "history": [], "comparables": []}
        result = main.forecast_case(case)
        assert_valid_output(self, result)


class TestHelpers(unittest.TestCase):
    def test_normal_ppf_known_values(self):
        self.assertAlmostEqual(main.normal_ppf(0.5), 0.0, places=9)
        self.assertAlmostEqual(main.normal_ppf(0.05), -1.6448536269514722,
                               places=6)
        self.assertAlmostEqual(main.normal_ppf(0.25), -0.6744897501960817,
                               places=6)
        self.assertAlmostEqual(main.normal_ppf(0.95), 1.6448536269514722,
                               places=6)
        self.assertAlmostEqual(main.normal_ppf(0.975), 1.959963984540054,
                               places=6)

    def test_weighted_quantile(self):
        pairs = [(1.0, 1.0), (2.0, 1.0), (3.0, 1.0), (4.0, 1.0)]
        self.assertEqual(main.weighted_quantile(pairs, 0.5), 2.0)
        self.assertEqual(main.weighted_quantile(pairs, 0.05), 1.0)
        self.assertEqual(main.weighted_quantile(pairs, 0.95), 4.0)
        heavy = [(1.0, 9.0), (100.0, 1.0)]
        self.assertEqual(main.weighted_quantile(heavy, 0.5), 1.0)
        self.assertEqual(main.weighted_quantile(heavy, 0.95), 100.0)

    def test_is_console_only(self):
        self.assertTrue(main.is_console_only("PS5 only"))
        self.assertTrue(main.is_console_only("Switch"))
        self.assertTrue(main.is_console_only("PS4"))
        self.assertFalse(main.is_console_only("PC, PS5, Xbox Series"))
        self.assertFalse(main.is_console_only("PC, Stadia, PS4/XB1"))

    def test_is_rolling_unlock(self):
        self.assertTrue(main.is_rolling_unlock(
            "Midnight local Oct 2, rolling; US at Eastern midnight."))
        self.assertTrue(main.is_rolling_unlock(
            "Consoles midnight local Feb 27."))
        self.assertFalse(main.is_rolling_unlock(
            "Single global unlock 10:00 UTC+8 = 2024-08-20T02:00Z."))
        self.assertFalse(main.is_rolling_unlock("unverified."))

    def test_comparable_tier(self):
        self.assertEqual(main.comparable_tier(
            "Early access 2023-06-01. Tier: early-access-contaminated."),
            "contaminated")
        self.assertEqual(main.comparable_tier(
            "unverified; F2P. Tier: weak."), "weak")
        self.assertEqual(main.comparable_tier(
            "Midnight local. Tier: comparable."), "comparable")

    def test_library_drops_bad_tiers_and_target_history(self):
        case = load_fixture("p00.in")
        library = main.build_library(case)
        names = [c["name"] for c, _ in library]
        self.assertNotIn(
            "Grand Theft Auto VI category before release "
            "(2026-08-27 extended-look premiere onward)", names)
        self.assertNotIn("Hogwarts Legacy", names)  # contaminated
        self.assertNotIn("Marvel Rivals", names)    # weak
        self.assertIn("Ghost of Y\u014dtei", names)  # console-only, rolling
        self.assertEqual(len(library), 26)


if __name__ == "__main__":
    unittest.main()
