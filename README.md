# 特许鹰眼 Franchise Sentinel

面向特许经营律师的法律风险情报监控工具。

它会定期检索商业特许经营、连锁加盟、行政处罚、加盟合同纠纷、未备案、虚假宣传、加盟商维权等线索，并推送到企业微信群。

## 核心能力

- 每隔固定时间抓取一次特许经营相关线索。
- 按法律风险相关性打分，减少泛泛的连锁商业新闻。
- 识别行政处罚、未备案、招商宣传风险、加盟合同纠纷、加盟商维权等类型。
- 接入 CCFA TOP300 品牌词库，提高重点连锁品牌命中率。
- 推送即时线索到企业微信。
- 支持每日汇总版，生成更像情报简报的内容。

## 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

复制配置：

```bash
cp config.example.json config.json
```

打开 `config.json`，填入企业微信机器人地址：

```json
"wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
```

只运行一轮：

```bash
python3 franchise_monitor.py --once
```

推送每日汇总：

```bash
python3 franchise_monitor.py --daily-summary
```

持续运行：

```bash
python3 franchise_monitor.py
```

## 文件说明

- `franchise_monitor.py`：主程序。
- `config.example.json`：配置示例，不包含机器人地址。
- `ccfa_top300_brands.json`：从 CCFA TOP300 公示中提取的品牌词库。
- `ccfa_top300_rows.json`：CCFA TOP300 原始表格结构化记录。
- `requirements.txt`：依赖列表。
- `使用说明.md`：中文使用说明。

## 安全说明

`config.json`、日志、历史记录和每日汇总素材默认不会上传到 GitHub，因为里面可能包含企业微信机器人地址、推送历史和内部线索。

如果你确认仓库是私有的，也可以自行调整 `.gitignore`。
