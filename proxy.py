"""
代理管理 - BestProxy socks5 代理获取和验活
"""
import uuid as uuid_mod
import requests
from config import PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS


def make_proxy_username(session_id):
    return f"{PROXY_USER}_life-30_session-{session_id}"


def get_proxies(session_id):
    username = make_proxy_username(session_id)
    proxy_url = f"socks5h://{username}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    return {"http": proxy_url, "https": proxy_url}


def get_proxies_with_check(max_retries=10):
    """获取一个验证通过的美国代理，返回 (proxies_dict, session_id)"""
    for attempt in range(max_retries):
        session_id = uuid_mod.uuid4().hex[:12]
        proxies = get_proxies(session_id)
        try:
            resp = requests.get(
                "http://ip-api.com/json/?fields=status,country,countryCode,query",
                proxies=proxies, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                ip = data.get("query", "unknown")
                country = data.get("countryCode", "")
                if country == "US":
                    print(f"  [代理] 美国IP验证通过: {ip} (尝试{attempt+1})")
                    return proxies, session_id
                else:
                    print(f"  [代理] 非美国IP({country}: {ip})，换IP... ({attempt+1}/{max_retries})")
        except Exception:
            pass
        if attempt < max_retries - 1:
            print(f"  [代理] IP不通，换新IP重试... ({attempt+1}/{max_retries})")
    raise RuntimeError(f"代理验证失败: 连续 {max_retries} 次未获取到美国IP")
