# 阶段 3-4 返工验证：ADS / OneDrive 占位与 rename 退化

- 日期：2026-10-20
- 修复提交：`c9b00c4`
- 范围：P0-2（ADS 与 OneDrive 占位独立拒绝策略）、P1-3（rename 退化）、P1-4/5（文档口径）
- 结论：P0 两项均落地并有真实 NTFS 证据；P1 已实现，Issue 登记见第 6 节。

## 1. 修改的文件清单

| 文件 | 改动 |
| --- | --- |
| `src/tidymate_core/scanning/streams.py` | **新增**。`GetFileInformationByHandleEx(FileStreamInfo)` 枚举 NTFS 备用数据流；句柄只用 `FILE_READ_ATTRIBUTES` 打开，避免触发 OneDrive 水化 |
| `src/tidymate_core/scanning/models.py` | `ErrorFlags.ADS` / `ErrorFlags.ONEDRIVE_PLACEHOLDER`；`FileEntry.alternate_streams`、`has_alternate_streams`、`is_onedrive_placeholder` |
| `src/tidymate_core/scanning/config.py` | `ScanConfig.detect_alternate_streams`（默认开；基准测试可关） |
| `src/tidymate_core/scanning/walker.py` | 每个普通文件检测 ADS，把 `OFFLINE` / `RECALL_ON_OPEN` / `RECALL_ON_DATA_ACCESS` 归为占位文件；`build_entry` 增加 `alternate_streams` 参数 |
| `src/tidymate_core/planning/models.py` | `ChangeStatus.FAILED`；`PlannedChange.error_kind`；`PlanStats.failed / ads_skipped / onedrive_skipped`；`Plan.failed()`、`Plan.skipped_with_kind()` |
| `src/tidymate_core/planning/planner.py` | ADS / OneDrive 默认 `skip` + `error_kind`；rename 退化到时间戳名，仍冲突则 `failed`；`PlanRequest.entries` 支持注入已扫描条目（测试用） |
| `src/tidymate_core/planning/report.py` | 摘要新增失败数、ADS / OneDrive 跳过数；新增「已跳过：ADS / OneDrive 占位」与「失败项」章节；统计块顶部加字节口径说明 |
| `tests/tidymate_core_tests/test_special_files.py` | **新增** 6 个用例（详见第 3、4 节） |
| `tests/tidymate_core_tests/test_report.py` | `plan.json` 字段集合加入 `error_kind`；报告章节断言加入新增两节 |
| `README.md` | FAQ：长路径跳过、ADS / OneDrive 跳过 |
| `docs/ROADMAP.md` | 已知欠缺第 31、34 条更新为已处理 |

写盘边界未变：`streams.py` 只打开 `FILE_READ_ATTRIBUTES` 句柄，不写任何字节；
`check_readonly.py` 通过（35 个产品文件，比修复前多 1 个新模块）。

## 2. P0：ADS / OneDrive 的处理语义

两类文件**不是** `reject`，而是 `skip`：文件本身没问题，危险的是"移动"这个动作。
计划里它们满足：

- `status = "skip"`；
- `error_kind = "ads"` 或 `"onedrive_placeholder"`；
- `notes[0]` 是具体证据（流名 / 属性位说明），`notes[1]` 是人工处理指引；
- 不进入 `executable()`，阶段 5 的执行器按 `error_kind` 直接拒绝执行。

两者同时命中时 `error_kind = "ads"`（流会丢是更直接的损坏），并在说明里注明
"the file is also a cloud placeholder"。

### 2.1 真实 NTFS 样例（`Zone.Identifier`）

沙箱：`inbox/photo.jpg` 附带真实 `Zone.Identifier` 流（`ZoneId=3`）。规则为
`move` → `Pictures/{name}`。真实 CLI 输出：

```text
TidyMate dry-run  batch=dryrun-20261020-183940  hash=c12d586505db6a5a
scanned=1 matched=1 execute=0 skip=1 reject=0 conflicts=0

 seq   status  op     rule             conflict       source                             -> destination
-------------------------------------------------------------------------------------------------------
   1   skip    move   images           -              C:\Users\ASUS\A...\inbox\photo.jpg -> -

dry-run only: no files were modified.
```

