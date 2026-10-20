# 阶段 5-6 验证报告：冲突处理与执行器

- 日期：2026-10-20
- 范围：M5（冲突处理：skip / rename / ask）与 M6（执行器：move / rename / copy / trash）
- 结论：四种操作、三种冲突策略、五道门禁、写前日志、幂等、崩溃恢复、取消与熔断均已落地；
  **首次允许真实写盘**，全部证据来自临时沙箱。
- 尚未完成：撤销（ROADMAP 阶段 6）、GUI 二次确认与 ask 弹窗（阶段 8）。

## 1. 写盘边界（本阶段最重要的变化）

阶段 5 之前，产品代码只有一个写入口（导出报告）。现在有三个，全部是 reviewed exception：

| 模块 | 允许做什么 | 依据 |
| --- | --- | --- |
| `execution/executor.py` | move / rename / copy / trash | 唯一移动文件的模块；删除只走 `send2trash` |
| `journal/db.py` | 建库、写 batches / operations | 写前日志，SQLite WAL，逐条提交 |
| `planning/artifacts.py` | 写 `plan.json` / `report.md` | 阶段 3-4 的报告导出 |

```text
$ python scripts/check_readonly.py
OK: no write calls in 39 product files.

$ python scripts/check_forbidden_apis.py
OK: no forbidden delete APIs in 56 scanned files.
```

## 2. 真实沙箱执行（原样输出）

沙箱 3 个文件：`photo.jpg`（move）、`notes.txt`（copy）、`junk.tmp`（trash）。

```text
TidyMate dry-run  batch=dryrun-20261020-193713  hash=d09cd496eb18ca25
scanned=3 matched=3 execute=3 skip=0 reject=0 conflicts=0

 seq   status  op     rule             conflict       source                             -> destination
-------------------------------------------------------------------------------------------------------
   1   execute trash  junk             -              C:\...\inbox\junk.tmp -> <recycle bin>
   2   execute copy   text             -              C:\...\inbox\notes.txt -> C:\...\Sorted\Text\notes.txt
   3   execute move   images           -              C:\...\inbox\photo.jpg -> C:\...\Sorted\Pictures\2026\photo.jpg

dry-run only: no files were modified.  batch=dryrun-20261020-193713
```

```text
将执行 3 条，涉及 2 个目录，其中 trash 1 条。
冲突策略：per-rule (skip 默认)
     1 ok         C:\...\inbox\junk.tmp -> -
     2 ok         C:\...\inbox\notes.txt -> C:\...\Sorted\Text\notes.txt
     3 ok         C:\...\inbox\photo.jpg -> C:\...\Sorted\Pictures\2026\photo.jpg

完成：ok=3 failed=0 skipped=0 interrupted=0
```

落盘结果（用文件系统快照，不看日志）：

```text
--- files in Sorted ---
Pictures/2026/photo.jpg 4
Text/notes.txt 5
--- inbox left ---
['notes.txt']          # copy 的源按设计保留；move 的源已消失
```

## 3. 门禁（任一不通过 → 整批拒绝）

| 门禁 | 实现 | 用例 |
| --- | --- | --- |
| 同 plan_hash 的 dry-run 存在 | `journal.load_plan` + hash 比对 | `test_gate_rejects_a_batch_without_a_preview`、`::test_gate_rejects_a_changed_plan` |
| 显式 `--apply` / 二次确认 | CLI 要求输入 `YES`（`--yes` 仅测试用） | `test_plan_then_apply_moves_files`、`test_first_run_prompt_can_abort_before_scanning` |
| 黑名单零命中 | `gate.evaluate` 对 src/dst 逐条检查 | 参数化：Windows / Program Files / ProgramData\Microsoft / $Recycle.Bin / Boot / 盘符根 / 用户目录 |
| 祖先零命中 | src 与 dst 互为祖先即拒绝 | `test_gate_rejects_an_ancestor_target` |
| SQLite 可写 + 空间 ≥ copy×1.2 | `Journal.check_writable` + `shutil.disk_usage` | `test_gate_rejects_when_the_copy_would_not_fit` |

黑名单是**代码**，不是配置：`check_blacklisted` 没有"关闭"参数（测试用 `inspect.signature` 锁住）。
UNC 单独走 `check_unc`，只有 `--allow-unc` 能放行，且其余校验照旧。

## 4. 四种操作与三种冲突策略

| 操作 | 实现要点 | 用例 |
| --- | --- | --- |
| move | 同卷 `os.rename`（目标存在即失败）；跨卷 copy→校验→rename→回收源 | `test_move_writes_intent_then_ok`、`test_cross_volume_move_copies_then_recycles` |
| rename | 仅同目录改名 | `test_rename_stays_in_the_same_directory` |
| copy | `shutil.copy2`，保留 mtime，源不动 | `test_copy_keeps_the_source_and_the_mtime` |
| trash | `send2trash`，日志留原始路径（`src`） | `test_trash_goes_to_the_recycle_bin` |

冲突策略：

| 策略 | 行为 | 用例 |
| --- | --- | --- |
| skip（默认） | 目标存在则记录 `skip` + `exists_on_disk` | `test_gate_rejects_a_blacklisted_target`（前置）、planner 既有用例 |
| rename | `name (1..999)` → `name_时间戳` → `failed` | `test_rename_falls_back_to_a_timestamp_after_999_candidates` |
| ask | CLI 逐条 y/n/s/q；`q` 中止且保留日志 | `test_ask_yes_never_overwrites_either`、`::test_ask_no_skips_without_touching`、`::test_ask_quit_aborts_the_batch` |

命令级覆盖：`plan --conflict rename` 会在计划 warnings 里写
"existing files are renamed, never overwritten"，`apply` 的确认框原样显示这句话。

