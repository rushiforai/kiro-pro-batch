"""
开卡 API - 支持多个渠道
10r: 批量开卡API
3r: key_id 查询卡信息（从文件取一张删一张）
huakai: 华开卡（卡密兑换）
"""
import time
import threading
import urllib3
from pathlib import Path
import requests
from config import (CARD_API_URL, CARD_API_LOGIN_URL, CARD_API_USERNAME,
                    CARD_API_PASSWORD, CARD_API_COOKIE, CARD_3R_API, CARD_HUAKAI_API,
                    ACCOUNTS_PER_CARD)
import config

urllib3.disable_warnings()
requests.packages.urllib3.disable_warnings()

_card_file_lock = threading.Lock()

_shared_card_lock = threading.Lock()
_shared_card = None
_shared_card_uses = 0


def _login():
    """重新登录，更新全局 token"""
    try:
        resp = requests.post(CARD_API_LOGIN_URL,
            json={"username": CARD_API_USERNAME, "password": CARD_API_PASSWORD},
            headers={"content-type": "application/json", "cookie": CARD_API_COOKIE,
                     "origin": CARD_API_URL.rsplit('/', 3)[0], "referer": CARD_API_URL.rsplit('/', 3)[0] + "/login.html",
                     "user-agent": "Mozilla/5.0"},
            timeout=30, verify=False, proxies={"http": None, "https": None})
        data = resp.json()
        token = data.get("token", "")
        if token:
            config.CARD_API_TOKEN = f"Bearer {token}"
            print(f"  [开卡API] 重新登录成功")
            return True
        print(f"  [开卡API] 登录失败: {data}")
        return False
    except Exception as e:
        print(f"  [开卡API] 登录异常: {e}")
        return False


def fetch(count=5):
    """
    获取多张卡，返回列表 [{"number", "expiry", "cvv"}, ...]
    返回 "AUTH_EXPIRED" 表示登录失效
    返回 [] 表示卡池暂无卡
    """
    for _attempt in range(3):
        try:
            resp = requests.post(CARD_API_URL,
                json={"count": count},
                headers={"authorization": config.CARD_API_TOKEN, "content-type": "application/json",
                         "cookie": CARD_API_COOKIE, "origin": CARD_API_URL.rsplit('/', 3)[0],
                         "referer": CARD_API_URL.rsplit('/', 3)[0] + "/user.html", "user-agent": "Mozilla/5.0"},
                timeout=30, verify=False, proxies={"http": None, "https": None})
            data = resp.json()
            if not data.get("success"):
                msg = data.get("message", "")
                code = data.get("code", "")
                print(f"  [开卡API] 失败: {data}")
                if "登录已失效" in msg or "未登录" in msg or code == "IAT_MISMATCH" or code == "NO_TOKEN" or "token" in msg.lower():
                    if _login():
                        return fetch(count)
                    return "AUTH_EXPIRED"
                return []
            cards_raw = data.get("cards", [])
            result = []
            for c in cards_raw:
                number = str(c.get("card_number", "")).replace(" ", "")
                raw_exp = c.get("expiry", "")
                if "/" in str(raw_exp):
                    parts = str(raw_exp).split("/")
                    expiry = parts[0].strip().zfill(2) + parts[1].strip()[-2:]
                else:
                    expiry = str(raw_exp).replace("/", "")
                cvv = str(c.get("cvv", ""))
                if number:
                    result.append({"number": number, "expiry": expiry, "cvv": cvv})
                    print(f"  [开卡API] 获取: {number[-4:]} | {expiry} | {cvv}")
            return result
        except Exception as e:
            if _attempt < 2:
                print(f"  [开卡API] 超时重试 ({_attempt+1}/3): {e}")
                time.sleep(3)
                continue
            print(f"  [开卡API] 异常: {e}")
            return []


