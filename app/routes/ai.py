from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.ai_advisor import AIAdvisorEngine

router = APIRouter(prefix="/api/ai", tags=["ai"])

class ExecuteAIRequest(BaseModel):
    email: str
    action: str

class ExecuteAllRequest(BaseModel):
    min_confidence: int = 80

@router.get("/recommendations")
def get_recommendations():
    advisor = AIAdvisorEngine()
    recs = advisor.generate_recommendations()
    return {
        "status": "success",
        "total": len(recs),
        "recommendations": recs
    }

@router.post("/execute")
def execute_recommendation(req: ExecuteAIRequest):
    advisor = AIAdvisorEngine()
    result = advisor.execute_recommendation(req.email, req.action)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

@router.post("/execute-all")
def execute_all_recommendations(req: ExecuteAllRequest):
    advisor = AIAdvisorEngine()
    result = advisor.execute_all_recommendations(max_confidence=req.min_confidence)
    return result
