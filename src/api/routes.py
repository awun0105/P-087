"""Điểm vào duy nhất của API: gắn router product, studio và auth; giữ hai endpoint chat mẫu của template."""

from fastapi import APIRouter, Depends, HTTPException

from src.agents.graph import agent
from src.api.auth import require_contributor
from src.api.auth import router as auth_router
from src.api.product import router as product_router
from src.api.studio import router as studio_router
from src.models.schemas import ChatRequest, ChatResponse

router = APIRouter()
# Product reads and Editor features are available to Guest; mutation routes enforce ownership.
# Review and release keep their explicit Reviewer dependencies.
router.include_router(product_router, dependencies=[Depends(require_contributor)])
router.include_router(studio_router)
router.include_router(auth_router)


# Chat is an Editor feature shared with Guest; the existing role check still blocks anonymous users.
@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_contributor)])
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat với AI agent."""
    try:
        result = await agent.ainvoke({"query": request.message})
        return ChatResponse(
            response=result.get("response", ""),
            analysis=result.get("analysis", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái agent."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}
