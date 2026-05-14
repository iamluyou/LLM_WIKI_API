# 桌面版源码对齐参考文档

> 本文档是 LLM-WIKI 桌面版 (`llm_wiki-main`) 的源码行为沉淀，供 API 版对齐参考。
> 生成日期：2026-05-13 | 桌面版版本：v0.4.9

---

## 1. 源码结构

```
src/
├── lib/                           # 核心业务逻辑（对齐重点）
│   ├── llm-client.ts              # LLM 统一流式调用入口
│   ├── llm-providers.ts           # 多 Provider 适配（OpenAI/Anthropic/Google/Ollama/Custom）
│   ├── search.ts                  # Token 搜索 + 向量搜索 + RRF 融合
│   ├── graph-relevance.ts         # 知识图谱构建 + 相关性计算
│   ├── context-budget.ts          # 上下文预算分配
│   ├── output-language.ts         # 输出语言检测 + 指令构建
│   ├── greeting-detector.ts       # 问候检测
│   ├── ingest.ts                  # Ingest 主流程（Stage 1 分析 + Stage 2 生成）
│   ├── embedding.ts               # 向量嵌入（LanceDB + chunk + search）
│   ├── text-chunker.ts            # Markdown 分块
│   ├── page-merge.ts              # 页面合并（frontmatter union + LLM body merge）
│   ├── ingest-cache.ts            # Ingest 缓存
│   ├── ingest-sanitize.ts         # Ingest 内容清洗
│   ├── lint.ts                    # Wiki 质量检查（结构 + 语义）
│   ├── deep-research.ts           # 深度研究（Web 搜索 + LLM 综合）
│   └── ...
├── components/
│   ├── chat/chat-panel.tsx        # 聊天面板（Query 管线主入口）
│   └── ...
├── stores/
│   ├── wiki-store.ts              # 全局状态（含 LlmConfig 定义）
│   ├── chat-store.ts              # 聊天状态
│   └── ...
└── commands/
    └── fs.ts                      # Tauri IPC 文件操作
```

---

## 2. LLM 调用层

### 2.1 `streamChat()` — 唯一 LLM 调用入口

**文件**: `src/lib/llm-client.ts`

```typescript
streamChat(
  config: LlmConfig,           // 包含 provider, apiKey, model, maxContextSize, reasoning 等
  messages: ChatMessage[],      // { role, content: string | ContentBlock[] }
  callbacks: StreamCallbacks,   // { onToken, onReasoningToken?, onDone, onError }
  signal?: AbortSignal,
  requestOverrides?: RequestOverrides  // 可选的采样参数覆盖
): Promise<void>
```

### 2.2 `RequestOverrides` — 采样参数

**文件**: `src/lib/llm-providers.ts`

```typescript
interface RequestOverrides {
  temperature?: number
  top_p?: number
  top_k?: number
  max_tokens?: number
  stop?: string | string[]
  reasoning?: ReasoningConfig    // { mode: "auto"|"off"|"low"|"medium"|"high"|"max", budgetTokens? }
}
```

### 2.3 各场景的 `requestOverrides` 传参（关键！）

| 调用场景 | `temperature` | `max_tokens` | `reasoning` | 说明 |
|---------|--------------|-------------|------------|------|
| **Query (chat-panel)** | 不传 | 不传 | 不传 | `streamChat(config, messages, callbacks, signal)` — **5 个参数中第 5 个 omitted** |
| **Ingest Stage 1** | `0.1` | `4096` | `{ mode: "off" }` | 分析阶段，低温度 + 禁用推理 |
| **Ingest Stage 2** | `0.1` | `8192` | `{ mode: "off" }` | 生成阶段，低温度 + 禁用推理 |
| **Page Merge** | `0.1` | 不传 | 不传 | 页面合并，仅设低温度 |
| **Semantic Lint** | 不传 | 不传 | 不传 | Lint 不设任何覆盖 |
| **Deep Research** | 不传 | 不传 | 不传 | 研究综合不设任何覆盖 |
| **Image Caption** | 不传 | 不传 | 不传 | 图片描述不设任何覆盖 |

### 2.4 OpenAI-Compatible Wire 的请求体构建

**文件**: `src/lib/llm-providers.ts` → `buildOpenAiBody()`

