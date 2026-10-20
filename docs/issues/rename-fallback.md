# Issue 草稿：rename fallback 增加时间戳阶段

> 状态：**待创建**（本机无 GitHub 凭据）。创建后请把编号回填到
> `docs/validation/STAGE-3-4-P0.md` 第 6 节，并关闭本 Issue（修复已在 `c9b00c4`）。

**标题**

```text
rename fallback: add a timestamp stage after name (2..999)
```

**正文（可直接粘贴到 GitHub）**

## 背景

`conflict: rename` 在目标已存在时只尝试 `name (2).ext` … `name (999).ext`，999 仍冲突
就放弃。修复前的行为是 `skip` + `"no free name found after 998 attempts"`，没有区分
「暂时冲突」和「彻底无法规划」。

## 期望行为

1. `name (2).ext` … `name (999).ext`；
2. 仍冲突 → `name_yyyyMMdd-HHmmss_ffffff.ext`（时间戳取自计划的 `created_at`，
   保证同一输入两次 dry-run 的 `plan_hash` 仍然相同）；
3. 仍冲突 → 条目标记 `failed`（`error_kind=rename_exhausted`），在报告「失败项」中
   单独列出，不得静默跳过，也不得计入 `skip`。

## 状态

已在 `c9b00c4` 实现，测试覆盖：

- `test_rename_falls_back_to_a_timestamp_after_999_candidates`
- `test_rename_marks_failed_when_the_timestamp_also_collides`
- `test_timestamp_fallback_keeps_the_plan_hash_stable`

细节见 `docs/validation/STAGE-3-4-P0.md` 第 4 节。

## 验收清单

- [x] 999 个候选全冲突时生成 `a_20261020-120000_000000.jpg`
- [x] 时间戳候选也冲突时 `status=failed`、`stats.failed=1`、报告出现「失败项 (1)」
- [x] 同一输入两次 dry-run 的 `plan_hash` 与目标名一致

## 备注

本 Issue 用于登记与回溯；若接受"修复已合并"，创建后可直接关闭并回填编号。
