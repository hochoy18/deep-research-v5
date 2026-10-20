# 项目里程碑

按能力切阶段。每个阶段都交付 Plan / Research / Write 三层的完整、端到端 **垂直切片 (vertical slice)**。各阶段是 **加深**, 不是横向扩展。

为什么用 vertical slice → `docs/adr/0001-vertical-slice-staging.md`。

> 本文件为中文版。英文版: `docs/milestones.md`。两版内容一致; 代码标识符、prompt_id、表名、SQL 一律保留英文 (它们是机器可读的)。

---

## Phase 1 — 垂直切片 MVP (α 版)

**目标**: 注册 → 登录 → query → 批准 plan → research → 报告, 端到端可运行。用户名 + 密码登录。仅做 tracing, 不做 eval 评分。

### 功能面 (三层各自)

**Auth (P1)**
- `POST /auth/signup` body `{username, password}` → `{token, user_id}`
- `POST /auth/login` body `{username, password}` → `{token, user_id}`
- `POST /auth/logout` 吊销该 token
- `GET  /auth/me` 从 bearer 取当前用户
- 每个 `/sessions*` 接口都要 JWT bearer; 缺 / 无效 → 401
- 密码存储: **bcrypt** (业内标准, 一个依赖)
- **P1 显式不做**: 密码重置 / 邮箱验证 / 2FA / OAuth / refresh token。(生产级 auth 在 P3 替换用户名 + 密码。)

**Plan 层**
- LangGraph 节点 `plan_generate(query) → StructuredPlan`
- LangGraph 节点 `plan_wait_human(state) → interrupt` (Approve 操作触发 resume)
- Langfuse prompt `plan_generate_system` (代码里不出现 model 名, 仅存于 Langfuse prompt config)
- Structured Plan 遵循 **`CONTEXT.md` 里的 JSON Schema** (`Plan` / `Section` / `Note` 的字段类型与边界)
- 前端页面 `/sessions/[id]/plan` 渲染 Structured Plan 编辑器
- 5 件套 HITL:
  - `POST /sessions/[id]/plan/edit` payload `{op: "edit" | "add" | "remove" | "note", section_id?, payload}`
  - `POST /sessions/[id]/plan/approve` 触发下游
- 每次编辑后写入 `app_db.plans`, `plans.version` +1
- **Edit 规则** (HITL 并发): `Edit` / `Add` / `Remove` / `Note` 一旦 `plan.approved == true` 就 **HTTP 422** 拒绝。Approve 翻转 latch; race 由 HTTP 顺序解决
- **Note 语义**: Section 级 Note 文本注入 Research 层 `sub_query_generate` prompt。P1 Note 只能挂 Section 级

**Research 层** (每个 Section 一个 subgraph)
- `sub_query_generate(section) → [sub_query]`:
  - 用 `section.sub_questions` (用户在 plan 层写的); 没有则 LLM 生成 2–3
  - **校验**: 1–5 个, 每个唯一非空 ≤200 字符
  - **失败兜底**: 非法输出 retry 最多 **3 次**; 第 4 次仍失败, 把整段 Section brief 当成唯一 sub-query
  - 包含 Section 的 `note.text`
- `web_search(query, top_k=4) → [Source]` (dashscope 主, 失败 fallback tavily)
- `merge_sources(sources)` → 按 Section 聚合
- **全局 URL 去重**: 同一 URL 在多个 sub-query 出现时合并成单个 Source (在 Report 里 1 次引用)
- `eval_per_sub_query(section, sources) → pass | fail` (P1 retry cap = **1**, 不是 2)
- Langfuse prompts: `research_sub_query_generate_system`, `research_eval_per_sub_query_system`
- 并发: section 之间**串行**, 同一 section 内 sub-query 之间**并行** (`asyncio.gather`)

**Write 层**
- `outline_generate(plan, all_sources) → outline`
- `draft_generate(outline, all_sources) → draft_with_citations`
- `polish(draft) → final_report` — **单次** polish
- Langfuse prompts: `write_outline_system`, `write_draft_system`, `write_polish_system`
- 输出: markdown (`TL;DR` + 章节 + `[n]` 行内引用 + Sources Appendix)
- 默认长度 3-5 页
- Citation 编号**全报告连续** (不是每个 section 各自重新数)

### 后端 API

