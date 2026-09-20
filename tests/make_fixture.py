"""生成确定性的合成 K 线，用于离线自测（无需联网）。"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

SYMBOLS = {
    "sz399006": (2400.0, 1.0),
    "sh000688": (1100.0, 1.2),
    "sz399673": (2600.0, 1.0),
    "sh588000": (1.20, 1.1),
    "sz159915": (2.30, 1.0),
    "sh000001": (3600.0, 0.4),
}


def build(base: float, amp: float, n: int = 140) -> list[dict]:
    """先趋势上行、再回落到 20/40 日线附近，制造压力位争夺的形态。"""
    start = date(2026, 3, 2)
    bars = []
    day = start
    for i in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        trend = base * (1 + 0.0035 * min(i, 100) - 0.0055 * max(0, i - 100))
        wave = base * amp * 0.004 * math.sin(i / 4.0)
        close = round(trend + wave, 4)
        openp = round(close * (1 - 0.0015 * math.cos(i / 3.0)), 4)
        high = round(max(openp, close) * 1.004, 4)
        low = round(min(openp, close) * 0.996, 4)
        vol = round(1_000_000 * (1 + 0.35 * math.sin(i / 6.0)) + (300_000 if i >= n - 2 else 0), 2)
        bars.append(
            {
                "date": day.isoformat(),
                "open": openp,
                "close": close,
                "high": high,
                "low": low,
                "volume": vol,
                "amount": round(vol * close * 100, 2),
            }
        )
        day += timedelta(days=1)
    return bars


def main() -> None:
    out = {sym: build(base, amp) for sym, (base, amp) in SYMBOLS.items()}
    path = Path(__file__).parent / "fixtures" / "sample_klines.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({sum(len(v) for v in out.values())} bars)")


if __name__ == "__main__":
    main()
