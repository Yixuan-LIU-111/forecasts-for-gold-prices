#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用阿里云百炼(DashScope)「免费大模型」qwen-turbo 的调用示例
============================================================

要点：
1. 通过阿里云 OpenAI 兼容接口 /chat/completions 发送完整 HTTP 请求。
2. API Key 从环境变量 DASHSCOPE_API_KEY 读取，遵守安全规范，不硬编码明文。
3. 覆盖：网络异常、HTTP 错误、鉴权失败(401/403)、返回结构异常等错误处理。
4. 可直接运行（需先 pip install requests 并设置环境变量）。

免费模型说明：
- qwen-turbo：阿里云百炼每月赠送 100 万 token 免费额度，适合分类/摘要/打分类任务。
- 如需更强能力可换 qwen-plus / qwen-max（按量计费，非免费）。

运行方式：
    export DASHSCOPE_API_KEY="你的阿里云API Key"
    pip install requests
    python ali_dashscope_free_llm_example.py
"""

import os
import sys

import requests  # pip install requests

# ---------------------------------------------------------------------------
# 配置参数
# ---------------------------------------------------------------------------
# 阿里云百炼 OpenAI 兼容模式基础地址（在此之上拼接 /chat/completions）
BASE_URL = "https://ws-1h7z52vtt1oj8b3p.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"

# 使用的免费模型名称
MODEL = "qwen-turbo"

# 单次请求超时时间（秒）
TIMEOUT = 30

# 采样温度：0 表示确定性输出，最适合情感打分/分类等需要稳定结果的任务
TEMPERATURE = 0.0

# 限制模型单次回复的最大 token 数（按需调整）
MAX_TOKENS = 512


def get_api_key() -> str:
    """从环境变量读取 API Key；缺失则抛出可读错误，避免把密钥写进代码。"""
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError(
            "未找到环境变量 DASHSCOPE_API_KEY。\n"
            "请先执行: export DASHSCOPE_API_KEY='你的阿里云API Key'"
        )
    return key


def call_qwen_turbo(prompt: str, temperature: float = TEMPERATURE) -> str:
    """调用 qwen-turbo 并返回模型文本回复。

    Args:
        prompt:      用户输入的提示词（本例为新闻情感分析示例）。
        temperature: 采样温度，0 更确定、1 更发散。

    Returns:
        模型生成的文本内容（str）。

    Raises:
        RuntimeError:   网络异常 / HTTP>=400 / 返回非 JSON / 结构异常。
        PermissionError: HTTP 401/403 鉴权失败。
    """
    url = f"{BASE_URL}/chat/completions"

    # Bearer 认证头：使用环境变量中的 API Key 进行鉴权
    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
    }

    # 请求体：遵循 OpenAI Chat Completions 格式
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": MAX_TOKENS,
    }

    # ---- 1) 发送请求：捕获网络层异常 ----
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        raise RuntimeError("请求超时，请检查网络或调大 TIMEOUT。")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("网络连接失败，请确认能否访问 dashscope.aliyuncs.com。")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"请求发生未知异常: {e}")

    # ---- 2) 鉴权失败：401/403 ----
    if resp.status_code in (401, 403):
        raise PermissionError(
            f"鉴权失败 (HTTP {resp.status_code})：API Key 无效或权限不足，"
            f"请检查 DASHSCOPE_API_KEY 是否正确、账户是否有 qwen-turbo 调用权限。"
        )

    # ---- 3) 其它 HTTP 错误 ----
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP 错误 {resp.status_code}：{resp.text[:300]}")

    # ---- 4) 解析 JSON 返回 ----
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"返回内容不是合法 JSON：{resp.text[:300]}")

    # ---- 5) 按 OpenAI 兼容结构提取文本 ----
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"返回结构异常 ({e})；原始响应：{data}")

    return content


def main() -> None:
    # 示例提示词：可直接替换为你的新闻情感分析 prompt
    prompt = (
        "你是一名金融新闻情感分析助手。请判断下面这条新闻对黄金价格的影响情感，"
        "仅用一句话回答，并给出 -1~+1 之间的数值评分。\n"
        "新闻：美联储宣布维持利率不变，但暗示年内可能加息一次。"
    )
    try:
        answer = call_qwen_turbo(prompt)
        print("模型回复：\n", answer)
    except (RuntimeError, PermissionError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
