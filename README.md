# TidyMate

Windows 本地文件整理器。按规则把散乱文件归入模板目录，**全程可预览、可撤销、默认不联网**。

> **当前状态：阶段 7-9（批次日志 + 一键撤销 + 错误报告）。可以整理，也可以撤回。**
> `plan` 预览、`apply` 执行、`undo` 撤销、`verify` 核对；每一步都写 SQLite 日志，
> 删除只进回收站，撤销默认先 dry-run。200 条混合变更的 apply→undo 往返已验证与
> apply 前逐字节一致（见 [`docs/validation/STAGE-7-9.md`](docs/validation/STAGE-7-9.md)）。
> GUI（阶段 8）与打包（阶段 9）尚未完成，GUI 的执行按钮仍是禁用的。
>
> **换会话 / 上下文用尽时**：从 [`docs/HANDOFF.md`](docs/HANDOFF.md) 继续，那里有当前基线、
> 已定决策和下一步。

## 为什么值得存在

现有的整理工具大多在"效率"上做加法，在"可逆性"上做减法：一键整理、静默覆盖、删掉不想要的。
TidyMate 反过来——先把"不会弄坏你的文件"做扎实，再谈整理得多快：

- **默认 Dry-run**：不给 `--apply` 就一个字节都不写。
- **删除只进回收站**：仓库里有静态扫描（`scripts/check_forbidden_apis.py`）在 CI 里拦截永久删除 API。
- **只读阶段零写盘**：`scripts/check_readonly.py` 用 AST 扫描产品代码，出现任何写调用即 CI 失败。
- **先写日志再动文件**：撤销依赖 SQLite 里的批次日志，日志不明的条目不回滚成"成功"。
- **系统/程序目录硬编码拒绝**，配置关不掉。
- **默认不联网**：运行时依赖只有 `typer` 与 `regex`，没有任何网络客户端。

## 快速开始（开发者）

```powershell
# 1. 准备一个演练沙箱：绝不要在真实目录上测试
pwsh -File scripts/make-sandbox.ps1

# 2. 安装（含开发依赖）
python -m pip install -e ".[dev]"

# 3. 验证链路
python -m pytest
python -m ruff check .
python -m mypy
python scripts/check_forbidden_apis.py
python scripts/check_readonly.py

# 4. 只读预览（不写盘，除非显式 --export）
python -m tidymate_cli plan <源目录> -r rules.yaml -o <目标根目录> --export <报告目录>

# 5. 扫描性能实测（1 万真实文件 / 10 万合成条目）
python scripts/bench_scan.py --mode real --count 10000
python scripts/bench_scan.py --mode synthetic --count 100000

# 6. 打包占位产物
python scripts/make_dist.py
```

`tidymate --version` 打印的版本、`dist/TidyMate-<version>-windows.zip` 的版本、
将来 MSI 的 ProductVersion、以及 git tag `v<version>`，**都来自同一个字符串**：
`src/tidymate_core/_version.py`。

## 目录结构

| 路径 | 作用 |
| --- | --- |
| `src/tidymate_core/` | 纯逻辑，无 UI、无网络。分层：`scanning` / `rules` / `templates` / `planning` / `conflicts` / `execution` / `journal` / `safety` / `reporting` |
| `src/tidymate_cli/` | Typer 命令行入口 |
| `src/tidymate_app/` | PySide6 桌面 shell（可选依赖 `.[gui]`） |
| `tests/` | `tidymate_core_tests`（单元）+ `tidymate_integration_tests`（仓库/打包契约） |
| `scripts/` | 沙箱、版本、打包、标签同步、删除 API 扫描 |
| `build/` | WiX v4 与 MSI 打包（阶段占位） |
| `docs/` | SECURITY / ROADMAP / CONTRIBUTING / SPONSORS / 阶段验证报告 |
| `.github/` | CI、Release、issue 表单、PR 模板、标签定义 |

分层的命名对映：原 .NET 方案里的 `src/TidyMate.Core/Scanning` → 这里的
`src/tidymate_core/scanning`（Python 包必须小写、可导入；层级语义完全一致）。

## 模板与规则

路径模板支持哪些变量、净化规则、哪些变量被明确禁止，见
[`docs/TEMPLATES.md`](docs/TEMPLATES.md)。

## FAQ

**为什么有些文件被跳过？**

路径超过 260 字符时默认跳过以保安全（铁律 8）。计划中的 `allow_long_path: true`
规则开关允许显式放行，但**仅当目标路径也能用 `\\?\` 前缀表示**时才允许；该开关
**当前版本尚未实现**，在阶段 5 随执行器落地前，超长路径源文件一律 `skip`，不会为它们
生成移动计划。

**为什么 ADS / OneDrive 占位文件被跳过？**

带 NTFS 备用数据流（如 `Zone.Identifier`）的文件一旦被移动，流可能悄悄丢失；
OneDrive "仅在线"占位文件在未下载完成时移动，可能留下 0 字节占位文件并损坏原件。
这两类条目会在报告里单独分组并给出处理步骤，默认不进入执行计划。

## 安全承诺（摘要）

完整威胁模型与报告渠道见 [`docs/SECURITY.md`](docs/SECURITY.md)。
安全漏洞**不要**开公开 issue。

## 许可

尚未选定。在你决定之前，本仓库**不是**可自由分发的开源项目。
