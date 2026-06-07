"""
Kiro Pro Batch Activation - Main Entry
Google Login / Builder ID Registration + Stripe Payment
"""
import time
import threading
import concurrent.futures
import requests

import auth_google
import auth_builderid
import auth_github
import kiro
import stripe_pay
import card_api
import storage
from proxy import get_proxies_with_check
from config import MAX_WORKERS, THREAD_START_DELAY, DEBUG_CARD

_print_lock = threading.Lock()


def _get_checkout_url_via_browser(page, token_info):
    """Builder ID: Navigate to settings page, click Upgrade button to get payment link (opens in new tab)"""
    page.get("https://app.kiro.dev/settings/account")
    time.sleep(5)

    # Click Upgrade to Pro+ button
    upgrade_btn = page.ele('text:Upgrade to Pro', timeout=15)
    if not upgrade_btn:
        upgrade_btn = page.ele('xpath://button[contains(., "Upgrade")]', timeout=5)
    if not upgrade_btn:
        raise RuntimeError(f"Upgrade button not found, URL: {page.url[:80]}")

    tabs_before = page.tabs_count
    upgrade_btn.click()
    print(f"  [BuilderID] Upgrade button clicked")
    time.sleep(8)

    # Wait for new tab to open
    for _ in range(20):
        if page.tabs_count > tabs_before:
            # Switch to newest tab
            new_tab = page.latest_tab
            new_url = new_tab.url
            if "checkout.stripe.com" in new_url or "billing.stripe.com" in new_url:
                print(f"  Checkout: {new_url[:60]}...")
                return new_url
        if "checkout.stripe.com" in page.url:
            print(f"  Checkout: {page.url[:60]}...")
            return page.url
        time.sleep(2)

    raise RuntimeError(f"Payment page not opened, URL: {page.url[:80]}")


