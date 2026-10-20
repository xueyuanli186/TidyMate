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

### 3.1 本机构建与验证（2026-10-20，WiX **v7**）

```text
$ wix --version
7.0.0+b8977d6

$ wix eula accept wix7          # v7 要求一次性接受 OSMF EULA
$ python build/build_msi.py --version 0.1.0       --source dist/TidyMate-0.1.0-windows       --output dist/TidyMate-0.1.0-windows.msi
msi    : ...\TidyMate-0.1.0-windows.msi (40890368 bytes)
version: 0.1.0
```

MSI 属性（用 WindowsInstaller COM 读取 Property 表）：

```text
ProductName=TidyMate
ProductVersion=0.1.0
Manufacturer=TidyMate Project
UpgradeCode={6F2A9C1E-4B7D-4E83-9C0A-2F5B8D7E1A34}
ALLUSERS=1
```

管理安装提取（`msiexec /a`，不修改系统）验证载荷：

```text
PFiles64\TidyMate\TidyMate.exe        2,205,606 bytes
PFiles64\TidyMate\cli	idymate.exe   6,103,117 bytes
PFiles64\TidyMate\VERSION.txt         TidyMate 0.1.0

$ ...\PFiles64\TidyMate\cli	idymate.exe --version
tidymate 0.1.0
```

### 3.2 安装与卸载验证（管理员，2026-10-20）

```text
uninstall {98AABDBC-...} exit=0
uninstall {6D99EDCD-...} exit=0
after uninstall: {"program": false, "menu": false, "arp": 0, "userdb": true}
install exit=0

ARP: TidyMate 0.1.0 {6D99EDCD-4348-4297-9337-16DC6F31254D}
TidyMate CLI.lnk -> C:\Program Files\TidyMate\cli\tidymate.exe
TidyMate.lnk     -> C:\Program Files\TidyMate\TidyMate.exe
$ tidymate --version
tidymate 0.1.0
user data: C:\Users\ASUS\AppData\Local\TidyMate\tidymate.db (28,672 bytes, 卸载后仍在)
```

验证到的三件事：程序文件与快捷方式随卸载消失；ARP 条目清零；**用户日志/数据库保留**。

### 3.3 本阶段抓到并修复的两个 bug

1. **`\t` 被当成制表符**：`Target="[INSTALLFOLDER]cli\tidymate.exe"` 编译后变成
   `cli<TAB>idymate.exe`，快捷方式失效。改用 XML 实体 `&#92;` 表示反斜杠。
   修复前用 WindowsInstaller COM 读 Shortcut 表确认，修复后同法确认。
2. **ProductCode 每次构建随机**：同版本重建后 `msiexec /x <msi>` 报 **1605**，ARP 里
   出现两条同版本记录。改为按版本派生稳定 UUID（uuid5），同一版本 ProductCode 固定、
   下一版本自动变化；测试 `test_product_code_is_stable_per_version` 锁住。

**真实安装未完成**：当前会话不是管理员，`msiexec /i ... /qn` 返回 **1603**（per-machine
安装需要提权）。因此"安装 → 快捷方式 → 卸载"仍属未验证项。

CI 侧：`dotnet tool install --global wix` 会装 v7，工作流已加入
`wix eula accept wix7`，否则 CI 也会被 WIX7015 拦住。

### 3.4 干净 Windows 11 VM 验收（2026-10-20）

VM：Windows 11 x64（VMware Workstation），账号 `admin`，**没有 Python、没有 Qt**。
`scripts/verify-install.ps1` 在 VM 内以管理员身份自动完成：安装 → 检查 → 启动 GUI →
卸载，并输出 JSON。

```json
{
  "is_admin": true,
  "installed": true,
  "cli_version": "tidymate 0.1.0",
  "gui_started": true,
  "user_data_before": false,
  "uninstall": {
    "program_left": false,
    "menu_left": false,
    "arp_left": 0,
    "{3F99551E-73EE-5C4E-921C-03E00FE6B48D}": 0,
    "user_data_after": true
  },
  "errors": []
}
```

- 安装后 `C:\Program Files\TidyMate` 共 192 个文件，两个可执行文件大小与主机一致
  （`TidyMate.exe` 2,205,606；`cli\tidymate.exe` 6,103,117）；
- 两个快捷方式目标都正确且指向存在的文件；
- ARP 只有一条 0.1.0，ProductCode 是稳定的 `{3F99551E-...}`；
- **GUI 在没有 Python 的机器上启动并保持运行**（脚本启动 6 秒后仍未退出，随后关闭）；
- 卸载后程序目录、开始菜单、ARP 全部清零，`%LOCALAPPDATA%\TidyMate` 保留。

结论：干净 Windows 11 上“安装 → 双击可用 → 卸载不丢用户数据”已成立。

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

1. **干净 VM**：已完成（见 3.4），无 Python/Qt 的 Windows 11 上安装、启动、卸载均通过。
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