```typescript
function buildOpenAiBody(messages, overrides?) {
  const translated = messages.map(m => ({ role: m.role, content: toOpenAiContent(m.content) }))
  return { messages: translated, stream: true, ...stripWireAgnosticOverrides(overrides) }
}

function stripWireAgnosticOverrides(overrides?) {
  const { reasoning: _reasoning, ...rest } = overrides ?? {}
  return rest  // 只展开 temperature, top_p, top_k, max_tokens, stop
}
```

**关键行为**：
- `overrides` 为 `undefined` 时，`stripWireAgnosticOverrides` 返回 `{}`
- 最终请求体 = `{ messages, stream: true }` — **不传 temperature, max_tokens 等任何采样参数**
- 模型使用自身默认值（glm-5.1 默认 temperature ≈ 0.95）

### 2.5 Provider 路由

```
provider === "custom" + apiMode === "chat_completions"  →  buildOpenAiCompatibleBody  →  buildOpenAiBody
provider === "ollama"                                  →  buildOpenAiCompatibleBody  →  buildOpenAiBody
provider === "openai"                                  →  buildOpenAiCompatibleBody  →  buildOpenAiBody
provider === "custom" + apiMode === "anthropic_messages" → buildAnthropicBodyWithReasoning
provider === "anthropic"                               →  buildAnthropicBodyWithReasoning
provider === "google"                                  →  buildGoogleBody
```

**Anthropic 特殊**：Anthropic wire **强制**设 `max_tokens: overrides?.max_tokens ?? 4096`（默认 4096）。

### 2.6 超时保护

- 30 分钟 backstop 超时（针对超大上下文推理模型）
- 区分用户取消 vs 网络错误 vs 超时
- 流中断检测：reasoning ≥ 200 字但 content = 0 → 报错提示

---

## 3. Query 管线

### 3.1 完整流程 (`chat-panel.tsx handleSend`)

```
1. 问候检测 (isGreeting) → 命中则跳过检索，直接对话
2. 预算分配 (computeContextBudget)
3. Token 搜索 + 向量搜索 + RRF 融合 → Top 10
4. 读取 index.md + purpose.md
5. Index 裁剪（超过预算时按相关性过滤）
6. 图 1 跳扩展 (buildRetrievalGraph + getRelatedNodes)
7. 优先级填充页面 (P0→P1→P2→P3)
8. 组装 System Prompt + 编号上下文
9. langReminder 注入到最后一条 user 消息前
10. streamChat(config, messages, callbacks, signal)  ← 不传 requestOverrides
11. 解析引用 + 写回 wiki（可选）
```

### 3.2 预算分配 (`context-budget.ts`)

```typescript
const DEFAULT_MAX_CTX = 204_800     // 200K chars
const RESPONSE_RESERVE_FRAC = 0.15  // 15% 留给回复
const INDEX_BUDGET_FRAC = 0.05      // 5% 留给 index
const PAGE_BUDGET_FRAC = 0.50       // 50% 留给页面内容
const PER_PAGE_FRAC = 0.30          // 单页最大占 pageBudget 的 30%
const PER_PAGE_FLOOR = 5_000        // 单页最小 5000 chars

// 计算：
maxCtx = maxContextSize || DEFAULT_MAX_CTX
responseReserve = maxCtx * 0.15
indexBudget = maxCtx * 0.05
pageBudget = maxCtx * 0.50
maxPageSize = min(pageBudget, max(5000, pageBudget * 0.30))
```

### 3.3 搜索 (`search.ts`)

#### Token 搜索评分

```typescript
const FILENAME_EXACT_BONUS = 200      // 文件名精确匹配
const PHRASE_IN_TITLE_BONUS = 50      // 短语在标题中出现
const PHRASE_IN_CONTENT_PER_OCC = 20  // 短语在内容中每次出现
const MAX_PHRASE_OCC_COUNTED = 10     // 短语出现次数上限
const TITLE_TOKEN_WEIGHT = 5          // 标题 token 匹配权重
const CONTENT_TOKEN_WEIGHT = 1        // 内容 token 匹配权重
```

#### 分词 (`tokenizeQuery`)

- 按空白 + 标点拆分
- 过滤停用词（中英文）
- CJK 文本额外生成 bigram + 单字
- 去重

#### RRF 融合

```typescript
const RRF_K = 60  // Cormack et al. (SIGIR 2009) 标准常数
// fused(p) = 1/(K + token_rank) + 1/(K + vector_rank)
// 仅在 token 列表或 vector 列表中的页面才参与
```

#### 向量搜索

