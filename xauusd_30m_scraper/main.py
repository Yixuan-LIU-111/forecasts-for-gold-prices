"""CLI 入口：XAU/USD 30 分钟行情获取（新浪财经）。

用法：
    python -m xauusd_30m_scraper.main            # 单次拉取并落盘（默认）
    python -m xauusd_30m_scraper.main --once     # 同上
    python -m xauusd_30m_scraper.main --serve    # 定时循环拉取（Ctrl+C 退出）
    python -m xauusd_30m_scraper.main --serve --interval 15
    python -m xauusd_30m_scraper.main --show-bars --count 10
    python -m xauusd_30m_scraper.main --once --dry-run   # 不落盘

说明：相对导入，请以模块方式执行（python -m）。
"""

import argparse
import logging
import sys
from pathlib import Path

from . import config
from . import storage
from .models import Bar, Quote
from .scheduler import run_once, run_server

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _print_quote(q: Quote) -> None:
    print("\n=== XAU/USD 实时报价（新浪 hf_XAU）===\n")
    print(f"  品种    : {q.series_name} ({q.symbol})")
    print(f"  报价时间: {q.timestamp} (北京时间)")
    print(f"  最新价  : {q.last:.2f}")
    print(f"  卖价    : {q.ask}")
    print(f"  昨收    : {q.prev_close}")
    print(f"  行情高  : {q.high}   行情低: {q.low}")
    print(f"  拉取时间: {q.fetched_at}\n")


def _print_bars(bars: list, count: int) -> None:
    bars = [b for b in bars if b.completed][-count:] if count else [b for b in bars if b.completed]
    print(f"\n=== 最近 {len(bars)} 根 30 分钟 K 线 (window={config.PREDICT_WINDOW}) ===\n")
    print(f"  {'timestamp':<20} {'open':>10} {'high':>10} {'low':>10} {'close':>10} {'n':>4}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*4}")
    for b in bars:
        print(f"  {b.timestamp:<20} {b.open:>10.2f} {b.high:>10.2f} {b.low:>10.2f} {b.close:>10.2f} {b.count:>4}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="XAU/USD 30 分钟行情获取（数据源：新浪财经）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="单次拉取并落盘（默认）")
    mode.add_argument("--serve", action="store_true", help="定时循环拉取（Ctrl+C 退出）")
    parser.add_argument("--show-bars", action="store_true", help="打印最近 K 线")
    parser.add_argument("--count", type=int, default=10, help="--show-bars 显示的条数")
    parser.add_argument("--interval", type=int, default=config.POLL_INTERVAL_SECONDS,
                        help="--serve 轮询间隔（秒）")
    parser.add_argument("--dry-run", action="store_true", help="拉取但不落盘")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    args = parser.parse_args()

    setup_logging(args.log_level)

    if args.serve:
        try:
            run_server(poll_interval=args.interval)
        except KeyboardInterrupt:
            pass
        return

    # 默认 / --once
    try:
        quote, bar, agg = run_once(dry_run=args.dry_run)
    except Exception as e:
        print(f"拉取失败: {e}")
        sys.exit(1)

    _print_quote(quote)
    print(f"当前 30 分钟 bar: {bar.timestamp} | O={bar.open:.2f} H={bar.high:.2f} "
          f"L={bar.low:.2f} C={bar.close:.2f} | samples={bar.count} | completed={bar.completed}")

    if args.show_bars:
        _print_bars(agg.get_bars(), args.count)

    if not args.dry_run:
        print(f"已保存: {config.LATEST_QUOTE_FILE.name}, {config.LATEST_BAR_FILE.name}")
    else:
        print("(dry-run：未落盘)")


if __name__ == "__main__":
    main()
