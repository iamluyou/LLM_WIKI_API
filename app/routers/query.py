"""智能问答接口"""

from fastapi import APIRouter

from app.models.wiki import QueryRequest, QueryResponse
from app.services.query_engine import run_query

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_wiki(req: QueryRequest):
    """智能问答（Level 2 — LLM-WIKI Query）"""
    return await run_query(
        question=req.question,
        save_to_wiki=req.save_to_wiki,
        language=req.language,
    )
