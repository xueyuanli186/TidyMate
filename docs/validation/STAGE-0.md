# 阶段 0 验证报告

- 日期：2026-10-20
- 版本：`0.1.0`（`src/tidymate_core/_version.py`）
- 阶段目标：搭出**能 build、能 test、CI 能出 Windows artifact** 的空壳，不实现任何文件移动/删除逻辑。

## 1. 验证环境

| 项 | 值 |
| --- | --- |
| OS | Windows 11（10.0.22621）x64 |
| Python | 3.13.7（仓库声明 `>=3.12`，CI 固定 3.12 + 3.13 双版本） |
| PowerShell | Windows PowerShell **5.1.22621**（本机无 `pwsh` 7；CI 用 `pwsh` 7） |
| git | **未安装**（`git` 不在 PATH，常见安装路径均不存在）→ 影响见第 5 节 |
| 包管理器 | pip 26.2.1（由 25.2 升级） |

## 2. 执行记录与真实输出

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `python -m pip install -e ".[dev]"` | 成功；安装 pytest 9.1.1 / pytest-cov 7.1.0 / mypy 2.4.0 / ruff 0.17.1 / typer 0.27.3 / PyYAML 6.0.3 / hypothesis 6.170.5 / build 1.6.1 |
| 2 | `python -m ruff check .` | `All checks passed!` |
| 3 | `python -m ruff format --check .` | `37 files already formatted` |
| 4 | `python -m mypy` | `Success: no issues found in 30 source files`（`strict = true`） |
| 5 | `python -m pytest` | **112 passed, 0 failed, 0 skipped**；覆盖率 **95.65%**（阈值 90%） |
| 6 | `python scripts/check_forbidden_apis.py` | `OK: no forbidden delete APIs in 24 scanned files.` |
| 7 | `python -m tidymate_cli --version` | `tidymate 0.1.0` |
| 8 | `python -m build --wheel --outdir dist` | `Successfully built tidymate-0.1.0-py3-none-any.whl` |
| 9 | `python scripts/make_dist.py` | `dist/TidyMate-0.1.0-windows.zip (1887 bytes)`；sha256 `02249801170f25c58efa89fa149575b25c5f6c61730edd3d2e66734b2468ca83` |
| 10 | `powershell -File scripts/make-sandbox.ps1` | 退出码 0；`entries: 35 (32 files)`；超长路径 328 字符（相对 272） |
| 11 | `python scripts/apply_labels.py --dry-run` | 输出 10 条 `gh label create ...`，末尾 `applied 10 labels` |

### 2.1 沙箱脚本真实清单（节选）

```text
TidyMate drill sandbox manifest
root      : C:\Users\ASUS\AppData\Local\Temp\tidymate-sbx-doc-112323
entries   : 35 (32 files)

PATH | KIND | BYTES | NOTE
inbox\notes.txt | file | 18 |
inbox\report.docx | file | 44 |
...
inbox\文件-中文名.txt | file | 20 |
inbox\keep\photo.jpg | file | 23 | duplicate basename A
inbox\tmp\photo.jpg | file | 23 | duplicate basename B
inbox\子目录 带空格\readme.txt | file | 25 |
empty-dir | dir | 0 | empty directory
inbox\zero-byte.bin | file | 0 | zero byte file
inbox\locked-readonly.txt | file | 17 | FILE_ATTRIBUTE_READONLY
inbox\system-flagged.dat | file | 24 | FILE_ATTRIBUTE_SYSTEM
inbox\hidden-attribute.txt | file | 24 | FILE_ATTRIBUTE_HIDDEN
inbox\with-alternate-stream.txt | file | 22 | has Zone.Identifier ADS
inbox\longname-nnnn...nnnn.txt | file | 22 | filename length 193
longpath\segment-LLL...01\...\segment-LLL...06\deep-payload.txt | file | 16 | long path: 328 chars, 272 relative
```

## 3. 验收标准逐条对照

