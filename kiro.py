"""
Kiro subscription management - Get Checkout URL, check status, enable overage
"""
import time
import uuid as uuid_mod
import requests
import cbor2

from config import KIRO_BASE, SUBSCRIPTION_PLAN


def get_checkout_url(token_info, proxies):
    """Get Stripe Checkout URL"""
    headers = _make_headers(token_info)
    sub_type_map = {"pro": "Q_DEVELOPER_STANDALONE_PRO", "pro+": "Q_DEVELOPER_STANDALONE_PRO_PLUS"}
    sub_type_value = sub_type_map.get(SUBSCRIPTION_PLAN, "Q_DEVELOPER_STANDALONE_PRO")
    resp = _request_with_retry('POST', f"{KIRO_BASE}/service/KiroWebPortalService/operation/GenerateSubscriptionManagementUrl",
        data=cbor2.dumps({"subscriptionType": sub_type_value, "profileArn": token_info.get("profile_arn", "")}), headers=headers, timeout=15, proxies=proxies)
    r = cbor2.loads(resp.content)
    checkout_url = r.get("encodedVerificationUrl", "")
    if not checkout_url:
        raise RuntimeError(f"Failed to get Checkout URL: {r}")
    return checkout_url


def check_subscription(token_info, proxies):
    """Query subscription status, return type string"""
    headers = _make_headers(token_info)
    resp = _request_with_retry('POST', f"{KIRO_BASE}/service/KiroWebPortalService/operation/GetUserUsageAndLimits",
        data=cbor2.dumps({"origin": "KIRO_IDE", "isEmailRequired": False, "profileArn": token_info.get("profile_arn", "")}),
        headers=headers, timeout=15, proxies=proxies)
    if resp.status_code == 200:
        r = cbor2.loads(resp.content)
        return r.get("subscriptionInfo", {}).get("type", "")
    return ""


def _request_with_retry(method, url, max_retries=3, **kwargs):
    """Request with retry, handle proxy SSL disconnect"""
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, **kwargs)
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.SSLError) as e:
            if attempt < max_retries - 1:
                print(f"  [Network] Connection error, retrying... ({attempt+1}/{max_retries})")
                time.sleep(3)
            else:
                raise


def enable_overage(token_info, proxies):
    """Enable overage, poll to confirm"""
    headers = _make_headers(token_info)
    update_body = cbor2.dumps({"overageConfiguration": {"overageEnabled": True}, "profileArn": token_info["profile_arn"]})
    check_body = cbor2.dumps({"origin": "KIRO_IDE", "isEmailRequired": True, "profileArn": token_info["profile_arn"]})

    print("  [Overage] Sending UpdateBillingPreferences...")
    _request_with_retry('POST', f"{KIRO_BASE}/service/KiroWebPortalService/operation/UpdateBillingPreferences",
        data=update_body, headers={**headers, "amz-sdk-invocation-id": str(uuid_mod.uuid4())}, timeout=15, proxies=proxies)

    for i, wait in enumerate([40, 35, 30, 25]):
        print(f"  [Overage] Waiting {wait}s before check {i+1}...")
        time.sleep(wait)
        _request_with_retry('POST', f"{KIRO_BASE}/service/KiroWebPortalService/operation/UpdateBillingPreferences",
            data=update_body, headers={**headers, "amz-sdk-invocation-id": str(uuid_mod.uuid4())}, timeout=15, proxies=proxies)
        resp = _request_with_retry('POST', f"{KIRO_BASE}/service/KiroWebPortalService/operation/GetUserUsageAndLimits",
            data=check_body, headers={**headers, "amz-sdk-invocation-id": str(uuid_mod.uuid4())}, timeout=15, proxies=proxies)
        if resp.status_code == 200:
            r = cbor2.loads(resp.content)
            enabled = r.get("overageConfiguration", {}).get("overageEnabled", False)
            print(f"  [Overage] Check {i+1}: overageEnabled = {enabled}")
            if enabled:
                print("  [Overage] Overage successfully enabled!")
                return True
    print("  [Overage] 4 checks all failed to confirm enabling")
    return False


def _make_headers(token_info):
    kvid = token_info["kvid"]
    idp = token_info.get("idp", "Google")
    cookie_parts = [
        f"AccessToken={token_info['access_token']}",
        f"RefreshToken={token_info['refresh_token']}",
        f"UserId={token_info['user_id']}",
        f"kiro-visitor-id={kvid}",
    ]
    if idp:
        cookie_parts.insert(2, f"Idp={idp}")
    return {
        "accept": "application/cbor", "content-type": "application/cbor", "smithy-protocol": "rpc-v2-cbor",
        "authorization": f"Bearer {token_info['access_token']}", "x-csrf-token": token_info.get("csrf_token", ""),
        "x-kiro-visitorid": kvid, "x-kiro-userid": token_info["user_id"],
        "amz-sdk-invocation-id": str(uuid_mod.uuid4()), "amz-sdk-request": "attempt=1; max=1",
        "origin": KIRO_BASE,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "cookie": "; ".join(cookie_parts),
    }
