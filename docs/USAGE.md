# 怎么用 TidyMate

> 面向使用者的操作指南。开发者视角的架构与验证记录在 `docs/validation/`。
> 当前是**阶段 8**：还没有安装包，需要从源码运行（阶段 9 打包后才会有 exe/MSI）。

## 0. 一次性准备

需要 Python 3.12 或 3.13。

```powershell
cd "E:\deepseek work\TidyMate"
python -m pip install -e ".[gui]"     # 装本体 + 图形界面
```

只跑命令行可以省掉 `gui`：

```powershell
python -m pip install -e .
```

检查是否能跑：

```powershell
python -m tidymate_cli --version
python -m tidymate_cli status
```

## 1. 先做一次安全演练（强烈建议）

不要第一次就指向真实目录。先生成演练沙箱：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\make-sandbox.ps1
```

最后一行会打印 `SANDBOX_ROOT=...`（形如 `%TEMP%\idymate-sandbox-20261020-202343`）。
把它记下来，后面的命令用它替换 `xxxx`。目录里是各种陷阱文件
（只读、长路径、junction、ADS、中文名、重名），全部是假数据。

然后写一个规则文件，例如 `rules.yaml`：

```yaml
rules:
  - id: images
    when: { ext: [".jpg", ".jpeg", ".png"] }
    action: { op: move, template: "Pictures/{year}/{name}", conflict: skip }

  - id: documents
    when: { ext: [".pdf", ".docx", ".xlsx", ".pptx"] }
    action: { op: move, template: "Documents/{year}/{ext_nodot}/{name}", conflict: rename }

  - id: junk
    when: { ext: [".tmp"] }
    action: { op: trash }
```

## 2. 预览（不改任何文件）

```powershell
python -m tidymate_cli plan "$env:TEMP\tidymate-sandbox-xxxx\inbox" `
    -r rules.yaml `
    -o "$env:TEMP\tidymate-sandbox-xxxx\Sorted" `
    --export "$env:TEMP\tidymate-sandbox-xxxx\reports"
```

输出里最关键的三个东西：

- `batch=dryrun-20261020-XXXXXX` —— 下一批操作要用的批次号；
- `execute / skip / reject / conflicts` —— 将执行、跳过、拒绝、冲突的数量；
- 表格里的 `!` 行 —— 冲突项，需要你决定。

同时会写 `plan.json` 与 `report.md`（`--export` 目录），`report.md` 里有人能读的说明。

## 3. 执行

```powershell
python -m tidymate_cli apply dryrun-20261020-XXXXXX
```

会先做五道门禁（预览的 plan_hash 是否还匹配、黑名单、祖孙目录、日志可写、磁盘空间），
任何一条不过就**整批拒绝**，不会"执行一半"。

通过后会显示：

```text
将执行 12 条，涉及 3 个目录，其中 trash 1 条。
冲突策略：按规则（skip 默认）
确认执行请输入 YES:
```

必须手动输入 `YES`（区分大小写不敏感，但空输入会重新提示，EOF/Ctrl+C 直接中止）。
`--yes` 只用于自动化测试，日常别用。

## 4. 核对与撤销

```powershell
python -m tidymate_cli verify dryrun-20261020-XXXXXX      # 日志与磁盘逐条对照
python -m tidymate_cli undo  dryrun-20261020-XXXXXX       # 先 dry-run 预览
python -m tidymate_cli undo  dryrun-20261020-XXXXXX --yes # 确认后真正回滚
```

`undo` 不带 `--yes` 时同样要求输入 `YES`。回滚会逐条校验文件大小与 mtime：
被你在 apply 之后改过的文件不会被动，标记为 `modified_since` 并写进错误报告。

其他查询：

```powershell
python -m tidymate_cli list-batches          # 最近的批次
python -m tidymate_cli show-batch <batch_id> # 单个批次的每条操作
python -m tidymate_cli status                # 最近批次 + 统计
```

## 5. 图形界面

```powershell
python -m tidymate_app.main
```

1. 填「源目录」「规则文件」「目标根目录」；
2. 点 **Dry-run 预览**，表格里看结果（冲突粉色、拒绝浅黄）；
3. 点 **执行…**，确认框会显示条数/目录数/trash 数/冲突策略，
   勾选「我已备份，或已在测试目录演练过」才能确认；
4. 点 **撤销…**，先看"将回滚 N 条"的预览，再勾选确认。

界面与命令行共用同一套门禁、执行器和撤销引擎，行为一致。

## 6. 文件与日志在哪

| 内容 | 位置 |
| --- | --- |
| 日志数据库 | `%LOCALAPPDATA%\TidyMate\tidymate.db`（可用 `--db` 指定） |
| 错误报告 | `%LOCALAPPDATA%\TidyMate\reports\errors-<batch_id>.md` / `.json` |
| 预览导出 | `plan` 的 `--export` 目录（`plan.json` / `report.md`） |
| 被删除的文件 | Windows 回收站（可用 `undo` 还原） |

## 7. 哪些文件会被跳过（正常现象）

- 只读 / 系统 / 隐藏属性文件；
- 符号链接、junction、其他 reparse point；
- 路径超过 260 字符的源文件；
- 硬链接、稀疏文件；
- 带备用数据流（如 `Zone.Identifier`）的文件；
- OneDrive "仅在线"未下载的占位文件。

这些在报告里都有单独分组与处理指引（例如 OneDrive 先"始终保留在此设备上"，
ADS 先用 Sysinternals Streams 查看）。

## 8. 已知限制

- 还没有安装包（阶段 9 才会出 PyInstaller/MSI）；
- GUI 执行是同步的，几百条会短暂卡住界面；
- GUI 没有历史批次选择器（撤销针对刚执行的批次；历史批次用 CLI）；
- 真人鼠标交互（文件选择框、拖列宽）尚未系统验证。

## 9. 出问题时

1. 先看 `%LOCALAPPDATA%\TidyMate\reports\errors-<batch_id>.md`；
2. `verify <batch_id>` 看日志与磁盘哪里不一致；
3. 撤销失败的文件不会被动，按报告里的 `error_kind` 处理：
   `modified_since`（被改过）、`missing`（不在了）、`src_occupied`（原位置被占）、
   `recycle_gone`（回收站里没了，需要从备份恢复）。