def run_single(username, password, totp, card_key_or_id, proxies, window_index=0, mode="google"):
    """Single account complete flow: login → check → get URL → open card → pay → enable overage"""
    import browser
    from config import CARD_CHANNEL
    from DrissionPage import ChromiumPage, ChromiumOptions

    page = None
    browser_id = None

    try:
        # 1. Login (select method based on mode)
        if mode == "builderid":
            print(f"[1/4] Builder ID registration/login: {username}")
        elif mode == "github":
            print(f"[1/4] GitHub protocol login: {username}")
        else:
            print(f"[1/4] Google login: {username}")
        login_error = None
        for login_attempt in range(3):
            try:
                if mode == "builderid":
                    token_info, page, browser_id = auth_builderid.login(username, totp, proxies, window_index)
                elif mode == "github":
                    token_info = auth_github.login(username, password, totp, proxies)
                    # GitHub pure protocol, no browser, need to open browser for payment later
                else:
                    token_info, page, browser_id = auth_google.login(username, password, totp, proxies, window_index)
                login_error = None
                break
            except Exception as e:
                login_error = e
                if browser_id:
                    browser.close(browser_id)
                    browser.delete(browser_id)
                    browser_id = None
                    page = None
                if login_attempt < 2:
                    if "SOCKS" in str(e) or "Connection" in str(e) or "SSL" in str(e):
                        proxies, _ = get_proxies_with_check()
                    print(f"  Login failed, retrying ({login_attempt+1}/2): {str(e)[:50]}")
                    time.sleep(3)
        if login_error:
            raise login_error

        # 2. Check if already Pro (auto retry with IP change on proxy disconnect)
        for _retry in range(3):
            try:
                sub_type = kiro.check_subscription(token_info, proxies)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.SSLError):
                proxies, _ = get_proxies_with_check()
                print(f"  [Network] Proxy disconnected, IP changed")
        else:
            sub_type = ""

        if "PRO" in sub_type:
            print(f"  [Skip] Already Pro!")
            storage.save_success(username, password, totp, token_info)
            return {"status": "success", "checkout_url": None, "token_info": token_info}
        print(f"  Current status: {sub_type or 'FREE'}")

        # 3. Get Checkout URL
        print(f"[2/4] Getting Checkout URL...")
        checkout_url = None
        if mode == "builderid" and page:
            checkout_url = _get_checkout_url_via_browser(page, token_info)
        else:
            for _retry in range(5):
                try:
                    checkout_url = kiro.get_checkout_url(token_info, proxies)
                    break
                except (requests.exceptions.ConnectionError, requests.exceptions.SSLError):
                    proxies, _ = get_proxies_with_check()
                    print(f"  [Network] Proxy disconnected, retrying ({_retry+1}/5)")
                except Exception as e:
                    if _retry < 4:
                        proxies, _ = get_proxies_with_check()
                        print(f"  [Network] Request failed, retrying ({_retry+1}/5): {str(e)[:40]}")
                        time.sleep(3)
                    else:
                        raise
        if not checkout_url:
            raise RuntimeError("Failed to get Checkout URL (5 retries)")
        print(f"  Checkout: {checkout_url[:60]}...")

        # GitHub pure protocol login has no browser, open one for payment
        if mode == "github" and not page:
            _, session_id = get_proxies_with_check()
            browser_id = browser.create(session_id, f"pay_{username[:10]}")
            debug_addr = browser.open_browser(browser_id, window_index)
            co = ChromiumOptions()
            co.set_address(debug_addr)
            page = ChromiumPage(co)

        # 4. Open payment page to check amount first, only open card if $0 (avoid waste)
        if card_key_or_id is None:
            print(f"  No card, login only")
            storage.save_success(username, password, totp, token_info)
            return {"status": "success", "checkout_url": checkout_url, "token_info": token_info}

        print(f"[3/4] Checking amount...")
        amount_status = stripe_pay.check_amount(checkout_url, page)
        if amount_status == "already_pro":
            storage.save_success(username, password, totp, token_info)
            return {"status": "success", "checkout_url": checkout_url, "token_info": token_info}
        if amount_status == "not_zero":
            print(f"  [Skip] Amount is not $0, skipping card opening")
            return {"status": "not_zero", "checkout_url": checkout_url, "token_info": token_info}
        if amount_status == "error":
            return {"status": "error", "checkout_url": checkout_url, "token_info": token_info}

        # Amount confirmed as $0, now open card
        if isinstance(card_key_or_id, tuple):
            if CARD_CHANNEL == "3r":
                print(f"  [Card Opening] 3r channel...")
                card_key = card_api.fetch_3r()
            elif CARD_CHANNEL == "huakai":
                card_key = card_api.get_shared_card()
            else:
                card_key = None
            if not card_key:
                print(f"  [Card Opening] Failed")
                return {"status": "error", "checkout_url": checkout_url, "token_info": token_info}
        elif card_key_or_id == "FETCH_ON_DEMAND":
            print(f"  [Card Opening] 10r channel...")
            batch = card_api.fetch(1)
            if not batch or batch == "AUTH_EXPIRED":
                print(f"  [Card Opening] Failed")
                return {"status": "error", "checkout_url": checkout_url, "token_info": token_info}
            card_key = batch[0]
        else:
            card_key = card_key_or_id

        # 5. Fill card and pay in same browser (page already loaded, skip reopening)
        print(f"[4/4] Browser Stripe payment...")
        status = stripe_pay.pay(checkout_url, card_key, page, page_already_loaded=True)

        # Retry once on page error/refresh with same browser
        if status == "error":
            print(f"  [Payment] Page error, retrying...")
            status = stripe_pay.pay(checkout_url, card_key, page)

        # Retry on decline with IP change (max 2 times)
        if status == "declined":
            for retry in range(2):
                print(f"  [Declined] Changing IP, retry ({retry+1}/2)...")
                if browser_id:
                    browser.close(browser_id)
                    browser.delete(browser_id)
                    browser_id = None
                proxies, session_id = get_proxies_with_check()
                browser_id = browser.create(session_id, f"retry_{username[:10]}")
                debug_addr = browser.open_browser(browser_id, window_index)
                co = ChromiumOptions()
                co.set_address(debug_addr)
                page = ChromiumPage(co)
                status = stripe_pay.pay(checkout_url, card_key, page)
                if status != "declined":
                    break

        if status == "success":
            storage.save_success(username, password, totp, token_info)
            print(f"[4/4] Enabling overage...")
            kiro.enable_overage(token_info, proxies)
        elif status == "declined":
            print(f"  Card declined")

        return {"status": status, "checkout_url": checkout_url, "token_info": token_info}

    finally:
        if browser_id:
            browser.close(browser_id)
            browser.delete(browser_id)