- 使用 LanceDB 存储嵌入向量
- 搜索流程：embed query → search topK×3 chunks → group by page → max-pool + weighted tail
- 页面评分：`top + min(tail * 0.3, max(0, 1 - top))`
- 向量搜索结果由 `searchWiki()` 内部合并到 token 搜索结果中，chat-panel 无需额外处理

#### 结果上限

```typescript
const MAX_RESULTS = 20  // searchWiki 最多返回 20 条，chat-panel 取 top 10
```

### 3.4 图扩展 (`graph-relevance.ts`)

#### 图节点结构

```typescript
interface RetrievalNode {
  id: string              // 文件名去掉 .md（如 "takin-platform"）
  title: string           // frontmatter title
  type: string            // frontmatter type (entity/concept/source/synthesis/comparison/query)
  path: string            // 文件绝对路径
  sources: readonly string[]  // frontmatter sources 数组
  outLinks: ReadonlySet<string>  // [[wikilink]] 出链
  inLinks: ReadonlySet<string>   // [[wikilink]] 入链
}
```

#### 相关性计算（4 信号加权）

```typescript
const WEIGHTS = {
  directLink: 3.0,      // 直接链接（双向）
  sourceOverlap: 4.0,   // 共享 source 文件数
  commonNeighbor: 1.5,   // Adamic-Adar 共同邻居
  typeAffinity: 1.0,     // 类型亲和度矩阵
}

// Type Affinity 矩阵
const TYPE_AFFINITY = {
  entity:    { concept: 1.2, entity: 0.8, source: 1.0, synthesis: 1.0, query: 0.8 },
  concept:   { entity: 1.2, concept: 0.8, source: 1.0, synthesis: 1.2, query: 1.0 },
  source:    { entity: 1.0, concept: 1.0, source: 0.5, query: 0.8, synthesis: 1.0 },
  query:     { concept: 1.0, entity: 0.8, synthesis: 1.0, source: 0.8, query: 0.5 },
  synthesis: { concept: 1.2, entity: 1.0, source: 1.0, query: 1.0, synthesis: 0.8 },
}
```

#### 图扩展调用

```typescript
// chat-panel.tsx 中的调用
const graph = await buildRetrievalGraph(pp, dataVersion)
const searchHitPaths = new Set(topSearchResults.map(r => r.path))  // 完整路径去重
const expandedIds = new Set<string>()

for (const result of topSearchResults) {
  const fileName = getFileName(result.path)      // 取文件名
  const nodeId = fileName.replace(/\.md$/, "")    // 去掉 .md 作为 node id
  const related = getRelatedNodes(nodeId, graph, 3)  // limit=3
  for (const { node, relevance } of related) {
    if (relevance < 2.0) continue                 // 最低相关性阈值
    if (searchHitPaths.has(node.path)) continue   // 用 node.path（绝对路径）去重
    if (expandedIds.has(node.id)) continue         // 避免重复扩展
    expandedIds.add(node.id)
    graphExpansions.push({ title: node.title, path: node.path, relevance })
  }
}
```

**关键细节**：
- `getRelatedNodes` 默认 `limit=5`，但 chat-panel 传入 `limit=3`
- 去重使用 `node.path`（**绝对路径**），不是 `node.id`
- `searchHitPaths` 由搜索结果的 `r.path` 构建
- 低于 `relevance < 2.0` 的节点丢弃

### 3.5 页面优先级填充

```
P0: titleMatch === true 的搜索结果（标题匹配）
P1: titleMatch === false 的搜索结果（内容匹配）
P2: 图扩展节点
P3: overview.md 兜底（仅当没有任何页面时）
```

填充规则：
- 每页内容超过 `maxPageSize` 则截断 + 加 `[\n\n[...truncated...]`
- 累计内容超过 `pageBudget` 则停止填充
- 单页放不下（`usedChars + content.length > pageBudget`）则跳过

### 3.6 System Prompt 构成

```
1. "You are a knowledgeable wiki assistant..."
2. "## Rules"（7 条规则，含 <!-- cited: --> 隐藏注释）
3. "## Wiki Purpose" + purpose.md 内容
4. "## Wiki Index" + 裁剪后的 index.md
5. "## Page List" + 编号页面列表
6. "## Wiki Pages" + 编号页面内容（用 --- 分隔）
7. "---"
8. "## ⚠️ MANDATORY OUTPUT LANGUAGE: {lang}"
```

