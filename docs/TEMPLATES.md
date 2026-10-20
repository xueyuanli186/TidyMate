# 模板参考

模板决定"文件会被放到哪里、叫什么名字"。它必须是**相对路径**，以配置里的
`outputRoot` 为基准拼接。

```yaml
action:
  op: move
  template: "Pictures/{year}/{ext_nodot}/{stem}{ext}"
```

上例会产出类似 `Pictures/2026/jpg/IMG_0001.jpg` 的路径。

## 变量

变量名**大小写敏感**，拼错不会"自动纠正"，而是整份规则文件被拒绝加载（铁律 6）。

### 时间（来自文件 mtime）

| 变量 | 含义 | 示例 |
| --- | --- | --- |
| `{year}` | 本地时区年份，4 位 | `2026` |
| `{month}` | 本地时区月份，2 位 | `03` |
| `{day}` | 本地时区日期，2 位 | `07` |
| `{hour}` | 本地时区小时，2 位 | `15` |
| `{minute}` | 本地时区分钟，2 位 | `04` |
| `{year_utc}` | UTC 年份 | `2026` |
| `{month_utc}` | UTC 月份 | `03` |
| `{day_utc}` | UTC 日期 | `07` |

> 本地与 UTC 会不一致。mtime 为 `2024-03-07T23:30Z` 时，`{day}` 在 UTC+8 下是
> `08`，`{day_utc}` 是 `07`。要跨机器可复现就用 `_utc` 系列；要符合用户直觉就用本地系列。

### 名称与类型

| 变量 | 含义 | 对 `IMG_0001.JPG` 的值 |
| --- | --- | --- |
| `{ext}` | 含点、小写 | `.jpg` |
| `{ext_nodot}` | 不含点、小写 | `jpg` |
| `{stem}` | 主文件名，保留原大小写 | `IMG_0001` |
| `{name}` | 完整原文件名 | `IMG_0001.JPG` |
| `{parent}` | 直接父目录名 | 取决于源路径 |

### 其他

| 变量 | 含义 | 示例 |
| --- | --- | --- |
| `{size_bucket}` | `tiny`(<100KB) / `small`(<10MB) / `medium`(<1GB) / `large` | `small` |
| `{rule_id}` | 命中的规则 id，便于追溯 | `images-by-year` |
| `{seq}` | 批内序号，6 位零填充 | `000042` |

## 明确禁止的变量

以下变量**一定报错**，不会降级、不会兼容：

`{path}` `{fullpath}` `{drive}` `{cwd}` `{userprofile}` `{home}` `{random}`，
以及任何以 `env` 或 `hash` 开头的变量（例如 `{env:USERPROFILE}`、`{hash8}`）。

理由只有两类：

- **泄露本机状态**：绝对路径、用户名、环境变量会进入目标路径，让报告和复现失去意义；
- **不可复现**：随机数会让同一份输入产生不同的 `plan_hash`。

## 净化规则

渲染结果在拼成路径之前会被逐段处理：

1. **非法字符替换**：`< > : " / \ | ? *` → `_`。
2. **控制字符移除**：`0x00–0x1F` 直接丢弃。
3. **首尾处理**：去掉**前导空格**，去掉**尾部空格和点**；**前导点保留**。
4. **长度限制**：单段超过 60 字符时截断，保留原扩展名，并追加 8 位哈希后缀
   （形如 `aaaa…-1f3c9b2e.jpg`），同时在 `plan.json` 的 `notes` 里标注被截断。
5. **空值兜底**：某一段净化后为空时，用 `untitled_{seq}` 填充并标注。

第 3 条容易被误解，单独说明：

> **为什么保留前导点？**
> Windows 只禁止文件名**以点或空格结尾**，并不禁止以点开头——`.gitignore`、`.env`
> 都是合法文件名。如果按"首尾都去点"处理，`{ext}` 渲染出的 `.jpg` 会被削成 `jpg`，
> 目标文件失去扩展名，属于数据损坏。因此规则是"去前导空格 + 去尾部空格和点"。
> 对应测试：`test_leading_dot_is_preserved`、`test_leading_space_and_trailing_dot_are_trimmed`。

## 路径形状限制

模板本身也会被校验，以下情况在**加载规则时**就报错，而不是等到执行：

| 情况 | 处理 |
| --- | --- |
| 以 `/` 或 `\` 开头 | 拒绝（模板必须相对） |
| 含盘符（`C:`） | 拒绝 |
| 出现 `..` 或 `.` 段 | 拒绝 |
| 连续分隔符 `a//b` | 拒绝 |
| 用 `\` 作分隔符 | 拒绝（统一用 `/`） |
| 字面量含 `<>:"\|?*` | 拒绝（作者写错了） |
| 花括号不配对 / 空 `{}` | 拒绝 |

注意区分：**模板字面量**里的非法字符是规则错误（加载即拒绝）；
**渲染值**里的非法字符是运行时数据（净化后继续），因为文件名里的 `:` 可能来自
其他文件系统。

## 目标路径的限制

渲染出的路径还要过三关（阶段 3 实现）：

- 落在 `outputRoot` 之下，且 `outputRoot` 本身不能是受保护目录；
- 文件名不能是 Windows 保留设备名（`CON`、`NUL`、`COM1`…`LPT9`）；
- 全路径 >260 字符时使用 `\\?\` 形式；>32767 字符则标记为不可执行。

## 示例

按年份归档图片：

```yaml
rules:
  - id: images-by-year
    when:
      ext: [".jpg", ".jpeg", ".png", ".heic"]
    action:
      op: move
      template: "Pictures/{year}/{ext_nodot}/{stem}{ext}"
      conflict: skip
```

按大小分桶、保留可追溯性：

```yaml
rules:
  - id: big-archives
    when:
      ext: [".zip", ".7z"]
      size: ">=100MB"
    action:
      op: move
      template: "Archives/large/{rule_id}/{year}/{name}"
      conflict: rename
```

按批次序号打散到一个目录：

```yaml
rules:
  - id: flat-numbered
    when:
      path_glob: "**/inbox/**"
    action:
      op: copy
      template: "Imported/{seq}-{stem}{ext}"
```
