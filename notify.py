import json
import os
from datetime import datetime

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE, "eval-results")
ALERT_LOG = os.path.join(LOG_DIR, "alerts.log")
CONFIG = os.path.join(BASE, "alerts_config.json")
os.makedirs(LOG_DIR, exist_ok=True)


def alert(message):
    line = f"{datetime.now().isoformat(timespec='seconds')} ALERT: {message}"
    print("\n" + line)
    try:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        if os.path.exists(CONFIG):
            with open(CONFIG, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            if cfg.get("telegram_token") and cfg.get("telegram_chat_id"):
                requests.post(f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage",
                              json={"chat_id": cfg["telegram_chat_id"], "text": line}, timeout=10)
    except Exception as e:
        print("(could not send the Telegram message:", type(e).__name__, ")")
