# 阶段 8 验证报告：GUI 执行与撤销

- 日期：2026-10-20
- 范围：PySide6 界面的执行、撤销、二次确认与撤销预览
- 结论：界面复用 `gate.evaluate` / `Executor` / `Undoer`，没有第二套逻辑；
  8 个 offscreen 用例覆盖"预览 → 执行 → 撤销"的真实文件往返。

## 1. 界面能力

| 控件 | 行为 |
| --- | --- |
| Dry-run 预览 | 扫描、生成计划、填表，并把计划写入日志（`record_preview`） |
| 执行… | 先跑门禁；失败则整批拒绝并弹窗列出问题；通过后弹确认框 |
| 撤销… | 先跑 `Undoer` 的 dry-run 预览；确认后真正撤销 |
| 导出报告 | 仍写 `plan.json` / `report.md` |

确认框内容（与 CLI 一致）：

```text
将执行 N 条，涉及 M 个目录，其中 trash X 条。
冲突策略：按规则（skip 默认）/ rename（自动改名，不覆盖任何已有文件）
[ ] 我已备份，或已在测试目录演练过        [确认] [取消]
```

**未勾选复选框时"确认"不会执行**；取消则一个字节都不写。

撤销预览框列出"将回滚 N 条"，并把预检失败项（`modified_since` / `missing` /
`src_occupied` / `recycle_gone`）逐条列出，再要求勾选确认。

## 2. 复用关系（无第二套逻辑）

```text
MainWindow._on_execute
  └─ execution_bridge.preflight → gate.evaluate          # 与 CLI 同一个门禁
  └─ execution_bridge.run_apply → Executor.run           # 与 CLI 同一个执行器
  └─ write_reports                                       # 同一个 M9 报告

MainWindow._on_undo
  └─ execution_bridge.undo_preview → Undoer.run(dry_run=True)
  └─ execution_bridge.run_undo     → Undoer.run()
```

`execution_bridge` 不导入 Qt，可在无显示环境单测。

## 3. 测试

```text
$ python -m pytest tests/tidymate_core_tests/test_gui.py -q
8 passed in 0.77s
```

| 用例 | 覆盖 |
| --- | --- |
| `test_execute_and_undo_buttons_start_disabled` | 初始状态 |
| `test_loading_a_plan_fills_the_table_and_enables_execution` | 预览后启用执行 |
| `test_dry_run_records_the_preview_for_the_gate` | 预览写入日志、hash 一致 |
| `test_confirming_execution_moves_files_then_undo_restores_them` | 真实移动 + 真实撤销 |
| `test_declining_the_confirmation_changes_nothing` | 取消确认零写盘 |
| `test_undo_preview_can_be_cancelled` | 撤销预览可取消 |
| `test_conflict_rows_are_highlighted` | 冲突高亮未回归 |
| `test_execution_without_a_plan_is_a_no_op` | 空操作安全 |

全量：`572 passed, 90.12% coverage`，ruff / mypy（97 文件）/ 两个安全闸门全过。

## 4. 未验证项

1. **真人鼠标交互**未验证：对话框点击、文件选择器、拖列宽仍只经过 offscreen 测试；
   与阶段 4 的记录一致。
2. 执行是同步的：200 条级别会短暂冻结界面（数秒），未做进度条/后台线程。
3. 撤销只针对"本次会话刚执行的批次"或当前预览批次，没有历史批次选择器
   （CLI 的 `list-batches` 可用；GUI 的历史列表留到后续）。
4. 未重新生成界面截图（阶段 4 的 `docs/images/gui-dry-run.png` 仍是最新的视觉参考）。

## 5. 复现

```powershell
python -m pip install -e ".[gui]"
python -m pytest tests/tidymate_core_tests/test_gui.py -q
python -m tidymate_app.main
```
