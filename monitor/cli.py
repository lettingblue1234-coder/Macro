"""命令行入口：python -m monitor.cli --config config.json"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .analyze import LEVELS, SymbolReport, analyze
from .datasource import Bar, FetchError, fetch_daily
from .report import render_console, render_markdown


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bars_from_fixture(raw: list[dict[str, Any]]) -> list[Bar]:
    return [Bar(**row) for row in raw]


def collect(cfg: dict[str, Any], fixture: Path | None = None) -> list[SymbolReport]:
    fixtures: dict[str, list[dict[str, Any]]] = (
        json.loads(fixture.read_text(encoding="utf-8")) if fixture else {}
    )
    reports: list[SymbolReport] = []
    for item in cfg["watchlist"]:
        code, market = item["code"], item["market"]
        key = f"{market}{code}"
        try:
            if fixtures:
                bars, source = _bars_from_fixture(fixtures[key]), "fixture"
            else:
                bars, source = fetch_daily(
                    code,
                    market,
                    limit=cfg.get("history_days", 260),
                    sources=cfg.get("sources", ("eastmoney", "tencent")),
                )
        except (FetchError, KeyError) as exc:
            print(f"[warn] {item['name']}({key}) 跳过：{exc}", file=sys.stderr)
            continue
        reports.append(
            analyze(
                name=item["name"],
                code=code,
                market=market,
                bars=bars,
                cfg=cfg,
                anchor=item.get("anchor"),
                levels=item.get("levels"),
                source=source,
            )
        )
    return reports


def diff_against_previous(
    reports: list[SymbolReport], previous: dict[str, Any] | None
) -> list[str]:
    """只报告发生了状态切换的项——盯盘要的是『变化』而不是每天的快照。"""
    if not previous:
        return []
    prev_by_code = {r["code"]: r for r in previous.get("reports", [])}
    changes: list[str] = []
    for r in reports:
        old = prev_by_code.get(r.code)
        if not old or old.get("date") == r.date:
            continue
        for w, ma in sorted(r.mas.items()):
            old_status = (old.get("mas", {}).get(str(w)) or {}).get("status")
            if old_status and old_status != ma.status:
                changes.append(f"{r.name} MA{w}：{old_status} → {ma.status}")
        if old.get("vol_state") and old["vol_state"] != r.vol_state:
            changes.append(f"{r.name} 量能：{old['vol_state']} → {r.vol_state}")
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="创业板/科创板 MA20、MA40 与量能监控")
    ap.add_argument("--config", default="config.json", type=Path)
    ap.add_argument("--data-dir", default="data", type=Path, help="latest.json 存放目录")
    ap.add_argument("--report-dir", default="reports", type=Path, help="Markdown 日报目录")
    ap.add_argument("--fixture", type=Path, help="离线测试用的本地 K 线 JSON")
    ap.add_argument("--no-write", action="store_true", help="只打印，不落盘")
    ap.add_argument(
        "--fail-on-alert", action="store_true", help="出现 ALERT 时以退出码 2 结束"
    )
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    reports = collect(cfg, args.fixture)
    if not reports:
        print("没有拿到任何标的数据。", file=sys.stderr)
        return 1

    latest_path = args.data_dir / "latest.json"
    previous = (
        json.loads(latest_path.read_text(encoding="utf-8"))
        if latest_path.exists()
        else None
    )
    changes = diff_against_previous(reports, previous)

    console = render_console(reports)
    if changes:
        console += "\n\n---- 较上一交易日的状态变化 ----\n" + "\n".join(
            f"* {c}" for c in changes
        )
    print(console)

    md = render_markdown(reports)
    if changes:
        md += "\n## 较上一交易日的状态变化\n\n" + "\n".join(f"- {c}" for c in changes) + "\n"

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(summary).write_text(md, encoding="utf-8")

    if not args.no_write:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        args.report_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": reports[0].date,
            "changes": changes,
            "reports": [r.to_dict() for r in reports],
        }
        latest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (args.report_dir / f"{reports[0].date}.md").write_text(md, encoding="utf-8")

    worst = max((LEVELS[r.worst_level] for r in reports), default=0)
    if args.fail_on_alert and worst >= LEVELS["ALERT"]:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
