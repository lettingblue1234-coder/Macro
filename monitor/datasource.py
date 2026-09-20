"""日线行情抓取。

零依赖（只用标准库），按优先级在多个免费源之间回退：
    1. 东方财富 push2his   —— 指数/ETF 通用，字段最全
    2. 腾讯   web.ifzq.gtimg.cn —— 备用
两个源都返回统一的 Bar 列表，按日期升序。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Sequence

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


@dataclass(frozen=True)
class Bar:
    """一根日 K。volume 单位为手，amount 单位为元。"""

    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float


class FetchError(RuntimeError):
    pass


def _get(url: str, referer: str = "", timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:  # pragma: no cover - 网络分支
        raise FetchError(f"{url} 抓取失败: {exc}") from exc


# --------------------------------------------------------------------------- 东方财富


def _em_secid(code: str, market: str) -> str:
    """东财 secid：沪市/科创/沪指=1，深市/创业板=0。"""
    return f"{'1' if market == 'sh' else '0'}.{code}"


def fetch_eastmoney(code: str, market: str, limit: int = 260) -> list[Bar]:
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={_em_secid(code, market)}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57"
        f"&klt=101&fqt=1&end=20500101&lmt={limit}"
    )
    payload = json.loads(_get(url, referer="https://quote.eastmoney.com/"))
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        raise FetchError(f"东方财富未返回 {market}{code} 的 K 线数据")

    bars: list[Bar] = []
    for line in klines:
        # 日期,开,收,高,低,成交量(手),成交额(元)
        d, o, c, h, low, vol, amt = line.split(",")[:7]
        bars.append(
            Bar(
                date=d,
                open=float(o),
                close=float(c),
                high=float(h),
                low=float(low),
                volume=float(vol),
                amount=float(amt),
            )
        )
    return bars


# --------------------------------------------------------------------------- 腾讯


def fetch_tencent(code: str, market: str, limit: int = 260) -> list[Bar]:
    symbol = f"{market}{code}"
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},day,,,{limit},qfq"
    )
    payload = json.loads(_get(url, referer="https://gu.qq.com/"))
    node = (payload.get("data") or {}).get(symbol) or {}
    rows = node.get("qfqday") or node.get("day") or []
    if not rows:
        raise FetchError(f"腾讯未返回 {symbol} 的 K 线数据")

    bars: list[Bar] = []
    for row in rows:
        # 日期,开,收,高,低,成交量(手)
        d, o, c, h, low, vol = row[:6]
        bars.append(
            Bar(
                date=d,
                open=float(o),
                close=float(c),
                high=float(h),
                low=float(low),
                volume=float(vol),
                amount=0.0,  # 腾讯该接口不给成交额
            )
        )
    return bars


SOURCES: dict[str, Callable[..., list[Bar]]] = {
    "eastmoney": fetch_eastmoney,
    "tencent": fetch_tencent,
}


def fetch_daily(
    code: str,
    market: str,
    limit: int = 260,
    sources: Sequence[str] = ("eastmoney", "tencent"),
) -> tuple[list[Bar], str]:
    """按顺序尝试数据源，返回 (日线列表, 实际生效的源名)。"""
    errors: list[str] = []
    for name in sources:
        fetcher = SOURCES.get(name)
        if fetcher is None:
            errors.append(f"未知数据源 {name}")
            continue
        try:
            bars = fetcher(code, market, limit=limit)
        except FetchError as exc:
            errors.append(str(exc))
            continue
        if bars:
            return bars, name
    raise FetchError("所有数据源均失败:\n  " + "\n  ".join(errors))