| 验收项 | 结论 | 证据 |
| --- | --- | --- |
| build 与 test 本地通过 | ✅ | 第 2 节 #2–#5、#8 |
| CI 能下载到 windows artifact | ✅ **已验证（2026-10-20 补记）** | GitHub Actions run [#39375183042](https://github.com/xueyuanli186/TidyMate/actions/runs/39375183042)（`5a88428`）五个 job 全绿，artifact `TidyMate-0.1.0-windows` 已产出（67,713 字节，sha256 `7ed571b1e30d5fc080b0f183601df85cc749d62dc2a2e1d47c9e6f1250c283cc`，保留 14 天）。run #1 的失败根因与修复见第 5 节 |
| 仓库治理文件存在且 YAML 有效 | ✅ | `test_repo_governance.py`：6 个 YAML 全部可解析；10 个标签名精确匹配；issue 表单字段完整；PR 模板含人工 review 条款 |
| 沙箱脚本结构符合预期并打印清单 | ✅ | 第 2 节 #10、2.1 节 |

## 4. .NET 措辞 → Python 实现 对照

| 原要求（.NET 措辞） | 本仓库实现 |
| --- | --- |
| `TidyMate.sln` + 三个项目文件 | 单个 `pyproject.toml`（hatchling），三个包同仓：`tidymate_core` / `tidymate_cli` / `tidymate_app` |
| `src/TidyMate.Core/Scanning` | `src/tidymate_core/scanning`（9 个分层包名与语义一一对应） |
| `<Nullable>enable</Nullable>` | `[tool.mypy] strict = true` |
| `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>` | `[tool.pytest.ini_options] filterwarnings = ["error"]` + CI 中 ruff/mypy 失败即失败 |
| `Directory.Build.props` 的 `Version` | `src/tidymate_core/_version.py`（hatchling 从它取版本；`scripts/version.py` 是唯一读取入口） |
| `dotnet restore/build/test` | `pip install -e ".[dev]"` / `python -m build` / `python -m pytest` |
| `WPF GUI` | PySide6（可选依赖 `.[gui]`，Core 不引用） |

## 5. 验证边界（已验证与未验证，如实记录）

1. **CI 已验证（2026-10-20 补记）**：安装 git 后仓库推送到 `https://github.com/xueyuanli186/TidyMate`，工作流真实执行了两轮：
   - **run #1**（`f91163e`）失败：`safety guard` job 三个实际步骤都通过，但
     `Post Set up Python 3.12` 失败。根因是 `cache: pip` 配在一个不安装任何包的
     job 上，`setup-python` 收尾时 pip 缓存目录不存在，保存缓存失败 → job 失败 →
     `package` 被 skip，**没有 artifact**。GitHub 的注解原文：
     *"Cache folder path is retrieved for pip but doesn't exist on disk"*。
   - **修复**（`5a88428`）：移除该 job 的 `cache: pip`；同时把 `pyproject.toml`
     的 license 对齐为 Apache-2.0（与仓库里的 LICENSE 一致，wheel 元数据已验证为
     `License: Apache-2.0` + `License-File: LICENSE`）。
   - **run #2（id `39375183042`）五个 job 全部 success**（lint / test 3.12 / test 3.13 / safety /
     package），artifact `TidyMate-0.1.0-windows`（67,713 字节）已产出。
   - **仍未验证**的只剩 `release.yml`：它由 `v*` tag 触发，本项目还没有正式发布。
2. **MSI（WiX v4）不存在**：`release.yml` 的 MSI 步骤是显式占位（打印警告并成功退出），
   Release 说明里写明 "Not included yet"。`build/build_msi.py` 存在但以退出码 69 拒绝执行。
3. **PySide6 已验证（2026-10-20 补记）**：阶段 0 时只有导入探测；阶段 4 写出窗口后，
   `PySide6 6.12.0` 安装成功，5 个 GUI 用例通过，并有原生渲染截图
   `docs/images/gui-dry-run.png`。详见 `docs/validation/STAGE-3-4.md` 第 6 节。
4. **符号链接降级为硬链接**：本机未开启开发者模式且非管理员，`New-Item -ItemType SymbolicLink`
   失败，脚本按设计降级为硬链接并把原因写入 manifest 的 NOTES 段。**符号链接分支本身未被真实执行过。**
5. **PowerShell 7 已验证（2026-10-20 补记）**：本机只有 5.1，但 CI 的 `safety` job
   用 `shell: pwsh`（PowerShell 7）在 `windows-latest` 上完整执行了
   `scripts/make-sandbox.ps1` 并成功产出了 manifest（run #2 该步骤 success）。
   结论：脚本在 5.1 与 7 上都能跑；但**这次 CI 只覆盖了“能跑通”，没有逐项断言
   脚本产物**（例如 junction 是否创建成功），那部分仍靠本地 5.1 的测试覆盖。

## 6. 本阶段刻意未做的事

- 没有任何文件移动、重命名、复制、删除、回收站、日志、扫描、规则、模板代码。
- `tidymate` 只有 `--version` 与 `status` 两个命令，`status` 明说 "not implemented yet"。
- 没有 LICENSE（许可未定），README 已注明"不是可自由分发的开源项目"。

## 7. 复现步骤

```powershell
cd "E:\deepseek work\TidyMate"
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
python scripts/check_forbidden_apis.py
python scripts/make_dist.py
pwsh -File scripts/make-sandbox.ps1     # 或用 powershell -ExecutionPolicy Bypass
```
