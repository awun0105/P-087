from fastapi import APIRouter, Depends, HTTPException

from src.agents.graph import agent
from src.api.auth import require_editor
from src.api.auth import router as auth_router
from src.api.routes_product import router as product_router
from src.api.studio import router as studio_router
from src.models.schemas import ChatRequest, ChatResponse

router = APIRouter()
# Route product (UI P0) cần Editor khi bật đăng nhập; duyệt/release cần Reviewer (ở từng route).
router.include_router(product_router, dependencies=[Depends(require_editor)])
router.include_router(studio_router)
router.include_router(auth_router)


@router.post("/chat", response_model=ChatResponse)
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