**注意**：桌面版 System Prompt **没有** "Cite ALL pages" 和 "THOROUGH and COMPREHENSIVE" 的措辞（这是 API 版自行添加的）。

### 3.7 语言处理

```typescript
// output-language.ts
getOutputLanguage(fallbackText)  // 用户配置 || 检测文本语言
buildLanguageDirective(text)     // 完整语言指令（用于 system prompt）
buildLanguageReminder(text)      // 短提醒（注入到 user 消息前）

// chat-panel 中的注入方式：
// 将 langReminder 拼接到最后一条 user 消息前：`[REMINDER: ...]\n\n{original_content}`
// 原因：vLLM/llama.cpp/Qwen3 的 chat template 要求 system 只在 index 0
```

### 3.8 多轮对话

```typescript
// chat-panel 使用 chat-store 维护多轮对话
const activeConvMessages = useChatStore.getState().getActiveMessages()
  .filter(m => m.role === "user" || m.role === "assistant")
  .slice(-maxHistoryMessages)  // 限制历史消息数

// 消息组装顺序：
// [system, ...historyMessages, currentUserWithLangReminder]
```

---

## 4. Ingest 管线

### 4.1 两阶段流程

```
Stage 1: 分析 (buildAnalysisPrompt)
  → streamChat(config, [{role:system, content: analysisPrompt}, {role:user, content: source}], callbacks, signal, { temperature: 0.1, reasoning: { mode: "off" }, max_tokens: 4096 })

Stage 2: 生成 (buildGenerationPrompt)
  → streamChat(config, [{role:system, content: generationPrompt}, {role:user, content: analysis + source}], callbacks, signal, { temperature: 0.1, reasoning: { mode: "off" }, max_tokens: 8192 })
```

### 4.2 Stage 1 分析 Prompt (`buildAnalysisPrompt`)

```
角色：You are an expert research analyst.
禁止：chain-of-thought, hidden reasoning, thinking transcript
语言：languageRule(sourceContent) 指令

输出结构：
  ## Key Entities     → 名称/类型/角色/是否已存在于 wiki
  ## Key Concepts     → 名称/定义/重要性/是否已存在
  ## Main Arguments & Findings → 核心主张/证据/证据强度
  ## Connections to Existing Wiki → 关联页面/增强/挑战/扩展
  ## Contradictions & Tensions → 冲突/内部张力
  ## Recommendations  → 建议创建/更新的页面/重点/开放问题

上下文：
  ## Wiki Purpose (for context)
  ## Current Wiki Index (for checking existing content)
```

### 4.3 Stage 2 生成 Prompt (`buildGenerationPrompt`)

```
角色：You are a wiki maintainer.
禁止：chain-of-thought, hidden reasoning, explanatory preamble
语言：languageRule(sourceContent) 指令

生成内容：
  1. wiki/sources/{sourceBaseName}.md  — 源文件摘要（必须使用此路径）
  2. wiki/entities/*.md — 实体页
  3. wiki/concepts/*.md — 概念页
  4. wiki/index.md — 更新索引（保留已有条目 + 添加新条目）
  5. wiki/log.md — 日志条目（## [YYYY-MM-DD] ingest | Title）
  6. wiki/overview.md — 更新总览

Frontmatter 规则（严格）：
  - 第一行必须是 ---
  - key: value 格式
  - 数组用 inline [a, b, c]
  - related 用 bare slugs，不用 [[wikilink]]
  - sources 必须包含源文件名

输出格式（严格）：
  ---FILE: wiki/path/to/page.md---
  (content with frontmatter)
  ---END FILE---

  ---REVIEW: type | Title---
  Description
  OPTIONS: Create Page | Skip
  PAGES: wiki/page1.md, wiki/page2.md
  SEARCH: query 1 | query 2 | query 3
  ---END REVIEW---

  第一个字符必须是 - (---FILE:)，否则整个响应被丢弃
  不允许任何前言、后语、markdown 表格、bullet list
```

### 4.4 Ingest 缓存

- 基于源文件内容 hash 的缓存检查
- 缓存命中时跳过 Stage 1 + Stage 2，但仍然执行图片提取和 caption
- 缓存存储在 `<project>/.llm-wiki/ingest-cache/`

### 4.5 页面合并 (`page-merge.ts`)

重新导入时，如果目标页面已存在：

1. **Frontmatter 数组字段 union 合并**（确定性，不需要 LLM）：
   - `sources`、`tags`、`related` 三个字段取并集
