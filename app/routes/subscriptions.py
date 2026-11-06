from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.database import db_session
from app.cleanfox import CleanfoxEngine
from app.unroll import UnrollEngine

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

class SubscriptionActionRequest(BaseModel):
    emails: List[str]
    action: str  # 'keep', 'keep_newest_only', 'rollup', 'unsubscribe_and_delete'

class BulkCleanRequest(BaseModel):
    max_open_rate: float = 0.15
    min_emails: int = 2

class PruneAllRequest(BaseModel):
    keep_count: int = 1

@router.get("")
def list_subscriptions(
    filter: str = "all",
    search: Optional[str] = None,
    sort: str = "clutter_desc"
):
    with db_session() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM senders WHERE 1=1"
        params = []

        if filter == "subscription":
            query += " AND category = 'subscription'"
        elif filter == "rollup":
            query += " AND action_preference = 'rollup'"
        elif filter == "keep_newest":
            query += " AND action_preference = 'keep_newest_only'"
        elif filter == "unsubscribed":
            query += " AND action_preference = 'unsubscribe_and_delete'"
        elif filter == "low_open_rate":
            query += " AND open_rate <= 0.15 AND total_received >= 2"

        if search:
            query += " AND (email LIKE ? OR name LIKE ?)"
            s_param = f"%{search.strip().lower()}%"
            params.extend([s_param, s_param])

        if sort == "clutter_desc":
            query += " ORDER BY clutter_score DESC, total_received DESC"
        elif sort == "open_rate_asc":
            query += " ORDER BY open_rate ASC, total_received DESC"
        elif sort == "total_desc":
            query += " ORDER BY total_received DESC"
        else:
            query += " ORDER BY total_received DESC"

        cursor.execute(query, params)
        senders = [dict(r) for r in cursor.fetchall()]

    return {"senders": senders, "total": len(senders)}

@router.post("/action")
def perform_action(req: SubscriptionActionRequest):
    valid_actions = ("keep", "keep_newest_only", "rollup", "unsubscribe_and_delete")
    if req.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")

    cleaner = CleanfoxEngine()
    digest = UnrollEngine()
    results = []

    for email_addr in req.emails:
        addr = email_addr.lower().strip()
        if req.action == "keep":
            digest.remove_from_rollup(addr)
            with db_session() as conn:
                conn.execute("UPDATE senders SET action_preference = 'keep' WHERE email = ?", (addr,))
            results.append({"email": addr, "status": "kept"})
        elif req.action == "keep_newest_only":
            res = cleaner.prune_older_editions(addr, keep_count=1)
            results.append(res)
        elif req.action == "rollup":
            digest.add_to_rollup(addr)
            results.append({"email": addr, "status": "rolled_up"})
        elif req.action == "unsubscribe_and_delete":
            res = cleaner.unsubscribe_and_delete_sender(addr)
            results.append(res)

    return {"status": "success", "results": results}

@router.post("/prune-all-newest")
def prune_all_subscriptions(req: PruneAllRequest):
    """
    Keep newest email while purging older backlog across all subscriptions.
    """
    cleaner = CleanfoxEngine()
    result = cleaner.prune_all_subscriptions(keep_count=req.keep_count)
    return result

@router.post("/bulk-clean")
def bulk_clean_low_open_rate(req: BulkCleanRequest):
    cleaner = CleanfoxEngine()
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT email FROM senders 
        WHERE open_rate <= ? 
          AND total_received >= ? 
          AND action_preference != 'unsubscribe_and_delete'
        """, (req.max_open_rate, req.min_emails))
        candidates = [r["email"] for r in cursor.fetchall()]

    cleaned = []
    for addr in candidates:
        res = cleaner.unsubscribe_and_delete_sender(addr)
        cleaned.append(res)

    return {
        "status": "success",
        "total_cleaned": len(cleaned),
        "results": cleaned
    }
