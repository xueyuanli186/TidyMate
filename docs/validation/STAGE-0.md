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
| CI 能下载到 windows artifact | ⚠️ **未验证** | 工作流已写好（`ci.yml` 的 `package` job + `upload-artifact`，名字 `TidyMate-0.1.0-windows`，保留 14 天）；但本机无 git，无法推送触发。等价步骤已在本地逐步执行通过（第 2 节 #8/#9） |
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

## 5. 未验证项与原因（必须如实记录）

1. **CI 未在 GitHub 上真实运行过**：本机没有 git，无法 `git init` / `push` / 打 tag。
   `ci.yml`、`release.yml` 只做了 YAML 语法与结构校验（pytest）和本地等价命令执行。
   **"能下载到 artifact" 这条验收目前是"未验证"，不是"通过"。**
2. **MSI（WiX v4）不存在**：`release.yml` 的 MSI 步骤是显式占位（打印警告并成功退出），
   Release 说明里写明 "Not included yet"。`build/build_msi.py` 存在但以退出码 69 拒绝执行。
3. **PySide6 未安装**：GUI 只有导入探测，未创建窗口。
4. **符号链接降级为硬链接**：本机未开启开发者模式且非管理员，`New-Item -ItemType SymbolicLink`
   失败，脚本按设计降级为硬链接并把原因写入 manifest 的 NOTES 段。**符号链接分支本身未被真实执行过。**
5. **PowerShell 7 未验证**：本机只有 5.1。脚本按 5.1 语法编写并实测通过；CI 用 pwsh 7，
   两者在 `-Stream`、`New-Item -ItemType Junction`、`::new()` 上行为一致，但**未实测**。

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