| Method | Path | 用途 |
|---|---|---|
| POST | `/auth/signup` | body `{username, password}` → `{token, user_id}` |
| POST | `/auth/login` | body `{username, password}` → `{token, user_id}` |
| POST | `/auth/logout` | 吊销 bearer |
| GET  | `/auth/me` | 从 bearer 取当前用户 |
| POST | `/sessions` | body `{query}` → `{session_id}` (需鉴权) |
| GET  | `/sessions/{id}/events` | SSE 流; 事件类型 `plan_ready` / `research_progress` / `report_ready` / `error`。**`research_progress` 每完成一个 Section 推一次** (Section 1/N → 2/N → …), 不按 sub-query 推 |
| POST | `/sessions/{id}/plan/edit` | 应用 HITL 编辑; **若 `plan.approved == true` 则 422** |
| POST | `/sessions/{id}/plan/approve` | 批准 plan; 设 `plan.approved = true`; 触发 research |
| GET  | `/sessions/{id}/report` | 最终 markdown 报告 (需鉴权) |
| GET  | `/sessions/{id}/state` | 当前 LangGraph state 快照 (需鉴权) |

### 基础设施 & 部署

- v5_frontend = Next.js (App Router) + TypeScript + `react-markdown` 渲染报告
- v5_backend = FastAPI + Python 3.11+ + LangGraph + LangChain + bcrypt (密码 hash)
- PostgreSQL: 一个实例, 两个库
  - `langgraph_checkpoints_db` — LangGraph 自管 schema
  - `app_db` — 项目自管表 (见下)
- Langfuse 自部署: prompt 注册 + traces
- P1 单租户无 multi-tenancy 隔离顾虑

### 可复用 seam (4 + 1; 跨阶段不变)

- `call_llm(prompt_id, variables, *, model_override=None)` — 所有 LLM 调用过这里
- `search_web(query, top_k=4, provider='dashscope')` — 主用 dashscope, 兜底 tavily
- `evaluate(rubric_name, text)` — Research 和 Write 都用
- `stream_event(event_type, payload)` — 所有 UI 事件
- `extract_citations(text)` — Research 和 Write 都要; 一个函数

代码不允许绕过这些 seam 直接接触: LLM provider / search provider / event channel / citation format。

### 数据库 schema (`app_db`)

```sql
users (
  id            UUID PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT now()
)

auth_token_blacklist (
  token_hash    TEXT PRIMARY KEY,    -- bearer token 的 SHA-256
  user_id       UUID REFERENCES users(id),
  expires_at    TIMESTAMP NOT NULL,  -- 拷自 JWT 的 'exp' claim
  created_at    TIMESTAMP NOT NULL DEFAULT now()
)

conversations (
  id              UUID PRIMARY KEY,
  user_id         UUID REFERENCES users(id),
  query           TEXT NOT NULL,
  report_md       TEXT,
  created_at      TIMESTAMP NOT NULL DEFAULT now(),
  updated_at      TIMESTAMP NOT NULL DEFAULT now()
)

messages (
  id              UUID PRIMARY KEY,
  conversation_id UUID REFERENCES conversations(id),
  role            TEXT,            -- 'user' | 'system' | 'event'
  content         TEXT,
  event_type      TEXT,            -- SSE 持久化
  created_at      TIMESTAMP NOT NULL DEFAULT now()
)

plans (
  id              UUID PRIMARY KEY,
  conversation_id UUID REFERENCES conversations(id),
  sections        JSONB,
  plan_note       TEXT,             -- Plan 级 Note (P2+); P1 留空
  version         INT NOT NULL,
  approved        BOOLEAN,
  approved_at     TIMESTAMP,
  created_at      TIMESTAMP NOT NULL DEFAULT now(),
  updated_at      TIMESTAMP NOT NULL DEFAULT now()    -- 每次 revision 更新
)
```

### Langfuse prompt 注册表 (P1)

代码用 `prompt_id` 引用; model 名放在每条 prompt 的 config 里:

| prompt_id | 用途 |
|---|---|
| `plan_generate_system` | plan_generate |
| `research_sub_query_generate_system` | sub_query_generate |
| `research_eval_per_sub_query_system` | eval_per_sub_query |
| `write_outline_system` | outline_generate |
| `write_draft_system` | draft_generate |
| `write_polish_system` | polish |

### P1 验收 (全部满足)

