"""
Proxy Management - BestProxy SOCKS5 proxy acquisition and validation
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
    """Get a US proxy that passed verification, return (proxies_dict, session_id)"""
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
                    print(f"  [Proxy] US IP verification passed: {ip} (attempt {attempt+1})")
                    return proxies, session_id
                else:
                    print(f"  [Proxy] Non-US IP ({country}: {ip}), changing IP... ({attempt+1}/{max_retries})")
        except Exception:
            pass
        if attempt < max_retries - 1:
            print(f"  [Proxy] IP not reachable, retrying with new IP... ({attempt+1}/{max_retries})")
    raise RuntimeError(f"Proxy verification failed: failed to get US IP after {max_retries} attempts")
