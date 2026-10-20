# 贡献指南

## 先读这三份

1. [`README.md`](../README.md) —— 项目是什么，当前处于哪个阶段。
2. [`docs/SECURITY.md`](SECURITY.md) —— 什么算安全漏洞，怎么报。
3. [`docs/ROADMAP.md`](ROADMAP.md) —— 现在允许做什么，什么还没轮到。

**阶段纪律**：当前阶段之外的功能不合并，哪怕实现得很漂亮。提前落地会让"可验证"变成"看起来能跑"。

## 环境

- Windows 10/11 x64
- Python 3.12+
- 不需要 Visual Studio、不需要 .NET SDK

```powershell
python -m pip install -e ".[dev]"
pwsh -File scripts/make-sandbox.ps1   # 演练沙箱，绝不在真实目录上测试
```

## 提交前必须通过

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest
python scripts/check_forbidden_apis.py
```

`pytest` 里 warnings 是错误（`filterwarnings = ["error"]`），覆盖率下限 90%。不达标就是没做完。

## 硬规则（PR 会被直接拒绝的情形）

- 出现任何永久删除调用：`os.remove`、`os.unlink`、`shutil.rmtree`、`Path.unlink`、
  `File.Delete`、`Directory.Delete`、`SHFileOperation`、`Remove-Item`、`rm -rf`。
  唯一的删除入口是 `send2trash`，且只用于"删除"这个显式操作和"回滚 copy 时删自己刚建的副本"。
- 新增"默认就写盘"的代码路径。所有写操作必须经过 `--apply`/二次确认闸门。
- 把黑名单、祖先检测、模板白名单做成"可配置关闭"。
- 修改了行为却没有对应测试；或者把失败的测试改成 `skip`。
- failed/skipped 被计入 success，或统计数字不是从日志表聚合出来的。
- 引入未在 PR 里说明的网络依赖。

## 触碰写盘逻辑的 PR 需要两个人

涉及移动/重命名/复制/删除/撤销的改动，**必须**有作者以外的第二人人工 review，并在 PR
模板的 4.1 里写明 reviewer。理由很简单：这类缺陷的代价不可逆，而作者对自测盲区天然免疫。

如果找不到 reviewer，把 PR 拆成"先加接口与测试（不接执行器）+ 后接执行器"两个。

## 提交信息

`<area>: <what changed>`，area 取 `core` / `cli` / `app` / `ci` / `docs` / `security`。

```
core: reject unresolved template variables instead of guessing
ci: run forbidden-delete scan on every PR
```

## Issue 标签

标签定义在 [`.github/labels.yml`](../.github/labels.yml)。同步到 GitHub：

```powershell
python scripts/apply_labels.py --dry-run
python scripts/apply_labels.py      # 需要 gh auth login
```

严重度用 `P0/P1/P2`：`P0` = 数据安全或状态造假，`P1` = 当前里程碑必须修，`P2` = 可排期。
`security` 标签的问题按 SECURITY.md 的流程处理，不要在公开 issue 里讨论利用细节。
