"""
Builder ID 注册/登录 - 用 BitBrowser + DrissionPage 自动化
直接翻译自 register.py 的 Playwright 流程
"""
import time
import random
import secrets
import requests
import cbor2
from DrissionPage import ChromiumPage, ChromiumOptions

from config import KIRO_BASE
import browser
from proxy import get_proxies_with_check

KIRO_PASSWORD = "YourPassword123!"
SIGNIN_URL = "https://app.kiro.dev/signin"

FIRST_NAMES = ["Aiden", "Caleb", "Dylan", "Finn", "Gavin", "Hunter", "Isaac", "Jace",
               "Kai", "Leo", "Miles", "Nolan", "Owen", "Parker", "Quinn", "Ryder",
               "Sienna", "Tessa", "Uma", "Vera", "Wren", "Xena", "Yara", "Zoe",
               "Archer", "Blake", "Cruz", "Dante", "Ellis", "Felix", "Grey", "Hugo"]
LAST_NAMES = ["Ashford", "Beckett", "Calloway", "Donovan", "Everett", "Fletcher", "Grayson", "Hartley",
              "Ingram", "Jennings", "Keller", "Lawson", "Mercer", "Norwood", "Oakley", "Preston",
              "Quinlan", "Ramsey", "Sinclair", "Thornton", "Underwood", "Vance", "Whitmore", "York",
              "Aldridge", "Brennan", "Chandler", "Dalton", "Emerson", "Farrell", "Garrison", "Holloway"]


def _kvid():
    return f"{int(time.time()*1000)}-{''.join(secrets.choice('0123456789abcdefghijklmnopqrstuvwxyz') for _ in range(11))}"


