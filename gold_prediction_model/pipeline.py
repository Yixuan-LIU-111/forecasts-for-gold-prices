"""端到端主流程 —— 行情采集 → 预处理 → 训练/评估 → 预测 → 产出。

一键运行：
    python pipeline.py                 # 默认：采集→预处理→训练→预测→落盘
    python pipeline.py --mode train    # 仅训练并保存模型
    python pipeline.py --mode predict  # 载入已训练模型做推理
    python pipeline.py --tune          # 训练前先做 AutoML 调参
    python pipeline.py --refresh       # 强制重新拉取行情
    python pipeline.py --schedule --interval 86400   # 定时循环运行

产出（位于 reports/ 与 artifacts/）：
    - logs/pipeline_<时间戳>.log      结构化运行日志
    - data/features_standard.csv      标准特征底表
    - reports/predictions_<tag>.csv   全量预测（概率/方向）
    - artifacts/<tag>_*.joblib        序列化模型 + 元信息
    - reports/pipeline_result_<tag>.json  运行结果汇总
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import collector as CL
import config as C
import model as M
import preprocess as PP
import sentiment_features as SF

LOG = logging.getLogger("pipeline")


def setup_logging(level: int = logging.INFO) -> Path:
    """控制台 + 文件双通道日志。"""
    log_dir = C.MODEL_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"pipeline_{ts}.log"

    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.handlers = [fh, sh]  # 重置，避免重复 handler
    return log_path


def run_once(args) -> dict:
    """执行一次完整流程（供调度器复用）。"""
    log_path = setup_logging()
    LOG.info("════════ 端到端流程启动 (mode=%s) ════════", args.mode)

    # ---------- 1) 采集 ----------
    collector = CL.MarketCollector()
    gold, macro = collector.collect_all(refresh_gold=args.refresh,
                                        refresh_macro=args.refresh)

    # ---------- 1.5) LLM 情感 / 鹰鸽特征 ----------
    sent_frame, sent_meta = None, None
    if not args.no_sentiment:
        LOG.info("▶ 构建 LLM 情感 / 鹰鸽特征（provider=%s）…", args.llm_provider)
        sent_frame, sent_meta = SF.build_sentiment_features(
            gold["date"], news_dir=args.news_dir, provider=args.llm_provider,
            use_cache=not args.refresh_news)
        LOG.info("   情感特征: %s", json.dumps(_trim(sent_meta), ensure_ascii=False, default=str))
    else:
        LOG.info("▶ 已禁用情感特征（--no-sentiment），按文档降级为宏观-only")

    # ---------- 2) 预处理 ----------
    feats = PP.run(gold, macro, horizon=args.horizon, sentiment=sent_frame, save=True)

    # ---------- 3) 训练 / 评估 ----------
    if args.mode in ("all", "train"):
        model = M.GoldDirectionModel(feature_set=args.feature_set, tag=args.tag)
        if args.tune:
            LOG.info("▶ AutoML 调参（特征集→lr→复杂度→采样→L1/L2）…")
            model.tune(feats)
        model.fit(feats)
        model.save()
        train_summary = {
            "horizon_minutes": model.horizon_minutes,
            "target": model.target_description,
            "horizon_bars": args.horizon,
            "feature_set": model.feature_set,
            "n_estimators": model.n_estimators,
            "cv_auc": round(model.cv_auc, 4) if model.cv_auc else None,
            "test_metrics": {k: round(v, 4) for k, v in model.test_metrics.items()},
            "naive_acc": round(model.naive_acc, 4),
            "excess_accuracy": round(model.test_metrics["accuracy"] - model.naive_acc, 4),
        }
        LOG.info("训练完成: %s", json.dumps(train_summary, ensure_ascii=False))

        # 情感消融：同一份数据上训练「宏观-only」基线，对比测试指标
        sentiment_in = sent_frame is not None and any(
            c in feats.columns for c in C.FEATURES_SENTIMENT)
        ablation = None
        if sentiment_in and args.feature_set == "full_stat_sent":
            base = M.GoldDirectionModel(feature_set="full_stat",
                                        tag=f"{args.tag}_macro_only")
            base.fit(feats)
            ablation = {
                "with_sentiment": {k: round(v, 4) for k, v in model.test_metrics.items()},
                "macro_only": {k: round(v, 4) for k, v in base.test_metrics.items()},
                "naive_acc": round(model.naive_acc, 4),
                "auc_delta": round(model.test_metrics["auc"] - base.test_metrics["auc"], 4),
                "acc_delta": round(model.test_metrics["accuracy"] - base.test_metrics["accuracy"], 4),
            }
            LOG.info("情感消融: %s", json.dumps(ablation, ensure_ascii=False))
    else:
        model = M.GoldDirectionModel.load(tag=args.tag)
        LOG.info("已载入模型 %s（CV_AUC=%.4f）", args.tag,
                 model.cv_auc if model.cv_auc else float("nan"))
        train_summary = None
        ablation = None

    # ---------- 4) 预测推理 ----------
    preds = model.predict(feats)
    out = feats[["date", "close", "target"]].copy()
    out = out.rename(columns={"target": "true_up"})
    out["proba_up"] = preds["proba_up"].values
    out["pred_class"] = preds["pred_class"].values
    out["direction"] = preds["direction"].values
    out["horizon_minutes"] = preds["horizon_minutes"].values
    pred_path = C.REPORT_DIR / f"predictions_{args.tag}.csv"
    out.to_csv(pred_path, index=False)
    LOG.info("预测结果已保存: %s（%d 行）", pred_path, len(out))

    # ---------- 5) 结果汇总 ----------
    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "log_file": str(log_path),
        "prediction_target": {
            "description": C.PREDICTION_TARGET,
            "horizon_minutes": C.TARGET_HORIZON_MINUTES,
            "design_bar_interval_minutes": C.DESIGN_BAR_INTERVAL_MINUTES,
            "actual_bar_interval_minutes": C.ACTUAL_BAR_INTERVAL_MINUTES,
        },
        "data": {
            "gold_rows": int(len(gold)),
            "macro_rows": int(len(macro)),
            "feature_rows": int(len(feats)),
            "date_range": [str(feats["date"].min().date()),
                           str(feats["date"].max().date())],
        },
        "sentiment_features": _trim(sent_meta) if sent_meta else {"enabled": False},
        "train": train_summary,
        "sentiment_ablation": ablation,
        "latest_prediction": {
            "date": str(out["date"].iloc[-1].date()),
            "close": float(out["close"].iloc[-1]),
            "proba_up": round(float(out["proba_up"].iloc[-1]), 4),
            "direction": out["direction"].iloc[-1],
            "horizon_minutes": int(out["horizon_minutes"].iloc[-1]),
        },
        "predictions_sample": out.tail(5).to_dict(orient="records"),
    }
    res_path = C.REPORT_DIR / f"pipeline_result_{args.tag}.json"
    res_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    LOG.info("结果汇总已保存: %s", res_path)
    LOG.info("最新预测: %s", result["latest_prediction"])
    LOG.info("════════ 端到端流程结束 ════════\n")
    return result


def _trim(meta: dict | None) -> dict:
    """精简 meta 以便日志/JSON 输出（去除超长字段）。"""
    if not meta:
        return {}
    return {k: v for k, v in meta.items() if k not in ("cached_to",)}


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="黄金价格方向预测 —— 端到端流程（采集→预处理→训练→预测）")
    p.add_argument("--mode", choices=("all", "train", "predict"), default="all",
                   help="运行模式：all=全链路, train=仅训练, predict=仅推理")
    p.add_argument("--horizon", type=int, default=C.HORIZON,
                   help=f"预测跨度（bar 数，默认 {C.HORIZON}，与文档 shift(-30) 对齐；"
                        f"目标=未来 {C.TARGET_HORIZON_MINUTES} 分钟")
    p.add_argument("--feature-set", default=C.PRIMARY_FEATURE_SET,
                   help="特征组: p0_doc / full / p0_stat / full_stat / full_stat_sent")
    p.add_argument("--tag", default="primary",
                   help="模型标签（影响产物文件名）")
    p.add_argument("--refresh", action="store_true",
                   help="强制重新拉取行情（忽略本地缓存）")
    p.add_argument("--no-sentiment", action="store_true",
                   help="禁用 LLM 情感/鹰鸽特征（按文档降级为宏观-only）")
    p.add_argument("--news-dir", default=str(C.NEWS_DIR),
                   help="新闻数据目录（news_scraper_llm 输出）")
    p.add_argument("--llm-provider", default=C.LLM_PROVIDER,
                   choices=("openai", "ollama", "rule"),
                   help="情感/鹰鸽提取方式：openai/ollama/rule（默认 rule 降级）")
    p.add_argument("--refresh-news", action="store_true",
                   help="重新构建情感特征（忽略情感缓存）")
    p.add_argument("--tune", action="store_true",
                   help="训练前执行 AutoML 调参")
    p.add_argument("--schedule", action="store_true",
                   help="定时循环运行（配合 --interval）")
    p.add_argument("--interval", type=float, default=86400,
                   help="定时模式下的拉取间隔（秒，默认 86400=1天）")
    p.add_argument("--verbose", action="store_true", help="DEBUG 日志")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.schedule:
        setup_logging(logging.DEBUG if args.verbose else logging.INFO)
        LOG.info("进入定时模式：每 %.0f 秒运行一次（Ctrl+C 退出）", args.interval)
        scheduler = CL.Scheduler(lambda: run_once(args), interval_sec=args.interval)
        try:
            scheduler.start()
            while scheduler._thread.is_alive():
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop()
            LOG.info("用户中断，调度器已停止")
        return
    return run_once(args)


if __name__ == "__main__":
    main()
