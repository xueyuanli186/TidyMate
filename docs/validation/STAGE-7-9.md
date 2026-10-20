# 阶段 7-9 验证报告：批次日志、一键撤销、错误报告

- 日期：2026-10-20
- 范围：M7（SQLite 批次日志）、M8（一键撤销）、M9（错误报告 + verify）
- 结论：200 条混合变更 apply → verify → undo → verify 全部通过，文件系统快照与 apply 前一致；
  九类必测用例均有自动化覆盖。

## 1. 200 条变更的真实往返（原样输出）

```text
sandbox: C:\Users\ASUS\AppData\Local\Temp\tidymate-79-hejx1xmg
files before: 200
=== plan ===
scanned=200 matched=200 execute=200 skip=0 reject=0 conflicts=0
=== apply (tail) ===
   197 ok   ...\inbox\报告 16.txt -> ...\Sorted\Text\2026\报告 16.txt
   198 ok   ...\inbox\报告 17.txt -> ...\Sorted\Text\2026\报告 17.txt
   199 ok   ...\inbox\报告 18.txt -> ...\Sorted\Text\2026\报告 18.txt
   200 ok   ...\inbox\报告 19.txt -> ...\Sorted\Text\2026\报告 19.txt
完成：ok=200 failed=0 skipped=0 interrupted=0
=== verify after apply ===
verify: 0 inconsistency(ies)
=== undo (tail) ===
     2 undone  ...\inbox\blob-001.bin -> ...\Sorted\Bin\blob-001.bin
     1 undone  ...\inbox\blob-000.bin -> ...\Sorted\Bin\blob-000.bin
撤销完成：undone=200 failed=0 status=undone
=== verify after undo ===
verify: 0 inconsistency(ies)
files after: 200
names identical: True
sizes identical: True | hashes identical: True | mtime within 2s: True
output files left: 0
=== status ===
latest batch : dryrun-20261020-200554 [undone] total=200 ok=0 failed=0 skipped=0 undo=200/200
```

说明：`ok` 在执行后从 200 变为 0 是设计使然——撤销后的行状态是 `undone`，统计列
`undo_ok=200/200`；`verify` 同时校验 `undone` 行的源路径存在。

## 2. M7 批次日志

- 路径：`%LOCALAPPDATA%\TidyMate\tidymate.db`（可用 `--db` 覆盖）；`WAL` + `busy_timeout=5000`。
- 表：`batches` / `operations`，字段按需求 DDL 全量落库（`app_version`、`roots`、`rules_hash`、
  `mode`、统计列、`undo_*`、`mtime_utc`、`src_existed`、`dst_existed_before`、`flags`、
  `recycle_ref`、`executed_at`、`undone_at`）。
- **唯一偏差**：需求 DDL 的 `id INTEGER AUTOINCREMENT` 没有采用，身份由
  `UNIQUE(batch_id, seq)` 承担；其余语义无删减。旧库用 `ALTER TABLE ADD COLUMN` 原地迁移
  （`test_journal_migrates_an_old_database`）。
- 写入策略：`intent(state=planned)` 先提交，执行后立即 `UPDATE` 终态；统计列由
  `refresh_stats()` 从 `operations` 用 SQL 重算（`agg_stats`），不信任内存计数。
- 命令：`status` / `list-batches` / `show-batch`（`--json`）。

## 3. M8 一键撤销

```text
undo <batch_id> [--yes] [--dry-run] [--db]
```

- 默认先 dry-run 展示"将回滚 N 条"，再要求输入 `YES`。
- 按 `seq` 降序，逐条独立事务，逐条写 `undone` / `undo_failed`。
- move/rename：`dst` 必须存在 → size 与 mtime 与日志一致 → 原位置空闲 → 移回
  （同卷 `os.rename`；跨卷 copy → size+sha256 校验 → `os.rename` → 回收 dst）。
- 失败分类：`modified_since` / `missing` / `src_occupied` / `recycle_gone` / `permission` /
  `unknown`；任何一条失败都**不会**覆盖或移动文件。
- copy：校验副本未变后送入回收站；trash：调用回收站还原（PowerShell Shell verb，
  按 `System.Recycle.DeletedFrom` + 文件名匹配）。
- 幂等：第二次 undo 返回 0 条、无副作用（batch 已是 `undone`）。
- 中断可续跑：取消后再次 undo 只处理未 `undone` 的行。
- 收尾：把本次创建且已空的输出目录送回收站（不永久删除），使 200 条往返后输出树为空。

