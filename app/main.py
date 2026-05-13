"""LLM-WIKI API Service — FastAPI 入口"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.models.wiki import WikiInitResponse
from app.routers import pages, query, sources, ingest, graph
from app.services.task_queue import task_queue
from app.services.wiki_initializer import init_wiki_root

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> None:
    """校验 Bearer token。API_KEY 为空时不校验。"""
    if not settings.api_key:
        return
    if credentials is None:
        logger.warning("[Auth] Missing Authorization header")
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if credentials.credentials != settings.api_key:
        logger.warning("[Auth] Invalid API key attempt")
        raise HTTPException(status_code=401, detail="Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    logger.info(f"Starting LLM-WIKI API Service on {settings.host}:{settings.port}")
    logger.info(f"Wiki root: {settings.wiki_root}")
    await task_queue.start()
    yield
    # 关闭
    await task_queue.stop()
    logger.info("Shutting down")


app = FastAPI(
    title="LLM-WIKI API",
    description="将 LLM-WIKI 桌面版核心能力封装为 HTTP API",
    version="0.2.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(pages.router, dependencies=[Depends(verify_api_key)])
app.include_router(query.router, dependencies=[Depends(verify_api_key)])
app.include_router(sources.router, dependencies=[Depends(verify_api_key)])
app.include_router(ingest.router, dependencies=[Depends(verify_api_key)])
app.include_router(graph.router, dependencies=[Depends(verify_api_key)])


@app.get("/health")
async def health_check():
    return {"status": "ok", "wiki_root": settings.wiki_root}


@app.post("/api/init", response_model=WikiInitResponse, dependencies=[Depends(verify_api_key)])
async def init_wiki(force: bool = False):
    """初始化 wiki_root 目录结构（目录+种子文件），幂等操作"""
    result = init_wiki_root(force=force)
    return WikiInitResponse(**result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