2. **Body 合并**（需要 LLM）：
   - 调用 `buildPageMerger(llmConfig)` 构建的 MergeFn
   - 传入 `{ temperature: 0.1 }`
   - 安全检查：LLM 输出 body 长度 < 70% 最长输入 → 拒绝，回退到 array-merged-only
3. **锁定字段回写**（确定性）：
   - `type`、`title`、`created` 强制保留已有值
4. 回退路径：LLM 失败 → 使用 incoming body + array-merged frontmatter

---

## 5. Embedding 管线

### 5.1 流程

```
1. chunkMarkdown(content, { targetChars, overlapChars })
2. for each chunk: fetchEmbedding(title + headingPath + chunkText, cfg)
3. vectorUpsertChunks(projectPath, pageId, chunks)
```

### 5.2 配置 (`EmbeddingConfig`)

```typescript
interface EmbeddingConfig {
  enabled: boolean
  model: string
  endpoint: string      // OpenAI-compatible /v1/embeddings
  apiKey?: string
  maxChunkChars?: number     // 默认 1000
  overlapChunkChars?: number // 默认 200
}
```

### 5.3 搜索 (`searchByEmbedding`)

```
1. fetchEmbedding(query, cfg)
2. vectorSearchChunks(projectPath, queryEmb, topK * 3)  // 过度获取
3. 按 page_id 分组，计算 blended score:
   - top = max(chunk_scores)
   - tail = sum(other_chunk_scores)
   - blended = top + min(tail * 0.3, max(0, 1 - top))
4. 排序取 topK
```

### 5.4 自动减半重试

- 如果 embedding 端点返回"input too long"类错误，自动将文本减半重试
- 最多重试 3 次，最低 64 chars
- 失败信息存储在 `lastEmbeddingError`

---

## 6. 问候检测 (`greeting-detector.ts`)

```typescript
const MAX_GREETING_LEN = 20  // 超过 20 字符不算问候
// 支持中/英/日/韩/欧洲语言
// 整句匹配（不是子串），strip 尾部标点
// "hello, how do I train a transformer?" → NOT a greeting
```

问候时的 System Prompt：
```
You are a wiki assistant for the project "{project.name}".
The user sent a casual greeting — reply briefly and naturally, in one or two sentences.
Do NOT invent wiki content or pretend to have retrieved pages.
Respond in {lang}.
```

---

## 7. Deep Research (`deep-research.ts`)

```
1. Web search（多查询合并去重）
2. LLM 综合（不传 requestOverrides）
3. 保存到 wiki/queries/research-{slug}-{date}.md
4. 自动 re-ingest 研究结果（生成 entities/concepts/交叉引用）
```

System Prompt 要点：
- 引导使用 [[wikilink]] 链接到已有 wiki 页面
- 提供已有 Wiki Index 供交叉引用
- 组织清晰章节 + [N] 引用 + 矛盾/空白标注

---

## 8. Lint (`lint.ts`)

### 8.1 结构性 Lint（不需要 LLM）

- **Orphan**: 无入链的页面
- **Broken link**: [[wikilink]] 指向不存在的页面
- **No outlinks**: 无出链的页面

### 8.2 语义 Lint（需要 LLM）

- 不传 `requestOverrides`
- 输出格式：`---LINT: type | severity | title---` / `---END LINT---`
- 类型：contradiction / stale / missing-page / suggestion

---

## 9. 关键对齐检查清单

### 9.1 已对齐 ✅

| 项目 | 桌面版行为 | API 版状态 |
|------|-----------|-----------|
| Query 不传 temperature | 默认 None（不传） | ✅ |
| Query 不传 max_tokens | 默认 None（不传） | ✅ |
| 图扩展 limit=3 | chat-panel 传 3 | ✅ |
| 图扩展去重用 node.path | searchHitPaths.has(node.path) | ✅ (使用 slug+.md 模拟 path) |
| relevance < 2.0 过滤 | 丢弃 | ✅ |
| 预算分配公式 | 5%+50%+15%+30% | ✅ |
| System Prompt 结构 | 7 个 section | ✅ |
| langReminder 注入位置 | 最后一条 user 消息前 | ✅ |
| 问候检测 | isGreeting → 跳过检索 | ✅ |
| RRF K=60 | 融合 token + vector | ✅ |
| Token 搜索评分权重 | FILENAME_EXACT=200 等 | ✅ |
| Ingest 两阶段 | Stage 1 分析 + Stage 2 生成 | ✅ 已实现 |
| Ingest 缓存 | 基于 content hash 的缓存跳过 | ✅ 已实现（SHA256 + 文件存在性校验） |
| Page Merge | LLM body merge + frontmatter union + locked fields | ✅ 三层合并已实现 |
| FILE/REVIEW 块解析 | FILE/REVIEW 输出格式 | ✅ 已实现 |

