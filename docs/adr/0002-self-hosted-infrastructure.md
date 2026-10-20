# ADR 0002 — 自托管基础设施

- 状态: 已采纳
- 日期: 2026-10-19

## 背景

项目需要:

1. 一份 **关系型存储**: LangGraph checkpoints + 应用表 (users、conversations、messages)。
2. 一份 **prompt 管理 + 可观测性**服务: Langfuse。

用户已经在跑这两份: 一个本地 PostgreSQL 实例 + 一份自部署 Langfuse。后端都能访问到。

## 候选方案

### 云托管 (Neon / Supabase for PostgreSQL; Langfuse Cloud)
- 启动时零运维。
- 长期订阅成本。
- 项目数据会离开用户自己的网络。

### 自托管 *(被采纳)*
- 用户已经在跑这两份。
- 没有按条记录的成本。
- 数据完全自主可控。
- 依赖后端到这两个实例稳定的网络可达路径。

### 混合 (一个自托管一个云)
- 凭据 / 连接字符串更难统一管理。
- 对本项目没有明显收益。

## 决策

两个都 **自托管**。PostgreSQL 用本地实例 (由用户直接配置)。Langfuse 用用户已有的部署 (另外单独配置)。

**数据库布局**: **一份 PostgreSQL 实例, 两个 database** —

- `langgraph_checkpoints_db` (LangGraph 自管 schema)
- `app_db` (users、conversations、messages、项目自有表)

不拆 schema, 不拆服务器。这样 LangGraph 的命名空间对运维一眼可见, 备份 / 迁移脚本也直白。

## 影响

+ 没有订阅成本。
+ 数据完全自主可控。
+ 走的是用户已在用的私网路径。
− 后端必须从环境变量读所有连接串 (Postgres / Langfuse host + key) — **禁止硬编码 URL**。
− 用户的 PostgreSQL 必须从后端所在位置可达。
− 启动时必须提供 Langfuse host + key; 在 `.env.example` 中给出文档。
− 两份服务都得可用项目才能跑; 若 Langfuse 短暂挂掉, 需要文档化的降级模式 (用本地缓存的 prompt 兜底)。
