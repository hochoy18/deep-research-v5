# ADR 0003 — 通过 seam 合并相似函数

- 状态: 已采纳
- 日期: 2026-10-19

## 背景

系统在三个层上都反复依赖四类外部 surface:

1. **LLM provider** — Bailian / dashscope 主; 未来可能增多
2. **Web search provider** — dashscope 主, Tavily 兜底
3. **评估 passage** — per-sub-query、whole-plan、audit、judge
4. **事件通道** — SSE 给前端, 将来可能 WS

外加一条 agent 内部 surface:

5. **Citation** — 从文本里抽 `[n]` 编号, 对应到 Sources Appendix

用户在项目启动时强调过: **做同样事情的函数必须合并, 不同点靠参数区分**。任何一处这些 surface 的 "第二实现", 都意味着换模型 / 换 provider / 改 trace 埋点时要在 N 处修改, 而不是一处。

## 候选方案

### 分散调用 (每个模块直接 import LLM / search / event 库)
- 每个调用点 "本地化", 一目了然。
- 一次模型切换要触到每个 `call_llm(...)` 调用点。
- provider 失败 / 兜底策略变更要改所有调用点。
- Trace 埋点要在每个调用点单独接。

### 每模块一个 wrapper (每层自己的 LLM helper / search helper)
- 每模块内聚性更好。
- 3 份几乎一样的 `call_llm` 早晚发散。
- 跨层一致性 (例如 429 时统一 retry) 难执行。

### Seam 优先 *(被采纳)*
- **5 条 seam**, 每条都是 `backend/app/seams/` 里的单个函数。
- `seams/` 之外的代码不允许直接 import LLM provider、search provider、event channel、citation parser。
- Tracing、retry、fallback、cache 都在 seam 内部实现 — 一次写完。

## 决策

**5 条 seam, 单一来源**。Seam 是一个函数, 其签名是其它代码唯一需要知道的事。实现放在 `backend/app/seams/`, 内部可以长肉而不破坏调用方。

| Seam | 函数签名 (草图) | 谁用 |
|---|---|---|
| `call_llm` | `(prompt_id: str, variables: dict, *, model_override: str \| None = None) -> str` | 所有层所有 LLM 调用 |
| `search_web` | `(query: str, top_k: int = 4, *, provider: str = 'dashscope') -> list[Source]` | Research 层 |
| `evaluate` | `(rubric_name: str, text: str, *, context: dict \| None = None) -> EvalResult` | Research / Write 的 eval |
| `stream_event` | `(event_type: str, payload: dict) -> None` | 后端 → 前端 |
| `extract_citations` | `(text: str, sources: list[Source]) -> list[Citation]` | Research → Write 交接, Write 审计 |

**Code-review 规则**: 任何 PR 在 `seams/` 之外引入对 LLM / search / event / citation 库的直接调用, review 直接拒绝。无例外, 包括一次性脚本。

## 影响

+ 换模型只改 Langfuse prompt config, 代码不动 (见 `docs/adr/0004-langfuse-prompt-as-model-routing.md`)
+ 换 search provider 只改 `provider=` 参数, 调用点不用重写
+ cancel mid-research、带 backoff 的 retry、trace 埋点、score 上报 — 全部实现一次
+ 前端事件协议变更不影响 Research / Write 代码
+ Citation 格式切换 (例如 `[n]` → `<cite n="..."/>`) 只改一处
− 多一层间接。
− Seam 签名必须能覆盖今天和合理的未来用例。`call_llm` 上的 `model_override` 参数就是为了 debug 提前留好的 — 这是 "提前设计 seam" 的代价。
− 引入新 provider (例如 OpenAI 跑评估) 只在 `seams/` 层级动手。

## 注

- 模块边界规则见 `docs/milestones.md` "Cross-phase constants" — 模块之间不能跨层 import; seam 是跨层唯一允许的触点。
- 本 ADR 记的是 **规则**; 具体 seam 清单在 milestones 与 code review 中固化。
