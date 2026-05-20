"""
BitBrowser 指纹浏览器管理
"""
import time
from pathlib import Path
import requests
from config import BITBROWSER_API, PROXY_HOST, PROXY_PORT, PROXY_PASS
from proxy import make_proxy_username

SCRIPT_DIR = Path(__file__).parent
YESCAPTCHA_EXT = str(SCRIPT_DIR.parent / "extensions" / "yescaptcha")


def create(session_id, name):
    """创建浏览器窗口，返回 browser_id"""
    username = make_proxy_username(session_id)
    payload = {
        "name": name,
        "proxyMethod": 2,
        "proxyType": "socks5",
        "host": PROXY_HOST,
        "port": str(PROXY_PORT),
        "proxyUserName": username,
        "proxyPassword": PROXY_PASS,
        "browserFingerPrint": {},
        "randomFingerprint": True,
    }
    resp = requests.post(f"{BITBROWSER_API}/browser/update", json=payload, timeout=15)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"BitBrowser 创建失败: {data}")
    return data["data"]["id"]


def open_browser(browser_id, window_index=0):
    """打开浏览器窗口（带 YesCaptcha 打码插件），返回 debug 地址"""
    win_x = (window_index % 5) * 512
    win_y = (window_index // 5) * 480
    payload = {
        "id": browser_id,
        "args": [
            f"--window-size=512,480",
            f"--window-position={win_x},{win_y}",
            f"--load-extension={YESCAPTCHA_EXT}",
            "--proxy-bypass-list=api.yescaptcha.com",
        ],
        "queue": True,
    }
    resp = requests.post(f"{BITBROWSER_API}/browser/open", json=payload, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"BitBrowser 打开失败: {data}")
    return data["data"]["http"]


def close(browser_id):
    try:
        requests.post(f"{BITBROWSER_API}/browser/close", json={"id": browser_id}, timeout=10)
    except Exception:
        pass


def delete(browser_id):
    try:
        time.sleep(3)
        requests.post(f"{BITBROWSER_API}/browser/delete", json={"id": browser_id}, timeout=10)
    except Exception:
        pass