### 9.2 待对齐 🔲

| 项目 | 桌面版行为 | API 版现状 | 优先级 |
|------|-----------|-----------|--------|
| Ingest Stage 1 参数 | `{ temperature: 0.1, reasoning: { mode: "off" }, max_tokens: 4096 }` | 无覆盖（默认值） | 高 |
| Ingest Stage 2 参数 | `{ temperature: 0.1, reasoning: { mode: "off" }, max_tokens: 8192 }` | `max_tokens=32000`，缺 temperature/reasoning | 高 |
| Page Merge 参数 | `{ temperature: 0.1 }` | 无覆盖（默认值） | 高 |
| Embedding | LanceDB chunk search + auto-halve retry | SQLite + numpy 实现，待验证细节 | 中 |
| Semantic Lint | LINT 块格式 | 未实现 | 低 |
| Deep Research | Web 搜索 + LLM 综合 + auto-ingest | 未实现 | 低 |
| Image Caption | VLM 描述 + 缓存 | 未实现 | Phase 2 |
| Ingest 图片提取 | PDF/PPTX/DOCX 图片 → wiki/media/ | 未实现 | Phase 2 |

### 9.3 设计差异（有意为之，无需对齐）

| 差异 | 原因 |
|------|------|
| 单轮 vs 多轮 | API 场景由调用方维护对话上下文 |
| HTTP 同步响应 vs SSE 流 | API 返回完整 JSON，桌面版流式渲染 |
| 文件锁互斥 | API 版用 filelock，桌面版用 project-mutex.ts |
| System Prompt "Cite ALL pages" + "THOROUGH" | API 版增强引用引导，桌面版无此措辞，可视为有益差异 |
| Embedding 存储 | API 版用 SQLite + numpy，桌面版用 LanceDB |

---

## 10. 参数速查表

### 10.1 LLM 调用参数

| 场景 | temperature | max_tokens | reasoning |
|------|------------|-----------|-----------|
| Query | **不传** | **不传** | **不传** |
| Ingest 分析 | 0.1 | 4096 | off |
| Ingest 生成 | 0.1 | 8192 | off |
| Page Merge | 0.1 | 不传 | 不传 |
| Semantic Lint | 不传 | 不传 | 不传 |
| Deep Research | 不传 | 不传 | 不传 |
| Image Caption | 不传 | 不传 | 不传 |

### 10.2 搜索参数

| 参数 | 值 |
|------|---|
| MAX_RESULTS | 20 |
| RRF_K | 60 |
| FILENAME_EXACT_BONUS | 200 |
| PHRASE_IN_TITLE_BONUS | 50 |
| PHRASE_IN_CONTENT_PER_OCC | 20 |
| TITLE_TOKEN_WEIGHT | 5 |
| CONTENT_TOKEN_WEIGHT | 1 |

### 10.3 图扩展参数

| 参数 | 值 |
|------|---|
| limit (chat-panel) | 3 |
| limit (默认) | 5 |
| relevance 阈值 | 2.0 |
| directLink 权重 | 3.0 |
| sourceOverlap 权重 | 4.0 |
| commonNeighbor 权重 | 1.5 |
| typeAffinity 权重 | 1.0 |

### 10.4 上下文预算参数

| 参数 | 值 |
|------|---|
| DEFAULT_MAX_CTX | 204,800 chars |
| RESPONSE_RESERVE_FRAC | 0.15 |
| INDEX_BUDGET_FRAC | 0.05 |
| PAGE_BUDGET_FRAC | 0.50 |
| PER_PAGE_FRAC | 0.30 |
| PER_PAGE_FLOOR | 5,000 chars |

### 10.5 Embedding 参数

| 参数 | 默认值 |
|------|-------|
| maxChunkChars | 1000 |
| overlapChunkChars | 200 |
| search topK multiplier | 3 |
| tail weight | 0.3 |
| auto-halve max retries | 3 |
| auto-halve floor | 64 chars |
