from fastapi import APIRouter
from app.cleanfox import CleanfoxEngine
from app.database import db_session

router = APIRouter(prefix="/api", tags=["dashboard"])

@router.get("/stats")
def get_stats():
    cleanfox = CleanfoxEngine()
    health = cleanfox.get_inbox_health_stats()
    return health

@router.get("/activity")
def get_activity_logs(limit: int = 30):
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?", (limit,))
        logs = [dict(r) for r in cursor.fetchall()]
    return {"logs": logs}