def fetch_3r(key_id=None):
    """
    3r渠道：从卡文件取一个 key_id 查询卡信息，用完从文件删除
    返回: {"number", "expiry", "cvv"} 或 None
    """
    card_file = Path(__file__).parent.parent / "shujuku" / "3r卡.txt"

    if not key_id:
        with _card_file_lock:
            if not card_file.exists():
                print(f"  [3r卡] 卡文件不存在: {card_file}")
                return None
            lines = [l.strip() for l in card_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith('#') and '#' not in l]
            if not lines:
                print(f"  [3r卡] 卡文件为空，无卡可用")
                return None
            key_id = lines[0]
            # 用一张删一张
            remaining = lines[1:]
            card_file.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
            print(f"  [3r卡] 取出: {key_id[:20]}... (剩余 {len(remaining)} 张)")

    try:
        # 先兑换（redeem）激活卡，轮询等待激活完成
        print(f"  [3r卡] 兑换激活中...")
        activated = False
        for attempt in range(15):  # 最多45秒（15次 x 3秒）
            try:
                redeem_resp = requests.post(
                    CARD_3R_API.replace('/query', '/redeem'),
                    json={"key_id": key_id, "redeem_mode": "451311"},
                    headers={"Content-Type": "application/json"},
                    timeout=15, verify=False)
            except Exception as e:
                print(f"  [3r卡] 请求异常，重试: {e}")
                time.sleep(3)
                continue

            if redeem_resp.status_code == 429:
                print(f"  [3r卡] 429限流，等待5秒重试... ({attempt+1}/15)")
                time.sleep(5)
                continue

            redeem_data = redeem_resp.json()
            if redeem_data.get("success"):
                activated = True
                break

            err = redeem_data.get("error", "")
            # 已激活/已使用 → 直接跳到查询
            if "已使用" in err or "已激活" in err or "已被使用" in err or "already" in err.lower() or "used" in err.lower() or "被使用" in err:
                print(f"  [3r卡] 卡已激活，直接查询")
                activated = True
                break
            # 暂时没卡/正在处理/429 → 等一下重试
            if "没有可用" in err or "处理" in err or "pending" in err.lower() or "wait" in err.lower() or "429" in err:
                if attempt < 14:
                    print(f"  [3r卡] {err[:30]}，等待重试... ({attempt+1}/15)")
                    time.sleep(5)
                    continue
            # 其他错误直接失败
            print(f"  [3r卡] 兑换失败: {err}")
            break

        if not activated:
            # 激活失败，把卡放回文件并标记
            with _card_file_lock:
                if card_file.exists():
                    content = card_file.read_text(encoding="utf-8")
                else:
                    content = ""
                card_file.write_text(content + f"{key_id}  # 激活失败\n", encoding="utf-8")
            print(f"  [3r卡] 激活超时/失败，已放回文件")
            return None

        # 激活成功，查询卡信息（也轮询，因为可能有延迟）
        for attempt in range(5):
            resp = requests.post(CARD_3R_API,
                json={"key_id": key_id},
                headers={"Content-Type": "application/json"},
                timeout=15, verify=False)
            data = resp.json()
            if data.get("success") and data.get("card", {}).get("pan"):
                break
            time.sleep(2)
        else:
            print(f"  [3r卡] 查询卡信息失败")
            return None
        data = resp.json()
        if not data.get("success"):
            print(f"  [3r卡] 查询失败: {data.get('error', '')}")
            return None
        card = data.get("card", {})
        if not card:
            return None
        pan = card.get("pan", "")
        cvv = card.get("cvv", "")
        exp_month = str(card.get("exp_month", "")).zfill(2)
        exp_year = str(card.get("exp_year", ""))[-2:]
        expiry = exp_month + exp_year

        if pan:
            print(f"  [3r卡] 获取: {pan[-4:]} | {expiry} | {cvv}")
            return {
                "number": pan,
                "expiry": expiry,
                "cvv": cvv,
            }
        return None
    except Exception as e:
        print(f"  [3r卡] 异常: {e}")
        return None


def get_shared_card():
    """
    获取共享卡：一张卡用 ACCOUNTS_PER_CARD 次后才取下一张。
    线程安全。
    """
    global _shared_card, _shared_card_uses
    with _shared_card_lock:
        if _shared_card and _shared_card_uses < ACCOUNTS_PER_CARD:
            _shared_card_uses += 1
            print(f"  [开卡] 复用卡 ...{_shared_card['number'][-4:]} ({_shared_card_uses}/{ACCOUNTS_PER_CARD})")
            return _shared_card.copy()
        new_card = fetch_huakai()
        if new_card:
            _shared_card = new_card
            _shared_card_uses = 1
            print(f"  [开卡] 新卡 ...{new_card['number'][-4:]} (1/{ACCOUNTS_PER_CARD})")
        else:
            _shared_card = None
            _shared_card_uses = 0
        return new_card


def fetch_huakai():
    """
    华开卡渠道：从 shujuku/华开卡.txt 取一个卡密，调 API 兑换
    用一张删一张
    返回: {"number", "expiry", "cvv"} 或 None
    """
    card_file = Path(__file__).parent.parent / "shujuku" / "华开卡.txt"

    with _card_file_lock:
        if not card_file.exists():
            print(f"  [华开卡] 卡文件不存在: {card_file}")
            return None
        lines = [l.strip() for l in card_file.read_text(encoding="utf-8").splitlines() if l.strip() and '#' not in l]
        if not lines:
            print(f"  [华开卡] 卡文件为空，无卡可用")
            return None
        code = lines[0]
        remaining = lines[1:]
        card_file.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
        print(f"  [华开卡] 取出: {code[:30]}... (剩余 {len(remaining)} 张)")

    try:
        resp = requests.post(CARD_HUAKAI_API,
            json={"codes": [code]},
            headers={"Content-Type": "application/json"},
            timeout=30, verify=False)
        data = resp.json()
        results = data.get("data", [])
        if not results:
            print(f"  [华开卡] 无返回数据")
            return None
        r = results[0]
        if not r.get("success"):
            print(f"  [华开卡] 兑换失败: {r.get('msg', '')}")
            # 放回文件标记失败
            with _card_file_lock:
                content = card_file.read_text(encoding="utf-8") if card_file.exists() else ""
                card_file.write_text(content + f"{code}  # 兑换失败\n", encoding="utf-8")
            return None
        card = r.get("card", {})
        number = card.get("cardNumber", "")
        expiry = card.get("expiry", "")  # 格式如 "1126" (MMYY)
        cvv = card.get("cvv", "")

        if number:
            print(f"  [华开卡] 获取: {number[-4:]} | {expiry} | {cvv}")
            return {"number": number, "expiry": expiry, "cvv": cvv}
        return None
    except Exception as e:
        print(f"  [华开卡] 异常: {e}")
        return None
