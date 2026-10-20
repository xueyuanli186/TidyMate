# 阶段 3-4 验证报告：路径模板 + Dry-run 预览

- 日期：2026-10-20
- 版本：`0.1.0`
- 阶段目标：M3 白名单路径模板、M4 三形态 dry-run 预览与冲突检测。**不修改用户文件。**

## 1. 写盘边界（本阶段最重要的一条）

阶段 3-4 首次出现"产品代码写文件"的需求：导出 `plan.json` 与 `report.md`。
处理方式是把写权限收敛到一个模块，并用 CI 静态检查盯住：

| 位置 | 是否允许写 | 说明 |
| --- | --- | --- |
| `src/tidymate_core/**`（除下一行） | ❌ 禁止 | `scripts/check_readonly.py` 用 AST 扫描，出现写调用即 CI 失败 |
| `src/tidymate_core/planning/artifacts.py` | ✅ 唯一例外 | 只写 `plan.json` / `report.md` 两个固定文件名；拒绝写入黑名单目录 |
| `src/tidymate_app/**`（GUI） | 通过 `artifacts.py` 间接写 | GUI 自己不调用写 API |
| 用户源文件 | ❌ 绝不 | 本阶段没有任何 move/rename/copy/trash 实现 |

```text
$ python scripts/check_readonly.py
OK: no write calls in 34 product files.
```

`readonly_guard.ALLOWED_MODULES` 里只有一条：
`tidymate_core/planning/artifacts.py`，注释写明放行原因与阶段。

## 2. 执行记录

```text
$ python -m ruff check .
All checks passed!
$ python -m ruff format --check .
88 files already formatted
$ python -m mypy
Success: no issues found in 78 source files
$ python -m pytest -q
481 passed, 1 skipped in 3.60s
TOTAL 1739 stmts / 92.70% / Required coverage of 90.0% reached

$ python scripts/check_forbidden_apis.py
OK: no forbidden delete APIs in 50 scanned files.

$ python scripts/check_readonly.py
OK: no write calls in 34 product files.
```

> 1 个 skip 是 GUI 测试：本机 `PySide6` 安装尚未完成（后台 pip 任务），见 §6。

## 3. 真实沙箱 dry-run 样例

沙箱由 `scripts/make-sandbox.ps1` 生成（34 个条目，含 junction、只读文件、
长路径、重复 basename）。规则文件：

```yaml
rules:
  - id: images
    priority: 10
    when: { ext: [".jpg", ".jpeg", ".png"] }
    action: { op: move, template: "Pictures/{year}/{name}", conflict: skip }
  - id: documents
    priority: 20
    when: { ext: [".pdf", ".docx", ".xlsx", ".pptx"] }
    action: { op: move, template: "Documents/{year}/{ext_nodot}/{name}", conflict: rename }
  - id: archives
    priority: 30
    when: { ext: [".zip", ".gz"] }
    action: { op: move, template: "Archives/{name}", conflict: skip }
  - id: junk
    priority: 40
    when: { ext: [".tmp"] }
    action: { op: trash }
```

### 3.1 终端表格（真实输出）

```text
TidyMate dry-run  batch=dryrun-20261020-123744  hash=97aed63463eeaf72
scanned=34 matched=9 execute=7 skip=2 reject=0 conflicts=2

 seq   status  op     rule             conflict       source                             -> destination
-------------------------------------------------------------------------------------------------------
   4   execute move   archives         -              C:\Users\ASUS\A...nbox\archive.zip -> C:\Users\ASUS\A...ives\archive.zip
   5   execute move   archives         -              C:\Users\ASUS\A...ox\bundle.tar.gz -> C:\Users\ASUS\A...es\bundle.tar.gz
   9   execute move   documents        -              C:\Users\ASUS\A...\inbox\deck.pptx -> C:\Users\ASUS\A...6\pptx\deck.pptx
  12   execute move   images           -              C:\Users\ASUS\A...x\keep\photo.jpg -> C:\Users\ASUS\A...s\2026\photo.jpg
  15   execute move   documents        -              C:\Users\ASUS\A...inbox\manual.pdf -> C:\Users\ASUS\A...6\pdf\manual.pdf
  18 ! skip    move   images           intra-batch    C:\Users\ASUS\A...\inbox\photo.jpg -> C:\Users\ASUS\A...s\2026\photo.jpg
... 3 more change(s) not shown; export plan.json for the full list
dry-run only: no files were modified.
plan.json : ...\tidymate-demo-reports2\plan.json
report.md : ...\tidymate-demo-reports2\report.md
```

