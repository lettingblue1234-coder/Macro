# Macro · 创业板/科创板 均线与量能监控

盯三件事：**MA20、MA40、成交量**，并把它们翻译成"站稳 / 贴线争夺 / 跌破 / 趋势证伪"这类能直接用于决策的状态。
逻辑来源与对应关系见 [`docs/logic.md`](docs/logic.md)。

零第三方依赖，只用 Python 3.10+ 标准库。

## 快速开始

```bash
python -m monitor.cli                 # 抓实时数据，打印+落盘
python -m monitor.cli --no-write      # 只看，不写文件
python -m monitor.cli --fixture tests/fixtures/sample_klines.json --no-write   # 离线演示
python tests/test_monitor.py          # 单测（离线）
```

输出：

* 终端表格 + 信号清单
* `reports/YYYY-MM-DD.md` —— Markdown 日报（含量能明细）
* `data/latest.json` —— 机器可读快照，下次运行会与它对比，额外输出**状态变化**

## 监控什么

默认盯 6 个标的（`config.json` 里改）：创业板指 399006、科创50 000688、创业板50 399673、
科创50ETF 588000、创业板ETF 159915、上证指数 000001。

每个标的计算：

* **MA20 / MA40**：均线值、收盘偏离百分比、均线自身 5 日斜率、连续站上/失守天数
* **量能**：成交量、VOL_MA5/10/20、量比（当日量 ÷ 前 5 日均量）、放量/平量/缩量
* **量价配合**：放量上涨 / 放量下跌 / 缩量反弹 / 缩量回调 …

## 状态判定

| 状态 | 条件 |
| --- | --- |
| `站稳` | 收盘高于均线 > `buffer_pct`，且连续 ≥ `hold_days` 天，且均线不向下 |
| `上方震荡` | 在均线上方但天数不够，尚未确认 |
| `贴线争夺` | 收盘距均线在 ±`buffer_pct` 以内 |
| `压制` | 在均线下方；距离 ≤ `near_pct` 时提示"逼近压力位，需放量突破" |
| `跌破` | 连续 ≥ `hold_days` 天收在均线下方 |

信号分三级：🟢 INFO / 🟡 WATCH / 🔴 ALERT。ALERT 只在**刚发生**时报（如当天确认失守），
之后降级为 WATCH，避免天天拉警报。

## 关键配置（`config.json`）

```jsonc
{
  "ma_windows": [20, 40],        // 要盯的均线，可加 [5, 10, 60]
  "hold_days": 3,                // 站稳/跌破需要连续几天确认
  "buffer_pct": 0.5,             // 贴线争夺的容差（%）
  "near_pct": 1.5,               // "逼近压力位"的距离阈值（%）
  "volume_surge_ratio": 1.2,     // 量比 ≥ 该值算放量
  "volume_shrink_ratio": 0.8,    // 量比 ≤ 该值算缩量
  "sources": ["eastmoney", "tencent"]
}
```

**启动位（重要）**：`watchlist` 里每个标的的 `anchor` 默认为 `null`。填上"上周三启动日"的最低价或收盘价后，
一旦价格跌回该位置就会报 ALERT —— 对应原文"再次回到启动位＝这轮趋势被证伪，考虑离场"。

```jsonc
{ "name": "创业板指", "code": "399006", "market": "sz", "anchor": 2680.5 }
```

上证指数还配了 `levels`（默认 3800，作者的加仓计划位），触及会提示。

## 自动化

`.github/workflows/market-monitor.yml` 每个交易日北京时间 **15:35** 自动运行：
跑监控 → 提交 `reports/` 和 `data/` 快照 → 出现 ALERT 时自动开 issue（GitHub 通知即预警推送）。
`.github/workflows/tests.yml` 在 push/PR 时跑离线单测。

> 数据源是东方财富 / 腾讯的公开接口，可能对海外 IP 有限制。若 GitHub runner 抓不到数据，
> 工作流会打 warning；本地或国内服务器上跑（`cron` + `python -m monitor.cli`）最稳。

## 结构

```
monitor/datasource.py   多源日线抓取（东财 → 腾讯回退）
monitor/indicators.py   纯函数指标：SMA、斜率、连续天数、量比
monitor/analyze.py      指标 → 状态 → 信号的规则层
monitor/report.py       终端表格 + Markdown 渲染
monitor/cli.py          入口、落盘、与上一交易日对比
tests/                  离线单测 + 合成 K 线生成器
```

## 免责声明

工具只做客观的均线与量能计算，不构成投资建议。
