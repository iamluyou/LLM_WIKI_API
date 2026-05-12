# LLM-WIKI API 架构设计技术文档

> 版本：v1.0 | 日期：2026-05-12 | 状态：已实现

## 1. 概述

本服务将 [LLM-WIKI](https://github.com/nashsu/llm_wiki) 桌面版的核心能力封装为 HTTP API，使外部系统可通过接口完成知识库的完整生命周期管理：**初始化 → 导入 → 消化 → 查询 → 删除**。

### 1.1 核心原则

- **效果对齐桌面版**：Prompt 完整复刻、目录结构一致、页面合并策略相同
- **不替代桌面版**：API 与桌面版共享同一 `WIKI_ROOT` 目录，通过文件锁互斥
- **Schema 驱动**：Ingest/Query 均读取 `purpose.md` + `schema.md` 作为 LLM 上下文
- **安全第一**：路径穿越防护、语言一致性守卫、硬失败隔离缓存

### 1.2 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.9+ | 兼容 macOS 系统自带版本 |
| Web 框架 | FastAPI | 异步、自动 OpenAPI 文档 |
| LLM SDK | openai (兼容模式) | 火山引擎 Ark 兼容 OpenAI 协议 |
| 任务队列 | asyncio.Queue + 后台任务 | 与桌面版一致的串行队列 |
| 项目锁 | filelock | 跨进程文件锁 |
| Frontmatter | python-frontmatter + pydantic | 解析 + 校验 |
| 配置 | pydantic-settings | .env + 环境变量 |

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     API Service (FastAPI)                        │
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │/api/init │ │/api/pages│ │/api/query│ │/api/     │          │
│  │(初始化)  │ │(检索)    │ │(智能问答)│ │sources   │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ │(导入/删除)│          │
│       │            │            │        └────┬─────┘          │
│       ▼            ▼            ▼             ▼                │
│  ┌─────────────────────────────────────────────────────┐       │
│  │              Service Layer (核心业务)                 │       │
│  │  WikiManager  SearchService  IngestEngine            │       │
│  │  QueryEngine   PageMerger   SourceLifecycle          │       │
│  │  WikiInitializer  SourceDeleteDecision  WikiCleanup   │       │
│  └────────────────────┬────────────────────────────────┘       │
│                       │                                         │
│       ┌───────────────┼───────────────┐                         │
│       ▼               ▼               ▼                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐                  │
│  │Prompt    │  │Parser    │  │Safety Layer  │                  │
│  │Engine    │  │Layer     │  │              │                  │
│  │├analysis │  │├file_    │  │├project_lock │                  │
│  │├genera-  │  │ blocks   │  │├path_guard   │                  │
│  │ tion     │  │├review_  │  │├language_    │                  │
│  │├merger   │  │ blocks   │  │ guard       │                  │
│  │└language │  │└front-  │  │└ingest_cache│                  │
│  │          │  │ matter   │  │              │                  │
│  └────┬─────┘  └──────────┘  └──────────────┘                  │
│       ▼                                                         │
│  ┌──────────┐                                                   │
│  │LLM Client│  (OpenAI 兼容, glm-5.1, reasoning=max)           │
│  └──────────┘                                                   │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              {WIKI_ROOT}/  (共享文件系统)
              ├── raw/sources/      ← API 写入
              ├── raw/assets/       ← Obsidian 附件
              ├── wiki/             ← API 读写
              │   ├── entities/
              │   ├── concepts/
              │   ├── sources/
              │   ├── queries/
              │   ├── comparisons/
              │   ├── synthesis/
              │   ├── thesis/
              │   ├── methodology/
              │   ├── findings/
              │   ├── index.md
              │   ├── overview.md
              │   └── log.md
              ├── .llm-wiki/        ← 备份 & 缓存
              │   ├── page-history/
              │   └── ingest-cache/
              ├── .obsidian/        ← Obsidian 配置
              ├── purpose.md        ← LLM 上下文
              └── schema.md         ← LLM 上下文
```

## 3. 目录初始化

### 3.1 初始化流程

`POST /api/init` 从 `app/templates/wiki_root/` 模板目录复制种子文件到目标 `WIKI_ROOT`。

```
POST /api/init
  │
  ├── 创建目录结构
  │   ├── raw/sources/, raw/assets/
  │   ├── wiki/{entities,concepts,sources,...}/
  │   └── .llm-wiki/{page-history,ingest-cache}/
  │
  ├── 复制种子文件（来自模板目录）
  │   ├── purpose.md          ← 官方 General 模板
  │   ├── schema.md           ← 官方 General 模板（含 Page Types、命名规范、Frontmatter 格式）
  │   ├── wiki/index.md       ← Wiki 索引
  │   ├── wiki/overview.md    ← 项目概览
  │   ├── wiki/log.md         ← 操作日志（含 {{date}} 占位符）
  │   └── .obsidian/*.json    ← Obsidian 兼容配置
  │
  └── 返回创建结果（幂等，已存在则跳过）
```

### 3.2 对齐官方 `create_project`

官方 Rust 实现（`src-tauri/src/commands/project.rs`）创建的内容与我们的模板完全一致：

| 对齐项 | 官方实现 | API 实现 |
|--------|---------|---------|
| 目录结构 | 7 基础目录 + 额外目录 | ✅ 完全一致 |
| schema.md | 由 `templates.ts` 的 `template.schema` 生成 | ✅ 使用官方 General 模板内容 |
| purpose.md | 由 `templates.ts` 的 `template.purpose` 生成 | ✅ 使用官方 General 模板内容 |
| wiki/index.md | 空索引 | ✅ 一致 |
| wiki/log.md | 含创建日期首条记录 | ✅ 一致 |
| wiki/overview.md | 带 heading | ✅ 一致 |
| .obsidian/ | app.json + appearance.json + core-plugins.json | ✅ 一致 |
| raw/assets/ | Obsidian 附件目录 | ✅ 一致 |

**API 额外创建**（桌面版在运行时按需创建）：
- `.llm-wiki/page-history/` — 页面备份
- `.llm-wiki/ingest-cache/` — SHA256 缓存

## 4. Ingest 管道

### 4.1 两步思维链

```
POST /api/ingest
  │
  ├── Step 1: Analysis（分析）
  │   │  Prompt: buildAnalysisPrompt()
  │   │  角色: expert research analyst
  │   │  输出: 6 大维度分析（实体/概念/主张/关联/矛盾/建议）
  │   │
  │   └── 缓存检查 → SHA256 命中则跳过
  │
  ├── Step 2: Generation（生成）
  │   │  Prompt: buildGenerationPrompt()
  │   │  角色: wiki maintainer
  │   │  输出: ---FILE: wiki/xxx.md--- / ---REVIEW: type | Title---
  │   │
  │   └── 7 条严格输出要求（首字符为 -、禁止前言等）
  │
  ├── 解析 FILE 块 → parseFileBlocks()
  │   └── 6 类危害修复（CRLF/截断/大小写/围栏/空路径/格式）
  │
  ├── 安全检查
  │   ├── isSafeIngestPath() — 路径穿越防护
  │   └── LanguageGuard — 语言一致性检查
  │
  ├── 页面合并（三层机制）
  │   ├── 第1层: Frontmatter 数组字段 Union 合并
  │   ├── 第2层: Body LLM 合并（buildPageMerger）+ 健全性检查
  │   └── 第3层: 锁定字段强制回写（type/title/created）
  │
  ├── 写入文件
  │   ├── 内容页 → 三层合并后写入
  │   ├── index.md / overview.md → 整体覆盖
  │   └── log.md → 追加
  │
  ├── 缓存保存（仅全部成功时）
  │
  └── 返回任务结果
```

### 4.2 异步任务模型

Ingest 是耗时操作（LLM 两步调用 + 可能的合并调用），采用异步任务模式：

1. `POST /api/ingest` → 立即返回 `task_id`
2. `GET /api/tasks/{task_id}` → 轮询任务状态
3. 内部通过 `asyncio.Queue` 串行执行（与桌面版一致）

## 5. Source 删除（级联删除）

### 5.1 删除流程

对齐桌面版 `source-lifecycle.ts` + `source-delete-decision.ts` + `wiki-cleanup.ts`：

```
DELETE /api/sources/{source_id}
  │
  ├── ① 删除 raw/sources/{file}.md
  ├── ② 清理 ingest-cache 中的条目
  │
  ├── ③ 扫描所有 wiki 页面，解析 frontmatter sources[]
  │       │
  │       ├── skip:   页面不引用该 source → 不处理
  │       ├── keep:   页面还有其他 source → 从 sources[] 移除该 source（正文不动）
  │       └── delete: 该 source 是唯一来源 → 删除整个页面
  │
  ├── ④ 级联清理
  │       ├── 删除 wiki/sources/{stem}.md 摘要页
  │       ├── 删除 wiki/media/{slug}/ 媒体目录
  │       ├── 清理 index.md 条目（结构化匹配，防误删 [[OpenAI]]）
  │       ├── 清理 [[wikilink]] 死链接 → 转纯文本
  │       └── 清理 frontmatter related[] 引用
  │
  └── ⑤ 追加删除日志到 wiki/log.md
```

### 5.2 核心决策函数 `decide_page_fate()`

```python
def decide_page_fate(sources: list[str], target_source: str) -> str:
    """
    返回 "skip" | "keep" | "delete"
    - sources 不含 target_source → skip
    - sources 含 target_source 且还有其他 → keep（仅移除引用）
    - sources 仅含 target_source → delete（删除页面）
    大小写不敏感匹配
    """
```

### 5.3 Wikilink 安全清理

使用结构化正则解析 `[[slug]]`，而非子串匹配，防止误删（如搜索 `ai` 误删 `[[OpenAI]]`）：

```python
# 归一化键：slug 和 title 两种形式都收录
def normalize_wiki_ref_key(ref: str) -> str:
    return ref.lower().replace(" ", "-")
```

## 6. 检索系统

### 6.1 混合检索管线

对齐桌面版 `search.ts` 的 `scoreFile`：

| 信号 | 权重 | 说明 |
|------|------|------|
| FILENAME_EXACT_BONUS | 200 | 文件名完全匹配 |
| PHRASE_IN_TITLE_BONUS | 50 | 标题含完整查询短语 |
| PHRASE_IN_CONTENT_PER_OCC | 20 | 内容中每出现一次（上限10次） |
| TITLE_TOKEN_WEIGHT | 5 | 标题中每个匹配 token |
| CONTENT_TOKEN_WEIGHT | 1 | 内容中每个匹配 token |

### 6.2 CJK 分词策略

对齐桌面版 `tokenizeQuery`：纯 bigram + 单字 + 原始 token，无外部分词库。

示例：`"默会知识"` → `["默会", "会知", "知识", "默", "会", "知", "识", "默会知识"]`

### 6.3 RRF 融合

向量搜索可选启用时，使用 Reciprocal Rank Fusion（K=60）融合 token 排名 + vector 排名。

## 7. 安全层

### 7.1 项目级互斥锁

所有写入操作通过 `with_project_lock` 保护，使用 `filelock` 实现跨进程互斥。超时 5 分钟。

覆盖范围：Ingest 写入、Query save_to_wiki、Source 删除、index.md/log.md 更新。

### 7.2 路径穿越防护

`isSafeIngestPath()` 拒绝：绝对路径、`..` 段、不以 `wiki/` 开头的路径、控制字符。

威胁模型：攻击者在源文档中注入提示词，LLM 生成 `---FILE: ../../../etc/passwd---`。

### 7.3 语言一致性守卫

`content_matches_target_language()` 检查生成内容是否与目标语言一致。跳过 log.md、entities/、sources/ 等合理包含跨语言专有名词的页面。

### 7.4 SHA256 增量缓存

- 相同 source 内容（SHA256 比对）→ 跳过 LLM 调用
- 存在硬失败 → 不保存缓存（防止冻结部分结果）
- 缓存存储在 `.llm-wiki/ingest-cache/`

## 8. 页面合并机制

### 8.1 三层合并

| 层级 | 范围 | 策略 | 说明 |
|------|------|------|------|
| 第1层 | sources/tags/related | Union 合并 | 纯集合运算，零 LLM 调用 |
| 第2层 | Body 正文 | LLM 合并 | 新旧不同时调用 buildPageMerger + 健全性检查 |
| 第3层 | type/title/created | 强制回写 | 即使 LLM 改了也恢复原值 |

### 8.2 健全性检查

| 检查 | 规则 | 失败处理 |
|------|------|----------|
| frontmatter 存在性 | 必须包含 `---` 开头 | 拒绝，fallback 数组合并 |
| Body 缩短阈值 | `len(merged) >= max(len(old), len(new)) * 0.7` | 拒绝，fallback |
| 数组字段完整性 | 合并后再次 union | 二次修复 |

### 8.3 备份

合并覆盖前 best-effort 备份到 `.llm-wiki/page-history/`，错误不阻塞主流程。

## 9. Prompt 保真度

### 9.1 对齐桌面版 Prompt 结构

| Prompt | 角色 | 核心结构 |
|--------|------|---------|
| `buildAnalysisPrompt` | expert research analyst | 角色定义 + 语言强制 + 6 维分析 + 上下文注入 + 反 CoT 指令 |
| `buildGenerationPrompt` | wiki maintainer | 角色定义 + 6 项生成 + Frontmatter 5 条规则 + FILE/REVIEW 格式 + 7 条严格要求 + 尾部语言重复 |
| `buildPageMerger` | — | 保留双方事实 + 消除冗余 + 重组织 + 保持 wikilink |

### 9.2 语言强制策略

- 首尾双次注入语言指令（利用 LLM 近期指令权重最高特性）
- `MANDATORY OUTPUT LANGUAGE: Chinese` 在 prompt 首尾各出现一次

## 10. 数据模型

### 10.1 Frontmatter Schema

所有页面必须包含：

```yaml
type: entity | concept | source | query | comparison | synthesis | overview | thesis | methodology | finding
title: Human-readable title
tags: []
related: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: []
```

Source 类型额外：`authors`, `year`, `url`, `venue`
Thesis 类型额外：`confidence`, `status`
Finding 类型额外：`source`, `confidence`, `replicated`

### 10.2 页面类型与目录映射

| 类型 | 目录 | 说明 |
|------|------|------|
| entity | wiki/entities/ | 命名事物 |
| concept | wiki/concepts/ | 抽象概念 |
| source | wiki/sources/ | 来源摘要 |
| query | wiki/queries/ | 开放问题 |
| comparison | wiki/comparisons/ | 对比分析 |
| synthesis | wiki/synthesis/ | 跨域综合 |
| thesis | wiki/thesis/ | 工作假设 |
| methodology | wiki/methodology/ | 研究方法 |
| finding | wiki/findings/ | 实证结果 |

## 11. API 接口详表

### 11.1 初始化

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/init` | POST | `force: bool` (query, 默认 false) | 初始化目录结构 |

### 11.2 查询侧

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/pages` | GET | keyword, type, tag, limit, offset | 内容检索 |
| `/api/pages/{slug}` | GET | — | 获取单页面 |
| `/api/query` | POST | question, save_to_wiki, language | 智能问答 |

### 11.3 导入侧

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/sources` | POST | title, content, filename | 存入资料 |
| `/api/sources/{source_id}` | DELETE | — | 级联删除 source |
| `/api/ingest` | POST | source_id (可选) | 执行 Ingest |
| `/api/tasks/{task_id}` | GET | — | 查询任务状态 |

### 11.4 辅助

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/stats` | GET | — | Wiki 统计 |
| `/api/graph` | GET | — | 知识图谱数据 |
| `/health` | GET | — | 健康检查 |

## 12. 模板与种子文件

### 12.1 模板目录

`app/templates/wiki_root/` 包含初始化所需的所有种子文件：

```
app/templates/wiki_root/
├── purpose.md              ← 官方 General 模板（Goal/Key Questions/Scope/Thesis）
├── schema.md               ← 官方 General 模板（Page Types/命名规范/Frontmatter/交叉引用/矛盾处理）
├── wiki/
│   ├── index.md            ← Wiki 索引
│   ├── overview.md         ← 项目概览
│   └── log.md              ← 操作日志（{{date}} 占位符）
└── .obsidian/
    ├── app.json            ← 附件文件夹指向 raw/assets
    ├── appearance.json     ← 暗色主题
    └── core-plugins.json   ← 启用核心插件
```

### 12.2 模板渲染

- `.md` 文件中的 `{{date}}` 占位符在初始化时替换为当前日期
- `.json` 文件原样复制
- 幂等：已存在的文件默认跳过，`force=true` 时覆盖

## 13. 与桌面版的差异

| 差异点 | 原因 | 影响 |
|--------|------|------|
| LLM 非确定性 | 同 prompt 不同调用输出不同 | 页面风格略有差异，正常现象 |
| 向量搜索（可选） | 初期 token 搜索 + RRF 已够用 | 检索召回率可后续增强 |
| 模板仅 General | API 不提供模板选择 UI | 可手动替换模板目录 |
| Deep Research | 桌面版特有功能 | Phase 2 |
| 多模态图像 | 管道复杂 | Phase 2 |

## 14. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Ingest 耗时长 | API 超时 | 异步任务模式 |
| 多端同时写入 | 数据冲突 | 项目级文件锁 |
| LLM 输出格式漂移 | 解析失败 | 围栏感知解析 + 软丢弃 |
| 页面合并冲突 | 信息丢失 | 三层合并 + 健全性检查 + 备份 |
| 路径穿越攻击 | 安全风险 | isSafeIngestPath |
| 语言不一致 | 内容混乱 | 语言守卫 + 首尾双次语言指令 |
| 缓存冻结部分结果 | 后续跳过失败页面 | 硬失败不保存缓存 |
