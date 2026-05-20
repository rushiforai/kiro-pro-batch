"""
文件保存 - 成功/失败账号的持久化
"""
import json
import threading
from pathlib import Path

_file_lock = threading.Lock()
SCRIPT_DIR = Path(__file__).parent


def save_success(username, password, totp, token_info):
    """保存成功开通的账号到 output/卡密.txt"""
    output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(exist_ok=True)
    token_data = {
        "accessToken": token_info["access_token"],
        "refreshToken": token_info["refresh_token"],
        "clientId": "",
        "clientSecret": "",
    }
    card_file = output_dir / "卡密.txt"
    line = f"{username}----{password}----{totp}{json.dumps(token_data, ensure_ascii=False)}\n"
    with _file_lock:
        with open(card_file, "a", encoding="utf-8") as f:
            f.write(line)
    print(f"  [OK] 凭据已保存: output/卡密.txt")


def save_failed(username, password, totp, reason="unknown"):
    """保存失败的号（带原因）"""
    failed_dir = SCRIPT_DIR / "已卖出的账户密码"
    failed_dir.mkdir(exist_ok=True)
    failed_file = failed_dir / "失败的号.txt"
    line = f"{username}----{password}----{totp}----{reason}\n"
    with _file_lock:
        with open(failed_file, "a", encoding="utf-8") as f:
            f.write(line)