`report.md` 的新章节（真实输出）：

```markdown
## 已跳过：ADS / OneDrive 占位

> 这两类文件**移动会损坏原始数据**，因此默认跳过；进入执行阶段后也不得触碰。

- ADS：NTFS alternate data stream present (e.g. Zone.Identifier): moving the file can drop the stream. Inspect it with Sysinternals Streams (streams -s <file>) and decide whether to clear it (streams -d <file>) before organising.
- OneDrive：OneDrive/cloud placeholder not fully downloaded: moving it can leave a 0-byte placeholder and corrupt the original. In the OneDrive client choose "Always keep on this device", wait for the download to finish, then re-run.

| seq | 类型 | source | 说明 |
| --- | --- | --- | --- |
| 1 | ADS | `C:\Users\ASUS\AppData\Local\Temp\tidymate-p0-82on0c9d\inbox\photo.jpg` | alternate data stream(s): Zone.Identifier |
```

`plan.json` 对应条目（真实片段）：

```json
{
  "seq": 1,
  "src": "C:\\Users\\ASUS\\AppData\\Local\\Temp\\tidymate-p0-82on0c9d\\inbox\\photo.jpg",
  "dst": null,
  "op": "move",
  "rule_id": "images",
  "status": "skip",
  "conflict": "none",
  "reason": null,
  "error_kind": "ads",
  "flags": ["ads"],
  "notes": [
    "alternate data stream(s): Zone.Identifier",
    "NTFS alternate data stream present (e.g. Zone.Identifier): moving the file can drop the stream. ..."
  ],
  "size": 8
}
```

统计：`ads_skipped=1, onedrive_skipped=0, will_execute=0, will_skip=1`。

### 2.2 OneDrive 占位的测试方式

Windows 不允许用户态设置 `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`，本机也没有真实
OneDrive 同步目录。因此测试通过 `PlanRequest.entries` 注入一个属性位来自测试的
`FileEntry`，走的是与真实扫描**完全相同**的 `planner` 路径；真实环境下的属性读取
由 `os.stat().st_file_attributes` 负责，属于操作系统契约，不在本仓库可控范围。

### 2.3 检测失败时怎么办（限制）

`list_alternate_streams()` 在句柄打不开（占用、权限）或非 Windows 时返回 `None`，
当前按"未发现流"处理，不标 `ads`。这是已知缺口：理论上会漏掉极少数被独占锁定的
文件。阶段 5 的执行器会在移动前用同一函数复查，并在 `None` 时按失败处理（写进
阶段 5 验收项）。已登记到 `docs/ROADMAP.md`。

## 3. 测试用例清单

| 用例 | 覆盖 |
| --- | --- |
| `test_real_zone_identifier_stream_is_detected_and_skipped` | 真实 NTFS 流被检测 → 计划 skip → 报告分组 → `plan.json` 的 `error_kind` |
| `test_onedrive_placeholder_is_skipped_with_guidance` | 注入 `RECALL_ON_DATA_ACCESS` → skip → 指引文案（含 "Always keep on this device"） |
| `test_ads_wins_over_onedrive_when_both_apply` | 同时命中时 `error_kind=ads`，说明里注明也是占位文件 |
| `test_rename_falls_back_to_a_timestamp_after_999_candidates` | 999 个候选全冲突 → `name_yyyyMMdd-HHmmss_ffffff.ext`（`a_20261020-120000_000000.jpg`） |
| `test_rename_marks_failed_when_the_timestamp_also_collides` | 时间戳也冲突 → `status=failed`、`error_kind=rename_exhausted`、`stats.failed=1` |
| `test_report_states_the_bytes_accounting_rule` | 报告统计块含指定口径文案 |
| `test_timestamp_fallback_keeps_the_plan_hash_stable` | 时间戳退化下同一输入两次 dry-run 的 `plan_hash` 与目标名一致 |