`!` 标记的是冲突行。三条 `photo.jpg`（`inbox/photo.jpg`、`inbox/keep/photo.jpg`、
`inbox/tmp/photo.jpg`）渲染到同一个 `Pictures\2026\photo.jpg`，第一条保留，后两条标
`intra-batch` 并跳过。

### 3.2 `plan.json`（真实片段）

```json
{
  "schema": 1,
  "batch_id": "dryrun-20261020-123744",
  "created_at": "2026-10-20T12:37:44.315887+08:00",
  "output_root": "C:\\Users\\ASUS\\AppData\\Local\\Temp\\tidymate-demo-122634\\Sorted",
  "rules_source": "C:\\Users\\ASUS\\AppData\\Local\\Temp\\tidymate-demo-rules.yaml",
  "plan_hash": "97aed63463eeaf72c982ba506d5a9f521bbc457803f6b740d16cdd720bf77817",
  "stats": {
    "total_scanned": 34,
    "matched": 9,
    "will_execute": 7,
    "will_skip": 2,
    "rejected": 0,
    "conflicts": 2,
    "conflicts_exists": 0,
    "conflicts_intra": 2,
    "conflicts_review": 0,
    "bytes_freed": 0,
    "bytes_added": 0,
    "by_rule": { "archives": 2, "documents": 4, "images": 3 }
  },
  "warnings": ["reparse point not followed (follow_symlinks=false): junction-to-inbox"],
  "changes": [
    {
      "seq": 4,
      "src": "C:\\...\\tidymate-demo-122634\\inbox\\archive.zip",
      "dst": "C:\\...\\tidymate-demo-122634\\Sorted\\Archives\\archive.zip",
      "op": "move",
      "rule_id": "archives",
      "status": "execute",
      "conflict": "none",
      "reason": null,
      "flags": [],
      "notes": [],
      "size": 16
    }
  ]
}
```

### 3.3 `report.md`（真实片段）

```markdown
## 摘要

| 指标 | 数值 |
| --- | --- |
| 总扫描数 | 34 |
| 命中规则数 | 9 |
| 将执行数 | 7 |
| 将跳过数 | 2 |
| 拒绝数 | 0 |
| 冲突总数 | 2 |
| ├ 与磁盘已存在冲突 | 0 |
| ├ 批内同名冲突 | 2 |
| └ 需人工确认 | 0 |
| 预计释放空间（trash） | 0 字节 |
| 预计新增占用（copy） | 0 字节 |

### ⚠️ 批内自相冲突（多条变更目标相同） (2)

| seq | source | destination | rule | notes |
| --- | --- | --- | --- | --- |
| 18 | `...\inbox\photo.jpg` | `...\Sorted\Pictures\2026\photo.jpg` | images | same destination as seq 12 |
| 24 | `...\inbox\tmp\photo.jpg` | `...\Sorted\Pictures\2026\photo.jpg` | images | same destination as seq 12 |
```

### 3.4 `plan_hash` 幂等（真实两次运行）

```text
run1=97aed63463eeaf72c982ba506d5a9f521bbc457803f6b740d16cdd720bf77817
run2=97aed63463eeaf72c982ba506d5a9f521bbc457803f6b740d16cdd720bf77817
identical=True
```

两次运行的 `batch_id` 不同（时间戳），`plan_hash` 相同。

## 4. 测试用例对照

### 4.1 模板（M3）

| 要求 | 用例 |
| --- | --- |
| 每个白名单变量正确渲染 | `test_template_render.py::test_each_whitelisted_variable_renders`（16 参数） |
| 白名单集合精确 | `::test_whitelist_matches_the_documented_set` |
| 本地/UTC 日期可不同 | `::test_local_and_utc_dates_can_differ` |
| size_bucket 边界 | `::test_size_bucket_boundaries`（7 参数） |
| `{path}` / `{env:USERPROFILE}` / `{hash8}` 显式禁止 | `::test_explicitly_forbidden_variables_are_rejected`、`::test_env_prefix_is_rejected_by_name`、`::test_hash_prefix_is_rejected` |
| 拼写错误 `{Year}` 报错并给变量名 | `::test_case_variants_are_rejected_and_named` |
| 未闭合花括号 | `::test_unbalanced_brace_is_rejected` |
| 连续分隔符 | `::test_consecutive_separator_is_rejected` |
| 纯空格结果兜底 | `::test_whitespace_only_render_falls_back` |
| 非法字符净化 `: * ? " < > |` | `::test_illegal_filename_characters_are_replaced`（7 参数，值来自文件名而非模板） |
| 控制字符 | `::test_control_characters_are_dropped` |
| 超长段截断 + 哈希稳定 | `::test_long_segment_is_truncated_with_hash_and_extension`、`::test_truncation_hash_is_stable_and_input_specific` |
| 句点开头保留（`.gitignore`） | `::test_leading_dot_is_preserved` |

