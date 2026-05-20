"""
Google OAuth 登录 - 用 BitBrowser 自动化完成
"""
import time
import uuid as uuid_mod
import pyotp
import requests
import cbor2
from DrissionPage import ChromiumPage, ChromiumOptions

from config import KIRO_BASE
import browser
from proxy import get_proxies_with_check


def _kvid():
    import secrets
    return f"{int(time.time()*1000)}-{''.join(secrets.choice('0123456789abcdefghijklmnopqrstuvwxyz') for _ in range(11))}"


def login(email, password, totp_secret, proxies, window_index=0):
    """
    Google OAuth 登录，返回 (token_info, page, browser_id)
    token_info 格式: {access_token, refresh_token, csrf_token, profile_arn, user_id, kvid}
    page: DrissionPage 对象（已登录状态，可复用于支付）
    browser_id: 用完后需要调用 browser.close + browser.delete
    """
    from proxy import get_proxies_with_check
    _, session_id = get_proxies_with_check()
    browser_id = browser.create(session_id, f"google_{email[:10]}")
    print(f"  [Google] BitBrowser 创建: {browser_id[:16]}...")

    try:
        debug_addr = browser.open_browser(browser_id, window_index)
        co = ChromiumOptions()
        co.set_address(debug_addr)
        page = ChromiumPage(co)

        # 启动网络监听，捕获 ExchangeToken 响应
        page.listen.start('ExchangeToken')

        page.get("https://app.kiro.dev/signin")
        time.sleep(3)

        # 点击 Google 登录按钮
        google_btn = page.ele('text:Google', timeout=10)
        if not google_btn:
            google_btn = page.ele('xpath://button[contains(., "Google")]', timeout=5)
        if google_btn:
            google_btn.click()
            print(f"  [Google] 点击 Google 登录按钮")
            time.sleep(6)
        else:
            raise RuntimeError("未找到 Google 登录按钮")

        # 填邮箱
        email_input = page.ele('#identifierId', timeout=10)
        if not email_input:
            raise RuntimeError(f"未找到邮箱输入框, URL: {page.url[:80]}")
        email_input.input(email)
        time.sleep(1)
        _click_next(page)
        print(f"  [Google] 邮箱已提交")
        time.sleep(6)

        # 填密码
        pwd_input = page.ele('xpath://input[@name="Passwd"]', timeout=10)
        if pwd_input:
            pwd_input.input(password)
            time.sleep(1)
            _click_next(page)
            print(f"  [Google] 密码已提交")
            time.sleep(6)
        else:
            body_text = page.run_js("return document.body ? document.body.innerText.substring(0, 200) : '';")
            raise RuntimeError(f"未找到密码输入框: {page.url[:80]} | {body_text[:100]}")

        # 检测手机扫码验证页面
        phone_verify = page.run_js("""
            var body = document.body ? document.body.innerText.toLowerCase() : '';
            if (body.includes('on your phone or tablet') || body.includes('在手机上') || body.includes('在您的手机')
                || body.includes('tap yes') || body.includes('check your phone') || body.includes('confirm it')
                || body.includes('device can') || body.includes('verify it')) return true;
            return false;
        """)
        if phone_verify:
            raise RuntimeError("需要手机扫码")

        # 填 TOTP
        totp_input = page.ele('xpath://input[@name="totpPin"]', timeout=8)
        if totp_input:
            if totp_secret.startswith("http"):
                try:
                    totp_resp = requests.get(totp_secret, timeout=10)
                    code = totp_resp.json().get("token", "")
                except Exception as e:
                    raise RuntimeError(f"获取2FA验证码失败: {e}")
            else:
                code = pyotp.TOTP(totp_secret.upper()).now()
            totp_input.input(code)
            time.sleep(1)
            _click_next(page)
            print(f"  [Google] TOTP 已提交: {code}")
            time.sleep(8)
        else:
            print(f"  [Google] 无 TOTP 页面")
            time.sleep(5)

        # 等待 Kiro 完成登录
        print(f"  [Google] 等待 Kiro 完成登录...")
        for _ in range(20):
            time.sleep(2)
            current_url = page.url
            if "app.kiro.dev" in current_url and "/signin" not in current_url:
                break
            if "consent" in current_url or "accounts.google.com" in current_url:
                _click_next(page)

        # 提取 cookies（包括 CsrfToken）
        time.sleep(3)
        cookies_list = page.cookies()
        token_data = {}
        for c in cookies_list:
            name = c.get('name', '') if isinstance(c, dict) else getattr(c, 'name', '')
            value = c.get('value', '') if isinstance(c, dict) else getattr(c, 'value', '')
            if name == 'AccessToken':
                token_data['access_token'] = value
            elif name == 'RefreshToken':
                token_data['refresh_token'] = value
            elif name == 'UserId':
                token_data['user_id'] = value
            elif name == 'CsrfToken':
                token_data['csrf_token'] = value

        if not token_data.get('access_token'):
            raise RuntimeError(f"未获取到 AccessToken, URL: {page.url[:80]}")

        # 从网络监听中获取 ExchangeToken 响应
        kvid = _kvid()
        csrf_token = ''
        profile_arn = ''

        # 等待并获取 ExchangeToken 的响应
        packet = page.listen.wait(timeout=5)
        if packet:
            try:
                resp_body = packet.response.body
                if resp_body:
                    data = cbor2.loads(resp_body)
                    csrf_token = data.get('csrfToken', '')
                    profile_arn = data.get('profileArn', '')
            except Exception as e:
                print(f"  [Google] 解析 ExchangeToken 响应失败: {e}")

        page.listen.stop()

        print(f"  [Google] 登录成功! UserId: {token_data['user_id'][:20]}...")
        if csrf_token:
            print(f"  [Google] CSRF: {csrf_token[:20]}...")
        else:
            print(f"  [Google] 警告: 未获取到 CSRF token")
        if profile_arn:
            print(f"  [Google] ProfileArn: {profile_arn[:40]}...")

        token_info = {
            "access_token": token_data['access_token'],
            "refresh_token": token_data['refresh_token'],
            "csrf_token": csrf_token,
            "profile_arn": profile_arn,
            "user_id": token_data['user_id'],
            "kvid": kvid,
        }
        return token_info, page, browser_id

    except Exception:
        browser.close(browser_id)
        browser.delete(browser_id)
        raise


def _click_next(page):
    page.run_js("""
        var buttons = document.querySelectorAll('button');
        for (var i = 0; i < buttons.length; i++) {
            var t = buttons[i].textContent.trim();
            if (t === 'Next' || t === '下一步' || t === 'Suivant' || t === 'Weiter' || t === 'Siguiente'
                || t.includes('Allow') || t.includes('Continue') || t.includes('允许') || t.includes('继续')) {
                buttons[i].click(); break;
            }
        }
    """)
