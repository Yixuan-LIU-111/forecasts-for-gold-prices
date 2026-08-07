"""
API 连通性诊断：仅发 1 条最小请求，验证 base_url + api_key 是否可用。
用法：
    cd "/Users/echo/Desktop/forecasts for gold prices"
    news_scraper_llm/.venv/bin/python news_scraper_llm/diag_api.py
"""
import json
import os
import urllib.request
import urllib.error

# 读取与 config.py 相同的 .env（绝对路径，避免 cwd 影响）
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _mask(s):
    if not s:
        return "(空)"
    if len(s) <= 10:
        return "****"
    return s[:6] + "..." + s[-4:]


def main():
    env = _load_env(_ENV_PATH)
    api_key = env.get("OPENAI_API_KEY", "")
    base_url = env.get("OPENAI_BASE_URL", "").rstrip("/")
    model = env.get("OPENAI_MODEL", "qwen-turbo")

    print(f"[DIAG] base_url = {base_url}")
    print(f"[DIAG] model    = {model}")
    print(f"[DIAG] api_key  = {_mask(api_key)} (len={len(api_key)})")

    if not api_key or api_key == "your-dashscope-api-key-here":
        print("[FAIL] API Key 未填写或仍是占位符，请在 .env 填入真实 key。")
        return
    if not base_url:
        print("[FAIL] base_url 为空。")
        return

    url = base_url + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "用一句话回复：ok"}],
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", "replace")
        print(f"[DIAG] HTTP 状态 = {status}")
        # 尝试抽取 content
        try:
            content = json.loads(body)["choices"][0]["message"]["content"]
            print(f"[OK] 模型返回: {content!r}")
        except Exception:
            print(f"[OK-ish] 状态码正常，返回前 800 字符:\n{body[:800]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"[FAIL] HTTP {e.code}")
        print(body[:800])
    except Exception as e:
        print(f"[FAIL] 请求异常: {e!r}")


if __name__ == "__main__":
    main()