### 4.2 计划与预览（M4）

| 要求 | 用例 |
| --- | --- |
| 批内同名冲突 | `test_planner.py::test_intra_batch_same_destination_is_detected` |
| 大小写不敏感冲突 | `::test_case_insensitive_intra_batch_conflict`、`test_targets_conflicts.py::test_conflict_key_is_case_insensitive` |
| 与磁盘已存在冲突 | `::test_existing_destination_is_skipped` |
| conflict: rename | `::test_rename_policy_finds_a_free_name` |
| conflict: ask | `::test_ask_policy_marks_for_review` |
| 只读文件拒绝 | `::test_read_only_file_is_rejected` |
| 祖先/自身检测 | `::test_target_equal_to_source_is_rejected_as_ancestor` |
| 黑名单输出根 | `::test_output_root_inside_blacklist_is_rejected`、`test_blacklist.py` 全文件 |
| trash 预览与空间统计 | `::test_trash_plan_frees_space` |
| plan_hash 幂等 | `::test_plan_hash_is_idempotent`、`test_dry_run_sandbox.py::test_two_dry_runs_produce_the_same_hash` |
| plan_hash 随内容变化 | `::test_plan_hash_changes_when_content_changes` |
| 统计与逐条一致 | `::test_stats_reconcile_with_entries`、`test_report.py::test_markdown_counts_match_change_list` |
| 报告三形态一致 | `test_report.py::test_markdown_numbers_match_json_numbers` |
| 报告含必需章节 | `::test_markdown_has_every_required_section` |
| dry-run 不碰源目录 | `test_dry_run_sandbox.py::test_dry_run_does_not_touch_the_source_tree` |
| 保留设备名拒绝 | `test_targets_conflicts.py::test_reserved_device_names_are_rejected` |
| 长目标路径 `\\?\` | `::test_long_target_requires_extended_prefix`、`::test_path_beyond_hard_limit_is_rejected` |
| GUI 执行按钮禁用 | `test_gui.py::test_execute_button_is_disabled_with_stage_label`（PySide6 未装时 skip） |

## 5. 与需求的两处刻意偏差（需要你确认）

1. **首尾 trim 只去掉"前导空格 + 尾部空格和点"**，保留前导点。
   原因：Windows 允许 `.gitignore`，禁止的是**结尾**的点/空格。按字面"首尾都去点"
   会把 `{ext}` 渲染出的 `.jpg` 变成 `jpg`，直接毁掉扩展名。测试
   `test_leading_dot_is_preserved` 锁住了这个决定。

2. **模板字面量里的非法字符仍然是"规则文件错误"**，只有**渲染值**里的非法字符才被
   净化。原因：模板里写 `a:b` 是作者写错了，应在加载时拒绝；而文件名里的 `:` 可能来自
   其他文件系统，属于运行时数据，应修复而不是让整批计划失败。

## 6. 未验证项与已知限制

1. **GUI 未在本机验证**：`PySide6` 后台安装未完成。GUI 代码已通过 ruff/mypy，
   `test_gui.py` 会在装有 PySide6 的机器上以 offscreen 方式运行。
2. **CI 已跑通（2026-10-20 补记）**：run #39375183042 五个 job 全绿，
   `check_forbidden_apis.py` / `check_readonly.py` / 沙箱步骤在 `windows-latest` 上
   真实执行通过，artifact `TidyMate-0.1.0-windows` 可下载。
3. **`conflict: rename` 只生成一层候选名**（`name (2).ext`），若该名也冲突会继续
   尝试到 999；不做批量重命名规划。
4. **`{parent}` 取源文件的直接父目录名**；对 `C:\a\b\c.txt` 是 `b`。
5. **长路径源文件仍被拒绝**（铁律 8 默认 skip），即使目标路径支持 `\\?\`。
6. **`bytes_freed` / `bytes_added` 只统计 trash / copy 且状态为 execute 的条目**；
   move/rename 不改变总占用，故不计入。
7. **`plan.json` 的 `created_at` 用本地时区偏移**，`Plan.created_at` 内部仍是 UTC。

## 7. 复现

```powershell
python -m ruff check .
python -m mypy
python -m pytest -q
python scripts/check_forbidden_apis.py
python scripts/check_readonly.py

# 真实沙箱
$root = Join-Path $env:TEMP ("tidymate-demo-" + (Get-Date -Format "HHmmss"))
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/make-sandbox.ps1 -Root $root
python -m tidymate_cli plan $root -r <rules.yaml> -o (Join-Path $root "Sorted") --export (Join-Path $env:TEMP "tidymate-reports")
```
