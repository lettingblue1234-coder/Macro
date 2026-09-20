"""渲染：终端表格 + Markdown 日报。"""

from __future__ import annotations

from .analyze import LEVELS, SymbolReport

BADGE = {"INFO": "🟢", "WATCH": "🟡", "ALERT": "🔴"}


def _w(text: str) -> int:
    """按终端显示宽度计算：CJK 字符占 2 列。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _w(text))


def _fmt(v: float | None, digits: int = 2, suffix: str = "") -> str:
    return "—" if v is None else f"{v:.{digits}f}{suffix}"


def _vol_wan(v: float | None) -> str:
    """成交量（手）→ 万手。"""
    return "—" if v is None else f"{v / 10000:.0f}万手"


def render_console(reports: list[SymbolReport]) -> str:
    lines: list[str] = []
    date = reports[0].date if reports else ""
    lines.append(f"===== A股均线/量能监控  {date} =====")
    header = f"{_pad('标的', 12)}{'收盘':>9}{'涨跌%':>8}{'MA20':>9}{'距MA20':>9}{'MA40':>9}{'距MA40':>9}{'量比':>7}  状态"
    lines.append(header)
    lines.append("-" * len(header))
    for r in reports:
        ma20 = r.mas.get(20)
        ma40 = r.mas.get(40)
        lines.append(
            f"{_pad(r.name, 12)}"
            f"{r.close:>9.2f}"
            f"{r.chg_pct:>+8.2f}"
            f"{_fmt(ma20.value if ma20 else None):>9}"
            f"{_fmt(ma20.gap_pct if ma20 else None, suffix='%'):>9}"
            f"{_fmt(ma40.value if ma40 else None):>9}"
            f"{_fmt(ma40.gap_pct if ma40 else None, suffix='%'):>9}"
            f"{_fmt(r.vol_ratio):>7}"
            f"  {BADGE[r.worst_level]} {r.pv_pattern}"
        )
    lines.append("")
    lines.append("---- 信号 ----")
    any_signal = False
    for r in reports:
        for s in sorted(r.signals, key=lambda x: -LEVELS[x.level]):
            any_signal = True
            lines.append(f"{BADGE[s.level]} {s.text}")
    if not any_signal:
        lines.append("（无触发信号）")
    return "\n".join(lines)


def render_markdown(reports: list[SymbolReport]) -> str:
    date = reports[0].date if reports else ""
    src = reports[0].source if reports else ""
    out: list[str] = [f"# A股均线/量能监控 · {date}", "", f"数据源：{src}", ""]

    out += [
        "| 标的 | 收盘 | 涨跌 | MA20 | 距MA20 | MA20状态 | MA40 | 距MA40 | MA40状态 | 量比 | 量价 |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for r in reports:
        ma20 = r.mas.get(20)
        ma40 = r.mas.get(40)
        out.append(
            f"| {r.name} | {r.close:.2f} | {r.chg_pct:+.2f}% "
            f"| {_fmt(ma20.value if ma20 else None)} | {_fmt(ma20.gap_pct if ma20 else None, suffix='%')} "
            f"| {ma20.status if ma20 else '—'} "
            f"| {_fmt(ma40.value if ma40 else None)} | {_fmt(ma40.gap_pct if ma40 else None, suffix='%')} "
            f"| {ma40.status if ma40 else '—'} "
            f"| {_fmt(r.vol_ratio)} | {r.pv_pattern} |"
        )

    out += ["", "## 量能明细", "", "| 标的 | 成交量 | VOL_MA5 | VOL_MA10 | VOL_MA20 | 量比 | 判定 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for r in reports:
        out.append(
            f"| {r.name} | {_vol_wan(r.volume)} | {_vol_wan(r.vol_ma5)} | {_vol_wan(r.vol_ma10)} "
            f"| {_vol_wan(r.vol_ma20)} | {_fmt(r.vol_ratio)} | {r.vol_state} |"
        )

    out += ["", "## 信号", ""]
    rows = [
        (s, r)
        for r in reports
        for s in sorted(r.signals, key=lambda x: -LEVELS[x.level])
    ]
    if not rows:
        out.append("无触发信号。")
    for s, _r in sorted(rows, key=lambda t: -LEVELS[t[0].level]):
        out.append(f"- {BADGE[s.level]} **{s.level}** `{s.code}` — {s.text}")
    return "\n".join(out) + "\n"
