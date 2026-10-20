# 路线图

按阶段推进，一次只做一个阶段。每个阶段结束都有一份 `docs/validation/` 下的验证报告，
以及一次按汇报模板的输出。阶段编号与验收标准以产品负责人确认为准；下表是**计划**，不是承诺。

| 阶段 | 主题 | 关键里程碑（M 编号） | 状态 |
| --- | --- | --- | --- |
| 0 | 骨架：能 build、能 test、CI 出 artifact | M0.1 工程与分层骨架 · M0.2 严格模式（mypy strict / warnings as errors） · M0.3 版本单一来源 · M0.4 CI/Release 工作流 · M0.5 仓库治理文件 · M0.6 删除 API 静态扫描 · M0.7 演练沙箱脚本 | ✅ 完成（2026-10-20） |
| 1 | 扫描与安全底座 | 目录遍历、错误容忍、黑名单常量、特殊文件识别（symlink/junction/ADS/只读/系统/长路径/UNC/OneDrive）、路径规范化 | 未开始 |
| 2 | 规则与模板 | 规则模型与匹配器、模板解析、变量白名单、非法字符拒绝、渲染 | 未开始 |
| 3 | 规划与 Dry-run 报告 | 变更计划、批内冲突检测、祖先目录逐条检测、dry-run 报告与统计 | 未开始 |
| 4 | 日志与状态机 | SQLite（WAL）批次/操作表、write-ahead、三态校验、状态统计从 SQL 聚合 | 未开始 |
| 5 | 执行器 | move / rename / copy / trash（send2trash）、逐项状态机、失败即停与报告 | 未开始 |
| 6 | 撤销 | 按 batch_id 回滚、copy 副本回滚走回收站、回收站还原（能力边界见验证报告） | 未开始 |
| 7 | CLI 完整化 | `scan/plan/apply/undo/status/verify`、`--apply` 二次确认语义、人类可读报告 | 未开始 |
| 8 | GUI | PySide6 界面、预览树、二次确认弹窗、首次运行提示 | 未开始 |
| 9 | 打包与发布 | PyInstaller onedir、WiX v4 MSI、便携 zip、签名（待定）、发布流程 | 未开始 |
| 10 | AI 建议（可选） | 默认关闭的元数据建议，只读文件名/扩展名/大小/时间，只出建议不执行 | 未开始 |

## 阶段 0 的已知欠缺（继承到后续阶段）

- 没有 `git` 本地仓库，CI 未在 GitHub 上真实执行过（见 `docs/validation/STAGE-0.md`）。
- MSI（WiX v4）只有工作流占位，没有 `.wxs`。
- PySide6 未安装（可选依赖），GUI 只有导入探测。
- `trash` 的撤销能力边界尚未验证（依赖 Shell 接口）。
