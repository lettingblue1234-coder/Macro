"""纯函数指标计算，不依赖网络，便于单测。"""

from __future__ import annotations

from typing import Sequence


def sma(values: Sequence[float], window: int) -> list[float | None]:
    """简单移动平均；前 window-1 项为 None。"""
    if window <= 0:
        raise ValueError("window 必须为正整数")
    out: list[float | None] = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        out.append(running / window if i >= window - 1 else None)
    return out


def last_sma(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def pct(a: float, b: float) -> float:
    """a 相对 b 的百分比偏离。"""
    if b == 0:
        return 0.0
    return (a - b) / b * 100.0


def slope_pct(series: Sequence[float | None], lookback: int = 5) -> float | None:
    """均线自身的斜率：最新值相对 lookback 根之前的百分比变化。"""
    clean = [v for v in series if v is not None]
    if len(clean) <= lookback:
        return None
    return pct(clean[-1], clean[-1 - lookback])


def streak_above(closes: Sequence[float], ma_series: Sequence[float | None]) -> int:
    """连续收盘站在均线上方的天数；若最新收盘在均线下方则返回负的连续天数。"""
    n = min(len(closes), len(ma_series))
    if n == 0:
        return 0
    idx = n - 1
    if ma_series[idx] is None:
        return 0
    above = closes[idx] >= ma_series[idx]
    count = 0
    while idx >= 0 and ma_series[idx] is not None and (closes[idx] >= ma_series[idx]) == above:
        count += 1
        idx -= 1
    return count if above else -count


def volume_ratio(volumes: Sequence[float], window: int = 5) -> float | None:
    """量比：最新成交量 / 前 window 日均量（不含当日）。"""
    if len(volumes) < window + 1:
        return None
    base = sum(volumes[-window - 1 : -1]) / window
    if base == 0:
        return None
    return volumes[-1] / base


def classify_volume(ratio: float | None, surge: float, shrink: float) -> str:
    if ratio is None:
        return "数据不足"
    if ratio >= surge:
        return "放量"
    if ratio <= shrink:
        return "缩量"
    return "平量"


def price_volume_pattern(chg_pct: float, vol_state: str) -> str:
    """量价配合的定性判断——对应作者说的『放量上涨才算站稳』。"""
    up = chg_pct > 0
    if vol_state == "放量":
        return "放量上涨" if up else "放量下跌"
    if vol_state == "缩量":
        return "缩量反弹" if up else "缩量回调"
    return "平量上涨" if up else "平量下跌"