def _random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _wait_for_code(code_link, timeout=120):
    """轮询接码 API 获取验证码（不走代理，需要带 cookie）"""
    import urllib3
    urllib3.disable_warnings()
    print(f"  [接码] 轮询验证码...")
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "accept": "application/json, text/html, */*",
    }
    cookies = {"server_name_session": "your_session_cookie"}
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(code_link, headers=headers, cookies=cookies, timeout=10, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                # 格式: {"code": 0, "message": "SUCCESS", "data": {"code": "871435"}}
                if data.get("code") == 0 and data.get("data"):
                    code = data["data"].get("code", "")
                    if code and str(code).isdigit():
                        print(f"  [接码] 收到验证码: {code}")
                        return str(code)
                # 兼容: {"code": "324640"}
                raw_code = data.get("code", "")
                if isinstance(raw_code, str) and raw_code.isdigit() and len(raw_code) >= 4:
                    print(f"  [接码] 收到验证码: {raw_code}")
                    return raw_code
        except Exception:
            pass
        time.sleep(5)
    print("  [接码] 超时未收到验证码")
    return None


def login(email, code_link, proxies, window_index=0):
    """
    Builder ID 注册流程（翻译自 register.py）
    返回 (token_info, page, browser_id)
    """
    _, session_id = get_proxies_with_check()
    browser_id = browser.create(session_id, f"bid_{email[:10]}")
    print(f"  [BuilderID] BitBrowser 创建: {browser_id[:16]}...")

    try:
        debug_addr = browser.open_browser(browser_id, window_index)
        co = ChromiumOptions()
        co.set_address(debug_addr)
        page = ChromiumPage(co)
        page.listen.start('ExchangeToken')

        # 1. 打开登录页
        page.get(SIGNIN_URL)
        time.sleep(4)

        # 2. 点击 Builder ID
        bid_btn = page.ele('text:Builder ID', timeout=15)
        if not bid_btn:
            bid_btn = page.ele('xpath://button[contains(., "Builder ID")]', timeout=5)
        if not bid_btn:
            raise RuntimeError("未找到 Builder ID 按钮")
        bid_btn.click()
        print(f"  [BuilderID] 已点击 Builder ID 按钮")
        time.sleep(5)

        # 3. 等待跳转到 signin.aws，输入邮箱
        for _ in range(15):
            if "signin.aws" in page.url:
                break
            time.sleep(2)
        email_input = page.ele('xpath://input[@placeholder="username@example.com"]', timeout=30)
        if not email_input:
            email_input = page.ele('xpath://input[@type="email"]', timeout=5)
        if not email_input:
            raise RuntimeError(f"未找到邮箱输入框, URL: {page.url[:80]}")
        email_input.input(email)
        print(f"  [BuilderID] 已输入邮箱: {email}")
        time.sleep(1)

        # 4. 点击 Continue
        page.run_js("""
            var btn = document.querySelector('[data-testid="test-primary-button"]');
            if (!btn) { var bs = document.querySelectorAll('button'); for(var i=0;i<bs.length;i++){var t=bs[i].textContent.trim();if(t==='Continue'||t==='Next'){btn=bs[i];break;}}}
            if (btn) btn.click();
        """)
        print(f"  [BuilderID] 已点击 Continue")
        time.sleep(6)

        # 5. 判断是注册还是登录
        for _ in range(10):
            if "profile.aws" in page.url:
                break
            time.sleep(2)

        # 检查是否出现密码框（已注册）
        pwd_check = page.ele('xpath://input[@type="password"]', timeout=3)
        if pwd_check and "profile.aws" not in page.url:
            print(f"  [BuilderID] 账号已存在，输入密码登录...")
            pwd_check.input(KIRO_PASSWORD)
            time.sleep(1)
            page.run_js("""
                var btn = document.querySelector('[data-testid="test-primary-button"]');
                if (!btn) { var bs = document.querySelectorAll('button'); for(var i=0;i<bs.length;i++){if(bs[i].textContent.includes('Sign in')){btn=bs[i];break;}}}
                if (btn) btn.click();
            """)
            time.sleep(8)
            for _ in range(20):
                if "app.kiro.dev" in page.url and "/signin" not in page.url:
                    break
                time.sleep(2)
            return _extract_token(page, browser_id)

        # 注册流程：输入姓名
        name_input = page.ele('xpath://div[@data-testid="signup-full-name-input"]//input', timeout=10)
        if not name_input:
            name_input = page.ele('xpath://input[contains(@id,"name") or contains(@name,"name") or contains(@placeholder,"name")]', timeout=5)
        name = _random_name()
        if name_input:
            name_input.input(name)
            print(f"  [BuilderID] 已输入姓名: {name}")
        else:
            raise RuntimeError("未找到姓名输入框")
        time.sleep(1)

        # 6. 点击 Next
        page.run_js("""
            var btn = document.querySelector('[data-testid="signup-next-button"]');
            if (!btn) { var bs = document.querySelectorAll('button'); for(var i=0;i<bs.length;i++){var t=bs[i].textContent.trim();if(t==='Next'){btn=bs[i];break;}}}
            if (btn) btn.click();
        """)
        print(f"  [BuilderID] 已点击 Next")
        time.sleep(5)

        # 7. 等待验证码输入框，获取验证码
        code_input = page.ele('xpath://input[contains(@placeholder,"6-digit")]', timeout=15)
        if not code_input:
            code_input = page.ele('xpath://input[@type="tel" or @inputmode="numeric"]', timeout=5)
        if not code_input:
            raise RuntimeError("未找到验证码输入框")

        code = _wait_for_code(code_link)
        if not code:
            raise RuntimeError(f"未能获取验证码: {email}")
        code_input.input(code)
        print(f"  [BuilderID] 已输入验证码: {code}")
        time.sleep(1)

        # 8. 点击 Verify
        page.run_js("""
            var btn = document.querySelector('[data-testid="email-verification-verify-button"]');
            if (!btn) { var bs = document.querySelectorAll('button'); for(var i=0;i<bs.length;i++){if(bs[i].textContent.includes('Verify')){btn=bs[i];break;}}}
            if (btn) btn.click();
        """)
        print(f"  [BuilderID] 已点击 Verify")
        time.sleep(5)

        # 9. 输入密码
        pwd_input = page.ele('xpath://input[@placeholder="Enter password"]', timeout=15)
        confirm_input = page.ele('xpath://input[@placeholder="Re-enter password"]', timeout=5)
        if pwd_input:
            pwd_input.input(KIRO_PASSWORD)
            time.sleep(0.5)
        if confirm_input:
            confirm_input.input(KIRO_PASSWORD)
        print(f"  [BuilderID] 已输入密码")
        time.sleep(1)

        # 10. 提交并等待跳转
        page.run_js("""
            var btn = document.querySelector('[data-testid="test-primary-button"]');
            if (!btn) { var bs = document.querySelectorAll('button'); for(var i=0;i<bs.length;i++){var t=bs[i].textContent.trim();if(t.includes('Create')||t.includes('Continue')){btn=bs[i];break;}}}
            if (btn) btn.click();
        """)
        print(f"  [BuilderID] 等待跳转到 app.kiro.dev...")

        for _ in range(30):
            if "app.kiro.dev" in page.url and "/signin" not in page.url:
                break
            time.sleep(2)

        return _extract_token(page, browser_id)

    except Exception:
        browser.close(browser_id)
        browser.delete(browser_id)
        raise


def _extract_token(page, browser_id):
    """从已登录的页面提取 token 信息，并主动获取 profileArn 和 csrfToken"""
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

    kvid = _kvid()
    csrf_token = token_data.get('csrf_token', '')
    profile_arn = ''

    packet = page.listen.wait(timeout=5)
    if packet:
        try:
            resp_body = packet.response.body
            if resp_body:
                data = cbor2.loads(resp_body)
                csrf_token = data.get('csrfToken', csrf_token)
                profile_arn = data.get('profileArn', '')
        except Exception:
            pass

    page.listen.stop()

    # 如果没拿到 profileArn 或 csrfToken，主动调 API 获取
    if not profile_arn or not csrf_token:
        import urllib3
        urllib3.disable_warnings()
        try:
            api_headers = {
                "accept": "application/cbor", "content-type": "application/cbor", "smithy-protocol": "rpc-v2-cbor",
                "authorization": f"Bearer {token_data['access_token']}",
                "x-kiro-visitorid": kvid, "x-kiro-userid": token_data["user_id"],
                "origin": KIRO_BASE,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
                "cookie": f"AccessToken={token_data['access_token']}; RefreshToken={token_data.get('refresh_token', '')}; UserId={token_data['user_id']}; kiro-visitor-id={kvid}",
            }
            resp = requests.post(f"{KIRO_BASE}/service/KiroWebPortalService/operation/GetUserUsageAndLimits",
                data=cbor2.dumps({"origin": "KIRO_IDE", "isEmailRequired": False}),
                headers=api_headers, timeout=15, verify=False)
            if resp.status_code == 200:
                r = cbor2.loads(resp.content)
                profile_arn = r.get("profileArn", profile_arn)
                csrf_from_resp = resp.headers.get("x-csrf-token", "")
                if csrf_from_resp:
                    csrf_token = csrf_from_resp
        except Exception as e:
            print(f"  [BuilderID] 获取 profileArn 失败: {e}")

    # Builder ID 用户的 profileArn 是固定值
    if not profile_arn:
        profile_arn = "arn:aws:codewhisperer:us-east-1:000000000000:profile/PLACEHOLDER"

    print(f"  [BuilderID] 注册/登录成功! UserId: {token_data['user_id'][:20]}...")
    if profile_arn:
        print(f"  [BuilderID] ProfileArn: {profile_arn[:50]}...")

    token_info = {
        "access_token": token_data['access_token'],
        "refresh_token": token_data.get('refresh_token', ''),
        "csrf_token": csrf_token,
        "profile_arn": profile_arn,
        "user_id": token_data['user_id'],
        "kvid": kvid,
        "idp": "",
    }
    return token_info, page, browser_id
