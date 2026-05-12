# LLM-WIKI API Service

将 [LLM-WIKI](https://github.com/nashsu/llm_wiki) 桌面版核心能力封装为 HTTP API，支持外部系统通过接口查询知识库、导入文档和删除资源。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key 和 Wiki 目录

# 启动服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 6003 --reload

# 访问 API 文档
open http://localhost:6003/docs
```

## 首次使用：初始化 Wiki 目录

如果目标 `WIKI_ROOT` 目录尚未创建，调用初始化接口：

```bash
curl -X POST http://localhost:6003/api/init
```

该接口会创建完整的目录结构（对齐桌面版 `create_project`），包括种子文件和 Obsidian 配置。幂等操作，重复调用安全。

## API 接口总览

### 初始化

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/init` | POST | 初始化 wiki_root 目录结构（幂等，对齐桌面版） |

### 查询侧

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/pages` | GET | 内容检索（关键词、类型、标签过滤，混合评分 + RRF） |
| `/api/pages/{slug}` | GET | 获取单个页面完整内容 |
| `/api/query` | POST | 智能问答（LLM 综合回答 + 可选写回 wiki） |

### 导入侧

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/sources` | POST | 存入原始资料到 raw/sources/ |
| `/api/sources/{source_id}` | DELETE | 删除 source 及其级联关联页面 |
| `/api/ingest` | POST | 执行 Ingest（LLM 两步思维链，异步） |
| `/api/tasks/{task_id}` | GET | 查询 Ingest 任务状态 |

### 辅助

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/stats` | GET | Wiki 统计信息 |
| `/api/graph` | GET | 知识图谱数据（节点 + 边） |
| `/health` | GET | 健康检查 |

## 使用示例

```bash
# 1. 初始化 wiki 目录（首次）
curl -X POST http://localhost:6003/api/init

# 2. 搜索
curl "http://localhost:6003/api/pages?keyword=LLM&limit=5"

# 3. 获取页面
curl "http://localhost:6003/api/pages/entities/llm-wiki"

# 4. 导入文档
curl -X POST http://localhost:6003/api/sources \
  -H "Content-Type: application/json" \
  -d '{"title": "新文档", "content": "# 新文档\n\n内容..."}'

# 5. 执行 Ingest（异步）
curl -X POST http://localhost:6003/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_id": "新文档-2026-05-12"}'

# 6. 查询任务状态
curl http://localhost:6003/api/tasks/task-20260512-001

# 7. 智能问答
curl -X POST http://localhost:6003/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "LLM-WIKI 和传统 RAG 有什么区别？"}'

# 8. 删除 source 及其关联页面
curl -X DELETE http://localhost:6003/api/sources/ai-native-era-2026-05-12
```

## 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `LLM_API_KEY` | — | LLM API 密钥（必填） |
| `LLM_BASE_URL` | 火山引擎 Ark | OpenAI 兼容接口地址 |
| `LLM_MODEL` | glm-5.1 | 模型名称 |
| `LLM_MAX_CONTEXT` | 262144 | 最大上下文长度 |
| `LLM_REASONING_MODE` | max | 推理模式 |
| `OUTPUT_LANGUAGE` | Chinese | 输出语言 |
| `WIKI_ROOT` | — | Wiki 目录绝对路径 |
| `HOST` | 0.0.0.0 | 监听地址 |
| `PORT` | 6003 | 监听端口 |
| `INGEST_CACHE_ENABLED` | true | 是否启用 SHA256 缓存 |

## 测试

```bash
python -m pytest tests/ -v
```

## 项目结构

```
WikiApi/
├── app/
│   ├── main.py                    # FastAPI 入口 + /api/init 端点
│   ├── config.py                  # 配置管理（pydantic-settings）
│   ├── routers/                   # API 路由
│   │   ├── pages.py               # 内容检索 + 单页面
│   │   ├── query.py               # 智能问答
│   │   ├── sources.py             # 存入资料 + 删除 source
│   │   ├── ingest.py              # Ingest + 任务状态
│   │   └── graph.py               # 知识图谱
│   ├── services/                  # 核心业务逻辑
│   │   ├── wiki_manager.py        # Wiki 文件读写
│   │   ├── wiki_initializer.py    # 目录初始化（从模板复制）
│   │   ├── ingest_engine.py       # Ingest 完整管道
│   │   ├── query_engine.py        # Query 检索管线
│   │   ├── search.py              # 混合检索（token + RRF）
│   │   ├── page_merger.py         # 页面三层合并
│   │   ├── source_lifecycle.py    # Source 删除流程编排
│   │   ├── source_delete_decision.py  # 页面命运决策（skip/keep/delete）
│   │   ├── wiki_cleanup.py        # 引用清理（wikilink/index/related）
│   │   ├── llm_client.py          # LLM 调用封装
│   │   └── task_queue.py          # 异步任务队列
│   ├── prompts/                   # Prompt 模板（对齐桌面版）
│   │   ├── analysis.py            # buildAnalysisPrompt
│   │   ├── generation.py          # buildGenerationPrompt
│   │   ├── merger.py              # buildPageMerger
│   │   └── language.py            # 语言规则
│   ├── parsers/                   # 输出解析
│   │   ├── file_blocks.py         # FILE 块解析（6 类危害修复）
│   │   ├── review_blocks.py       # REVIEW 块解析
│   │   └── frontmatter.py         # Frontmatter 严格解析与校验
│   ├── safety/                    # 安全防护
│   │   ├── project_lock.py        # 项目级互斥锁
│   │   ├── path_guard.py          # 路径穿越防护
│   │   ├── language_guard.py      # 语言一致性守卫
│   │   └── ingest_cache.py        # SHA256 增量缓存
│   ├── models/
│   │   └── wiki.py                # 数据模型
│   └── templates/wiki_root/       # 初始化种子模板（对齐官方）
│       ├── purpose.md
│       ├── schema.md
│       ├── wiki/
│       │   ├── index.md
│       │   ├── overview.md
│       │   └── log.md
│       └── .obsidian/             # Obsidian 配置
├── tests/                         # 248 个测试用例
├── DESIGN.md                      # 架构设计文档
└── requirements.txt
```

## 与 LLM-WIKI 桌面版的关系

本服务**不依赖桌面版代码**，仅共享同一文件系统目录（`WIKI_ROOT`）。两者可以同时运行，通过文件锁互斥保证并发安全。

详细架构设计见 [DESIGN.md](./DESIGN.md)。
