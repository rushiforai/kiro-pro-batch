"""
GitHub OAuth 纯协议登录 - 不需要浏览器
"""
import re
import time
import secrets
import hashlib
import base64
import uuid as uuid_mod
from urllib.parse import parse_qs, urlparse

import cbor2
import pyotp
import requests
import urllib3

urllib3.disable_warnings()

KIRO_BASE = "https://app.kiro.dev"


def _kvid():
    return f"{int(time.time()*1000)}-{''.join(secrets.choice('0123456789abcdefghijklmnopqrstuvwxyz') for _ in range(11))}"


def login(github_username, github_password, totp_secret, proxies):
    """纯协议完成 GitHub OAuth 登录，返回 token_info dict"""
    kvid = _kvid()
    cv = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    cc = base64.urlsafe_b64encode(hashlib.sha256(cv.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_hex(16)

    resp = requests.post(f"{KIRO_BASE}/service/KiroWebPortalService/operation/InitiateLogin",
        data=cbor2.dumps({"idp": "Github", "redirectUri": "https://app.kiro.dev/signin/oauth", "codeChallenge": cc, "codeChallengeMethod": "S256", "state": state}),
        headers={"Accept": "application/cbor", "Content-Type": "application/cbor", "smithy-protocol": "rpc-v2-cbor",
                 "User-Agent": "Mozilla/5.0", "Origin": KIRO_BASE, "x-kiro-visitorid": kvid,
                 "amz-sdk-invocation-id": str(uuid_mod.uuid4()), "amz-sdk-request": "attempt=1; max=1",
                 "Cookie": f"kiro-visitor-id={kvid}"},
        timeout=15, proxies=proxies, verify=False)
    rd = cbor2.loads(resp.content)
    rurl = rd["redirectUrl"]
    kst = parse_qs(urlparse(rurl).query).get("state", [""])[0]

    s = requests.Session()
    s.proxies = proxies
    s.verify = False
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"})

    r = s.get(rurl, allow_redirects=True)
    at_match = re.search(r'name="authenticity_token" value="([^"]+)"', r.text)
    if not at_match:
        raise RuntimeError(f"GitHub 登录页解析失败: {r.url[:80]}")
    at = at_match.group(1)
    rtm = re.search(r'name="return_to" value="([^"]*)"', r.text)

    r = s.post("https://github.com/session",
        data={"commit": "Sign in", "authenticity_token": at, "login": github_username,
              "password": github_password, "return_to": rtm.group(1) if rtm else ""},
        allow_redirects=True)

    at_match = re.search(r'name="authenticity_token" value="([^"]+)"', r.text)
    if not at_match:
        raise RuntimeError(f"GitHub 密码提交后解析失败: {r.url[:80]}")
    at = at_match.group(1)

    # TOTP
    if totp_secret.startswith("http"):
        totp_resp = requests.get(totp_secret, timeout=10, verify=False)
        otp_code = totp_resp.json().get("token", "")
    else:
        otp_code = pyotp.TOTP(totp_secret.upper()).now()

    r = s.post("https://github.com/sessions/two-factor",
        data={"authenticity_token": at, "app_otp": otp_code},
        allow_redirects=True)

    r = s.get(rurl, allow_redirects=True)
    if "/login/oauth/authorize" in r.url:
        hf = dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', r.text))
        hf["authorize"] = "1"
        r = s.post(r.url, data=hf, allow_redirects=True)

    code = parse_qs(urlparse(r.url).query).get("code", [""])[0]
    if not code:
        raise RuntimeError(f"GitHub OAuth 未获取到 code, url={r.url[:100]}")

    sess = requests.Session()
    sess.proxies = proxies
    sess.verify = False
    resp = sess.post(f"{KIRO_BASE}/service/KiroWebPortalService/operation/ExchangeToken",
        data=cbor2.dumps({"idp": "Github", "code": code, "codeVerifier": cv,
                         "redirectUri": "https://app.kiro.dev/signin/oauth", "state": kst}),
        headers={"Accept": "application/cbor", "Content-Type": "application/cbor", "smithy-protocol": "rpc-v2-cbor",
                 "User-Agent": "Mozilla/5.0", "Origin": KIRO_BASE, "x-kiro-visitorid": kvid,
                 "amz-sdk-invocation-id": str(uuid_mod.uuid4()), "amz-sdk-request": "attempt=1; max=1",
                 "Cookie": f"kiro-visitor-id={kvid}"},
        timeout=15)
    result = cbor2.loads(resp.content)
    access_token = result["accessToken"]
    csrf_token = result["csrfToken"]
    profile_arn = result["profileArn"]
    cookies_dict = {c.name: c.value for c in sess.cookies}
    user_id = cookies_dict.get("UserId", "")
    refresh_token = cookies_dict.get("RefreshToken", "")

    print(f"  [GitHub] 协议登录成功! UserId: {user_id[:20]}...")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "csrf_token": csrf_token,
        "profile_arn": profile_arn,
        "user_id": user_id,
        "kvid": kvid,
        "idp": "Github",
    }
