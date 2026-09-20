"""离线单测：指标数学 + 信号规则 + CLI 端到端（使用合成 K 线）。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor.analyze import analyze  # noqa: E402
from monitor.cli import collect, diff_against_previous, load_config  # noqa: E402
from monitor.datasource import Bar  # noqa: E402
from monitor.indicators import (  # noqa: E402
    classify_volume,
    last_sma,
    pct,
    price_volume_pattern,
    sma,
    slope_pct,
    streak_above,
    volume_ratio,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "sample_klines.json"


def bars_from(closes, volumes=None):
    vols = volumes or [1000.0] * len(closes)
    return [
        Bar(f"2026-01-{i + 1:02d}", c, c, c, c, v, c * v)
        for i, (c, v) in enumerate(zip(closes, vols))
    ]


class TestIndicators(unittest.TestCase):
    def test_sma_alignment(self):
        out = sma([1, 2, 3, 4, 5], 3)
        self.assertEqual(out[:2], [None, None])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[4], 4.0)

    def test_last_sma_insufficient(self):
        self.assertIsNone(last_sma([1, 2], 5))
        self.assertAlmostEqual(last_sma([1, 2, 3], 3), 2.0)

    def test_pct(self):
        self.assertAlmostEqual(pct(110, 100), 10.0)
        self.assertEqual(pct(1, 0), 0.0)

    def test_slope_pct(self):
        series = [None, None] + [float(v) for v in range(10, 20)]
        self.assertAlmostEqual(slope_pct(series, 5), pct(19, 14))

    def test_streak_above_positive_and_negative(self):
        closes = [10, 10, 10, 12, 13, 14]
        ma = sma(closes, 3)
        self.assertGreater(streak_above(closes, ma), 0)
        down = [14, 13, 12, 8, 7, 6]
        self.assertLess(streak_above(down, sma(down, 3)), 0)

    def test_volume_ratio_excludes_today(self):
        vols = [100.0, 100.0, 100.0, 100.0, 100.0, 200.0]
        self.assertAlmostEqual(volume_ratio(vols, 5), 2.0)
        self.assertIsNone(volume_ratio([1.0, 2.0], 5))

    def test_classify_and_pattern(self):
        self.assertEqual(classify_volume(1.5, 1.2, 0.8), "放量")
        self.assertEqual(classify_volume(0.5, 1.2, 0.8), "缩量")
        self.assertEqual(classify_volume(1.0, 1.2, 0.8), "平量")
        self.assertEqual(classify_volume(None, 1.2, 0.8), "数据不足")
        self.assertEqual(price_volume_pattern(-1.0, "放量"), "放量下跌")
        self.assertEqual(price_volume_pattern(1.0, "缩量"), "缩量反弹")


CFG = {
    "ma_windows": [20, 40],
    "hold_days": 3,
    "buffer_pct": 0.5,
    "near_pct": 1.5,
    "volume_ratio_window": 5,
    "volume_surge_ratio": 1.2,
    "volume_shrink_ratio": 0.8,
    "slope_lookback": 5,
}


class TestSignals(unittest.TestCase):
    def test_hold_above_ma20(self):
        closes = [100.0] * 40 + [101.0, 103.0, 105.0, 107.0]
        r = analyze("测试", "000000", "sh", bars_from(closes), CFG)
        self.assertEqual(r.mas[20].status, "站稳")
        self.assertTrue(any(s.code == "MA20_HOLD" for s in r.signals))

    def test_broken_ma_raises_alert(self):
        closes = [100.0] * 40 + [96.0, 94.0, 92.0]
        r = analyze("测试", "000000", "sh", bars_from(closes), CFG)
        self.assertEqual(r.mas[20].status, "跌破")
        self.assertTrue(any(s.code == "MA20_LOST" and s.level == "ALERT" for s in r.signals))

    def test_anchor_break_is_alert(self):
        closes = [100.0] * 44
        r = analyze("测试", "000000", "sh", bars_from(closes), CFG, anchor=101.0)
        alerts = [s for s in r.signals if s.code == "ANCHOR_BROKEN"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, "ALERT")

    def test_volume_surge_down_is_alert(self):
        closes = [100.0] * 43 + [95.0]
        vols = [1000.0] * 43 + [3000.0]
        r = analyze("测试", "000000", "sh", bars_from(closes, vols), CFG)
        self.assertEqual(r.pv_pattern, "放量下跌")
        self.assertTrue(any(s.code == "VOL_DOWN" and s.level == "ALERT" for s in r.signals))
        self.assertEqual(r.worst_level, "ALERT")

    def test_level_watch(self):
        closes = [3900.0] * 43 + [3790.0]
        r = analyze(
            "上证指数", "000001", "sh", bars_from(closes), CFG,
            levels=[{"price": 3800, "note": "加仓计划位"}],
        )
        self.assertTrue(any(s.code == "LEVEL_REACHED" for s in r.signals))


class TestEndToEnd(unittest.TestCase):
    def test_collect_with_fixture(self):
        cfg = load_config(ROOT / "config.json")
        reports = collect(cfg, FIXTURE)
        self.assertEqual(len(reports), len(cfg["watchlist"]))
        for r in reports:
            self.assertIn(20, r.mas)
            self.assertIn(40, r.mas)
            self.assertIsNotNone(r.mas[40].value)
            self.assertIsNotNone(r.vol_ratio)
            json.dumps(r.to_dict(), ensure_ascii=False)  # 必须可序列化

    def test_diff_detects_status_change(self):
        cfg = load_config(ROOT / "config.json")
        reports = collect(cfg, FIXTURE)
        previous = {
            "date": "1999-01-01",
            "reports": [
                {
                    "code": reports[0].code,
                    "date": "1999-01-01",
                    "vol_state": "缩量" if reports[0].vol_state != "缩量" else "放量",
                    "mas": {"20": {"status": "上一状态占位"}},
                }
            ],
        }
        changes = diff_against_previous(reports, previous)
        self.assertTrue(any("MA20" in c for c in changes))
        self.assertTrue(any("量能" in c for c in changes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
