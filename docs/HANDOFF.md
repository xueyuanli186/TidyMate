# 交接简报（Session Handoff）

> **这个文件是为了"上下文用完"而存在的。** 对话窗口会被清空，仓库不会。
> 新会话（哪怕模型没有任何历史）只需要读 `README.md` + 本文件，就能接着干。
> 规则：**每完成一个里程碑，就回来更新第 2、4 节**，不要把状态只留在聊天记录里。

## 1. 一句话现状

阶段 0-4 已完成且可复现；**阶段 5（日志与执行器）尚未写一行代码**。
仓库干净，基线全绿。产品现在能扫描、匹配规则、渲染目标、检测冲突、导出报告，
但**仍然不能移动任何文件**——这是刻意的。

## 2. 基线（2026-10-20 实测，可直接复现）

| 项 | 值 |
| --- | --- |
| 分支 / 提交 | `main` @ 阶段 9（便携版 + MSI 已本机构建） |
| 测试 | `572 passed`（57s），覆盖率 `90.30%`（门槛 90%） |
| 静态检查 | `ruff check` / `ruff format --check`（119 文件）/ `mypy`（99 文件）全过 |
| 安全闸门 | `check_forbidden_apis.py`：`OK ... 61+ scanned files`；`check_readonly.py`：`OK ... 43 product files` |
| 版本 | `0.1.0`，唯一来源 `src/tidymate_core/_version.py` |

复现命令（在仓库根目录）：

```powershell
python -m pytest -q
python -m ruff check . ; python -m ruff format --check .
python -m mypy
python scripts/check_forbidden_apis.py
python scripts/check_readonly.py
```

## 3. 已经拍板、不要再重新讨论的决定

1. **默认 dry-run**：不给 `--apply` 就零写盘（铁律）。
2. **删除只进回收站**：永久删除 API 在 CI 里被静态拦截，没有"临时放行"的开关。
3. **写权限按模块白名单发放**：`readonly_guard.ALLOWED_MODULES` 目前只有
   `tidymate_core/planning/artifacts.py`（阶段 3-4 的报告导出）。阶段 5 要落地执行器时，
   **新增条目 + PR 里写明理由**才是正确做法；把检查脚本注释掉是错误做法。
4. **模板变量 = 16 个白名单**；`{path}` / `{env:...}` / `{hash8}` 显式拒绝。
   细节见 `docs/TEMPLATES.md`。
5. **首尾 trim 保留前导点**（否则 `.jpg` → `jpg` 会毁扩展名），
   由 `test_leading_dot_is_preserved` 锁定。
6. **模板字面量里的非法字符 = 规则文件错误**；只有渲染出来的值才净化。
7. 版本号只改 `_version.py`，其余（CLI、dist 名、未来的 MSI、git tag）都从它派生。
8. **ADS / OneDrive 占位是 `skip`，不是 `reject`**：`error_kind` 为 `ads` /
   `onedrive_placeholder`。阶段 5 的执行器必须按 `error_kind` 拒绝执行这两类条目，
   且要在移动前复查（见第 5 节第一条）。

## 4. 下一步：发布前验证

1. 在干净 Windows 11 VM 上安装 MSI、启动 GUI、卸载，确认用户数据不被删除；
2. 打 `v0.1.0` tag 验证 `release.yml`（仍未实测）；
3. 决定是否购买代码签名证书（未签名 MSI 会触发 SmartScreen）；
4. GUI 的 P1 遗留：同步执行冻结界面、缺少历史批次选择器（v0.2.0）。

## 5. 已知欠缺与坑（别重复踩）

- **ADS 检测的失败路径**：`list_alternate_streams()` 在句柄打不开时返回 `None`，扫描
  阶段按"无流"处理。阶段 5 的执行器必须在移动前复查，`None` 时该条目按失败处理，
  不能当作干净文件放行。
- **真实 OneDrive 环境未验证**：占位属性是注入的（Windows 不允许手工设置
  `RECALL_ON_DATA_ACCESS`），见 `docs/validation/STAGE-3-4-P0.md` 第 2.2 节。
- **`allow_long_path` 尚不存在**：README FAQ 已写明"计划中、未实现"，别在别处
  宣称它可用。
- CI 已跑通（run #39375183042，五 job 全绿）；`release.yml` 仍未验证（需要 `v*` tag）。
- MSI 只有工作流占位，没有 `.wxs`。
- GUI 只验证了 offscreen 渲染与真实截图（`docs/images/gui-dry-run.png`），
  **真人鼠标交互**（文件对话框、拖列宽、导出）没验证过。
- GUI 测试 + coverage 同时开会在退出阶段 `0xC0000409` 崩溃；已通过 fixture 里
  `close()` + `deleteLater()` + `processEvents()` 修掉，别把 teardown 删了。
- `path_glob` 匹配完整绝对路径：`*.txt` 匹配不到东西，必须写 `**/`。
- `conflict: rename` 只生成单条候选名，最多试到 999。
- 真正的 symlink 未实测（用 junction 覆盖了 reparse point）。
- trash 的撤销能力边界未验证，依赖 Shell 接口。
- ADS / OneDrive 占位文件只识别属性位，没有"跳过并分类"策略。

## 6. 新会话开场白（复制即用）

```text
继续 TidyMate，工作目录 E:\deepseek work\TidyMate。全程用中文思考和回复。
先读 docs/HANDOFF.md 和 AGENTS.md，再看 docs/ROADMAP.md 的阶段 5。
这次只做 M5.1（SQLite 日志库），做完跑第 2 节那五条命令并更新 HANDOFF 第 2 节。
```

要点：**一次一个里程碑**，把"读大文件"的活丢给 subagent，只把结论带回来。

## 7. 上下文管理约定

- 一个会话 = 一个里程碑。做完就写回仓库（文档、验证报告、HANDOFF），再开新会话。
- 聊天记录不是记忆：任何"决定"和"实测数字"都必须落在 `docs/` 里。
- 需要通读大文件时用 subagent 并行读，主会话只接收摘要，避免上下文被原文占满。
- 卡住超过两轮就停下来写清楚"卡在哪、试过什么"，比继续硬撑更省上下文。
