import csv
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List

from app.config import load_config, save_config, BASE_DIR
from app.gmail_client import GmailClient
from app.scheduler import ScanManager
from app.database import db_session, log_activity

router = APIRouter(prefix="", tags=["settings"])

class SettingsUpdate(BaseModel):
    gmail_user: Optional[str] = None
    gmail_app_password: Optional[str] = None
    gatekeeper_enabled: Optional[bool] = None
    gatekeeper_auto_challenge: Optional[bool] = None
    challenge_subject: Optional[str] = None
    challenge_template: Optional[str] = None
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval_minutes: Optional[int] = None
    vip_keywords: Optional[List[str]] = None

class ScanRequest(BaseModel):
    limit: int = 500

@router.get("/settings")
def get_settings():
    conf = load_config()
    # Mask password for UI
    safe_conf = conf.copy()
    pw = safe_conf.get("gmail_app_password", "")
    if len(pw) > 4:
        safe_conf["gmail_app_password_masked"] = pw[:2] + ("*" * (len(pw) - 4)) + pw[-2:]
    else:
        safe_conf["gmail_app_password_masked"] = "****"
    return safe_conf

@router.post("/settings")
def update_settings(update: SettingsUpdate):
    data = update.model_dump(exclude_unset=True)
    # Strip spaces from app password if updated
    if "gmail_app_password" in data and data["gmail_app_password"]:
        data["gmail_app_password"] = data["gmail_app_password"].replace(" ", "")
    saved = save_config(data)
    log_activity("settings_update", "Updated system settings.")
    return {"status": "success", "settings": saved}

@router.post("/settings/test-connection")
def test_connection():
    client = GmailClient()
    success, msg = client.test_connection()
    return {"success": success, "message": msg}

@router.get("/scan/status")
def get_scan_status():
    mgr = ScanManager.get_instance()
    return {
        "is_scanning": mgr.is_scanning,
        "last_scan_time": mgr.last_scan_time,
        "last_scan_result": mgr.last_scan_result
    }

@router.post("/scan/trigger")
def trigger_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    mgr = ScanManager.get_instance()
    if mgr.is_scanning:
        return {"status": "busy", "message": "Scan already in progress."}

    background_tasks.add_task(mgr.run_scan, limit=req.limit)
    return {"status": "started", "message": f"Inbox triage scan started for up to {req.limit} emails."}

@router.post("/scan/import-preview-csv")
def import_preview_csv():
    """Import existing scan data from email_cleaner/preview_cleanup.csv if available."""
    old_csv_path = Path("C:/Users/FERANMI/.gemini/antigravity/scratch/email_cleaner/preview_cleanup.csv")
    if not old_csv_path.exists():
        return {"status": "not_found", "message": "No existing preview_cleanup.csv found."}

    imported_count = 0
    try:
        with open(old_csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            from app.gmail_client import parse_sender_info
            from datetime import datetime
            
            with db_session() as conn:
                for row in reader:
                    sender_raw = row.get("sender", "")
                    name, email_addr = parse_sender_info(sender_raw)
                    if not email_addr:
                        continue
                    
                    conn.execute("""
                    INSERT INTO senders (email, name, category, total_received, total_read, open_rate, first_seen, last_seen, clutter_score)
                    VALUES (?, ?, 'subscription', 1, 0, 0.0, ?, ?, 75.0)
                    ON CONFLICT(email) DO UPDATE SET
                        total_received = total_received + 1,
                        last_seen = excluded.last_seen
                    """, (email_addr, name, datetime.utcnow().isoformat(), row.get("date", "")))
                    imported_count += 1

        log_activity("imported_csv", f"Imported {imported_count} records from previous cleaner run.")
        return {"status": "success", "imported": imported_count}
    except Exception as e:
        return {"status": "error", "message": str(e)}