真实运行日志（`pytest -v`，原样）：

```text
collecting ... collected 7 items

tests/tidymate_core_tests/test_special_files.py::test_real_zone_identifier_stream_is_detected_and_skipped PASSED [ 14%]
tests/tidymate_core_tests/test_special_files.py::test_onedrive_placeholder_is_skipped_with_guidance PASSED [ 28%]
tests/tidymate_core_tests/test_special_files.py::test_ads_wins_over_onedrive_when_both_apply PASSED [ 42%]
tests/tidymate_core_tests/test_special_files.py::test_rename_falls_back_to_a_timestamp_after_999_candidates PASSED [ 57%]
tests/tidymate_core_tests/test_special_files.py::test_rename_marks_failed_when_the_timestamp_also_collides PASSED [ 71%]
tests/tidymate_core_tests/test_special_files.py::test_report_states_the_bytes_accounting_rule PASSED [ 85%]
tests/tidymate_core_tests/test_special_files.py::test_timestamp_fallback_keeps_the_plan_hash_stable PASSED [100%]

============================== 7 passed in 0.40s ==============================
```

## 4. P1：rename 退化算法

`_next_available()` 现在分三级：

1. `name (2).ext` … `name (999).ext`；
2. `name_yyyyMMdd-HHmmss_ffffff.ext`，时间戳取自计划的 `created_at`（不是
   `datetime.now()`），保证同一输入两次 dry-run 的 `plan_hash` 仍然相同；
3. 仍冲突 → `status=failed`、`error_kind=rename_exhausted`，报告「失败项」列出。

`failed` 不是 `reject`：输入合法，是环境占满了；阶段 5 会把 `failed` 记为执行失败，
不会重试、也不会悄悄跳过。

## 5. 文档补充

- `README.md` FAQ 新增两条：长路径跳过、ADS / OneDrive 跳过。
- `report.md` 统计块顶部：**字节变化口径：仅包含 trash 释放空间 + copy 占用空间，
  move/rename 未计入（前者不改变磁盘占用，后者仅改名）。**

> 偏差说明：需求原文要求在 FAQ 写"可在规则中显式配置 `allow_long_path: true`"。
> 该开关目前**不存在**（规则模型没有这个字段），照原文写会让文档承诺一个跑不通的
> 配置。因此 FAQ 写成了"计划中的开关、当前版本尚未实现、阶段 5 落地前一律 skip"。
> 若需要，我可以把 `allow_long_path` 作为独立工单实现并补测试。

## 6. P1 的 GitHub Issue

当前环境没有 `gh` CLI，也没有可用的 GitHub token（`git credential fill` 提示无凭据），
因此**无法**直接创建 Issue。已按产品负责人的选择改为"网页手工创建"：

- 标题与正文：`docs/issues/rename-fallback.md`（可直接整段粘贴）；
- 修复提交：`c9b00c4`；
- **编号：待回填**。创建后把编号写回本节，并把该文档的"状态"改为已创建。

在此之前，这一条不能声称"已登记"。

## 7. 回归（真实输出）

```text
$ python -m pytest -q
Required test coverage of 90.0% reached. Total coverage: 93.01%
493 passed in 3.43s

$ python -m ruff check .
All checks passed!

$ python -m ruff format --check .
96 files already formatted

$ python -m mypy
Success: no issues found in 81 source files

$ python scripts/check_forbidden_apis.py
OK: no forbidden delete APIs in 52 scanned files.

$ python scripts/check_readonly.py
OK: no write calls in 35 product files.
```

## 8. 未验证项

1. **真实 OneDrive 目录**：未验证，属性位来自注入（原因见 2.2）。
2. **非 NTFS 卷**：ADS 测试在 FAT32/exFAT 上会 skip；检测函数返回 `()` 或 `None`。
3. **ADS 检测失败路径**：句柄被独占时按"无流"处理，属已知缺口。
4. **真人交互**：同前，GUI 交互路径仍未验证。
