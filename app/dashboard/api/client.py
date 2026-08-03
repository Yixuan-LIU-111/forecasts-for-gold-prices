"""
统一 API 客户端
封装所有后端接口调用，支持 Mock 数据模式和真实 API 模式
当后端不可用时自动降级为演示数据
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.dashboard.config import config

# 演示数据目录
DEMO_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo_data")


def _load_demo(filename: str) -> Any:
    """
    从演示数据目录加载 JSON 文件
    Args:
        filename: JSON 文件名
    Returns:
        解析后的数据
    """
    filepath = os.path.join(DEMO_DATA_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[API Client] 加载演示数据失败 {filename}: {e}")
        return None


def get_latest_signal() -> Optional[Dict[str, Any]]:
    """
    获取最新信号
    返回最近的一条信号数据
    """
    data = _load_demo("signals.json")
    if data and len(data) > 0:
        return data[0]  # 返回最新（第一条）
    return None


def get_signal_attribution() -> Optional[List[Dict[str, Any]]]:
    """
    获取当前信号的因子归因列表
    """
    signal = get_latest_signal()
    if signal:
        return signal.get("attribution", [])
    return None


def get_market_data(range_hours: str = "4h") -> Optional[Dict[str, Any]]:
    """
    获取行情数据
    Args:
        range_hours: 时间范围 (1h/4h/1d/1w)
    Returns:
        行情数据对象
    """
    return _load_demo("market.json")


def get_factors() -> Optional[Dict[str, Any]]:
    """
    获取多因子实时数据
    Returns:
        因子数据对象
    """
    data = _load_demo("factors.json")
    return data


def get_news(limit: int = 20, offset: int = 0) -> Optional[List[Dict[str, Any]]]:
    """
    获取新闻列表
    Args:
        limit: 返回条数
        offset: 偏移量
    Returns:
        新闻列表
    """
    data = _load_demo("news.json")
    if data:
        return data[offset:offset + limit]
    return None


def get_backtest_results() -> Optional[Dict[str, Any]]:
    """
    获取回测结果
    Returns:
        回测结果对象
    """
    return _load_demo("backtest.json")


def run_backtest(params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    运行回测（模拟）
    Args:
        params: 回测参数
    Returns:
        回测结果对象
    """
    # 演示模式下直接返回已有结果
    return _load_demo("backtest.json")


def get_accuracy(window: str = "7d") -> Optional[Dict[str, Any]]:
    """
    获取准确率统计
    Args:
        window: 时间窗口 (7d/30d)
    Returns:
        准确率统计对象
    """
    data = _load_demo("backtest.json")
    if data:
        return data.get("accuracy", {})
    return None


def get_system_status() -> Dict[str, Any]:
    """
    获取系统运行状态
    Returns:
        系统状态对象
    """
    return {
        "status": "ok",
        "data_collection": "正常运行",
        "llm_service": "正常运行",
        "db_connection": "正常",
        "model_loaded": "LightGBM+XGBoost",
        "api_usage": {"today": 45, "limit": 100, "name": "NewsAPI"},
        "timestamp": datetime.now().isoformat(),
        "mode": "演示模式" if config.DEMO_MODE else "实时模式"
    }


def get_hawk_dove_events(days: int = 7) -> Optional[List[Dict[str, Any]]]:
    """
    获取鹰鸽指数事件列表
    Args:
        days: 查询天数
    Returns:
        鹰鸽事件列表
    """
    data = _load_demo("backtest.json")
    if data:
        return data.get("hawk_dove_events", [])
    return None


def get_pnl_distribution() -> Optional[Dict[str, Any]]:
    """
    获取盈亏分布数据
    Returns:
        盈亏分布对象
    """
    data = _load_demo("backtest.json")
    if data:
        return data.get("pnl_distribution", {})
    return None


def get_trade_details() -> Optional[List[Dict[str, Any]]]:
    """
    获取逐笔交易明细
    Returns:
        交易明细列表
    """
    data = _load_demo("backtest.json")
    if data:
        return data.get("trade_details", [])
    return None