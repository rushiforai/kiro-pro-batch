"""
Kiro Pro 批量开通 - Web UI
Flask + 实时状态轮询
"""
import sys
import os
import json
import time
import threading
import re as _re
from pathlib import Path
from flask import Flask, render_template, request, jsonify

SCRIPT_DIR = Path(__file__).parent
SHUJUKU_DIR = Path(__file__).parent.parent / "shujuku"

app = Flask(__name__, template_folder=str(SCRIPT_DIR / "templates"))

task_state = {
    "running": False,
    "accounts": [],
    "stats": {"total": 0, "success": 0, "failed": 0, "running": 0, "skipped": 0},
    "config": {},
    "history": [],
}
_state_lock = threading.Lock()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/state')
def get_state():
    with _state_lock:
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            import importlib
            import config as cfg
            importlib.reload(cfg)
            task_state["config"] = {
                "workers": cfg.MAX_WORKERS,
                "plan": cfg.SUBSCRIPTION_PLAN,
                "channel": cfg.CARD_CHANNEL,
                "per_card": cfg.ACCOUNTS_PER_CARD,
            }
        except Exception:
            pass
        return jsonify(task_state)


@app.route('/api/import-accounts', methods=['POST'])
def import_accounts():
    data = request.json
    text = data.get("text", "")
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    SHUJUKU_DIR.mkdir(exist_ok=True)
    (SHUJUKU_DIR / "传入账户.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    accounts = []
    for line in lines:
        parts = line.split("----")
        if len(parts) == 4:
            accounts.append({"username": parts[0], "mode": "google", "status": "waiting", "status_text": "等待", "detail": "", "elapsed": ""})
        elif len(parts) == 3:
            accounts.append({"username": parts[0], "mode": "google", "status": "waiting", "status_text": "等待", "detail": "", "elapsed": ""})
        elif len(parts) == 2:
            accounts.append({"username": parts[0], "mode": "builderid", "status": "waiting", "status_text": "等待", "detail": "", "elapsed": ""})
    with _state_lock:
        task_state["accounts"] = accounts
        task_state["stats"] = {"total": len(accounts), "success": 0, "failed": 0, "running": 0, "skipped": 0}
    return jsonify({"message": f"已导入 {len(accounts)} 个账号"})


@app.route('/api/import-cards', methods=['POST'])
def import_cards():
    data = request.json
    text = data.get("text", "")
    codes = [c.strip() for c in text.replace("\n", ",").split(",") if c.strip()]
    SHUJUKU_DIR.mkdir(exist_ok=True)
    (SHUJUKU_DIR / "华开卡.txt").write_text("\n".join(codes) + "\n", encoding="utf-8")
    return jsonify({"message": f"已导入 {len(codes)} 张卡密"})


@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.json
    config_path = SCRIPT_DIR / "config.py"
    content = config_path.read_text(encoding="utf-8")
    if "workers" in data:
        content = _re.sub(r'MAX_WORKERS\s*=\s*\d+', f'MAX_WORKERS = {data["workers"]}', content)
    if "plan" in data:
        content = _re.sub(r'SUBSCRIPTION_PLAN\s*=\s*"[^"]*"', f'SUBSCRIPTION_PLAN = "{data["plan"]}"', content)
    if "channel" in data:
        content = _re.sub(r'CARD_CHANNEL\s*=\s*"[^"]*"', f'CARD_CHANNEL = "{data["channel"]}"', content)
    if "per_card" in data:
        content = _re.sub(r'ACCOUNTS_PER_CARD\s*=\s*\d+', f'ACCOUNTS_PER_CARD = {data["per_card"]}', content)
    config_path.write_text(content, encoding="utf-8")
    return jsonify({"message": "配置已保存"})


@app.route('/api/start', methods=['POST'])
def start_task():
    if task_state["running"]:
        return jsonify({"message": "任务已在运行中"})
    t = threading.Thread(target=_run_task, daemon=True)
    t.start()
    return jsonify({"message": "任务已启动"})


@app.route('/api/stop', methods=['POST'])
def stop_task():
    task_state["running"] = False
    return jsonify({"message": "正在停止..."})


def _update_account(username, **kwargs):
    with _state_lock:
        for acc in task_state["accounts"]:
            if acc["username"] == username:
                acc.update(kwargs)
                break
        stats = {"total": len(task_state["accounts"]), "success": 0, "failed": 0, "running": 0, "skipped": 0}
        for acc in task_state["accounts"]:
            if acc["status"] == "success":
                stats["success"] += 1
            elif acc["status"] == "failed":
                stats["failed"] += 1
            elif acc["status"] in ("login", "checkout", "paying"):
                stats["running"] += 1
            elif acc["status"] == "skipped":
                stats["skipped"] += 1
        task_state["stats"] = stats


def _run_task():
    task_state["running"] = True
    accounts_file = SHUJUKU_DIR / "传入账户.txt"
    if not accounts_file.exists():
        task_state["running"] = False
        return

    lines = [l.strip() for l in accounts_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        task_state["running"] = False
        return

    accounts_file.write_text("", encoding="utf-8")

    sys.path.insert(0, str(SCRIPT_DIR))
    os.chdir(str(SCRIPT_DIR))

    import builtins
    original_print = builtins.print

    def patched_print(*args, **kwargs):
        msg = " ".join(str(a) for a in args)
        for acc in task_state["accounts"]:
            if acc["username"] in msg:
                if "登录" in msg and "成功" not in msg:
                    _update_account(acc["username"], status="login", detail=msg[-60:])
                elif "Checkout" in msg:
                    _update_account(acc["username"], status="checkout", detail="")
                elif "支付" in msg or "Stripe" in msg:
                    _update_account(acc["username"], status="paying", detail=msg[-60:])
                elif "凭据已保存" in msg or "[OK]" in msg:
                    _update_account(acc["username"], status="success", detail="Pro已开通")
                elif "失败" in msg:
                    _update_account(acc["username"], status="failed", detail=msg[-60:])
                break
        original_print(*args, **kwargs)

    builtins.print = patched_print
    try:
        import main
        import importlib
        importlib.reload(main)
        main.batch_run("\n".join(lines))
    except Exception as e:
        original_print(f"任务异常: {e}")
    finally:
        builtins.print = original_print
        task_state["running"] = False
        with _state_lock:
            task_state["history"].insert(0, {
                "time": time.strftime("%Y-%m-%d %H:%M"),
                "total": task_state["stats"]["total"],
                "success": task_state["stats"]["success"],
                "failed": task_state["stats"]["failed"],
            })
            if len(task_state["history"]) > 20:
                task_state["history"] = task_state["history"][:20]


if __name__ == "__main__":
    print("Kiro Pro Web UI: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