## 5. 文件移动/删除逻辑自检（逐条）

**1）不覆盖任何已有文件。**
所有写路径在动手前检查目标是否存在：`_ensure_absent()` 覆盖 rename / move / copy；
同卷 move 用 `os.rename`，Windows 上目标存在会抛 `FileExistsError`，不存在"先删再放"的分支；
跨卷 move 先把副本落到 `*.tidymate-partial`，再 `os.rename` 到最终名（同样不覆盖）。
仓库里没有 `os.replace`，也没有任何 `overwrite=True` 的调用。
证据：`test_executor_refuses_to_overwrite_an_existing_destination`（旧内容原样保留、源文件仍在）、
`test_ask_yes_never_overwrites_either`（用户选择"执行"也不会覆盖，结果是 `failed`）。

**2）不永久删除。**
唯一的删除 API 是 `send2trash`；连"回滚自己刚写的副本"也走回收站
（`_move_across_volumes` 的失败分支）。CI 的文本扫描覆盖 `os.remove` / `unlink` /
`shutil.rmtree` / `File.Delete` / `SHFileOperation` 等 12 类写法，命中即红。
证据：`python scripts/check_forbidden_apis.py` → `OK ... 56 scanned files`。

**3）不误报成功。**
`ok` 只在两件事都被验证后写入：目标存在（`os.path.exists(dst)`）且
move/rename 的源已消失。跨卷额外比对文件大小与 SHA-256。
日志写入顺序是 intent（planned）→ 操作 → finish(ok/failed)，任何时刻崩溃都不会出现
"日志说成功但文件没动"。
证据：`test_move_writes_intent_then_ok` 断言 journal 的 `state`、`final_dst` 与磁盘一致。

**4）写前日志、崩溃可辨。**
`journal.intent()` 提交后才调用文件系统；崩溃留下的 `planned` 行由 `recover()` 改为
`interrupted`，不会猜成 `ok`。
证据：`test_recover_marks_unfinished_intent_as_interrupted`（源文件仍在，状态是 interrupted）。

**5）重复执行被拒绝、断点可续。**
`batches.status == applied` 时 `start_apply` 抛 `BatchAlreadyAppliedError`；
崩溃后重跑会跳过 `completed_seqs` 里已 `ok` 的条目。
证据：`test_repeated_apply_of_the_same_batch_is_rejected`、
`test_completed_operations_are_skipped_on_rerun`、CLI 用例 `test_second_apply_of_the_same_batch_is_refused`（exit 4）。

**6）失败不静默、熔断可暂停。**
单条失败写 `failed` + `error_kind`（`in_use` / `permission_denied` / `disk_full` / `os_error`），
连续 5 条失败触发熔断并停止批次。
证据：`test_fuse_stops_after_consecutive_failures`。

**7）取消后已完成部分仍可撤销。**
每条操作之间检查 `CancelToken`；取消只停止后续，不回收已完成的结果。
证据：`test_cancel_stops_between_operations`。

**8）特殊文件不静默通过。**
ADS / OneDrive 占位在计划阶段 `skip` 并分类（阶段 3-4 返工）；
只读、系统、硬链接、稀疏、reparse point、长路径在计划阶段 `reject` 并写明原因；
被占用文件在执行阶段 `failed` 且 `error_kind=in_use`。

## 6. 测试

新增/更新：

- `tests/tidymate_core_tests/test_execution.py`：27 个用例（四种操作、门禁、幂等、恢复、熔断、取消、黑名单类别、空间）；
- `tests/tidymate_integration_tests/test_apply_cli.py`：5 个用例（plan → apply 落盘、未预览拒绝、重复 apply 拒绝、首次运行中止、黑名单整批拒绝）；
- `tests/tidymate_integration_tests/test_ask_cli.py`：3 个用例（y / n / q）；
- 更新 `test_smoke.py`（CLI 表面、status 文案）、`test_blacklist.py`（`C:` 视为根）。

```text
$ python -m pytest -q
Required test coverage of 90.0% reached. Total coverage: 90.59%
529 passed in 4.23s
```

## 7. 与需求的偏差与未验证项

1. **GUI 二次确认与 ask 弹窗未实现**：当前 GUI 是阶段 4 的最小界面，执行按钮仍禁用；
   GUI 属于阶段 8，届时复用 `Executor` 与 `gate.evaluate`，确认框文案已由 CLI 固化。
2. **跨卷 move 只有模拟证据**：本机没有第二个卷，测试用 monkeypatch 走同一条代码路径；
   真实跨卷（U 盘/网络盘）未验证。
3. **`--limit` / `--only-rule` 已有测试**（`test_limit_and_only_rule`），但 CLI 层只覆盖了 `--limit` 的默认路径。
4. **安装器目录检测是启发式**：只看目录顶层是否有 `unins*.exe` / `*.msi`，不递归；
   深层嵌套的程序目录可能漏判。
5. **撤销（ROADMAP 阶段 6）未开始**：日志已经能支撑按 batch 回滚（每条的 src/dst/state 都在），
   但回滚引擎本身没有实现。

## 8. 复现

```powershell
python -m pytest -q
python -m ruff check . ; python -m ruff format --check .
python -m mypy
python scripts/check_forbidden_apis.py
python scripts/check_readonly.py

# 沙箱演练
$root = Join-Path $env:TEMP ("tidymate-demo-" + (Get-Date -Format "HHmmss"))
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/make-sandbox.ps1 -Root $root
python -m tidymate_cli plan $root -r <rules.yaml> -o (Join-Path $root "Sorted") --yes
python -m tidymate_cli apply <batch_id> --yes
```
