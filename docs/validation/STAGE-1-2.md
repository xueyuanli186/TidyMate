# 阶段 1-2 验证报告：目录扫描 + 规则引擎

- 日期：2026-10-20
- 版本：`0.1.0`
- 阶段目标：M1 递归流式扫描、M2 规则引擎最小版。**全程只读，不写盘、不删除。**

## 1. 验证环境

| 项 | 值 |
| --- | --- |
| OS | Windows 11（10.0.22621）x64 |
| Python | 3.13.7 |
| git | 2.56.0.windows.2（安装在 `E:\yingyong\Git\`，未进 PATH，用绝对路径调用） |
| 运行时依赖 | `regex` 2026.9.29、`typer` 0.27.3 |

## 2. 执行记录与真实输出

```text
$ python -m ruff check .
All checks passed!

$ python -m ruff format --check .
69 files already formatted

$ python -m mypy
Success: no issues found in 61 source files

$ python -m pytest -q
351 passed in 2.98s
TOTAL 1217 stmts / 93% / Required test coverage of 90.0% reached. Total coverage: 93.00%

$ python scripts/check_forbidden_apis.py
OK: no forbidden delete APIs in 41 scanned files.

$ python scripts/check_readonly.py
OK: no write calls in 27 product files.

$ python -m tidymate_cli status
tidymate 0.1.0
stage           : 2 (scan + rules, read-only)
scanner         : streaming os.scandir, long-path aware, error tolerant
rules           : YAML, all-or-nothing validation, regex timeout 200 ms
journal         : not implemented yet
write commands  : none (this stage cannot modify anything)
network         : disabled (no network dependency is installed)
```

## 3. 性能实测

### 3.1 一万真实文件（验收项：< 3 秒）

```json
{
  "mode": "real",
  "requested": 10000,
  "created": 10000,
  "files": 10000,
  "dirs": 21,
  "errors": 0,
  "elapsed_s": 0.177,
  "files_per_second": 56636,
  "root": "C:\\Users\\ASUS\\AppData\\Local\\Temp\\tidymate-bench-10000-20261020-115935",
  "note": "real NTFS directory I/O; empty files created by the harness"
}
```

首轮（冷缓存）为 `0.180s / 55438 files/s`，第二、三轮稳定在 `0.177-0.180s`。
**结论：远低于 3 秒上限，约有 16 倍余量。**

### 3.2 十万文件（合成数据，说明生成方式）

```json
{
  "mode": "synthetic",
  "requested": 100000,
  "created": 100000,
  "files": 100000,
  "dirs": 101,
  "errors": 0,
  "elapsed_s": 1.523,
  "files_per_second": 65676,
  "root": "C:\\bench-root",
  "note": "in-memory entries injected into the walker; no disk I/O"
}
```

**生成方式（必须说明，避免被当成磁盘实测）**：`scripts/bench_scan.py --mode synthetic`
在内存中构造 `100` 个目录 × `1000` 个 `DirEntry`（每个带 `st_size=128`、
`st_attributes=0x20`、固定 mtime），通过 `scandir` 注入点喂给真实的
`iter_scan`。因此这个数字测的是 **walker 自身的簿记开销**（路径规范化、条目构造、
计数、取消检查），**不含磁盘 I/O**，不能当作 10 万文件的磁盘扫描耗时。

若要测 10 万真实文件的磁盘扫描，执行：

```powershell
python scripts/bench_scan.py --mode real --count 100000
```

（会在 `%TEMP%` 下创建 10 万个空文件；脚本按铁律不删除任何东西，需你手动清理。）

### 3.3 复现命令

```powershell
python scripts/bench_scan.py --mode real --count 10000 --json
python scripts/bench_scan.py --mode synthetic --count 100000 --json
```

## 4. 测试与验收项对照（逐条用例名）

### 4.1 M1 扫描

| 验收要求 | 用例 |
| --- | --- |
| 递归流式枚举，不全量加载 | `test_walker.py::test_finds_all_files`、`test_walker_errors.py::test_cancel_stops_scan_and_keeps_partial_stats`（边扫边产出，句柄级消费） |
| 支持取消 | `test_walker_errors.py::test_cancel_stops_scan_and_keeps_partial_stats`、`::test_cancel_before_start_reports_cancelled` |
| 权限拒绝不中断 | `test_walker_errors.py::test_permission_denied_directory_does_not_abort` |
| 错误后继续扫兄弟目录 | `test_walker_errors.py::test_scan_continues_to_sibling_directories_after_error` |
| 路径过长分类 | `test_walker_errors.py::test_path_too_long_by_errno` |
| 被占用分类 | `test_walker_errors.py::test_in_use_error_by_winerror` |
| stat 失败单条记录、不影响其他文件 | `test_walker_errors.py::test_stat_error_on_file_is_recorded_and_skipped_over` |
| 符号链接/ junction 默认不跟随且单独报告 | `test_walker.py::test_junction_is_skipped_and_reported_by_default` |
| 显式开启才跟随 | `test_walker.py::test_junction_is_followed_when_enabled` |
| 长路径（>260）仍可达 | `test_walker.py::test_long_path_file_is_reachable` |
| 条目字段完整（name/stem/ext/size/mtime/attributes/flags） | `test_walker.py::test_entry_metadata_matches_disk`、`test_scan_models.py` 全文件 |
| ext 含点且小写 | `test_walker.py::test_extension_is_lowercased`、`test_scan_models.py::test_ext_is_lowercase_with_dot` |
| 无扩展名 / 双扩展名 / 点文件 | `test_scan_models.py::test_file_without_extension`、`::test_double_extension_uses_last_segment`、`::test_dotfile_has_no_extension` |
| 长路径标记 | `test_scan_models.py::test_long_path_flag_is_derived` |
| UNC 标记 | `test_scan_models.py::test_unc_flag_is_derived` |
| maxDepth | `test_walker.py::test_max_depth_zero_only_root`、`::test_max_depth_one_includes_first_level` |
| maxFileSize | `test_walker.py::test_max_file_size_filters_large_files` |
| excludeDirs 通配 | `test_walker.py::test_exclude_dir_by_glob`、`::test_exclude_dir_is_case_insensitive` |
| excludeDirs 绝对路径 | `test_walker.py::test_exclude_dir_by_absolute_path` |
| excludeHidden / excludeSystem | `test_walker.py::test_exclude_hidden`、`::test_exclude_system` |
| 统计与条目一致（不掺假） | `test_walker.py::test_stats_are_consistent_with_entries`、`test_walker_errors.py::test_reparse_entry_is_skipped_not_failed` |
| 多根目录 | `test_walker.py::test_scan_accepts_multiple_roots` |
| 配置校验 | `test_scan_config.py` 全文件 |

### 4.2 M2 规则引擎

| 验收要求 | 用例 |
| --- | --- |
| ext 大小写混合（`.JPG` 命中 `.jpg`） | `test_rules_matcher.py::test_ext_matches_case_insensitively` |
| size 边界（正好 1MB） | `test_size_expr.py::test_boundary_is_inclusive_for_greater_equal`、`test_rules_matcher.py::test_size_boundary_exactly_one_megabyte` |
| size 非法表达式报错 | `test_size_expr.py::test_invalid_expressions_are_rejected`（6 个参数） |
| size 单位/运算符 | `test_size_expr.py::test_units_are_case_insensitive`、`::test_decimal_amounts_are_exact`、`::test_equality_and_inequality` |
| mtime 边界 | `test_time_expr.py::test_absolute_date_boundary_is_inclusive_for_greater_equal` |
| mtime 时区（UTC 比较） | `test_time_expr.py::test_same_instant_in_two_timezones_is_the_same_threshold`、`::test_utc_and_local_represent_the_same_instant` |
| mtime naive 拒绝（禁止本地时间混用） | `test_time_expr.py::test_naive_mtime_is_rejected` |
| mtime 相对表达 | `test_time_expr.py::test_last_n_days_is_anchored_to_injected_now`、`::test_older_than_is_strictly_older` |
| path_glob 与 path_regex 组合（AND） | `test_rules_matcher.py::test_path_glob_and_regex_are_anded` |
| glob `*` 不跨分隔符 / `**` 任意深度 | `test_rules_matcher.py::test_path_glob_single_star_does_not_cross_separator`、`::test_path_glob_double_star_matches_any_depth` |
| UNC 路径匹配 | `test_rules_matcher.py::test_unc_path_matches_glob` |
| name_regex 恶意回溯超时被保护 | `test_regex_safe.py::test_timeout_returns_false_and_warns`、`test_rules_matcher.py::test_timeout_is_reported_and_treated_as_no_match` |
| 灾难性模式在编译期被拒 | `test_regex_safe.py::test_catastrophic_patterns_are_rejected` |
| 缺字段 → 整体拒绝 | `test_rules_loader.py::test_missing_id_is_rejected`、`::test_missing_when_is_rejected`、`::test_missing_action_is_rejected` |
| 类型错 → 整体拒绝 | `::test_wrong_priority_type_is_rejected`、`::test_boolean_priority_is_rejected`、`::test_wrong_enabled_type_is_rejected`、`::test_ext_as_string_is_rejected` |
| 重复 id → 整体拒绝 | `::test_duplicate_rule_id_is_rejected` |
| regex 不可编译 → 整体拒绝 | `::test_uncompilable_regex_is_rejected` |
| 未知字段（拼写错）→ 拒绝 | `::test_unknown_rule_key_is_rejected`、`::test_unknown_when_key_is_rejected`、`::test_unknown_action_key_is_rejected` |
| YAML 重复 key → 拒绝 | `::test_duplicate_yaml_key_is_rejected` |
| 一次报出全部错误 | `::test_all_errors_are_collected_at_once` |
| 错误带行号 | `::test_size_error_points_at_the_size_line`（断言第 5 行） |
| priority 小者先匹配 | `test_rules_engine.py::test_priority_decides_the_winner`、`test_rules_loader.py::test_rules_are_sorted_by_priority` |
| firstMatchOnly 默认 true / 可关闭 | `test_rules_engine.py::test_first_match_only_returns_one`、`::test_first_match_only_can_be_disabled` |
| 禁用规则不匹配 | `test_rules_engine.py::test_disabled_rule_never_matches` |
| 同优先级按文件顺序 | `test_rules_loader.py::test_equal_priority_keeps_file_order` |
| 端到端：扫描 + 规则 + 匹配 | `test_scan_and_match.py::test_scan_and_match_end_to_end` |

## 5. 本阶段的两个非显然设计决定

### 5.1 `path_glob` 匹配**完整绝对路径**，且 `*` 不跨分隔符

`fnmatch` 里 `*` 会跨过分隔符，导致 `*.txt` 匹配 `C:\a\b\c.txt`，规则作者无法表达
"只匹配某一层"。因此把 glob 翻译成正则并**整体锚定**：

- `*.txt` → `^(?:[^\\]*\.txt)$`，对任何绝对路径都不匹配（绝对路径必然含分隔符）；
- `**/*.txt` → 任意深度；
- `**/Downloads/**` → 匹配 `C:\Downloads\a.txt`（零级）和 `C:\Users\me\Downloads\a.txt`。

代价是"写 `*.txt` 什么也匹配不到"，收益是**行为可预测**。文档与示例统一教 `**/` 写法。

### 5.2 YAML 布尔只认 `true`/`false`

PyYAML 遵循 YAML 1.1，会把 `off`/`on`/`yes`/`no` 解析成布尔值。实测中 `id: off`
直接变成了 `False`，然后报出"id 必须是字符串"这种让用户莫名其妙的错误。
loader 里重设了 bool 隐式解析器（YAML 1.2 语义），并用
`test_rules_loader.py::test_yaml_1_1_boolean_words_stay_strings` 与
`::test_enabled_rejects_yaml_1_1_spellings` 锁住。

## 6. 未验证项与已知限制

1. **CI 仍未在 GitHub 真实运行**：本机 git 可用并已提交，但**没有远程仓库地址**，
   无法 push / 打 tag。工作流新增的 `check_readonly.py` 步骤只做了本地等价验证。
2. **10 万文件没有真实磁盘实测**：见 §3.2，合成数据的口径已写明。
3. **符号链接（symlink）未实测**：本机未开开发者模式，用 **junction** 覆盖了
   reparse point 路径；`os.symlink` 分支需要开发者在开发者模式下补验。
4. **`follow_symlinks=true` 的环检测**只有单元级覆盖（`seen_dirs` 的
   `(st_dev, st_ino)`），没有真实环路端到端测试。
5. **ADS、OneDrive 占位文件未识别**：`FileAttributes` 已定义 `OFFLINE` /
   `RECALL_ON_*` 位并会进入 `error_flags`，但没有对占位文件做"跳过+分类"的策略，
   属于阶段 8（执行前安全校验）范围。
6. **`excludeHidden` 依赖 Win32 属性位**，在非 NTFS 文件系统上可能不生效。
7. **`maxFileSize` 用 `st_size` 判断**，对稀疏文件与压缩文件是"逻辑大小"，与磁盘占用
   不一致；这是刻意选择（用户理解的是文件大小）。

## 7. 新增依赖说明

`regex>=2024.0`（运行时）。理由只有一个：**标准库 `re` 无法给单次匹配设置超时**，
而"恶意正则导致规则引擎卡死"是本项目必须防的攻击面。`regex` 是纯本地库，不联网，
不读文件，只编译与匹配字符串。阶段 0 的依赖清单里没有它，这里显式记录这次增加。
