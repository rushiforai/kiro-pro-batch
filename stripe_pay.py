"""
Stripe browser payment - BitBrowser auto card filling
"""
import json
import time
import random
import uuid as uuid_mod
from pathlib import Path

import requests
from DrissionPage import ChromiumPage, ChromiumOptions

import browser
from proxy import get_proxies_with_check

INVALID_CARD_FILE = Path(__file__).parent.parent / "shujuku" / "无效卡.json"


def _save_invalid_card(card_info):
    """Record invalid card"""
    INVALID_CARD_FILE.parent.mkdir(exist_ok=True)
    records = []
    if INVALID_CARD_FILE.exists():
        try:
            records = json.loads(INVALID_CARD_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            records = []
    if not any(r.get("number") == card_info.get("number") for r in records):
        records.append({"number": card_info.get("number", ""), "expiry": card_info.get("expiry", ""), "cvv": card_info.get("cvv", ""), "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        INVALID_CARD_FILE.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [Payment] Invalid card recorded: {card_info.get('number', '')[-4:]}")


# ── Tax-exempt state addresses ──
US_ADDRESSES = [
    ("Portland", "OR", "97205", "815 SW Park Ave"),
    ("Portland", "OR", "97211", "4230 NE Fremont St"),
    ("Eugene", "OR", "97401", "720 E 13th Ave"),
    ("Salem", "OR", "97301", "155 Liberty St NE"),
    ("Bend", "OR", "97702", "915 SW Simpson Ave"),
    ("Billings", "MT", "59101", "415 N Broadway"),
    ("Missoula", "MT", "59801", "325 N Higgins Ave"),
    ("Bozeman", "MT", "59715", "412 W Main St"),
    ("Helena", "MT", "59601", "315 N Last Chance Gulch"),
    ("Wilmington", "DE", "19801", "920 N King St"),
    ("Dover", "DE", "19901", "316 S Governors Ave"),
    ("Newark", "DE", "19711", "280 E Main St"),
    ("Manchester", "NH", "03101", "875 Elm St"),
    ("Nashua", "NH", "03060", "215 Main St"),
    ("Concord", "NH", "03301", "48 N Main St"),
    ("Anchorage", "AK", "99501", "615 W 5th Ave"),
    ("Fairbanks", "AK", "99701", "410 Cushman St"),
    ("Juneau", "AK", "99801", "245 Marine Way"),
]
FIRST_NAMES = ["Ethan", "Liam", "Noah", "Mason", "Logan", "Oliver", "Emma", "Olivia", "Ava", "Sophia",
               "Jackson", "Caleb", "Owen", "Wyatt", "Abigail", "Ella", "Grace", "Chloe", "Riley", "Lily"]
LAST_NAMES = ["Mitchell", "Campbell", "Roberts", "Carter", "Phillips", "Evans", "Turner", "Parker",
              "Collins", "Edwards", "Stewart", "Morris", "Murphy", "Rivera", "Cook", "Rogers",
              "Morgan", "Peterson", "Cooper", "Reed"]


def _random_identity():
    city, state, zip_code, address = random.choice(US_ADDRESSES)
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    parts = address.split(" ", 1)
    if parts[0].isdigit():
        new_num = int(parts[0]) + random.randint(-100, 200)
        if new_num < 10:
            new_num = random.randint(100, 9999)
        address = f"{new_num} {parts[1]}"
    return {"name": f"{first} {last}", "address": address, "city": city, "state": state, "zip": zip_code}


def check_amount(checkout_url, page):
    """
    Open Stripe Checkout page, check if amount is $0
    Return: "zero" | "not_zero" | "already_pro" | "error"
    Don't close page, can fill card directly on same page later
    """
    page.get(checkout_url)
    time.sleep(8)

    page_ok = page.run_js("""
        return document.readyState === 'complete' &&
                   !document.body.innerText.includes('ERR_PROXY') &&
                   !document.body.innerText.includes('ERR_CONNECTION') &&
                   document.body.innerText.length > 50;
    """)
    if not page_ok:
        print("  [Payment] Page loading failed")
        return "error"

    if "billing.stripe.com" in page.url:
        print("  [Payment] Already Pro (billing page)")
        return "already_pro"

    amount_el = page.ele('xpath://span[@class="CurrencyAmount"]', timeout=5)
    if amount_el:
        amount_text = amount_el.text.strip()
        print(f"  [Payment] Amount: {amount_text.encode('ascii', 'replace').decode()}")
        if "0.00" not in amount_text:
            return "not_zero"
    else:
        body_text = page.ele("tag:body").text if page.ele("tag:body") else ""
        if "0.00" not in body_text:
            print(f"  [Payment] No $0 amount detected")
            return "not_zero"

    return "zero"


def pay(checkout_url, card_info, page, page_already_loaded=False):
    """
    Open Stripe Checkout in existing browser page, auto fill card and pay
    page: DrissionPage object (same browser from auth_google.login)
    page_already_loaded: If True, skip opening page (already done by check_amount)
    Amount check done by check_amount, no re-check here
    Return: "success" | "declined" | "invalid_card" | "error"
    """
    if not page_already_loaded:
        page.get(checkout_url)
        time.sleep(8)

        page_ok = page.run_js("""
            return document.readyState === 'complete' &&
                       !document.body.innerText.includes('ERR_PROXY') &&
                       !document.body.innerText.includes('ERR_CONNECTION') &&
                       document.body.innerText.length > 50;
        """)
        if not page_ok:
            print("  [Payment] Page loading failed")
            return "error"

        if "billing.stripe.com" in page.url:
            print("  [Payment] Already Pro (billing page)")
            return "success"

    # Generate identity
    identity = _random_identity()
    card = {
        "number": card_info["number"],
        "expiry": card_info["expiry"],
        "cvv": card_info["cvv"],
        "name": identity["name"],
        "address": identity["address"],
        "city": identity["city"],
        "state": identity["state"],
        "zip": identity["zip"],
    }
    print(f"  [Payment] Card: ...{card['number'][-4:]} | {card['name']}")

    # Select country
    country_sel = page.ele('xpath://select[contains(@aria-label,"Country") or contains(@name,"country")]', timeout=5)
    if country_sel:
        try:
            country_sel.select("United States")
        except Exception:
            try:
                country_sel.select("US")
            except Exception:
                pass
        time.sleep(2)

    # Fill card number
    card_input = page.ele('xpath://input[contains(@aria-label,"Card number") or contains(@aria-label,"卡号")]', timeout=10)
    if card_input:
        card_input.input(card["number"])
        time.sleep(2)

        # Detect invalid card number
        invalid_card = page.run_js("""
            var el = document.querySelector('.FieldError-container');
            if (el && el.innerText.toLowerCase().includes('invalid')) return true;
            return false;
        """)
        if invalid_card:
            print(f"  [Payment] Invalid card number: {card['number']}")
            _save_invalid_card(card_info)
            return "invalid_card"

    # Fill expiry
    exp_input = page.ele('xpath://input[contains(@aria-label,"Expir") or contains(@aria-label,"到期")]', timeout=5)
    if exp_input:
        exp_input.input(card["expiry"])
        time.sleep(1)

    # Fill CVV
    cvv_input = page.ele('xpath://input[contains(@aria-label,"CVC") or contains(@aria-label,"安全码")]', timeout=5)
    if cvv_input:
        cvv_input.input(card["cvv"])
        time.sleep(1)

    # Fill name
    name_field = page.ele('xpath://input[contains(@id,"billingName") or contains(@name,"billingName") or contains(@aria-label,"Name")]', timeout=5)
    if name_field:
        name_field.clear()
        name_field.input(card["name"])
        time.sleep(1)

    # Manual address entry
    manual_btn = page.ele("text:Enter address manually", timeout=3)
    if not manual_btn:
        manual_btn = page.ele("text:手动输入地址", timeout=2)
    if manual_btn:
        manual_btn.click()
        time.sleep(2)

    # Fill address
    addr1 = page.ele('xpath://input[contains(@aria-label,"Address") or contains(@name,"addressLine1")]', timeout=5)
    if addr1:
        addr1.input(card["address"])
        time.sleep(1)

    city_field = page.ele('xpath://input[contains(@aria-label,"City") or contains(@name,"city")]', timeout=5)
    if city_field:
        city_field.input(card["city"])
        time.sleep(1)

    zip_field = page.ele('xpath://input[contains(@aria-label,"ZIP") or contains(@name,"postalCode")]', timeout=5)
    if zip_field:
        zip_field.input(card["zip"])
        time.sleep(1)

    state_sel = page.ele('xpath://select[contains(@aria-label,"State") or contains(@name,"state")]', timeout=5)
    if state_sel:
        try:
            state_sel.select(card["state"])
        except Exception:
            pass
        time.sleep(1)

    print("  [Payment] Information filled, clicking subscribe...")

    # Click submit
    page.run_js("""
        var btn = document.querySelector('button.SubmitButton') || document.querySelector('button[type="submit"]');
        if (btn) { btn.scrollIntoView({block: 'center'}); }
    """)
    time.sleep(1)
    page.run_js("""
        var btn = document.querySelector('button.SubmitButton') || document.querySelector('button[type="submit"]');
        if (btn) btn.click();
    """)

    # Wait for result
    time.sleep(10)
    for wait_i in range(60):
        if "checkout.stripe.com" not in page.url:
            print("  [Payment] Page redirected, payment complete")
            return "success"

        # Detect declined
        declined = page.run_js("""
            var el = document.querySelector('.FieldError-container');
            if (el && el.innerText.toLowerCase().includes('declined')) return true;
            var body = document.body.innerText.toLowerCase();
            if (body.includes('card has been declined')) return true;
            return false;
        """)
        if declined:
            print("  [Payment] Card declined")
            return "declined"

        # Detect unable to authenticate
        auth_fail = page.run_js("""
            var body = document.body.innerText.toLowerCase();
            return body.includes('unable to authenticate');
        """)
        if auth_fail:
            print("  [Payment] Unable to authenticate, retrying...")
            page.run_js("""
                var btn = document.querySelector('button.SubmitButton') || document.querySelector('button[type="submit"]');
                if (btn) btn.click();
            """)
            time.sleep(5)
            continue

        if wait_i % 10 == 9:
            print(f"  [Payment] Waiting... ({(wait_i+1)*3}s)")
        time.sleep(3)

    # Final check
    if "checkout.stripe.com" not in page.url:
        return "success"
    return "error"
