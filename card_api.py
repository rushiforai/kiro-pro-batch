"""
Card Opening API - Support multiple channels
10r: Batch card opening API
3r: Query card info by key_id (take one delete one from file)
huakai: HuaKai cards (credential redemption)
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
    """Re-login, update global token"""
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
            print(f"  [Card API] Re-login successful")
            return True
        print(f"  [Card API] Login failed: {data}")
        return False
    except Exception as e:
        print(f"  [Card API] Login error: {e}")
        return False


def fetch(count=5):
    """
    Get multiple cards, return list [{"number", "expiry", "cvv"}, ...]
    Return "AUTH_EXPIRED" indicates login expired
    Return [] indicates no cards in pool
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
                print(f"  [Card API] Failed: {data}")
                if "login expired" in msg or "not logged in" in msg or code == "IAT_MISMATCH" or code == "NO_TOKEN" or "token" in msg.lower():
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
                    print(f"  [Card API] Got: {number[-4:]} | {expiry} | {cvv}")
            return result
        except Exception as e:
            if _attempt < 2:
                print(f"  [Card API] Timeout retry ({_attempt+1}/3): {e}")
                time.sleep(3)
                continue
            print(f"  [Card API] Error: {e}")
            return []


def fetch_3r(key_id=None):
    """
    3r channel: take one key_id from card file to query card info, delete after use
    Return: {"number", "expiry", "cvv"} or None
    """
    card_file = Path(__file__).parent.parent / "database" / "3r_cards.txt"

    if not key_id:
        with _card_file_lock:
            if not card_file.exists():
                print(f"  [3r Card] Card file not found: {card_file}")
                return None
            lines = [l.strip() for l in card_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith('#') and '#' not in l]
            if not lines:
                print(f"  [3r Card] Card file empty, no cards available")
                return None
            key_id = lines[0]
            # Take one delete one
            remaining = lines[1:]
            card_file.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
            print(f"  [3r Card] Took: {key_id[:20]}... (remaining {len(remaining)})")

    try:
        # First redeem (activate) the card, poll and wait for activation to complete
        print(f"  [3r Card] Activating...")
        activated = False
        for attempt in range(15):  # max 45 seconds (15 times x 3 seconds)
            try:
                redeem_resp = requests.post(
                    CARD_3R_API.replace('/query', '/redeem'),
                    json={"key_id": key_id, "redeem_mode": "451311"},
                    headers={"Content-Type": "application/json"},
                    timeout=15, verify=False)
            except Exception as e:
                print(f"  [3r Card] Request error, retrying: {e}")
                time.sleep(3)
                continue

            if redeem_resp.status_code == 429:
                print(f"  [3r Card] Rate limited, waiting 5s... ({attempt+1}/15)")
                time.sleep(5)
                continue

            redeem_data = redeem_resp.json()
            if redeem_data.get("success"):
                activated = True
                break

            err = redeem_data.get("error", "")
            # Already activated/used → skip to query
            if "used" in err or "activated" in err or "already" in err.lower() or "used" in err.lower():
                print(f"  [3r Card] Card already activated, querying")
                activated = True
                break
            # Temporarily unavailable/processing/429 → wait and retry
            if "unavailable" in err or "processing" in err or "pending" in err.lower() or "wait" in err.lower() or "429" in err:
                if attempt < 14:
                    print(f"  [3r Card] {err[:30]}, retrying... ({attempt+1}/15)")
                    time.sleep(5)
                    continue
            # Other errors → fail
            print(f"  [3r Card] Activation failed: {err}")
            break

        if not activated:
            # Activation failed, put card back in file with marker
            with _card_file_lock:
                if card_file.exists():
                    content = card_file.read_text(encoding="utf-8")
                else:
                    content = ""
                card_file.write_text(content + f"{key_id}  # activation_failed\n", encoding="utf-8")
            print(f"  [3r Card] Activation timeout/failed, returned to file")
            return None

        # Activation successful, query card info (also poll for potential delay)
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
            print(f"  [3r Card] Query card info failed")
            return None
        data = resp.json()
        if not data.get("success"):
            print(f"  [3r Card] Query failed: {data.get('error', '')}")
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
            print(f"  [3r Card] Got: {pan[-4:]} | {expiry} | {cvv}")
            return {
                "number": pan,
                "expiry": expiry,
                "cvv": cvv,
            }
        return None
    except Exception as e:
        print(f"  [3r Card] Error: {e}")
        return None


def get_shared_card():
    """
    Get shared card: one card is used ACCOUNTS_PER_CARD times before getting next.
    Thread-safe.
    """
    global _shared_card, _shared_card_uses
    with _shared_card_lock:
        if _shared_card and _shared_card_uses < ACCOUNTS_PER_CARD:
            _shared_card_uses += 1
            print(f"  [Card Opening] Reuse card ...{_shared_card['number'][-4:]} ({_shared_card_uses}/{ACCOUNTS_PER_CARD})")
            return _shared_card.copy()
        new_card = fetch_huakai()
        if new_card:
            _shared_card = new_card
            _shared_card_uses = 1
            print(f"  [Card Opening] New card ...{new_card['number'][-4:]} (1/{ACCOUNTS_PER_CARD})")
        else:
            _shared_card = None
            _shared_card_uses = 0
        return new_card


def fetch_huakai():
    """
    HuaKai card channel: take one credential from database/huakai_cards.txt, call API to redeem
    Take one delete one
    Return: {"number", "expiry", "cvv"} or None
    """
    card_file = Path(__file__).parent.parent / "database" / "huakai_cards.txt"

    with _card_file_lock:
        if not card_file.exists():
            print(f"  [HuaKai] Card file not found: {card_file}")
            return None
        lines = [l.strip() for l in card_file.read_text(encoding="utf-8").splitlines() if l.strip() and '#' not in l]
        if not lines:
            print(f"  [HuaKai] Card file empty, no cards available")
            return None
        code = lines[0]
        remaining = lines[1:]
        card_file.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
        print(f"  [HuaKai] Took: {code[:30]}... (remaining {len(remaining)})")

    try:
        resp = requests.post(CARD_HUAKAI_API,
            json={"codes": [code]},
            headers={"Content-Type": "application/json"},
            timeout=30, verify=False)
        data = resp.json()
        results = data.get("data", [])
        if not results:
            print(f"  [HuaKai] No response data")
            return None
        r = results[0]
        if not r.get("success"):
            print(f"  [HuaKai] Redemption failed: {r.get('msg', '')}")
            # Put back in file with failed marker
            with _card_file_lock:
                content = card_file.read_text(encoding="utf-8") if card_file.exists() else ""
                card_file.write_text(content + f"{code}  # redemption_failed\n", encoding="utf-8")
            return None
        card = r.get("card", {})
        number = card.get("cardNumber", "")
        expiry = card.get("expiry", "")  # format like "1126" (MMYY)
        cvv = card.get("cvv", "")

        if number:
            print(f"  [HuaKai] Got: {number[-4:]} | {expiry} | {cvv}")
            return {"number": number, "expiry": expiry, "cvv": cvv}
        return None
    except Exception as e:
        print(f"  [HuaKai] Error: {e}")
        return None