## 4. M9 错误报告与 verify

- `apply` / `undo` 结束写 `reports/errors-<batch_id>.md` 与 `.json`：
  按 `error_kind` 分组，每条含 src/dst/原因/建议动作/对撤销的影响；`failed` 与 `skipped`
  分列且都不计入 `ok`；出现 `unknown` 时报告顶部有醒目警告。
- 数字来自 `Journal.agg_stats`（SQL），报告与 CLI 输出同源。
- `verify <batch_id> [--sample N] [--json]`：逐行对照文件系统，输出
  `missing_after_apply` / `size_mismatch` / `not_restored` / `undo_failed_and_missing` /
  `interrupted` 等不一致项，作为"全部复原"的证据。

## 5. 必测用例对照

| # | 用例 | 测试 |
| --- | --- | --- |
| 1 | 200 条混合变更 apply→undo 全量复原 | `test_200_changes_apply_then_undo_restores_everything`（真实运行见第 1 节） |
| 2 | 撤销幂等 | `test_second_undo_reports_nothing_and_changes_nothing` |
| 3 | 中断续跑 | `test_undo_can_resume_after_cancel` |
| 4 | dst 被修改 | `test_modified_destination_is_not_moved_back` |
| 5 | dst 被删除 | `test_missing_destination_is_reported` |
| 6 | src 被占用 | `test_occupied_source_is_reported` |
| 7 | trash 还原 / 回收站已空 | `test_trash_undo_restores_the_file`、`test_recycle_gone_is_reported_without_crashing` |
| 8 | 状态一致性 | `test_stats_match_sql_and_disk`、`test_error_report_has_groups_and_sql_numbers` |
| 9 | 崩溃恢复 | `test_crash_recovery_marks_interrupted_as_partial` |

补充分支：损坏的 `recycle_ref`、未知 op、无 dst 行、旧库迁移、安装器目录门禁、
CLI 的 `list-batches` / `show-batch` / `verify --json` / `undo --dry-run`。

```text
$ python -m pytest -q
569 passed, 1 skipped, 90.12% coverage
```

## 6. 文件移动/删除逻辑自检（M8 版）

1. **不覆盖**：回滚前先查原位置是否已存在（`src_occupied`），存在就失败；跨卷回滚先写
   `*.tidymate-undo` 暂存，校验后 `os.rename`（目标不存在才成功）。
2. **不永久删除**：撤销里唯一的删除是 `send2trash`（副本、回收站还原失败后的残余、
   工具自己创建的空目录）；`check_forbidden_apis.py` 仍然为零命中。
3. **不误报成功**：`undone` 只在"源路径重新存在"后写入（`_undo_move` 的返回值 + `verify`
   复核）；`undo_failed` 绝不写 `undone_at`，也不计入 `undo_ok`。
4. **不移动被用户改过的文件**：size / mtime 与日志不一致即 `modified_since`，文件留在原处。
5. **不猜**：`dst` 不存在就是 `missing`，回收站里没有就是 `recycle_gone`，都给出人工指引。
6. **可续跑**：每条独立提交；`undo_candidates` 只取 `state='ok' AND undone_at IS NULL`。
7. **状态可核对**：`verify` 不信日志，逐行 stat；统计列来自 SQL 聚合。

## 7. 未实现 / 已知偏差

1. **GUI 的撤销与确认**仍未做（阶段 8）；CLI 已完整。
2. 回收站还原依赖 PowerShell + Shell verb，**中文/英文动词已兼容**，但真实回收站行为
   只在 Windows 本机验证过；CI 上是同一个 `windows-latest` 镜像。
3. `id` 自增列省略（见第 2 节），身份由 `UNIQUE(batch_id, seq)` 承担。
4. mtime 比较有 2 秒容差，用于吸收文件系统时间戳精度差异。
5. 撤销后清理空目录走回收站；若用户在原输出目录里另有空目录，不会被删除（只处理
   本次 batch 的 `final_dst` 父链，且位于 batch 的 `output_root` 下）。

## 8. 复现

```powershell
python -m pytest -q
python -m ruff check . ; python -m ruff format --check .
python -m mypy
python scripts/check_forbidden_apis.py
python scripts/check_readonly.py

python -m tidymate_cli plan <inbox> -r rules.yaml -o <out> --yes
python -m tidymate_cli apply <batch_id> --yes
python -m tidymate_cli verify <batch_id>
python -m tidymate_cli undo <batch_id> --yes
python -m tidymate_cli verify <batch_id>
```
