# SKILL.md — 特许鹰眼项目操作规范

> 本文件是 Loop Engineering 的 **Skills 层**：将项目知识固化，任何 Agent 接手时无需从零猜测意图。
> 修改前请先读 `VISION.md`，修改后更新本文件。

---

## 项目基本信息

| 字段 | 内容 |
|---|---|
| 项目名称 | 特许鹰眼 / Franchise Sentinel |
| 定位 | 商业特许经营法律风险情报监控机器人 |
| 核心用户 | 特许经营律师 |
| 主要语言 | Python 3.11+ |
| 编码 | UTF-8 |

## 核心文件

| 文件 | 职责 | 可独立运行 |
|---|---|---|
| `franchise_monitor.py` | 主程序：抓取→评分→过滤→推送 | `python3 franchise_monitor.py --once` |
| `state_sync.py` | 状态文件与 GitHub 私有仓库同步 | `python3 state_sync.py pull` / `push` |
| `config.json` | 私有配置（含企微 webhook），不提交 Git | — |
| `config.example.json` | 配置模板，提交 GitHub | — |
| `ccfa_top300_brands.json` | CCFA TOP300 品牌关键词库 | — |
| `requirements.txt` | 依赖：`requests beautifulsoup4 schedule lxml` | — |
| `pushed_history.json` | 已推送内容 ID（去重用） | — |
| `daily_findings.json` | 当日入库线索（每日简报用） | — |

## 运行模式

```bash
# 两小时监控（实时推送）
python3 franchise_monitor.py --once

# 每日简报
python3 franchise_monitor.py --daily-summary

# 干跑测试（不推送、不写历史）
python3 franchise_monitor.py --once --dry-run

# 状态同步（由 GitHub Actions 调用）
python3 state_sync.py pull   # 拉取云端状态到本地
python3 state_sync.py push   # 回写本地状态到云端
```

## 状态管理（Memory 层）

两个文件通过 GitHub 私有仓库 `C-ReCaLl/franchise-sentinel-state` 持久化，
由 `state_sync.py` 在每次 GitHub Actions 运行前 pull、运行后 push。

**正常流程（GitHub Actions）：**

```
pull 状态文件 → run_once / --daily-summary → push 状态文件
```

**本地调试流程：**

```
# 本地已有 config.json，直接运行
python3 franchise_monitor.py --once

# 本地已有 pushed_history.json，不会重复推送
```

## 环境变量

| 变量 | 用途 | 来源 |
|---|---|---|
| `WECOM_WEBHOOK` | 企微机器人地址 | GitHub Secrets / 本地 config.json |
| `STATE_REPO` | 状态仓库名 | GitHub Actions 环境变量 |
| `GITHUB_TOKEN` | 状态仓库写入权限 | GitHub Secrets |

## 搜索管道（Pipeline）

```
search_queries (61条)
    ↓
SEARCH_SOURCES (百度新闻 + 搜狗微信)
    ↓
dedupe_articles()       # URL去重 + 标题去重
    ↓
enrich_and_filter()
    ├─ score_article()  # 关键词+品牌+来源评分
    ├─ fetch_article_detail()  # 补抓正文（二次评分）
    ├─ attach_publish_date()   # 时间解析
    ├─ is_recent_article()     # 30天时效过滤
    └─ is_relevant()           # 相关性判断
    ↓
TOP N → push_to_wecom()  # 企微推送
    ↓
append_daily_findings()  # 写入 daily_findings.json
    ↓
save_history()           # 写入 pushed_history.json
```

## 评分规则

- 关键词权重：`商业特许经营=8`, `特许经营=7`, `行政处罚=6`, `未备案=6` 等（见 `SCORE_RULES`）
- 品牌命中：每命中一个重点品牌 +4 分
- 来源加成：市监/商务部/法院 +5，法治日报 +4，公众号 +3
- 最低推送分数：`min_relevance_score`（默认 6）
- 强制通过条件：品牌命中 + 风险标签 → 即使分数 <6 也推送

## 时间解析（`parse_publish_datetime`）

支持格式：

| 格式 | 示例 | 说明 |
|---|---|---|
| 相对时间 | "3小时前"、"2天前" | 以当前时间计算 |
| 今天/昨天 | "今天"、"昨天" | — |
| 完整日期 | "2026-06-15"、"2026年6月15日" | 年/月/日全 |
| 月日 | "6月15日" | 以当前年份补全 |

**注意**：正文（`detail`）不参与时间判断，避免页脚推荐文章干扰。

## GitHub Actions 工作流

| 工作流 | 触发 | cron | 用途 |
|---|---|---|---|
| `franchise-monitor.yml` | 定时 + 手动 | `0 */2 * * *`（UTC） | 两小时一次监控推送 |
| `franchise-daily-summary.yml` | 定时 + 手动 | `0 1 * * *`（UTC = 北京09:00） | 每日简报 |

两个工作流均使用 `if: always()` 保证即使任务失败也 push 状态。

## 增加新的搜索词

1. 在 `config.example.json` 的 `search_queries` 中追加（不要直接改 `config.json`）。
2. 用 `--dry-run` 验证新词命中率。
3. 新词生效后，提交 GitHub，Actions 下次自动运行时会读取新配置。

## 增加新的直连源

在 `franchise_monitor.py` 的 `DIRECT_SOURCES` 列表中追加：

```python
{
    "name": "来源名称",
    "url": "https://...",
    "parser": "generic_list",   # 或 "baidu_news", "sogou_wechat"
},
```

> `generic_list` 解析器从 HTML 中提取所有 `<a>` 标签作为候选链接，适合新闻列表页。
> 如果需要特殊解析逻辑，写一个新函数并在 `PARSERS` 字典中注册。

## 常见问题

**Q: 企微没有收到推送？**
→ 检查 `WECOM_WEBHOOK` 是否正确；检查 GitHub Actions 日志是否有推送记录。

**Q: 推送了旧新闻？**
→ 可能是 `pushed_history.json` 在新沙箱里被清空了。云端状态仓库 `franchise-sentinel-state` 已保证跨次持久化。

**Q: 搜索结果变少？**
→ 可能是百度/搜狗反爬加强了。用 `--dry-run` 查看实际抓到了多少条。

**Q: 想临时关闭某个搜索词？**
→ 在 `config.json` 中注释掉对应行（JSON 不支持 `#` 注释，改为删除该行）。