def batch_run(accounts_text):
    """
    Batch execution
    accounts_text: one account per line
    Format 2 fields: email----code_link (Builder ID)
    Format 3 fields: username----password----totp (GitHub: no @ / Google: with @)
    Format 4 fields: email----password----ignore----totp (Google)
    """
    from config import CARD_CHANNEL

    accounts = []
    for line in accounts_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("----")
        if len(parts) == 4:
            accounts.append({"username": parts[0], "password": parts[1], "totp": parts[3], "mode": "google"})
        elif len(parts) == 3:
            # @ present is Google, no @ is GitHub
            mode = "google" if "@" in parts[0] else "github"
            accounts.append({"username": parts[0], "password": parts[1], "totp": parts[2], "mode": mode})
        elif len(parts) == 2:
            accounts.append({"username": parts[0], "password": "", "totp": parts[1], "mode": "builderid"})

    if not accounts:
        print("No valid accounts")
        return

    use_debug = len(accounts) < 10

    print(f"{'='*60}")
    print(f"  Batch task: {len(accounts)} accounts")
    print(f"  Channel: {CARD_CHANNEL} | {'Debug mode' if use_debug else 'On-demand card opening'}")
    print(f"{'='*60}\n")

    # Execution
    results = []
    declined_count = {}
    consecutive_declined = {"count": 0}  # Consecutive decline count
    stop_flag = {"stopped": False}

    # Window slot queue (control window arrangement position)
    import queue
    slot_queue = queue.Queue()
    for s in range(MAX_WORKERS):
        slot_queue.put(s)

    def worker(acc):
        username = acc["username"]
        if stop_flag["stopped"]:
            return {"account": username, "success": False, "status": "skipped", "reason": "cards_exhausted"}
        window_slot = slot_queue.get()
        try:
            if stop_flag["stopped"]:
                return {"account": username, "success": False, "status": "skipped", "reason": "cards_exhausted"}
            proxies, _ = get_proxies_with_check()
            if use_debug:
                card = DEBUG_CARD
            elif CARD_CHANNEL in ("3r", "huakai"):
                card = ("ON_DEMAND",)
            else:
                card = "FETCH_ON_DEMAND"
            result = run_single(username, acc["password"], acc["totp"], card, proxies, window_slot, mode=acc.get("mode", "google"))
            if isinstance(result, dict):
                status = result["status"]
                acc["_checkout_url"] = result.get("checkout_url")
                acc["_token_info"] = result.get("token_info")
            else:
                status = result
            if status == "declined":
                declined_count[username] = declined_count.get(username, 0) + 1
                consecutive_declined["count"] += 1
                if consecutive_declined["count"] >= 10:
                    stop_flag["stopped"] = True
                    print(f"  [!] 10 consecutive declines, stopping all tasks")
            else:
                consecutive_declined["count"] = 0
            if status == "error" and not use_debug:
                from pathlib import Path
                if CARD_CHANNEL == "3r":
                    card_file = Path(__file__).parent.parent / "database" / "3r_cards.txt"
                elif CARD_CHANNEL == "huakai":
                    card_file = Path(__file__).parent.parent / "database" / "huakai_cards.txt"
                else:
                    card_file = None
                if card_file and (not card_file.exists() or not [l for l in card_file.read_text(encoding="utf-8").splitlines() if l.strip() and '#' not in l]):
                    stop_flag["stopped"] = True
                    print(f"  [!] Cards exhausted, no more new tasks")
            return {"account": username, "success": status == "success", "status": status, "reason": status}
        except Exception as e:
            err_msg = str(e)
            if "account_not_found" in err_msg:
                reason = "Account not found"
            elif "phone scan" in err_msg:
                reason = "Phone verification required"
            elif "captcha" in err_msg:
                reason = "Captcha triggered"
            elif "account_suspended" in err_msg:
                reason = "Account suspended"
            elif "password" in err_msg or "Passwd" in err_msg:
                reason = "Password page error"
            elif "AccessToken" in err_msg:
                reason = "Login incomplete"
            elif "CSRF" in err_msg:
                reason = "CSRF fetch failed"
            elif "Checkout" in err_msg:
                reason = "Failed to get payment link"
            else:
                reason = err_msg[:60]
            print(f"  [{username[:10]}] Failed: {reason}")
            return {"account": username, "success": False, "status": "error", "reason": reason}
        finally:
            slot_queue.put(window_slot)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for acc in accounts:
            if stop_flag["stopped"]:
                results.append({"account": acc["username"], "success": False, "status": "skipped", "reason": "cards_exhausted"})
                continue
            futures.append(executor.submit(worker, acc))
            time.sleep(THREAD_START_DELAY)
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Collect accounts with checkout_url but failed payment for retry round
    retry_accounts = []
    for acc in accounts:
        r = next((r for r in results if r["account"] == acc["username"]), None)
        if r and not r["success"] and r["status"] not in ("skipped", "not_zero") and acc.get("_checkout_url"):
            retry_accounts.append(acc)

    if retry_accounts and not stop_flag["stopped"]:
        print(f"\n{'='*60}")
        print(f"  Retry round: {len(retry_accounts)} accounts with payment link but failed, changing IP...")
        print(f"{'='*60}\n")

        def retry_worker(acc):
            username = acc["username"]
            window_slot = slot_queue.get()
            try:
                if stop_flag["stopped"]:
                    return {"account": username, "success": False, "status": "skipped", "reason": "stopped"}
                import browser as _browser
                proxies, session_id = get_proxies_with_check()
                browser_id = _browser.create(session_id, f"retry_{username[:8]}")
                debug_addr = _browser.open_browser(browser_id, window_slot)
                co = ChromiumOptions()
                co.set_address(debug_addr)
                page = ChromiumPage(co)
                try:
                    if use_debug:
                        card_key = DEBUG_CARD
                    elif CARD_CHANNEL in ("3r", "huakai"):
                        card_key = card_api.get_shared_card()
                    else:
                        card_key = None
                    if not card_key:
                        return {"account": username, "success": False, "status": "error", "reason": "no_card"}
                    status = stripe_pay.pay(acc["_checkout_url"], card_key, page)
                    if status == "success":
                        token_info = acc.get("_token_info", {})
                        storage.save_success(username, acc["password"], acc["totp"], token_info)
                        if token_info:
                            kiro.enable_overage(token_info, proxies)
                        return {"account": username, "success": True, "status": "success", "reason": "success"}
                    return {"account": username, "success": False, "status": status, "reason": status}
                finally:
                    _browser.close(browser_id)
                    _browser.delete(browser_id)
            except Exception as e:
                return {"account": username, "success": False, "status": "error", "reason": str(e)[:40]}
            finally:
                slot_queue.put(window_slot)

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            retry_futures = []
            for acc in retry_accounts:
                retry_futures.append(executor.submit(retry_worker, acc))
                time.sleep(THREAD_START_DELAY)
            for f in concurrent.futures.as_completed(retry_futures):
                r = f.result()
                # Update results
                for i, old_r in enumerate(results):
                    if old_r["account"] == r["account"]:
                        results[i] = r
                        break

    # Save failed (skip skipped)
    for r in results:
        if not r["success"] and r["status"] != "skipped":
            acc = next((a for a in accounts if a["username"] == r["account"]), None)
            if acc:
                storage.save_failed(acc["username"], acc["password"], acc["totp"], r.get("reason", r["status"]))

    # Summary
    ok = sum(1 for r in results if r["success"])
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"\n{'='*60}")
    print(f"  Complete! Success: {ok}/{len(results)}" + (f" | Skipped (no cards): {skipped}" if skipped else ""))
    print(f"{'='*60}")
    for r in results:
        icon = "[OK]" if r["success"] else "[--]" if r["status"] == "skipped" else "[X]"
        extra = f" ({r.get('reason', r['status'])})" if not r["success"] else ""
        print(f"  {icon} {r['account']}{extra}")


if __name__ == "__main__":
    from pathlib import Path
    import threading

    ACCOUNTS_FILE = Path(__file__).parent.parent / "database" / "input_accounts.txt"
    _accounts_lock = threading.Lock()

    if not ACCOUNTS_FILE.exists():
        print(f"Accounts file not found: {ACCOUNTS_FILE}")
    else:
        lines = [l.strip() for l in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            print("Accounts file is empty")
        else:
            print(f"[Preparing] Reading {len(lines)} accounts from file")
            # Clear file (all taken)
            ACCOUNTS_FILE.write_text("", encoding="utf-8")
            batch_run("\n".join(lines))
