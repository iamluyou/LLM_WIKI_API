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
| `/api/sources` | POST | 存入原始资料到 raw/sources/（重名自动重命名，对齐桌面版 getUniqueDestPath） |
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
# 认证 header（API_KEY 为空时跳过认证）
AUTH="Authorization: Bearer sk-xxx"

# 1. 初始化 wiki 目录（首次）
curl -X POST http://localhost:6003/api/init -H "$AUTH"

# 2. 搜索
curl "http://localhost:6003/api/pages?keyword=LLM&limit=5" -H "$AUTH"

# 3. 获取页面
curl "http://localhost:6003/api/pages/entities/llm-wiki" -H "$AUTH"

# 4. 导入文档
curl -X POST http://localhost:6003/api/sources \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"title": "新文档", "content": "# 新文档\n\n内容..."}'

# 5. 执行 Ingest（异步）
curl -X POST http://localhost:6003/api/ingest \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"source_id": "新文档-2026-05-12"}'

# 6. 查询任务状态
curl http://localhost:6003/api/tasks/task-20260512-001 -H "$AUTH"

# 7. 智能问答
curl -X POST http://localhost:6003/api/query \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"question": "LLM-WIKI 和传统 RAG 有什么区别？"}'

# 8. 删除 source 及其关联页面
curl -X DELETE http://localhost:6003/api/sources/ai-native-era-2026-05-12 -H "$AUTH"
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
| `API_KEY` | — | API 认证密钥（为空则不校验，请求时 `Authorization: Bearer <API_KEY>`） |
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
│   │   ├── query_engine.py        # Query 检索管线（图增强+预算+编号引用）
│   │   ├── search.py              # 混合检索（token + RRF）
│   │   ├── graph_relevance.py     # 图增强检索（4信号1跳扩展）
│   │   ├── context_budget.py      # 上下文预算分配
│   │   ├── page_merger.py         # 页面三层合并
│   │   ├── source_lifecycle.py    # Source 删除流程编排
│   │   ├── source_delete_decision.py  # 页面命运决策（skip/keep/delete）
│   │   ├── wiki_cleanup.py        # 引用清理（wikilink/index/related）
│   │   ├── llm_client.py          # LLM 调用封装（默认不传 max_tokens/temperature，对齐桌面版）
│   │   └── task_queue.py          # 异步任务队列（状态持久化到 tasks.json）
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
│   │   ├── ingest_sanitize.py     # LLM 输出清洗（围栏/前缀/Wikilink 修复）
│   │   └── ingest_cache.py        # SHA256 增量缓存 + 文件存在性校验
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
├── tests/                         # 343 个测试用例
├── DESIGN.md                      # 架构设计文档
└── requirements.txt
```

## 与 LLM-WIKI 桌面版的关系

本服务**不依赖桌面版代码**，仅共享同一文件系统目录（`WIKI_ROOT`）。两者可以同时运行，通过文件锁互斥保证并发安全。

## 关键机制

### Source 重名处理

对齐官方桌面版 `getUniqueDestPath` 策略，**绝不覆盖已有文件**：

| 优先级 | 文件名格式 | 示例 |
|--------|-----------|------|
| 1 | 原始文件名 | `report.md` |
| 2 | 追加日期 | `report-20260512.md` |
| 3 | 日期+计数器 | `report-20260512-2.md`（2~99） |
| 4 | 兜底：毫秒时间戳 | `report-20260512-1749723456789.md` |

### Ingest 内容清洗

LLM 生成的内容可能包含格式错误（代码围栏包装、Frontmatter 前缀、Wikilink 列表语法错误），`ingest_sanitize.py` 在写入前自动修复，避免 Frontmatter 解析失败导致正文丢失。

### Generation 源内容注入

Generation Prompt 拆分为 system（规则+示例）+ user（上下文+源内容），使 LLM 能基于真实素材生成更准确的知识页面。

### 页面合并改进

三层合并的第1层改为直接文本操作（正则替换），第2层 LLM 合并接收第1层结果，确保数组字段不丢失。支持 block form（`name:\n  - a\n  - b`）和 inline form（`name: [a, b]`）两种 frontmatter 数组格式解析与替换（对齐官方 `parseFrontmatterArray`/`writeFrontmatterArray`）。index.md/overview.md 采用直接覆盖策略（对齐官方 listing pages）。

### 缓存文件存在性校验

Ingest 缓存命中时（SHA256 比对通过），额外验证所有 `files_written` 仍存在于磁盘，防止幽灵条目（文件被删除但缓存仍声称其存在）。对齐官方 `ingest-cache.ts` 的 bug 修复。

### Query 管线对齐桌面版

对齐官方 `chat-panel.tsx handleSend` 完整流程：token 搜索 Top-10 → 图增强 1 跳扩展（每节点 Top-3，4 信号加权：directLink 3.0 + sourceOverlap 4.0 + Adamic-Adar 1.5 + typeAffinity 1.0，relevance≥2.0 过滤，`node.path` 去重对齐桌面版 `searchHitPaths`）→ 预算控制（5% index + 50% pages + 15% reserve）→ 优先级填充（P0 标题匹配 > P1 内容匹配 > P2 图扩展 > P3 overview 兜底）→ 编号引用 `[1][2]` + `<!-- cited: -->` → LLM 综合回答（不传 `max_tokens`/`temperature`，对齐桌面版不设 `requestOverrides`）。

### 任务状态持久化

Ingest 任务状态持久化到 `{WIKI_ROOT}/.llm-wiki/tasks.json`，服务重启后任务记录可恢复。重启时处于 `processing` 的任务自动标记为 `failed`（因处理过程已中断）。

详细架构设计见 [DESIGN.md](./DESIGN.md)。
