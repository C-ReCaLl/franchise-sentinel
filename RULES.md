# RULES.md — 特许鹰眼项目编码规范与质量门

> 本文件是 Loop Engineering 的 **Rules 层**：定义代码规范、测试要求和验证流程。
> 任何 Agent 修改代码后，必须通过这些规则才能被视为"完成"。

---

## 一、代码规范

### 1.1 Python 风格

- 使用 PEP 8 风格。
- 缩进：4 个空格。
- 行宽：120 字符（比标准 80 更宽松，适合中文注释）。
- 字符串引号：双引号优先，内部单引号无需转义。
- 中文注释：允许且鼓励，因为项目面向中文法律场景。

### 1.2 函数签名

- 所有函数必须有 docstring，说明功能、参数、返回值。
- 参数类型提示可选，但鼓励使用。
- 复杂逻辑必须加行内注释。

```python
def parse_publish_datetime(text: str) -> datetime:
    """
    从文本中解析发布时间。

    支持格式：
    - 相对时间："3小时前"、"2天前"
    - 今天/昨天
    - 完整日期："2026-06-15"、"2026年6月15日"
    - 月日："6月15日"（以当前年份补全）

    参数：
        text: 包含时间信息的字符串

    返回：
        解析成功返回 datetime，失败返回 None
    """
```

### 1.3 错误处理

- 网络请求必须有超时（默认 10 秒，全文回填 10 秒）。
- 异常必须捕获并记录，不能抛出让程序崩溃。
- 关键步骤失败时，记录 WARNING 级别日志，继续执行其他步骤。

```python
try:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
except requests.RequestException as e:
    logging.warning(f"请求失败：{url} | {e}")
    return None
```

### 1.4 日志规范

- 使用 `logging` 模块，不要 `print`。
- 日志级别：
  - `INFO`：正常流程节点（如"开始搜索"、"推送成功"）
  - `WARNING`：非致命错误（如某个来源抓取失败）
  - `ERROR`：致命错误（如企微推送失败）
- 日志格式：`%(asctime)s [%(levelname)s] %(message)s`

### 1.5 配置文件

- `config.json` 是私有文件，**绝不提交 Git**。
- `config.example.json` 是模板，提交 GitHub。
- 新增配置项时，必须同时更新 `config.example.json`。

### 1.6 状态文件

- `pushed_history.json` 和 `daily_findings.json` 由 `state_sync.py` 管理。
- 不要直接修改这两个文件的格式。
- 新增字段时，确保向后兼容（旧版本能读取新版本文件）。

---

## 二、测试规范

### 2.1 测试文件

- 测试文件放在 `tests/` 目录下。
- 命名：`test_<模块名>.py`。
- 使用 `pytest` 框架。

### 2.2 必须测试的函数

| 函数 | 测试重点 | 原因 |
|---|---|---|
| `parse_publish_datetime` | 各种时间格式解析正确性 | 时间判断是过滤核心 |
| `score_article` | 不同输入的分数计算 | 推送质量的关键 |
| `is_recent_article` | 边界日期判断 | 避免旧新闻漏过 |
| `is_relevant` | 相关/不相关文章判断 | 过滤准确性 |
| `state_sync.pull` | 从云端拉取正常 | 状态同步可靠性 |
| `state_sync.push` | 向云端回写正常 | 状态同步可靠性 |

### 2.3 测试原则

- **确定性测试**：输入固定，输出必须固定。不要依赖外部网络（用 `unittest.mock` 或 `responses` 库 mock HTTP）。
- **边界测试**：测试边界条件（如 30 天前 vs 31 天前、分数 5 vs 6）。
- **异常测试**：测试网络超时、解析失败、空输入等异常情况。

### 2.4 测试覆盖率目标

- 核心函数（`parse_publish_datetime`、`score_article`、`is_recent_article`）覆盖率 >= 90%。
- 整体覆盖率 >= 70%。

---

## 三、质量门（Quality Gates）

任何代码改动必须通过以下全部检查，才能合并到主分支：

### Gate 1：语法检查

```bash
python3 -m py_compile franchise_monitor.py
python3 -m py_compile state_sync.py
```

### Gate 2：单元测试

```bash
python3 -m pytest tests/ -v --tb=short
```

### Gate 3：干跑测试

```bash
python3 franchise_monitor.py --once --dry-run
```

要求：
- 不报错
- 日志显示正常抓取和评分流程
- 不推送、不写历史

### Gate 4：状态同步测试

```bash
# 确保环境变量已设置
export STATE_REPO=C-ReCaLl/franchise-sentinel-state
export GITHUB_TOKEN=<your-token>

python3 state_sync.py pull
python3 state_sync.py push
```

要求：
- pull 成功拉取文件
- push 成功回写文件（或检测到无变化跳过）

### Gate 5：GitHub Actions 验证

- 推送 workflow 文件到 GitHub
- 手动触发 workflow
- 查看 Actions 日志，确认所有步骤成功

### Gate 6：企微推送验证（仅最终发布前）

- 运行一次真实监控（去掉 `--dry-run`）
- 确认企微收到推送
- 检查推送内容格式正确

---

## 四、Git 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 风格：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

类型：

| 类型 | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `docs` | 文档更新 |
| `test` | 增加/修改测试 |
| `refactor` | 重构（不改变行为） |
| `chore` | 杂项（依赖更新、配置调整等） |

示例：

```
feat(search): 增加 site:thepaper.cn 搜索词

fix(parser): 修复 "昨天" 时间解析在跨年时出错的问题

test(score): 增加 score_article 边界测试

docs(adr): 记录 GitHub Actions 替代 TRAE 自动化的决策
```

---

## 五、Loop Engineering 工作流

当 Agent 接到修改任务时，按以下流程执行：

```
1. 读 SKILL.md → 了解项目结构和管道
2. 读 VISION.md → 确认改动不违反架构决策
3. 读 RULES.md → 了解编码规范和质量门
4. 制定计划 → 在对话中说明改动范围和预期影响
5. 执行改动 → 修改代码
6. 本地验证 → 运行 Gate 1-4
7. 提交 GitHub → 创建 commit，推送到主仓库
8. GitHub Actions 验证 → 手动触发 workflow，确认 Gate 5
9. 企微验证 → 运行真实监控，确认 Gate 6
10. 更新文档 → 如有架构变更，更新 VISION.md；如有流程变更，更新 SKILL.md
```

---

## 六、Agent 自检清单

每次修改完成后，Agent 必须自检：

- [ ] 语法检查通过
- [ ] 新增/修改的函数有 docstring
- [ ] 异常处理完善
- [ ] 日志使用 `logging` 而非 `print`
- [ ] `config.example.json` 已同步更新
- [ ] 测试已补充（如修改了核心函数）
- [ ] 干跑测试通过
- [ ] GitHub Actions workflow 无需修改，或已同步更新
- [ ] SKILL.md / VISION.md 已同步更新（如需要）
