"""新浪 XAU/USD 实时报价 HTTP 客户端（带重试与超时）。

仅使用标准库 urllib，避免引入额外依赖；所有网络异常都被捕获并按
指数退避重试，最终仍失败则抛 FetchError 交上层处理。
"""

import logging
import time
import urllib.error
import urllib.request
from typing import Optional

from . import config
from .errors import FetchError

logger = logging.getLogger(__name__)


def _build_request() -> urllib.request.Request:
    return urllib.request.Request(
        config.SINA_QUOTE_URL,
        headers=config.REQUEST_HEADERS,
        method="GET",
    )


def fetch_quote_raw() -> str:
    """拉取原始行情串（含重试）。

    Returns:
        形如 ``var hq_str_hf_XAU="...";`` 的原始文本。

    Raises:
        FetchError: 重试耗尽仍失败，或返回内容为空 / 非预期。
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            req = _build_request()
            with urllib.request.urlopen(req, timeout=config.REQUEST_TIMEOUT) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                text = resp.read().decode(charset, errors="ignore")

            if not text or "hq_str" not in text:
                # 空响应（如未带 Referer 时新浪返回 ``var hq_str_hf_XAU="";``）
                raise FetchError(f"返回内容异常或为空: {text!r}")

            logger.debug("拉取成功 (attempt=%d), 长度=%d", attempt, len(text))
            return text

        except urllib.error.HTTPError as e:
            last_exc = e
            logger.warning("HTTP 错误 attempt=%d/%d: %s %s",
                           attempt, config.MAX_RETRIES, e.code, e.reason)
        except urllib.error.URLError as e:
            last_exc = e
            logger.warning("网络错误 attempt=%d/%d: %s", attempt, config.MAX_RETRIES, e.reason)
        except TimeoutError as e:
            last_exc = e
            logger.warning("超时 attempt=%d/%d: %s", attempt, config.MAX_RETRIES, e)
        except FetchError as e:
            last_exc = e
            logger.warning("内容校验失败 attempt=%d/%d: %s", attempt, config.MAX_RETRIES, e)
        except Exception as e:  # 兜底：任何意外都不应中断调度循环
            last_exc = e
            logger.warning("未知错误 attempt=%d/%d: %r", attempt, config.MAX_RETRIES, e)

        if attempt < config.MAX_RETRIES:
            delay = min(config.RETRY_BASE_DELAY * (2 ** (attempt - 1)), config.RETRY_MAX_DELAY)
            logger.info("%.1f 秒后重试…", delay)
            time.sleep(delay)

    raise FetchError(f"拉取 {config.SINA_QUOTE_URL} 失败（已重试 {config.MAX_RETRIES} 次）: {last_exc}")
