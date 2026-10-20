# AGENTS.md

本文件给在这个仓库里工作的 AI 代理看。人类可读的交接信息在
[`docs/HANDOFF.md`](docs/HANDOFF.md)。

## 沟通语言

- **思考过程与回复一律用中文。** 这是产品负责人的明确要求（2026-10-20）。
- 代码、注释、docstring、commit message 沿用仓库现状（英文），不要因为语言偏好
  去批量重写已有代码或注释。新增的 `docs/` 文档用中文。

## 工作方式

- 开工前先读 `docs/HANDOFF.md` 和 `docs/ROADMAP.md` 里当前阶段那一行。
- 一次只推进一个里程碑（M 编号），做完跑 HANDOFF 第 2 节的五条命令，并更新基线。
- 任何与 `docs/HANDOFF.md` 第 3 节"已拍板决策"冲突的需求，先停下来问，不要自行改。
