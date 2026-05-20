"""
Kiro Pro 批量开通 - 主入口
Google 登录 / Builder ID 注册 + Stripe 支付
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
    """Builder ID: 跳转到设置页点击 Upgrade 按钮获取支付链接（新标签页打开）"""
    page.get("https://app.kiro.dev/settings/account")
    time.sleep(5)

    # 点击 Upgrade to Pro+ 按钮
    upgrade_btn = page.ele('text:Upgrade to Pro', timeout=15)
    if not upgrade_btn:
        upgrade_btn = page.ele('xpath://button[contains(., "Upgrade")]', timeout=5)
    if not upgrade_btn:
        raise RuntimeError(f"未找到 Upgrade 按钮, URL: {page.url[:80]}")

    tabs_before = page.tabs_count
    upgrade_btn.click()
    print(f"  [BuilderID] 已点击 Upgrade 按钮")
    time.sleep(8)

    # 等待新标签页打开
    for _ in range(20):
        if page.tabs_count > tabs_before:
            # 切到最新标签页
            new_tab = page.latest_tab
            new_url = new_tab.url
            if "checkout.stripe.com" in new_url or "billing.stripe.com" in new_url:
                print(f"  Checkout: {new_url[:60]}...")
                return new_url
        if "checkout.stripe.com" in page.url:
            print(f"  Checkout: {page.url[:60]}...")
            return page.url
        time.sleep(2)

    raise RuntimeError(f"未打开支付页, URL: {page.url[:80]}")


def run_single(username, password, totp, card_key_or_id, proxies, window_index=0, mode="google"):
    """单个账号的完整流程：登录 → 检查 → 获取URL → 开卡 → 支付 → 超售"""
    import browser
    from config import CARD_CHANNEL
    from DrissionPage import ChromiumPage, ChromiumOptions

    page = None
    browser_id = None

    try:
        # 1. 登录（根据 mode 选择方式）
        if mode == "builderid":
            print(f"[1/4] Builder ID 注册/登录: {username}")
        elif mode == "github":
            print(f"[1/4] GitHub 协议登录: {username}")
        else:
            print(f"[1/4] Google 登录: {username}")
        login_error = None
        for login_attempt in range(3):
            try:
                if mode == "builderid":
                    token_info, page, browser_id = auth_builderid.login(username, totp, proxies, window_index)
                elif mode == "github":
                    token_info = auth_github.login(username, password, totp, proxies)
                    # GitHub 纯协议，没有浏览器，后续需要开浏览器支付
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
                    print(f"  登录失败，重试 ({login_attempt+1}/2): {str(e)[:50]}")
                    time.sleep(3)
        if login_error:
            raise login_error

        # 2. 检查是否已是 Pro（代理断连自动换IP重试）
        for _retry in range(3):
            try:
                sub_type = kiro.check_subscription(token_info, proxies)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.SSLError):
                proxies, _ = get_proxies_with_check()
                print(f"  [网络] 代理断连，已换IP重试")
        else:
            sub_type = ""

        if "PRO" in sub_type:
            print(f"  [跳过] 已经是 Pro!")
            storage.save_success(username, password, totp, token_info)
            return {"status": "success", "checkout_url": None, "token_info": token_info}
        print(f"  当前状态: {sub_type or 'FREE'}")

        # 3. 获取 Checkout URL
        print(f"[2/4] 获取 Checkout URL...")
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
                    print(f"  [网络] 代理断连，已换IP重试 ({_retry+1}/5)")
                except Exception as e:
                    if _retry < 4:
                        proxies, _ = get_proxies_with_check()
                        print(f"  [网络] 请求失败，换IP重试 ({_retry+1}/5): {str(e)[:40]}")
                        time.sleep(3)
                    else:
                        raise
        if not checkout_url:
            raise RuntimeError("获取 Checkout URL 失败（5次重试）")
        print(f"  Checkout: {checkout_url[:60]}...")

        # GitHub 纯协议登录没有浏览器，这里开一个用于支付
        if mode == "github" and not page:
            _, session_id = get_proxies_with_check()
            browser_id = browser.create(session_id, f"pay_{username[:10]}")
            debug_addr = browser.open_browser(browser_id, window_index)
            co = ChromiumOptions()
            co.set_address(debug_addr)
            page = ChromiumPage(co)

        # 4. 先打开支付页检查金额，确认 $0 后才开卡（避免浪费）
        if card_key_or_id is None:
            print(f"  无卡，仅登录")
            storage.save_success(username, password, totp, token_info)
            return {"status": "success", "checkout_url": checkout_url, "token_info": token_info}

        print(f"[3/4] 检查金额...")
        amount_status = stripe_pay.check_amount(checkout_url, page)
        if amount_status == "already_pro":
            storage.save_success(username, password, totp, token_info)
            return {"status": "success", "checkout_url": checkout_url, "token_info": token_info}
        if amount_status == "not_zero":
            print(f"  [跳过] 金额非$0，不开卡")
            return {"status": "not_zero", "checkout_url": checkout_url, "token_info": token_info}
        if amount_status == "error":
            return {"status": "error", "checkout_url": checkout_url, "token_info": token_info}

        # 金额确认为 $0，现在才开卡
        if isinstance(card_key_or_id, tuple):
            if CARD_CHANNEL == "3r":
                print(f"  [开卡] 3r渠道...")
                card_key = card_api.fetch_3r()
            elif CARD_CHANNEL == "huakai":
                card_key = card_api.get_shared_card()
            else:
                card_key = None
            if not card_key:
                print(f"  [开卡] 开卡失败")
                return {"status": "error", "checkout_url": checkout_url, "token_info": token_info}
        elif card_key_or_id == "FETCH_ON_DEMAND":
            print(f"  [开卡] 10r渠道开卡...")
            batch = card_api.fetch(1)
            if not batch or batch == "AUTH_EXPIRED":
                print(f"  [开卡] 开卡失败")
                return {"status": "error", "checkout_url": checkout_url, "token_info": token_info}
            card_key = batch[0]
        else:
            card_key = card_key_or_id

        # 5. 在同一个浏览器里填卡支付（页面已加载，跳过重复打开）
        print(f"[4/4] 浏览器 Stripe 支付...")
        status = stripe_pay.pay(checkout_url, card_key, page, page_already_loaded=True)

        # 页面刷新/error时，用同一个浏览器重新打开支付页重试1次
        if status == "error":
            print(f"  [支付] 页面异常，重新打开支付页重试...")
            status = stripe_pay.pay(checkout_url, card_key, page)

        # 拒卡换IP重试（最多2次）
        if status == "declined":
            for retry in range(2):
                print(f"  [拒卡] 换IP重试 ({retry+1}/2)...")
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
            print(f"[4/4] 开启超售...")
            kiro.enable_overage(token_info, proxies)
        elif status == "declined":
            print(f"  卡被拒绝")

        return {"status": status, "checkout_url": checkout_url, "token_info": token_info}

    finally:
        if browser_id:
            browser.close(browser_id)
            browser.delete(browser_id)


def batch_run(accounts_text):
    """
    批量运行
    accounts_text: 每行一个账号
    格式2字段: 邮箱----接码链接 (Builder ID)
    格式3字段: 用户名----密码----totp (GitHub: 无@符号 / Google: 有@符号)
    格式4字段: 邮箱----密码----丢弃----totp (Google)
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
            # 有 @ 是 Google，没有 @ 是 GitHub
            mode = "google" if "@" in parts[0] else "github"
            accounts.append({"username": parts[0], "password": parts[1], "totp": parts[2], "mode": mode})
        elif len(parts) == 2:
            accounts.append({"username": parts[0], "password": "", "totp": parts[1], "mode": "builderid"})

    if not accounts:
        print("没有有效账号")
        return

    use_debug = len(accounts) < 10

    print(f"{'='*60}")
    print(f"  批量任务: {len(accounts)} 个账号")
    print(f"  渠道: {CARD_CHANNEL} | {'调试模式' if use_debug else '按需开卡'}")
    print(f"{'='*60}\n")

    # 执行
    results = []
    declined_count = {}
    consecutive_declined = {"count": 0}  # 连续拒卡计数
    stop_flag = {"stopped": False}

    # 窗口槽位队列（控制窗口排列位置）
    import queue
    slot_queue = queue.Queue()
    for s in range(MAX_WORKERS):
        slot_queue.put(s)

    def worker(acc):
        username = acc["username"]
        if stop_flag["stopped"]:
            return {"account": username, "success": False, "status": "skipped", "reason": "卡已用完"}
        window_slot = slot_queue.get()
        try:
            if stop_flag["stopped"]:
                return {"account": username, "success": False, "status": "skipped", "reason": "卡已用完"}
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
                    print(f"  [!] 连续10张卡被拒，停止所有任务")
            else:
                consecutive_declined["count"] = 0
            if status == "error" and not use_debug:
                from pathlib import Path
                if CARD_CHANNEL == "3r":
                    card_file = Path(__file__).parent.parent / "shujuku" / "3r卡.txt"
                elif CARD_CHANNEL == "huakai":
                    card_file = Path(__file__).parent.parent / "shujuku" / "华开卡.txt"
                else:
                    card_file = None
                if card_file and (not card_file.exists() or not [l for l in card_file.read_text(encoding="utf-8").splitlines() if l.strip() and '#' not in l]):
                    stop_flag["stopped"] = True
                    print(f"  [!] 卡已用完，不再提交新任务")
            return {"account": username, "success": status == "success", "status": status, "reason": status}
        except Exception as e:
            err_msg = str(e)
            if "account_not_found" in err_msg:
                reason = "账号不存在"
            elif "手机扫码" in err_msg:
                reason = "需要手机扫码"
            elif "captcha" in err_msg:
                reason = "触发验证码"
            elif "account_suspended" in err_msg:
                reason = "账号被封"
            elif "密码" in err_msg or "Passwd" in err_msg:
                reason = "密码页异常"
            elif "AccessToken" in err_msg:
                reason = "登录未完成"
            elif "CSRF" in err_msg:
                reason = "CSRF获取失败"
            elif "Checkout" in err_msg:
                reason = "获取支付链接失败"
            else:
                reason = err_msg[:60]
            print(f"  [{username[:10]}] 失败: {reason}")
            return {"account": username, "success": False, "status": "error", "reason": reason}
        finally:
            slot_queue.put(window_slot)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for acc in accounts:
            if stop_flag["stopped"]:
                results.append({"account": acc["username"], "success": False, "status": "skipped", "reason": "卡已用完"})
                continue
            futures.append(executor.submit(worker, acc))
            time.sleep(THREAD_START_DELAY)
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # 收集有 checkout_url 但支付失败的，换IP重试一轮
    retry_accounts = []
    for acc in accounts:
        r = next((r for r in results if r["account"] == acc["username"]), None)
        if r and not r["success"] and r["status"] not in ("skipped", "not_zero") and acc.get("_checkout_url"):
            retry_accounts.append(acc)

    if retry_accounts and not stop_flag["stopped"]:
        print(f"\n{'='*60}")
        print(f"  重试轮: {len(retry_accounts)} 个有支付链接但失败的账号，换IP重试...")
        print(f"{'='*60}\n")

        def retry_worker(acc):
            username = acc["username"]
            window_slot = slot_queue.get()
            try:
                if stop_flag["stopped"]:
                    return {"account": username, "success": False, "status": "skipped", "reason": "停止"}
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
                        return {"account": username, "success": False, "status": "error", "reason": "无卡"}
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
                # 更新 results
                for i, old_r in enumerate(results):
                    if old_r["account"] == r["account"]:
                        results[i] = r
                        break

    # 保存失败的（跳过的不保存）
    for r in results:
        if not r["success"] and r["status"] != "skipped":
            acc = next((a for a in accounts if a["username"] == r["account"]), None)
            if acc:
                storage.save_failed(acc["username"], acc["password"], acc["totp"], r.get("reason", r["status"]))

    # 汇总
    ok = sum(1 for r in results if r["success"])
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"\n{'='*60}")
    print(f"  完成! 成功: {ok}/{len(results)}" + (f" | 跳过(无卡): {skipped}" if skipped else ""))
    print(f"{'='*60}")
    for r in results:
        icon = "[OK]" if r["success"] else "[--]" if r["status"] == "skipped" else "[X]"
        extra = f" ({r.get('reason', r['status'])})" if not r["success"] else ""
        print(f"  {icon} {r['account']}{extra}")


if __name__ == "__main__":
    from pathlib import Path
    import threading

    ACCOUNTS_FILE = Path(__file__).parent.parent / "shujuku" / "传入账户.txt"
    _accounts_lock = threading.Lock()

    if not ACCOUNTS_FILE.exists():
        print(f"账户文件不存在: {ACCOUNTS_FILE}")
    else:
        lines = [l.strip() for l in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not lines:
            print("账户文件为空")
        else:
            print(f"[准备] 从文件读取 {len(lines)} 个账号")
            # 清空文件（全部取出）
            ACCOUNTS_FILE.write_text("", encoding="utf-8")
            batch_run("\n".join(lines))