**功能 — Auth**:
- `POST /auth/signup` 新用户名密码 → 201 返 `{token, user_id}`; 重名 → 409
- `POST /auth/login` 正确凭证 → 200 返 `{token, user_id}`; 密码错 → 401
- `POST /auth/logout` → token 黑名单; 同 bearer 再调 `/sessions*` → 401
- `GET /auth/me` 从 bearer 返当前用户; 缺 / 无效 bearer → 401
- `/sessions*` 无 bearer → 401

**功能 — Plan / Research / Write**:
- 单次 query → plan 在约 5s 内渲染到编辑器
- 5 件套 HITL 全部跑通; `Edit` / `Add` / `Remove` / `Note` 在 `Approve` 之后返 422
- Approve 触发 research; SSE 事件流到 UI; `research_progress` **每个 Section 推一次**
- Dashscope 失败 (mock) → Tavily 兜底
- 最终报告渲染, `[n]` 引用能对应回 Sources Appendix; **全报告连续编号**
- Plan Section 数 **1 ≤ N ≤ 8**: 0 拒收, > 8 提示用户先合并
- Plan 字段级校验生效 (`title` 1–100, `brief` 1–500, `sub_questions` 0–5 个每个 ≤200, `note.text` ≤1000)
- Sub-query 生成非法 → retry 上限 3 次, 然后用整段 Section brief 当唯一 sub-query (可 mock 失败验证)
- **Source URL 去重**: 同一 URL 在两个 sub-query 出现时, Report 里只有 1 个 Source
- 同 section 内 3 个 sub-query 耗时 ≈ max(单个耗时), 不是 sum
- **Note 注入**: Section Note 文本能影响生成的 sub-query (手动 diff 可接受)

**功能 — 错误 & 续**:
- **上游 LLM 拒答**:
  - *Plan / Draft / Outline(用户面)* → 后端返 422 + LLM 原因; UI 提示用户改 query
  - *`sub_query_generate` / `polish`(内部)* → 按 P1 spec 静默 fallback(sub_query 3 次 retry 后用 Section brief;polish 跳过 → 直接出 `draft_with_citations`)。拒答记 Langfuse,不暴露用户
- **Section 数据不足**: 该 section 标 `Insufficient data`; 报告其余部分照常交付 (整份报告不失败)
- **浏览器刷新 / 多 tab**: `GET /sessions/{id}/state` 返回当前 LangGraph checkpoint; SSE 支持 `Last-Event-ID` 重连
- **数据保留**: 会话 (含 checkpoint + report) 自最后活动起保留 **30 天**

**可观测性**:
- Langfuse 看到每个 session 一条 trace, 每个 LangGraph 节点一个 span
- 所有 LLM 调用携带 `prompt_id`
- 所有 web-search 调用记录 provider (`dashscope` | `tavily`) 在 span 上

**交付物**:
- v5_frontend 能 build, 能跑, 浏览器里跑完注册 → 登录 → query → 报告
- v5_backend 能 build, 能跑, 10 个 endpoint 全部 OK (4 auth + 6 session)
- PostgreSQL 迁移脚本干净跑通 (`alembic` 或同类)
- Langfuse prompts 已注册
- Demo 脚本: `docs/demo/p1.md` — 从干净 checkout 到一份报告的完整步骤

### P1 显式不做

- ❌ Whole-plan coverage eval
- ❌ 2-retry cap on per-sub-query eval (P1 = 1)
- ❌ Multi-pass write polish (P1 = 1)
- ❌ Langfuse scoring / 质量评判
- ❌ 密码重置 / 邮箱验证 / 2FA / OAuth / refresh token (P1 auth = 仅用户名 + 密码 + JWT)
- ❌ Conversation 历史 UI (P1 存, 不列)
- ❌ Cancel mid-research
- ❌ Sub-query 硬上限 (P1 用软规则; P2 用 P1 telemetry 数据回填)
- ❌ Per-sub-query 细粒度 progress 事件 (P1 = per-Section)
- ❌ Plan 级 Note (P1 Note 仅 Section 级)

### P1 的 Sub-query 占位行为

(同原版, P2 用 telemetry 替换):

1. **用户的 sub_questions 全部上**
2. **空 → LLM 按软目标 2-3 生成**
3. **执行顺序** — section 串行, 同一 section 内 sub-query 并行
4. **不设硬上限** — P1 运行中观察并量化

---

