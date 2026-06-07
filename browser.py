"""
BitBrowser fingerprint browser management
"""
import time
from pathlib import Path
import requests
from config import BITBROWSER_API, PROXY_HOST, PROXY_PORT, PROXY_PASS
from proxy import make_proxy_username

SCRIPT_DIR = Path(__file__).parent
YESCAPTCHA_EXT = str(SCRIPT_DIR.parent / "extensions" / "yescaptcha")


def create(session_id, name):
    """Create a browser window, return browser_id"""
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
        raise RuntimeError(f"BitBrowser creation failed: {data}")
    return data["data"]["id"]


def open_browser(browser_id, window_index=0):
    """Open browser window (with YesCaptcha captcha plugin), return debug address"""
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
        raise RuntimeError(f"BitBrowser open failed: {data}")
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
