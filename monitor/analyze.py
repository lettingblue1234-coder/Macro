"""把指标翻译成交易语言：站稳 / 跌破 / 证伪 / 量能配合。

规则来自 docs/logic.md 里拆解的那套框架：
  · 20 日线、40 日线是反弹的主要压力位，需要"站稳"而不是"摸到"
  · 摸到压力位后回落到启动位 → 趋势证伪，考虑离场
  · 站稳要放量确认；缩量上涨只算反弹不算变盘
  · 跌破启动位/关键点位 → 去更低位置寻底
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .datasource import Bar
from .indicators import (
    classify_volume,
    last_sma,
    pct,
    price_volume_pattern,
    slope_pct,
    sma,
    streak_above,
    volume_ratio,
)

LEVELS = {"INFO": 0, "WATCH": 1, "ALERT": 2}


@dataclass
class Signal:
    level: str
    code: str
    text: str

    def __str__(self) -> str:
        mark = {"INFO": "·", "WATCH": "!", "ALERT": "!!"}[self.level]
        return f"[{mark}] {self.text}"


@dataclass
class MaView:
    window: int
    value: float | None
    gap_pct: float | None       # 收盘价相对均线的偏离，正=在上方
    slope_pct: float | None     # 均线自身 5 日斜率
    streak: int                 # 连续站上(+)/跌破(-)天数
    status: str                 # 站稳 / 上方震荡 / 压制 / 跌破 / 数据不足


@dataclass
class SymbolReport:
    name: str
    code: str
    market: str
    date: str
    close: float
    chg_pct: float
    volume: float
    amount: float
    vol_ratio: float | None
    vol_state: str
    vol_ma5: float | None
    vol_ma10: float | None
    vol_ma20: float | None
    pv_pattern: str
    mas: dict[int, MaView]
    anchor: float | None
    anchor_gap_pct: float | None
    levels: list[dict[str, Any]] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    source: str = ""

    @property
    def worst_level(self) -> str:
        if not self.signals:
            return "INFO"
        return max((s.level for s in self.signals), key=lambda lv: LEVELS[lv])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mas"] = {str(k): asdict(v) for k, v in self.mas.items()}
        d["signals"] = [asdict(s) for s in self.signals]
        d["worst_level"] = self.worst_level
        return d


def _ma_status(
    gap: float | None, streak: int, slope: float | None, hold_days: int, buffer_pct: float
) -> str:
    if gap is None:
        return "数据不足"
    if gap > buffer_pct:
        if streak >= hold_days and (slope is None or slope >= 0):
            return "站稳"
        return "上方震荡"
    if gap >= -buffer_pct:
        return "贴线争夺"
    if streak <= -hold_days:
        return "跌破"
    return "压制"


def analyze(
    name: str,
    code: str,
    market: str,
    bars: list[Bar],
    cfg: dict[str, Any],
    anchor: float | None = None,
    levels: list[dict[str, Any]] | None = None,
    source: str = "",
) -> SymbolReport:
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    last = bars[-1]

    windows: list[int] = cfg.get("ma_windows", [20, 40])
    hold_days: int = cfg.get("hold_days", 3)
    buffer_pct: float = cfg.get("buffer_pct", 0.5)
    near_pct: float = cfg.get("near_pct", 1.5)
    surge: float = cfg.get("volume_surge_ratio", 1.2)
    shrink: float = cfg.get("volume_shrink_ratio", 0.8)

    chg_pct = pct(last.close, bars[-2].close) if len(bars) >= 2 else 0.0
    ratio = volume_ratio(volumes, cfg.get("volume_ratio_window", 5))
    vol_state = classify_volume(ratio, surge, shrink)

    mas: dict[int, MaView] = {}
    for w in windows:
        series = sma(closes, w)
        value = last_sma(closes, w)
        gap = pct(last.close, value) if value else None
        slope = slope_pct(series, cfg.get("slope_lookback", 5))
        streak = streak_above(closes, series)
        mas[w] = MaView(
            window=w,
            value=value,
            gap_pct=gap,
            slope_pct=slope,
            streak=streak,
            status=_ma_status(gap, streak, slope, hold_days, buffer_pct),
        )

    anchor_gap = pct(last.close, anchor) if anchor else None

    report = SymbolReport(
        name=name,
        code=code,
        market=market,
        date=last.date,
        close=last.close,
        chg_pct=chg_pct,
        volume=last.volume,
        amount=last.amount,
        vol_ratio=ratio,
        vol_state=vol_state,
        vol_ma5=last_sma(volumes, 5),
        vol_ma10=last_sma(volumes, 10),
        vol_ma20=last_sma(volumes, 20),
        pv_pattern=price_volume_pattern(chg_pct, vol_state),
        mas=mas,
        anchor=anchor,
        anchor_gap_pct=anchor_gap,
        levels=[
            {**lv, "gap_pct": pct(last.close, float(lv["price"]))}
            for lv in (levels or [])
        ],
        source=source,
    )
    report.signals = _build_signals(report, hold_days, buffer_pct, near_pct)
    return report


def _build_signals(
    r: SymbolReport, hold_days: int, buffer_pct: float, near_pct: float
) -> list[Signal]:
    out: list[Signal] = []

    for w, ma in sorted(r.mas.items()):
        if ma.value is None or ma.gap_pct is None:
            continue
        tag = f"MA{w}"

        if ma.status == "站稳":
            if r.vol_state == "缩量" and ma.streak == hold_days:
                out.append(
                    Signal(
                        "WATCH",
                        f"{tag}_HOLD_LOW_VOL",
                        f"{r.name} 连续 {ma.streak} 日站上 {tag}({ma.value:.2f})，"
                        f"但缩量({r.vol_ratio:.2f}倍)，站稳成色不足",
                    )
                )
            else:
                out.append(
                    Signal(
                        "INFO",
                        f"{tag}_HOLD",
                        f"{r.name} 站稳 {tag}({ma.value:.2f})，连续 {ma.streak} 日，"
                        f"偏离 +{ma.gap_pct:.2f}%",
                    )
                )
        elif ma.status == "上方震荡":
            out.append(
                Signal(
                    "INFO",
                    f"{tag}_ABOVE",
                    f"{r.name} 站上 {tag}({ma.value:.2f}) {ma.streak} 日，"
                    f"未满 {hold_days} 日确认",
                )
            )
        elif ma.status == "贴线争夺":
            out.append(
                Signal(
                    "WATCH",
                    f"{tag}_AT_LINE",
                    f"{r.name} 贴 {tag}({ma.value:.2f}) 争夺，偏离 {ma.gap_pct:+.2f}%，"
                    f"{r.pv_pattern}",
                )
            )
        elif ma.status == "压制":
            if abs(ma.gap_pct) <= near_pct:
                out.append(
                    Signal(
                        "WATCH",
                        f"{tag}_NEAR_RESIST",
                        f"{r.name} 逼近 {tag} 压力位({ma.value:.2f})，"
                        f"距离 {ma.gap_pct:+.2f}%，需放量突破",
                    )
                )
        elif ma.status == "跌破":
            # 刚确认失守才报 ALERT；之后降级为 WATCH，避免天天拉警报
            fresh = ma.streak == -hold_days
            out.append(
                Signal(
                    "ALERT" if fresh else "WATCH",
                    f"{tag}_LOST" if fresh else f"{tag}_STILL_LOST",
                    f"{r.name} {'今日确认失守' if fresh else '持续失守'} {tag}"
                    f"({ma.value:.2f})，已 {abs(ma.streak)} 日，偏离 {ma.gap_pct:+.2f}%",
                )
            )

    # 启动位 —— 摸到压力位后跌回启动位 = 趋势证伪
    if r.anchor and r.anchor_gap_pct is not None:
        if r.close <= r.anchor:
            out.append(
                Signal(
                    "ALERT",
                    "ANCHOR_BROKEN",
                    f"{r.name} 跌回启动位 {r.anchor:.2f}（现价 {r.close:.2f}，"
                    f"{r.anchor_gap_pct:+.2f}%）——本轮趋势证伪，按计划考虑离场",
                )
            )
        elif r.anchor_gap_pct <= near_pct:
            out.append(
                Signal(
                    "WATCH",
                    "ANCHOR_NEAR",
                    f"{r.name} 回落至启动位 {r.anchor:.2f} 附近"
                    f"（+{r.anchor_gap_pct:.2f}%），反复考验的底大概率不是真底",
                )
            )

    # 自定义关键点位（如上证 3800 的加仓计划位）
    for lv in r.levels:
        price = float(lv["price"])
        note = lv.get("note", "关键位")
        gap = lv["gap_pct"]
        if r.close <= price:
            out.append(
                Signal(
                    "WATCH",
                    "LEVEL_REACHED",
                    f"{r.name} 触及 {note} {price:.0f}（现价 {r.close:.2f}，{gap:+.2f}%）",
                )
            )
        elif gap <= near_pct:
            out.append(
                Signal(
                    "INFO",
                    "LEVEL_NEAR",
                    f"{r.name} 距 {note} {price:.0f} 仅 {gap:+.2f}%",
                )
            )

    # 量能异动
    if r.vol_ratio is not None:
        if r.pv_pattern == "放量下跌":
            out.append(
                Signal(
                    "ALERT",
                    "VOL_DOWN",
                    f"{r.name} 放量下跌：量比 {r.vol_ratio:.2f}，跌 {r.chg_pct:.2f}%",
                )
            )
        elif r.pv_pattern == "放量上涨":
            out.append(
                Signal(
                    "INFO",
                    "VOL_UP",
                    f"{r.name} 放量上涨：量比 {r.vol_ratio:.2f}，涨 {r.chg_pct:.2f}%",
                )
            )
        elif r.pv_pattern == "缩量反弹" and r.chg_pct >= 1.0:
            out.append(
                Signal(
                    "WATCH",
                    "VOL_THIN_RALLY",
                    f"{r.name} 缩量反弹 {r.chg_pct:.2f}%（量比 {r.vol_ratio:.2f}），"
                    f"量价背离",
                )
            )
    return out