## Phase 2 — 加深 + Eval 评分 + 历史视图

**目标**: 收紧 eval, 提升 write 质量, 锁定 sub-query 规则, 暴露会话历史。Auth 已在 P1 上线, 本阶段加深其它方面。

### 三层各自加深

**Plan 层**
- 可选 LangGraph 节点 `plan_suggested_edits(plan, query) → delta_suggestions` (不在关键路径上)
- 每次 plan 修订作为新行插入 `plans` 表, `version` +1
- **Plan 级 Note** 与 Section 级 Note 共存 (Plan 级 Note 应用到所有 Section)
- Diff / 可视化 UI 延后到 P3 (P2 存, 不展示)

**Research 层**
- 新节点 `eval_whole_plan(all_section_sources) → coverage_report` (所有 Section 完成后跑)
- 覆盖规则: 每个 Plan Section 必须有 ≥1 个 `authority_score >= 0.5` 的来源
- Auto-fill: 若 Section 覆盖不足, 自动生成 1-2 个 sub-query 再搜一次 (一轮, 不重试)
- Eval retry cap: **1 → 2**
- 评估 rubric 新增项:
  - 来源权威 (domain heuristic — `.edu`, `.gov`, 知名站点加权)
  - Claim-level 冲突检测 (LLM judge: 两个 source 是否意见相左)
- **Sub-query 规则锁定**, 以 P1 telemetry 为依据:
  - session cap (e.g. ≤ 20)
  - section cap (e.g. ≤ 5)
  - trust level (若 P1 显示用户输入质量高, 保持 "用用户的, 补到 N")
- Tavily fallback 比率在 Langfuse dashboard 暴露 (P1 只 log, P2 出看板)

**Write 层**
- Polish 循环: 1 次 → **2 次** (`polish_2x(draft)`)
- 新审计节点 `audit_citations(report, sources)` 在交付前运行
  - 校验报告中每个 `[n]` 都能映回 Sources Appendix
  - 解析不到的, 重写该段并重新 audit
- Citation 一致性在交付时强制

### 会话历史视图

- 新接口: `GET /conversations` — 列出用户历史会话 (标题取自首条 query, 时间戳, 最后活动)
- 前端 Profile 页渲染列表; 点击一行打开 `/sessions/{id}/state` 续上会话
- 若是已结束会话, 直接拉 `GET /sessions/{id}/report`
- 超过 30 天留存窗口的会话 → 410 Gone

### 可观测性

- Langfuse scoring: 注册 `eval_judge_quality` prompt, 跑在结束的报告上
- Trace span 显示: 每个 section 的 eval pass/fail, 最终 judge 分数 (1–5), 重试次数
- Langfuse dashboard 预置查询:
  - pass-rate 趋势
  - 每个 `prompt_id` 的 retry rate
  - fallback rate (`dashscope` vs `tavily`)
  - 平均 sources/section 分布

### P2 验收

- Whole-plan eval 跑起来, 给 Section 自动补搜
- Per-sub-query eval retry 上限 2
- Polish 2 次, audit 在交付前抓到不一致
- Sub-query 规则写入 `docs/research_rules.md` 并落入代码
- P1 demo 可复现
- Langfuse dashboard 显示
- 会话历史列表可看; 点击已结束的会话能打开存好的 Report

### P2 显式不做 (留 P3)

- Cancel mid-research
- Plan version diff UI
- Hallucination guardrail
- 生产级鉴权 (OAuth 替换用户名 + 密码)
- 限流
- 多语言 UI

---

## Phase 3 — 生产化

**目标**: 健壮、可观测、可上线。

### Research 加固

- 来源权威启发式升级为打分公式:
  - `domain_class` (academic / news / blog / unknown) + `citation_count_proxy` (常见索引里的出现率) → `authority_score`
- Claim-level 冲突检测: LLM 抽取每条 source 的核心 claims, 把 source 间冲突作为 `conflicts.json` 附到报告
- 向量缓存:
  - 加 `pgvector` 扩展
  - 缓存历史 `Source.text` 的 embedding, key 是归一化的 query
  - 每次新搜前先查缓存, 覆盖达标就跳过
- **取消**: `POST /sessions/{id}/cancel` 翻标志; LangGraph 在每个 node 边界检测; 通过 checkpoint 回滚清理部分 state

### Write 加固

