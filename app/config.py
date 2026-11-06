import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Lightweight zero-dependency .env loader (only used locally, not on Vercel)
def _load_env_file(filepath: Path):
    if not filepath.exists():
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

_load_env_file(BASE_DIR / ".env")

# On Vercel, /tmp is the only writable directory
IS_VERCEL = bool(os.getenv("VERCEL"))
DATA_DIR = Path("/tmp/zeninbox_data") if IS_VERCEL else (BASE_DIR / "data")

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

CONFIG_FILE = DATA_DIR / "settings.json"

DEFAULT_CONFIG = {
    "gmail_user": "",
    "gmail_app_password": "",
    "access_pin": "",
    "imap_server": "imap.gmail.com",
    "imap_port": 993,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 465,
    "gated_folder": "ZenInbox/Gated",
    "rollup_folder": "ZenInbox/Rollup",
    "trash_folder": "[Gmail]/Trash",
    "auto_sync_enabled": False,
    "auto_sync_interval_minutes": 15,
    "gatekeeper_enabled": True,
    "gatekeeper_auto_challenge": False,
    "challenge_subject": "Attention required: Verify to reach my Priority Inbox",
    "challenge_template": (
        "Hi,\n\n"
        "I use ZenInbox (an intelligent gatekeeper) to guard my inbox against unsolicited email. "
        "Your message was held in my quarantine folder.\n\n"
        "If your email is important and direct 1-to-1 correspondence, please reply to this message "
        "with 'VERIFIED' in the subject line or body to be automatically added to my allowlist.\n\n"
        "Thank you!"
    ),
    "vip_keywords": [
        "selar", "ileoja", "receipt", "invoice", "payment",
        "order confirmation", "e-ticket", "statement", "transaction",
        "salary", "bank", "payslip", "security alert", "otp", "verification code",
        "gtco", "access bank", "zenith", "kuda", "moniepoint", "opay"
    ],
    "batch_scan_limit": 1000
}

def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_conf = json.load(f)
                config.update(user_conf)
        except Exception:
            pass
    # Always let environment variables win
    for env_key, cfg_key in [
        ("GMAIL_USER", "gmail_user"),
        ("GMAIL_APP_PASSWORD", "gmail_app_password"),
        ("ACCESS_PIN", "access_pin"),
    ]:
        v = os.getenv(env_key)
        if v:
            config[cfg_key] = v
    return config

def save_config(new_config: dict) -> dict:
    current = load_config()
    current.update(new_config)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception as e:
        print(f"[Config Save Warning] Could not write to {CONFIG_FILE}: {e}")
    return current
