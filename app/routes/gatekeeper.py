from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import db_session, log_activity
from app.gatekeeper import GatekeeperEngine

router = APIRouter(prefix="/api/gatekeeper", tags=["gatekeeper"])

class AllowlistEntry(BaseModel):
    pattern: str
    type: str = "email"
    reason: Optional[str] = "Manual entry"

class BlocklistEntry(BaseModel):
    pattern: str
    type: str = "email"
    reason: Optional[str] = "Manual entry"

@router.get("/quarantine")
def list_quarantine():
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM quarantine_items WHERE status = 'pending' ORDER BY id DESC")
        items = [dict(r) for r in cursor.fetchall()]
    return {"items": items}

@router.post("/quarantine/{item_id}/approve")
def approve_quarantine(item_id: int):
    engine = GatekeeperEngine()
    success = engine.approve_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Quarantine item not found")
    return {"status": "success", "message": "Email moved to INBOX and sender added to Allowlist."}

@router.post("/quarantine/{item_id}/block")
def block_quarantine(item_id: int):
    engine = GatekeeperEngine()
    success = engine.block_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Quarantine item not found")
    return {"status": "success", "message": "Email moved to Trash and sender blocked."}

@router.post("/quarantine/{item_id}/challenge")
def send_quarantine_challenge(item_id: int):
    engine = GatekeeperEngine()
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM quarantine_items WHERE id = ?", (item_id,))
        item = cursor.fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Quarantine item not found")

        engine.send_challenge(item["sender_email"], item["subject"])
        cursor.execute("UPDATE quarantine_items SET challenge_sent_at = ? WHERE id = ?", (datetime.utcnow().isoformat(), item_id))

    return {"status": "success", "message": f"Verification challenge sent to {item['sender_email']}."}

@router.get("/allowlist")
def get_allowlist():
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM allowlist ORDER BY id DESC")
        rules = [dict(r) for r in cursor.fetchall()]
    return {"allowlist": rules}

@router.post("/allowlist")
def add_allowlist_rule(entry: AllowlistEntry):
    with db_session() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO allowlist (pattern, type, reason, created_at)
        VALUES (?, ?, ?, ?)
        """, (entry.pattern.strip().lower(), entry.type, entry.reason, datetime.utcnow().isoformat()))
    log_activity("allowlist_add", f"Added {entry.pattern} to allowlist ({entry.type})")
    return {"status": "success", "message": f"Added {entry.pattern} to allowlist."}

@router.delete("/allowlist/{rule_id}")
def delete_allowlist_rule(rule_id: int):
    with db_session() as conn:
        conn.execute("DELETE FROM allowlist WHERE id = ?", (rule_id,))
    return {"status": "success"}

@router.get("/blocklist")
def get_blocklist():
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM blocklist ORDER BY id DESC")
        rules = [dict(r) for r in cursor.fetchall()]
    return {"blocklist": rules}

@router.post("/blocklist")
def add_blocklist_rule(entry: BlocklistEntry):
    with db_session() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO blocklist (pattern, type, reason, created_at)
        VALUES (?, ?, ?, ?)
        """, (entry.pattern.strip().lower(), entry.type, entry.reason, datetime.utcnow().isoformat()))
    log_activity("blocklist_add", f"Added {entry.pattern} to blocklist ({entry.type})")
    return {"status": "success", "message": f"Added {entry.pattern} to blocklist."}

@router.delete("/blocklist/{rule_id}")
def delete_blocklist_rule(rule_id: int):
    with db_session() as conn:
        conn.execute("DELETE FROM blocklist WHERE id = ?", (rule_id,))
    return {"status": "success"}
