# 阶段 9 验证报告：便携版与 MSI

- 日期：2026-10-20
- 范围：PyInstaller onedir 打包、便携 zip、WiX v4 MSI、CI 发布链路
- 结论：便携版已在本机真实构建并通过冒烟（`tidymate --version` → `0.1.0`）；
  MSI 的 WiX 源与构建脚本已落地，本机没有 WiX v4，**由 CI 验证**，不在此谎称已产出安装包。

## 1. 便携版（本机真实产物）

```text
$ python scripts/make_dist.py
bundle : E:\deepseek work\TidyMate\dist\TidyMate-0.1.0-windows
zip    : ...\TidyMate-0.1.0-windows.zip (54287528 bytes)
sha256 : 577d5f0c89134bfd0ba7d84a897e131e1d83f43b73c6c726e5ecc107acc371ab
```

目录布局：

```text
TidyMate-0.1.0-windows/
    TidyMate.exe        GUI（windowed，无控制台）
    _internal/          Qt 6 / Python 3.13 运行时
    cli/
        tidymate.exe    CLI（console）
        _internal/      CLI 自己的运行时
    VERSION.txt
```

冒烟（真实输出）：

```text
$ .\dist\TidyMate-0.1.0-windows\cli\tidymate.exe --version
tidymate 0.1.0
```

为什么 CLI 在 `cli/` 子目录：两个可执行文件各自带一份 `_internal`，互不干扰。

## 2. 一次失败与原因（记录在案）

最初的 spec 用**两个 Analysis + 一个共享 PYZ**，产出的 `tidymate.exe` 启动后无输出、
无限挂起（120 秒仍未退出），且两个 exe 大小完全相同——共享 `PYZ-00.pyz` 让两个入口
互相覆盖。改为**两次独立 PyInstaller 构建**后 CLI 立即正常。

这个坑值得保留：以后想"省体积"合并两个入口时，先验证 `--version` 能打印。

## 3. MSI（WiX v4）

- 源：`build/wix/TidyMate.wxs`
  - per-machine 安装到 `ProgramFiles64Folder\TidyMate`；
  - `<Files Include="$(var.SourceDir)\**" />` 收割整个 onedir 树；
  - 开始菜单两个快捷方式（GUI 与 CLI）；
  - `MajorUpgrade`；卸载只删程序文件与快捷方式，**不碰 `%LOCALAPPDATA%\TidyMate`**
    （没有 `RemoveFolderEx`，没有用户数据目录）；
- 构建：`python build/build_msi.py --version <v> --source <bundle> --output <msi>`
  - 版本由 `_version.py` 归一化为 `MAJOR.MINOR.PATCH`；
  - 没有 WiX 时返回 69 并说明安装方法，**不会假成功**。
- CI：`package` job 安装 `wix`（dotnet tool）后构建 MSI，并校验 zip、sha256、两个 exe、
  MSI 都存在；artifact 上传包含 `.msi`。

本机未安装 WiX v4，因此 MSI 的"安装 → 运行 → 卸载"未在本机验证；CI 只验证"能构建"。
**未验证项**：干净 VM 上安装/卸载、快捷方式、SmartScreen/签名、升级路径。

## 4. CI 变更

`package` job 现在：

1. `pip install ... pyinstaller`；
2. `python scripts/make_dist.py`（PyInstaller 构建 + zip + sha256）；
3. `dotnet tool install --global wix` + `python build/build_msi.py ...`；
4. 校验 `cli/tidymate.exe`、`TidyMate.exe`、zip、sha256、msi；
5. 上传 `zip` / `zip.sha256` / `msi` / `whl`。

`release.yml` 的 MSI 占位已替换为真实构建步骤，并把 `dist/*.msi` 加入发布文件。

## 5. 测试

```text
$ python -m pytest -q
572 passed, 90.30% coverage
```

打包契约测试（不跑 PyInstaller，CI 跑）：

- bundle/zip 命名；
- `zip_bundle` 只写相对路径、拒绝不存在的目录；
- sha256 与 hashlib 一致；
- 入口文件存在、布局常量在脚本里；
- WiX 使用 `$(var.Version)` / `$(var.SourceDir)`，安装到 Program Files，且不含
  `RemoveFolderEx` / `LocalAppDataFolder`（用户数据不被卸载删除）；
- MSI 版本归一化（`0.1.0.dev1` → `0.1.0`）；
- 没有 WiX 时 `build_msi.py` 返回 69。

## 6. 未验证项

1. **MSI 的安装/卸载**：本机无 WiX，只有 CI 构建证据。
2. **干净 Windows 11 VM**：便携版与 MSI 都未在无 Python 环境的机器上启动过。
3. **GUI 版首次启动**：windowed exe 无法在当前无显示环境冒烟。
4. **签名**：未签名，SmartScreen 会告警（是否购买证书仍未决定）。
5. 版本仍是 `0.1.0`；发布流程需要打 `v0.1.0` tag，`release.yml` 未实测。

## 7. 复现

```powershell
python -m pip install pyinstaller
python scripts/make_dist.py
.\dist\TidyMate-0.1.0-windows\cli\tidymate.exe --version

# MSI（需要 WiX v4）
dotnet tool install --global wix
python build/build_msi.py --version 0.1.0 `
    --source dist/TidyMate-0.1.0-windows `
    --output dist/TidyMate-0.1.0-windows.msi
```
