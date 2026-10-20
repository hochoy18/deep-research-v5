# ADR 0004 — Langfuse Prompt 作为模型路由的 SSOT

- 状态: 已采纳
- 日期: 2026-10-19

## 背景

系统同时使用多款 Bailian 模型 (`qwen-max`、`qwen-plus`、`qwen-turbo`、`qwen-long`, 可选 `deepseek-r1`)。不同的 prompt 适合不同的模型 — 例如 `qwen-turbo` 跑快速子问题生成, `qwen-plus` 跑评估, `qwen-max` 跑最终润色。切换某个 prompt 用的模型必须 **不需要重新部署** 就能完成。

## 候选方案

### 调用点硬编码模型名
- 例如 `call_llm("plan_generate_system", variables, model="qwen-max")`。
- 简单。
- 每次换模型要触到所有调用点。
- dev / staging / prod 各自漂移, 没有审计痕迹。

### Env-var 配置文件 (例如 `MODEL_FOR_PLAN_SYSTEM=qwen-max`)
- 让代码不再写死模型名。
- 没有哪个模型产出哪段输出的审计线索 (env var 不会被 trace)。
- 变更不与 prompt 一起版本化。

### Langfuse Prompt config *(被采纳)*
- 每条 Langfuse Prompt 有一个 `config` 字段, 带 `{model, temperature, ...}`。
- 代码只引用 `prompt_id`。
- 换模型是 Langfuse UI 的操作; 代码不动。
- Langfuse trace 自动展示每次请求用了哪个模型 — 因为换模型导致的质量回退, 看 trace 就能定位。

## 决策

**Langfuse Prompt metadata 是哪个模型 (以及其它生成参数) 跑哪条 prompt 的唯一来源**。`call_llm` seam 只接 `prompt_id` 和 `variables` — **永不接模型名**。

一个 debug 出口: `model_override` 参数供测试与调试用, 但生产调用路径都不应传它。

P1 阶段首批注册的 prompt (`docs/milestones.md` P1 → "Langfuse prompt registry") 是这套机制的种子; 后续阶段新增 prompt 都继承同一规则。

## 影响

+ 代码与具体模型解耦。
+ 换模型 = Langfuse UI 改动, 不需要重新部署。
+ Trace 自带 "每次请求用的模型" 字段 (Langfuse 原生, 不是我们手写的)。
+ Prompt 版本与模型版本在 Langfuse 一起版本化 — "上版 prompt + 上版模型" 一键回滚很直接。
− 所有 LLM 调用都需要在启动时去 Langfuse 拉 prompt。**缓解**: 内存缓存 + TTL (默认 60s)。Langfuse 短暂挂掉时, seam 回退到缓存; 冷启动且无缓存时, seam 抛错并让 session 可见地失败 — 优于静默用错模型。
− 加新模型 = 改 Langfuse, 不改代码 (摩擦很低)。
− `model_override` 存在, 必须仅在测试中使用 — review 规则: 任何生产调用点不允许传非 null 的 `model_override`。

## 注

- 见 ADR 0003, seam 强制 "代码只引用 `prompt_id`" 这条不变量。
- 见 `CONTEXT.md` "External systems" 看模型清单。
