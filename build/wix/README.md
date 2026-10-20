# WiX v4 打包计划（阶段 0 占位）

这个目录现在**只有文档**。阶段 0 不产出 MSI，也不假装产出 MSI：`release.yml` 里的
MSI 步骤是一条会打印警告、并以成功退出码结束的占位，Release 说明里也明确写了
"Not included yet: MSI installer"。

## 目标形态

```
dist/TidyMate-<version>-windows.zip        便携版（onedir + python 运行时）
dist/TidyMate-<version>-windows.msi        安装包（WiX v4，per-machine 或 per-user 待定）
```

## 为什么是 onedir + MSI，而不是 onefile

- `onefile` 每次启动都要解压到临时目录：启动慢、临时目录残留、杀软启发式扫描命中率高。
- `onedir` 目录结构稳定，WiX 收割（harvest）时文件清单可预期，升级/修复更可控。

## 待验证（不确定，需要实测，不写死结论）

1. **PyInstaller 与 PySide6 的 onedir 产物体积与依赖**：Qt 插件目录（`platforms/`、
   `styles/`、`imageformats/`）必须显式带上，否则 GUI 在无 dev 环境的机器上黑屏/崩溃。
2. **WiX v4 的目录收割方式**：`<Files Include="...">` 通配 vs `heat.exe` 生成的 `.wxs`。
   两者在 v4 下的推荐用法需要以实测结果为准，本阶段不下结论。
3. **MSI ProductVersion 与升级规则**：MSI 只接受 `MAJOR.MINOR.PATCH` 三段数字，
   主版本变化会触发 major upgrade；版本号必须来自 `src/tidymate_core/_version.py`。
4. **安装位置与权限**：per-user 安装（`%LOCALAPPDATA%`）不需要提权，但"系统目录黑名单"
   与"程序目录黑名单"的实现要能识别自己安装在哪，避免把自己整理掉。
5. **签名**：未签名 MSI 会触发 SmartScreen。是否购买证书尚未决定。
6. **卸载时的数据处理**：卸载**不得**删除用户的撤销日志与配置，也不得清理用户目录。
   这一点必须在 WiX 里显式排除，不能依赖默认行为。

## 落地时的验收（预留）

- 干净 Windows 11 VM 上安装 → `tidymate --version` 与 MSI 版本一致 → dry-run 可用 → 卸载。
- 卸载后 `%LOCALAPPDATA%\TidyMate\journal.db` 仍在（用户可自行决定是否删除）。
- MSI 不含任何网络安装步骤。