- 新流水线: `outline → draft → fact_check → polish → final`
- `fact_check`:
  - 报告中每个 `[n]` 必须由 Source[n] 内容支撑
  - 支撑不住触发段落重写; 重写上限 2 次, 仍不行就丢弃该引用并打 `flag` 标记
- Hallucination judge (`eval_judge_hallucination`): 句子级打分, 分数超阈值则重写该句

### Plan 加固

- Query 意图分类 (`plan_classify_intent`): 输出 `{intent ∈ academic | commercial | technical | other}`, 带置信度
- Plan 模板存为 `backend/app/plan_templates/{intent}.yaml`:
  ```yaml
  academic:
    default_sections: [background, prior_work, methodology, results, open_questions]
    typical_lens: peer_reviewed_first
  ```
- 高置信度匹配走模板; 否则 LLM 全生成
- 用户可手动 opt-out (Plan 编辑器提供开关)

### 基础设施

- **生产鉴权: OAuth 替换 P1 的用户名 + 密码**。迁移路径: 老用户重新用 OAuth 登录一次, 不需要密码重置
- 限流: per-user, per-hour; 超限返 429 + `Retry-After`
- 除 Langfuse 外加监控:
  - 每层 (Plan / Research / Write) 的 p50 / p95 延迟
  - eval pass rate 趋势
  - fallback rate 趋势
  - 错误预算消耗
- 多语言 UI: i18n; 至少 English + Chinese
- Sentry (或同类) 报错; OpenTelemetry trace 叠在 LangGraph span 上

### P3 验收

- 100% eval 信号 (per-sub-query, whole-plan, final judge) 在 Langfuse 可查
- Cancel mid-research 在一个 node 边界内停下; 无孤儿 checkpoint
- 常见 intent queries (≥80% 测试集) 命中缓存模板 → plan 生成耗时下降可见
- Hallucination 率 (judge) 低于阈值 (e.g. < 5%)
- OAuth 登录正常; 压测下触发限流
- Latency 看板上线

### P3 显式不做

- 移动 App
- 其他 LLM 供应商 (Anthropic / OpenAI / 其他)
- 公开 API
- Team workspace / 协作
- 用户上传信源 (PDF, URL)

---

## Phase 4+ — P3 之后 (占位)

P3 完成后再定。按预期价值排序的候选:

1. **用户上传信源** — 用户上传 PDF / 粘贴 URL, 加 ingestion + chunking
2. **长时异步调研** — 启动一次调研跑数小时; 完成后通知 (email / webhook)
3. **其他 LLM 供应商** — 泛化 model-routing seam 适配 Anthropic / OpenAI 等
4. **Team workspace** — 共享 session, 在 plan 上评论
5. **移动 App / PWA** — 只读 / 看板

---

## 跨阶段常量

每个阶段都适用, **不会变**:

- **模块边界** — 三层 (Plan / Research / Write) 各占独立子包, 不允许跨层 import; 跨层协调只走 LangGraph state seam 与下面列出的公共 seam (4 + 1)。见 `docs/adr/0003-function-consolidation.md`。
- **4 条 seam + 1**: `call_llm`, `search_web`, `evaluate`, `stream_event`, `extract_citations` — 每条 surface 的单一入口
- **Langfuse Prompt 是 per-prompt 模型选择的唯一来源**; 代码只用 `prompt_id`. 见 `docs/adr/0004-langfuse-prompt-as-model-routing.md`
- **一个 PostgreSQL 实例, 两个库**: `langgraph_checkpoints_db` (LangGraph 自管) + `app_db` (项目自管)
- **P2 共 11 个 endpoint**(P1: 4 auth + 6 session;P2 新增 `GET /conversations` → 7 session)。P3 新增 `POST /sessions/{id}/cancel`(共 12 个)
- **并发模型**: section 串行, 同 section 内 sub-query 并行 — 每个阶段如此
- **Bailian / dashscope 主用** LLM 与 web-search; tavily 作 web-search 兜底
- **Citation 编号**: 全报告连续, 永不分 section 重新数

---

## 跟踪

- 每阶段 ticket 在 issue tracker (GitHub issues via `gh` CLI; see `docs/agents/issue-tracker.md`)
- 每个阶段 tracer-bullet: 先实施 blocker ticket, 在 seam 处 demo, 再加深
- P1 是今天硬验收的阶段; P2/P3 验收随设计演化
