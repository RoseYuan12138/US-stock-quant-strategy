"""
FMP API 基础客户端
- 统一认证、重试、限速
- 所有下载脚本共用此模块
"""
import os
import time
import threading
import requests

BASE_URL = "https://financialmodelingprep.com/stable"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

# 限速器：Premium = 750 calls/min，保守用 700
# _rate_lock 保证多线程安全，避免并发超速
_CALLS_PER_MIN = int(os.environ.get("FMP_RATE_LIMIT", "700"))
_MIN_INTERVAL = 60.0 / _CALLS_PER_MIN
_last_call_time = [0.0]
_rate_lock = threading.Lock()


def _rate_limit():
    with _rate_lock:
        now = time.time()
        elapsed = now - _last_call_time[0]
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_call_time[0] = time.time()


def get(endpoint, retries=3, **params):
    """单次 API 调用，带限速和指数退避重试"""
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise EnvironmentError("FMP_API_KEY not set. Run: export FMP_API_KEY=your_key")

    params["apikey"] = api_key
    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(retries):
        _rate_limit()
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 5
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            if isinstance(data, str) and "Restricted" in data:
                raise PermissionError(f"Endpoint restricted on current plan: {endpoint}")
            return data
        except PermissionError:
            raise
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)

    return []


def ensure_cache_dir(subdir=""):
    path = os.path.join(CACHE_DIR, subdir) if subdir else CACHE_DIR
    os.makedirs(path, exist_ok=True)
    return path
