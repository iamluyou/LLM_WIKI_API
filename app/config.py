import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # LLM 配置
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/coding/v3",
        alias="LLM_BASE_URL",
    )
    llm_model: str = Field(default="glm-5.1", alias="LLM_MODEL")
    llm_max_context: int = Field(default=262144, alias="LLM_MAX_CONTEXT")
    llm_reasoning_mode: str = Field(default="max", alias="LLM_REASONING_MODE")

    # 输出语言
    output_language: str = Field(default="Chinese", alias="OUTPUT_LANGUAGE")

    # Wiki 目录
    wiki_root: str = Field(
        default="/Users/leisheng/Desktop/MyWiki/MyAiReachWiki",
        alias="WIKI_ROOT",
    )

    # API 认证
    api_key: str = Field(default="", alias="API_KEY")

    # 服务配置
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=6003, alias="PORT")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # Ingest 配置
    ingest_concurrency: int = Field(default=1, alias="INGEST_CONCURRENCY")
    ingest_save_to_wiki: bool = Field(default=True, alias="INGEST_SAVE_TO_WIKI")
    ingest_cache_enabled: bool = Field(default=True, alias="INGEST_CACHE_ENABLED")

    # 桌面版 Ingest 委托（方案 B）
    desktop_ingest_enabled: bool = Field(default=False, alias="DESKTOP_INGEST_ENABLED")
    desktop_clip_url: str = Field(default="http://127.0.0.1:19827", alias="DESKTOP_CLIP_URL")

    # 向量搜索（可选）
    embedding_enabled: bool = Field(default=False, alias="EMBEDDING_ENABLED")
    embedding_model: str = Field(default="", alias="EMBEDDING_MODEL")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_endpoint: str = Field(default="", alias="EMBEDDING_ENDPOINT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def effective_embedding_api_key(self) -> str:
        """Embedding API Key，回退到 LLM API Key"""
        return self.embedding_api_key or self.llm_api_key

    @property
    def effective_embedding_endpoint(self) -> str:
        """Embedding endpoint，自动从 LLM base URL 推导"""
        if self.embedding_endpoint:
            return self.embedding_endpoint
        # 从 LLM base URL 推导: .../v3 → .../v3/embeddings
        base = self.llm_base_url.rstrip("/")
        # 去掉 /chat/completions 后缀
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        return f"{base}/embeddings"

    @property
    def wiki_raw_dir(self) -> str:
        return os.path.join(self.wiki_root, "raw", "sources")

    @property
    def wiki_dir(self) -> str:
        return os.path.join(self.wiki_root, "wiki")

    @property
    def llm_wiki_meta_dir(self) -> str:
        return os.path.join(self.wiki_root, ".llm-wiki")

    @property
    def page_history_dir(self) -> str:
        return os.path.join(self.llm_wiki_meta_dir, "page-history")

    @property
    def ingest_cache_dir(self) -> str:
        return os.path.join(self.llm_wiki_meta_dir, "ingest-cache")


settings = Settings()
