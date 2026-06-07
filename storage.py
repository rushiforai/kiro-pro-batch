"""
File persistence - Success/failure account persistence
"""
import json
import threading
from pathlib import Path

_file_lock = threading.Lock()
SCRIPT_DIR = Path(__file__).parent


def save_success(username, password, totp, token_info):
    """Save successful account to output/credentials.txt"""
    output_dir = SCRIPT_DIR / "output"
    output_dir.mkdir(exist_ok=True)
    token_data = {
        "accessToken": token_info["access_token"],
        "refreshToken": token_info["refresh_token"],
        "clientId": "",
        "clientSecret": "",
    }
    card_file = output_dir / "credentials.txt"
    line = f"{username}----{password}----{totp}{json.dumps(token_data, ensure_ascii=False)}\n"
    with _file_lock:
        with open(card_file, "a", encoding="utf-8") as f:
            f.write(line)
    print(f"  [OK] Credentials saved: output/credentials.txt")


def save_failed(username, password, totp, reason="unknown"):
    """Save failed account (with reason)"""
    failed_dir = SCRIPT_DIR / "sold_account_passwords"
    failed_dir.mkdir(exist_ok=True)
    failed_file = failed_dir / "failed_accounts.txt"
    line = f"{username}----{password}----{totp}----{reason}\n"
    with _file_lock:
        with open(failed_file, "a", encoding="utf-8") as f:
            f.write(line)
