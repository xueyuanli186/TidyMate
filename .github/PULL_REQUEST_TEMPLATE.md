# Pull Request

## 1. 变更说明

<!-- 做了什么、为什么。不要只贴标题。 -->

## 2. 关联 issue

<!-- 用 "Closes #123" / "Refs #123" 的形式；没有 issue 的 PR 请先开 issue。 -->

Closes #

## 3. 变更类型

- [ ] 缺陷修复（bug）
- [ ] 新功能（enhancement）
- [ ] 文档（documentation）
- [ ] 重构 / 内部质量（无行为变化）
- [ ] 构建、CI、打包
- [ ] 安全加固

## 4. 自检清单（必须逐条勾选，未勾选不进入 review）

### 4.1 安全底线

- [ ] **本 PR 是否触碰文件移动 / 重命名 / 复制 / 删除 / 撤销逻辑？**
      <!-- 勾选"是"时：必须由除作者外的第二人人工 review，并在下方写明 reviewer 与结论。
           没有人愿意 review 的话，请拆成"先加测试与接口、后加执行"两个 PR。 -->
      - [ ] 否（仅文档 / CI / 测试 / 纯逻辑规划层）
      - [ ] 是 → 已指定人工 reviewer：`@____`，结论：____
- [ ] 没有新增任何永久删除调用（`os.remove` / `os.unlink` / `shutil.rmtree` / `File.Delete` / `SHFileOperation` / `Remove-Item`）。
      <!-- CI 的 safety job 会扫；本地可跑 python scripts/check_forbidden_apis.py -->
- [ ] 删除行为（若有）只走 `send2trash`，并在 PR 描述里说明为什么需要删除。
- [ ] 真实写盘仍然只能通过显式 `--apply` 或 GUI 二次确认进入；没有新增"默认就写"的路径。
- [ ] 系统/程序目录黑名单没有新增任何配置开关，且命中路径仍然被拒绝并单独报告。
- [ ] 模板变量、路径祖先检测、特殊文件分类的既有测试没有被削弱或跳过。
- [ ] 没有引入网络依赖；如涉及 AI/联网，默认关闭且只读元数据。

### 4.2 测试与状态真实性

- [ ] 新增/修改的行为都有对应测试（缺陷修复请附"修复前会失败"的用例）。
- [ ] `pytest` 全绿；新增跳过（skip）用例已说明原因。
- [ ] failed / skipped 没有被计入 success；报告数字可从日志复现（若是 reporting 改动）。
- [ ] 覆盖率没有下降（`fail_under = 90` 仍通过）。

### 4.3 仓库卫生

- [ ] 本地跑过 `python -m ruff check .`、`python -m ruff format --check .`、`python -m mypy`。
- [ ] 没有提交 `*.db`、`.venv/`、`dist/`、`coverage.xml` 或任何沙箱目录。
- [ ] 版本号只在 `src/tidymate_core/_version.py` 改动（如发布 PR 涉及）。
- [ ] 行为变化已同步更新 `docs/ROADMAP.md` 或相关文档。

## 5. 测试证据

<!-- 粘贴真实命令与输出摘要（失败数、跳过数、覆盖率）。不要写"已测试"。 -->

```text
$ python -m pytest
...
```

## 6. 风险与回滚

<!-- 这次改动最坏会导致什么？如何回退？涉及写盘的必须写。 -->
