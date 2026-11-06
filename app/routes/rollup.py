from fastapi import APIRouter
from app.database import db_session
from app.unroll import UnrollEngine

router = APIRouter(prefix="/api/rollup", tags=["rollup"])

@router.get("/items")
def get_rollup_items():
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rollup_items ORDER BY id DESC LIMIT 100")
        items = [dict(r) for r in cursor.fetchall()]
    return {"items": items, "total": len(items)}

@router.post("/send-digest")
def send_daily_digest():
    unroll = UnrollEngine()
    success, msg = unroll.send_daily_digest()
    return {"success": success, "message": msg}

@router.post("/mark-all-read")
def mark_all_read():
    with db_session() as conn:
        conn.execute("UPDATE rollup_items SET is_read = 1 WHERE is_read = 0")
    return {"status": "success", "message": "All rollup items marked as read."}
