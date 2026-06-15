#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
特许经营法律风险情报监控

适合场景：
1. 监控商业特许经营、连锁加盟、行政处罚、加盟纠纷等信息。
2. 将高相关内容推送到企业微信群。
3. 为特许经营律师提供“可输出观点”的早期线索。
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin

import requests
import schedule
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
HISTORY_FILE = BASE_DIR / "pushed_history.json"
DAILY_FINDINGS_FILE = BASE_DIR / "daily_findings.json"
LOG_FILE = BASE_DIR / "monitor.log"


DEFAULT_CONFIG = {
    "wecom_webhook": "",
    "fetch_interval_minutes": 30,
    "max_push_per_round": 10,
    "min_relevance_score": 6,
    "fetch_article_detail": True,
    "detail_fetch_limit_per_round": 20,
    "daily_summary_time": "09:00",
    "max_article_age_days": 30,
    "require_publish_date": True,
    "priority_brands": [],
    "ccfa_top300_brands": [],
    "search_queries": [
        "商业特许经营 行政处罚",
        "特许经营 行政处罚",
        "特许经营 处罚决定书",
        "加盟 行政处罚",
        "招商加盟 虚假宣传 处罚",
        "加盟费 退费 判决",
        "特许经营 合同纠纷 判决",
        "加盟商 维权 退费",
        "未备案 特许经营",
        "酒店 加盟 行政处罚",
        "餐饮 加盟 行政处罚",
        "site:mp.weixin.qq.com 特许经营 行政处罚",
        "site:zhihu.com 特许经营 加盟 纠纷",
        "site:xiaohongshu.com 加盟 维权",
        "site:weibo.com 加盟 退费",
        "特许经营 未备案 处罚",
        "两店一年 违规 罚款",
        "加盟 合同纠纷 品牌方 败诉",
        "特许经营 信息披露 违法",
        "快招 骗局 加盟 维权",
        "特许经营 备案 撤销",
        "加盟 冷静期 法院 判决",
        "特许人 虚假宣传 罚款",
        "加盟费 退还 判决",
        "特许经营 监管 新规",
        "商务违法行为 加盟 处罚",
        "未备案 招商 罚款",
        "加盟商 解约 胜诉",
        "特许经营 不合规 整改",
        "品牌方 加盟 连带责任",
        "商务部 特许经营 备案 企业 违规",
        "加盟 跑路 总部 责任",
        "特许经营 合同 无效 案例",
        "区域代理 加盟 纠纷 2026",
        "商标 无效宣告",
        "商标 撤销",
    ],
    "exclude_keywords": ["游戏加盟", "手游", "二次元", "明星", "影视", "彩票", "加盟广告", "招商电话"],
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# 分数越高，说明越接近“特许经营法律风险情报”
SCORE_RULES = {
    "商业特许经营": 8,
    "特许经营": 7,
    "特许人": 6,
    "被特许人": 6,
    "加盟合同": 6,
    "加盟商": 5,
    "加盟费": 5,
    "品牌授权": 4,
    "招商加盟": 4,
    "连锁加盟": 4,
    "信息披露": 5,
    "行政处罚": 6,
    "处罚决定书": 6,
    "责令改正": 5,
    "罚款": 4,
    "没收违法所得": 5,
    "虚假宣传": 5,
    "违法广告": 4,
    "未备案": 6,
    "备案": 2,
    "撤销": 3,
    "退费": 4,
    "退还": 4,
    "退款": 3,
    "解除合同": 4,
    "解约": 4,
    "冷静期": 5,
    "合同纠纷": 4,
    "合同无效": 5,
    "法院判决": 4,
    "判决": 3,
    "起诉": 3,
    "败诉": 3,
    "胜诉": 3,
    "连带责任": 4,
    "维权": 3,
    "投诉": 3,
    "快招": 4,
    "骗局": 4,
    "跑路": 4,
    "总部责任": 4,
    "商务违法行为": 5,
    "不合规": 4,
    "整改": 3,
    "商标无效宣告": 5,
    "无效宣告": 4,
    "商标撤销": 5,
    "商标": 2,
    "加盟": 2,
    "连锁": 1,
}


RISK_LABEL_RULES = [
    ("行政处罚", ["行政处罚", "处罚决定书", "责令改正", "罚款", "没收违法所得"]),
    ("未备案/备案风险", ["未备案", "备案", "商业特许经营"]),
    ("信息披露风险", ["信息披露"]),
    ("招商宣传风险", ["虚假宣传", "违法广告", "招商加盟", "收益承诺", "快招", "骗局"]),
    ("加盟合同纠纷", ["加盟合同", "合同纠纷", "退费", "退还", "退款", "解除合同", "解约", "冷静期", "判决", "起诉", "败诉", "胜诉", "合同无效", "连带责任"]),
    ("加盟商维权/舆情", ["加盟商", "维权", "投诉", "踩坑", "跑路", "总部责任"]),
    ("商标/IP风险", ["商标", "无效宣告", "商标撤销", "商标无效宣告"]),
]


SOURCE_WEIGHT = {
    "信用中国": 5,
    "市场监管": 5,
    "市监": 5,
    "商务部": 5,
    "法院": 5,
    "裁判": 5,
    "法治日报": 4,
    "公众号": 3,
    "百度新闻": 2,
    "搜狗微信": 2,
    "知乎": 1,
    "小红书": 1,
    "微博": 1,
}


SEARCH_SOURCES = [
    {
        "name": "百度新闻",
        "url": "https://news.baidu.com/ns?word={query}&tn=news&from=news&cl=2&rn=20&ct=1",
        "parser": "baidu_news",
    },
    {
        "name": "搜狗微信",
        "url": "https://weixin.sogou.com/weixin?type=2&query={query}&ie=utf8",
        "parser": "sogou_wechat",
        "delay": 3,
    },
]


DIRECT_SOURCES = [
    {
        "name": "市场监管总局",
        "url": "https://www.samr.gov.cn/xw/zj/",
        "parser": "generic_list",
    },
    {
        "name": "中国连锁经营协会",
        "url": "https://www.ccfa.org.cn/portal/cn/newsList.jsp?contentId=3694769&pageSize=20&pageNum=1",
        "parser": "generic_list",
    },
    {
        "name": "商务部特许经营系统",
        "url": "http://txjy.syggs.mofcom.gov.cn/",
        "parser": "generic_list",
    },
    {
        "name": "法治日报",
        "url": "http://www.legaldaily.com.cn/",
        "parser": "generic_list",
    },
    {
        "name": "澎湃新闻·法治",
        "url": "https://www.thepaper.cn/list_25634",
        "parser": "generic_list",
    },
    {
        "name": "澎湃新闻·财经",
        "url": "https://www.thepaper.cn/list_25635",
        "parser": "generic_list",
    },
    {
        "name": "上观新闻·产经",
        "url": "https://m.jfdaily.com/staticsg/wap/subsection?id=303",
        "parser": "generic_list",
    },
]


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config.update(user_config)

    # 环境变量优先，适合服务器部署，避免把机器人地址写进代码或仓库。
    env_webhook = os.getenv("WECOM_WEBHOOK", "").strip()
    if env_webhook:
        config["wecom_webhook"] = env_webhook

    return config


CONFIG = load_config()


def normalize_text(text: str) -> str:
    text = str(text or "")
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate(text: str, max_len: int = 120) -> str:
    text = normalize_text(text)
    return text[:max_len] + "…" if len(text) > max_len else text


def current_now() -> datetime:
    return datetime.now()


def parse_publish_datetime(text: str) -> Optional[datetime]:
    """从标题、摘要、正文中尽量识别发布时间。识别不到返回 None。"""
    text = normalize_text(text)
    now = current_now()

    relative_patterns = [
        (r"(\d+)\s*分钟[前内]", "minutes"),
        (r"(\d+)\s*小时[前内]", "hours"),
        (r"(\d+)\s*天前", "days"),
    ]
    for pattern, unit in relative_patterns:
        m = re.search(pattern, text)
        if m:
            value = int(m.group(1))
            if unit == "minutes":
                return now - timedelta(minutes=value)
            if unit == "hours":
                return now - timedelta(hours=value)
            return now - timedelta(days=value)

    if "今天" in text:
        return now
    if "昨天" in text:
        return now - timedelta(days=1)
    if "前天" in text:
        return now - timedelta(days=2)

    full_date_patterns = [
        r"(20\d{2})[年/\-.](\d{1,2})[月/\-.](\d{1,2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    full_date_candidates = []
    for pattern in full_date_patterns:
        for m in re.finditer(pattern, text):
            try:
                year, month, day = map(int, m.groups())
                dt = datetime(year, month, day)
                # 排除明显未来日期，避免把“2026榜单”等非发布时间误判为新新闻。
                if dt <= now + timedelta(days=1):
                    full_date_candidates.append(dt)
            except ValueError:
                continue
    if full_date_candidates:
        return max(full_date_candidates)

    month_day_candidates = []
    for m in re.finditer(r"(?<!年)(?<!\d)(\d{1,2})月(\d{1,2})日", text):
        try:
            month, day = map(int, m.groups())
            dt = datetime(now.year, month, day)
            if dt <= now + timedelta(days=1):
                month_day_candidates.append(dt)
        except ValueError:
            continue
    return max(month_day_candidates) if month_day_candidates else None


def article_date_text(article: dict) -> str:
    # 不使用正文 detail 里的日期做发布时间判断。
    # 很多新闻页正文/侧栏/页脚会出现“当前日期”或其他推荐文章日期，容易把旧新闻误判成新新闻。
    return " ".join([
        article.get("published_at", ""),
        article.get("title", ""),
        article.get("summary", ""),
        article.get("url", ""),
    ])


def attach_publish_date(article: dict) -> dict:
    dt = parse_publish_datetime(article_date_text(article))
    article["_publish_dt"] = dt
    article["_publish_date"] = dt.strftime("%Y-%m-%d") if dt else ""
    return article


def is_recent_article(article: dict) -> bool:
    dt = article.get("_publish_dt")
    require_date = bool(CONFIG.get("require_publish_date", True))
    max_age_days = int(CONFIG.get("max_article_age_days", 30))
    if not dt:
        article["_freshness_reason"] = "未识别到发布时间"
        return not require_date

    age_days = (current_now() - dt).days
    if age_days < 0:
        article["_freshness_reason"] = "发布时间疑似未来日期"
        return False
    if age_days > max_age_days:
        article["_freshness_reason"] = f"发布时间超过 {max_age_days} 天"
        return False

    article["_freshness_reason"] = f"发布时间 {article.get('_publish_date')}"
    return True


def make_article_id(title: str, url: str) -> str:
    normalized_title = re.sub(r"\s+", "", title.strip())
    normalized_url = url.strip().split("#")[0]
    raw = f"{normalized_title}|{normalized_url}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def make_title_id(title: str) -> str:
    normalized_title = re.sub(r"[\s_\-—｜|:：,，。！!？?]+", "", title.strip().lower())
    return "title:" + hashlib.md5(normalized_title.encode("utf-8")).hexdigest()


def load_history() -> set:
    history = set()
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            history.update(data.get("ids", []))
        except Exception as e:
            logger.warning(f"读取历史记录失败，将重新初始化：{e}")

    # 兼容旧版本：旧历史只记录链接 ID。这里把每日素材里的标题也加入历史，减少同一新闻换来源重复推送。
    if DAILY_FINDINGS_FILE.exists():
        try:
            with open(DAILY_FINDINGS_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
            for item in items if isinstance(items, list) else []:
                title = item.get("title", "")
                if title:
                    history.add(make_title_id(title))
        except Exception as e:
            logger.warning(f"读取每日素材标题去重失败：{e}")
    return history


def save_history(history: set):
    ids = list(history)[-5000:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "updated": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


def load_daily_findings() -> list:
    if not DAILY_FINDINGS_FILE.exists():
        return []
    try:
        with open(DAILY_FINDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"读取每日汇总素材失败，将重新初始化：{e}")
        return []


def save_daily_findings(items: list):
    # 只保留最近 7 天，避免文件越来越大。
    recent = []
    now_ts = time.time()
    for item in items:
        ts = item.get("_saved_ts", now_ts)
        if now_ts - ts <= 7 * 24 * 3600:
            recent.append(item)
    with open(DAILY_FINDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(recent, f, ensure_ascii=False, indent=2)


def append_daily_findings(articles: list):
    if not articles:
        return
    items = load_daily_findings()
    existing = {item.get("_id") for item in items}
    today = datetime.now().strftime("%Y-%m-%d")
    for art in articles:
        if art.get("_id") in existing:
            continue
        items.append({
            "_id": art.get("_id"),
            "_saved_ts": time.time(),
            "date": today,
            "title": art.get("title", ""),
            "url": art.get("url", ""),
            "source": art.get("source", ""),
            "summary": art.get("summary", ""),
            "score": art.get("_score", 0),
            "risk_labels": art.get("_risk_labels", []),
            "brand_hits": art.get("_brand_hits", []),
            "keyword_hits": art.get("_keyword_hits", []),
            "lawyer_view": lawyer_view(art),
        })
    save_daily_findings(items)


def get_all_brands() -> list:
    brands = []
    brands.extend(CONFIG.get("priority_brands", []))
    brands.extend(CONFIG.get("ccfa_top300_brands", []))
    ccfa_brand_file = BASE_DIR / "ccfa_top300_brands.json"
    if ccfa_brand_file.exists():
        try:
            with open(ccfa_brand_file, "r", encoding="utf-8") as f:
                brands.extend(json.load(f))
        except Exception as e:
            logger.warning(f"读取 CCFA 品牌库失败：{e}")
    cleaned = []
    for brand in brands:
        brand = str(brand).strip()
        if brand and brand not in cleaned:
            cleaned.append(brand)
    return cleaned


def score_article(article: dict) -> dict:
    title = article.get("title", "")
    summary = article.get("summary", "")
    detail = article.get("detail", "")
    source = article.get("source", "")
    text = f"{title} {summary} {detail}"

    exclude_hits = [kw for kw in CONFIG.get("exclude_keywords", []) if kw and kw in text]
    if exclude_hits:
        article["_score"] = 0
        article["_exclude_hits"] = exclude_hits
        article["_keyword_hits"] = []
        article["_brand_hits"] = []
        article["_risk_labels"] = []
        return article

    score = 0
    keyword_hits = []
    for kw, weight in SCORE_RULES.items():
        if kw in text:
            score += weight
            keyword_hits.append(kw)

    brand_hits = []
    for brand in get_all_brands():
        if brand and brand in text:
            brand_hits.append(brand)
            score += 4

    for source_key, weight in SOURCE_WEIGHT.items():
        if source_key in source:
            score += weight

    risk_labels = []
    for label, words in RISK_LABEL_RULES:
        if any(word in text for word in words):
            risk_labels.append(label)

    article["_score"] = score
    article["_keyword_hits"] = keyword_hits[:12]
    article["_brand_hits"] = brand_hits[:8]
    article["_risk_labels"] = risk_labels[:5]
    return article


def is_relevant(article: dict) -> bool:
    score = article.get("_score", 0)
    keyword_hits = article.get("_keyword_hits", [])
    brand_hits = article.get("_brand_hits", [])
    risk_labels = article.get("_risk_labels", [])
    min_score = int(CONFIG.get("min_relevance_score", 6))

    if score >= min_score:
        return True

    # 品牌 + 法律风险词，即使分数略低，也保留。
    if brand_hits and risk_labels:
        return True

    # “特许经营”本身非常强，单独出现也尽量保留。
    if "特许经营" in keyword_hits or "商业特许经营" in keyword_hits:
        return True

    return False


def request_text(url: str, headers: Optional[dict] = None, timeout: int = 12) -> str:
    resp = requests.get(url, headers=headers or HEADERS, timeout=timeout)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    return resp.text


def parse_baidu_news(html: str, base_url: str, source_name: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    for item in soup.select(".result, .result-op"):
        title_tag = item.select_one("h3 a") or item.select_one(".c-title a")
        if not title_tag:
            continue
        title = normalize_text(title_tag.get_text(" ", strip=True))
        url = title_tag.get("href", "")
        summary_tag = item.select_one(".c-summary, .c-abstract")
        summary = normalize_text(summary_tag.get_text(" ", strip=True)) if summary_tag else ""
        item_text = normalize_text(item.get_text(" ", strip=True))
        published_at = ""
        dt = parse_publish_datetime(item_text)
        if dt:
            published_at = dt.strftime("%Y-%m-%d")
        if title and url:
            articles.append({
                "title": title,
                "url": url,
                "summary": summary,
                "source": source_name,
                "published_at": published_at,
            })
    return articles


def parse_sogou_wechat(html: str, base_url: str, source_name: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    for item in soup.select(".news-list li, .txt-box"):
        title_tag = item.select_one("h3 a, .txt-box h3 a")
        if not title_tag:
            continue
        title = normalize_text(title_tag.get_text(" ", strip=True))
        href = title_tag.get("href", "")
        if href and not href.startswith("http"):
            href = urljoin("https://weixin.sogou.com", href)
        account_tag = item.select_one(".account, .s-p")
        account = normalize_text(account_tag.get_text(" ", strip=True)) if account_tag else "公众号"
        summary_tag = item.select_one("p.txt, .str_info, .digest")
        summary = normalize_text(summary_tag.get_text(" ", strip=True)) if summary_tag else ""
        item_text = normalize_text(item.get_text(" ", strip=True))
        published_at = ""
        dt = parse_publish_datetime(item_text)
        if dt:
            published_at = dt.strftime("%Y-%m-%d")
        if title and href:
            articles.append({
                "title": f"[公众号] {title}",
                "url": href,
                "summary": f"{account} {summary}",
                "source": source_name,
                "published_at": published_at,
            })
    return articles


def parse_generic_list(html: str, base_url: str, source_name: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    seen = set()
    for a in soup.find_all("a", href=True):
        title = normalize_text(a.get_text(" ", strip=True))
        href = a.get("href", "")
        if len(title) < 6:
            continue
        if any(x in href.lower() for x in [".jpg", ".png", ".gif", "javascript:", "#"]):
            continue
        url = urljoin(base_url, href)
        key = f"{title}|{url}"
        if key in seen:
            continue
        seen.add(key)
        dt = parse_publish_datetime(f"{title} {href}")
        articles.append({
            "title": title,
            "url": url,
            "summary": "",
            "source": source_name,
            "published_at": dt.strftime("%Y-%m-%d") if dt else "",
        })
    return articles[:50]


PARSERS = {
    "baidu_news": parse_baidu_news,
    "sogou_wechat": parse_sogou_wechat,
    "generic_list": parse_generic_list,
}


def fetch_search_sources() -> list:
    articles = []
    queries = CONFIG.get("search_queries", [])
    for query in queries:
        for source in SEARCH_SOURCES:
            source_name = f"{source['name']}·{query}"
            try:
                url = source["url"].format(query=quote(query))
                logger.info(f"搜索：{source_name}")
                html = request_text(url)
                parser = PARSERS[source["parser"]]
                articles.extend(parser(html, url, source_name))
            except Exception as e:
                logger.warning(f"{source_name} 抓取失败：{e}")
            time.sleep(source.get("delay", 1.2))
    return articles


def fetch_direct_sources() -> list:
    articles = []
    for source in DIRECT_SOURCES:
        try:
            logger.info(f"抓取固定来源：{source['name']}")
            html = request_text(source["url"])
            parser = PARSERS[source["parser"]]
            articles.extend(parser(html, source["url"], source["name"]))
        except Exception as e:
            logger.warning(f"{source['name']} 抓取失败：{e}")
        time.sleep(1.2)
    return articles


def fetch_article_detail(article: dict) -> str:
    url = article.get("url", "")
    if not url or not url.startswith("http"):
        return ""
    try:
        html = request_text(url, timeout=10)
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        meta_texts = []
        for selector in [
            "meta[property='article:published_time']",
            "meta[name='publishdate']",
            "meta[name='pubdate']",
            "meta[name='date']",
            "meta[itemprop='datePublished']",
            "time",
        ]:
            for node in soup.select(selector):
                meta_texts.append(node.get("content") or node.get("datetime") or node.get_text(" ", strip=True))
        candidates = soup.select("article, .article, .content, .main, .detail, #content, p")
        if candidates:
            text = " ".join(normalize_text(x.get_text(" ", strip=True)) for x in candidates)
        else:
            text = normalize_text(soup.get_text(" ", strip=True))
        text = " ".join(meta_texts + [text])
        return truncate(text, 1200)
    except Exception:
        return ""


def dedupe_articles(articles: list) -> list:
    seen = set()
    result = []
    for art in articles:
        title = normalize_text(art.get("title", ""))
        url = art.get("url", "").strip()
        if not title or not url:
            continue
        key = make_article_id(title, url)
        url_key = url.split("#")[0]
        if url_key in seen:
            continue
        if key in seen:
            continue
        title_key = make_title_id(title)
        if title_key in seen:
            continue
        seen.add(key)
        seen.add(url_key)
        seen.add(title_key)
        art["title"] = title
        art["url"] = url
        art["summary"] = truncate(art.get("summary", ""), 240)
        art["_id"] = key
        art["_title_id"] = title_key
        result.append(art)
    return result


def lawyer_view(article: dict) -> str:
    labels = article.get("_risk_labels", [])
    hits = set(article.get("_keyword_hits", []))

    views = []
    if "行政处罚" in labels:
        views.append("核查处罚依据、违法事实、处罚机关和是否可类比到客户招商合规。")
    if "未备案/备案风险" in labels:
        views.append("关注是否涉及未完成商业特许经营备案即开展招商。")
    if "招商宣传风险" in labels:
        views.append("关注招商材料是否存在收益承诺、夸大宣传或误导性表述。")
    if "加盟合同纠纷" in labels:
        views.append("关注加盟费退还、解除合同、信息披露和冷静期相关争议。")
    if "维权" in hits or "投诉" in hits:
        views.append("关注是否有加盟商集中投诉，可能演化为群体性纠纷。")

    if not views:
        views.append("建议结合品牌背景、加盟模式和公开合同条款判断法律风险。")
    return "；".join(views[:2])


def priority_label(score: int) -> str:
    if score >= 18:
        return "高"
    if score >= 10:
        return "中"
    return "低"


def build_wecom_message(articles: list) -> dict:
    now = datetime.now().strftime("%m月%d日 %H:%M")
    lines = [
        "## 特许经营法律风险情报",
        f"> 时间：{now}　本轮新增：{len(articles)} 条",
        "",
    ]
    for i, art in enumerate(articles, 1):
        score = art.get("_score", 0)
        level = priority_label(score)
        title = truncate(art.get("title", ""), 58)
        source = art.get("source", "未知来源")
        url = art.get("url", "")
        labels = "、".join(art.get("_risk_labels", [])) or "待判断"
        brands = "、".join(art.get("_brand_hits", [])) or "未命中重点品牌"
        keywords = "、".join(art.get("_keyword_hits", [])[:6]) or "无"
        summary = truncate(art.get("summary", ""), 90)
        publish_date = art.get("_publish_date") or art.get("published_at") or "未知"

        lines.append(f"**{i}. [{level}优先级] {title}**")
        lines.append(f"> 发布时间：{publish_date}")
        lines.append(f"> 风险类型：{labels}")
        lines.append(f"> 命中品牌：{brands}")
        lines.append(f"> 命中词：{keywords}｜分数：{score}")
        if summary:
            lines.append(f"> 摘要：{summary}")
        lines.append(f"> 律师关注：{lawyer_view(art)}")
        lines.append(f"来源：{source}")
        if url:
            lines.append(f"[查看原文]({url})")
        lines.append("")

    lines.append("_自动监控结果仅作线索提示，正式对外观点建议复核原文和处罚/判决文书。_")
    return {"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}}


def post_markdown_to_wecom(content: str) -> bool:
    webhook = CONFIG.get("wecom_webhook", "").strip()
    if not webhook:
        logger.warning("未配置企业微信机器人地址，无法推送。")
        return False
    try:
        resp = requests.post(
            webhook,
            json={"msgtype": "markdown", "markdown": {"content": content}},
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            return True
        logger.error(f"推送失败：{data}")
        return False
    except Exception as e:
        logger.error(f"推送异常：{e}")
        return False


def push_to_wecom(articles: list) -> bool:
    if "--dry-run" in sys.argv:
        logger.info("干跑模式：不推送企微，不写入历史。")
        for art in articles:
            logger.info(
                f"[干跑] {art.get('_score')}分 {art.get('_publish_date')} "
                f"{art.get('title')} {art.get('url')}"
            )
        return False

    webhook = CONFIG.get("wecom_webhook", "").strip()
    if not webhook:
        logger.warning("未配置企业微信机器人地址，本轮只打印结果，不推送。")
        for art in articles:
            logger.info(f"[预览] {art.get('_score')}分 {art.get('title')} {art.get('url')}")
        return False

    batch_size = 4
    ok = True
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        payload = build_wecom_message(batch)
        try:
            resp = requests.post(webhook, json=payload, timeout=10)
            data = resp.json()
            if data.get("errcode") == 0:
                logger.info(f"推送成功：第 {i // batch_size + 1} 批，共 {len(batch)} 条")
            else:
                logger.error(f"推送失败：{data}")
                ok = False
        except Exception as e:
            logger.error(f"推送异常：{e}")
            ok = False
        time.sleep(0.6)
    return ok


def build_daily_summary_message(items: list) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    today_items = [item for item in items if item.get("date") == today]
    today_items.sort(key=lambda x: x.get("score", 0), reverse=True)

    high = [x for x in today_items if x.get("score", 0) >= 18]
    punishment = [x for x in today_items if "行政处罚" in x.get("risk_labels", [])]
    contract = [x for x in today_items if "加盟合同纠纷" in x.get("risk_labels", [])]
    brands = []
    for item in today_items:
        for brand in item.get("brand_hits", []):
            if brand not in brands:
                brands.append(brand)

    lines = [
        "## 特许经营法律风险每日简报",
        f"> 日期：{today}｜入库线索：{len(today_items)} 条｜高优先级：{len(high)} 条",
        f"> 行政处罚：{len(punishment)} 条｜加盟合同纠纷：{len(contract)} 条",
    ]
    if brands:
        lines.append(f"> 今日命中品牌：{'、'.join(brands[:12])}")
    lines.append("")

    if not today_items:
        lines.append("今日暂无达到入库标准的新线索。")
        return "\n".join(lines)

    lines.append("### 今日重点线索")
    for i, item in enumerate(today_items[:8], 1):
        labels = "、".join(item.get("risk_labels", [])) or "待判断"
        brand_text = "、".join(item.get("brand_hits", [])) or "未命中重点品牌"
        title = truncate(item.get("title", ""), 58)
        lines.append(f"**{i}. {title}**")
        lines.append(f"> 风险类型：{labels}｜分数：{item.get('score', 0)}")
        lines.append(f"> 命中品牌：{brand_text}")
        lines.append(f"> 律师关注：{item.get('lawyer_view', '建议复核原文后判断法律风险。')}")
        if item.get("url"):
            lines.append(f"[查看原文]({item['url']})")
        lines.append("")

    lines.append("### 今日可输出观点")
    if punishment:
        lines.append("- 监管处罚仍集中在商业特许经营备案、招商宣传、加盟资质和信息披露等环节。")
    if contract:
        lines.append("- 加盟合同纠纷线索可重点关注退费、解除合同、虚假宣传和冷静期争议。")
    if brands:
        lines.append("- 命中 TOP300 或重点连锁品牌时，建议同步检查同业客户的招商材料、备案状态和合同模板。")
    lines.append("_本简报为自动线索汇总，不构成正式法律意见；对外引用前请复核原文。_")
    return "\n".join(lines)


def send_daily_summary():
    items = load_daily_findings()
    content = build_daily_summary_message(items)
    ok = post_markdown_to_wecom(content)
    logger.info("每日汇总推送完成" if ok else "每日汇总推送失败")
    return ok


def fetch_all_sources() -> list:
    raw = []
    raw.extend(fetch_search_sources())
    raw.extend(fetch_direct_sources())
    return dedupe_articles(raw)


def enrich_and_filter(raw_articles: list, history: set) -> list:
    candidates = []
    detail_limit = int(CONFIG.get("detail_fetch_limit_per_round", 20))
    should_fetch_detail = bool(CONFIG.get("fetch_article_detail", True))
    detail_count = 0

    for art in raw_articles:
        if art["_id"] in history or art.get("_title_id") in history:
            continue

        score_article(art)

        # 第一轮分数偏低但标题像处罚/判决/特许经营时，补抓正文再评分。
        text = f"{art.get('title', '')} {art.get('summary', '')}"
        worth_detail = any(x in text for x in ["处罚", "判决", "特许经营", "加盟", "备案", "退费"])
        if should_fetch_detail and detail_count < detail_limit and worth_detail:
            detail = fetch_article_detail(art)
            if detail:
                art["detail"] = detail
                score_article(art)
                detail_count += 1
                time.sleep(0.8)

        attach_publish_date(art)
        if not is_recent_article(art):
            logger.info(f"跳过非最新内容：{art.get('_freshness_reason')}｜{art.get('title')}")
            continue

        if is_relevant(art):
            candidates.append(art)

    candidates.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return candidates


def run_once():
    logger.info("=" * 60)
    logger.info("开始新一轮特许经营法律风险监控")
    history = load_history()

    raw_articles = fetch_all_sources()
    logger.info(f"抓取原始内容：{len(raw_articles)} 条")

    new_articles = enrich_and_filter(raw_articles, history)
    logger.info(f"筛选后相关内容：{len(new_articles)} 条")

    max_push = int(CONFIG.get("max_push_per_round", 10))
    to_push = new_articles[:max_push]

    if to_push:
        push_ok = push_to_wecom(to_push)
        if push_ok:
            append_daily_findings(to_push)
            # 只把真正推送成功的内容写入历史，避免“没推送但被标记已读”。
            for art in to_push:
                history.add(art["_id"])
                history.add(art.get("_title_id"))
            save_history(history)
        else:
            logger.warning("本轮推送未成功，暂不写入已推送历史。")
    else:
        logger.info("本轮没有达到推送标准的新内容。")

    logger.info("本轮完成")


def main():
    print("=" * 60)
    print("特许经营法律风险情报监控")
    print("=" * 60)
    print(f"配置文件：{CONFIG_FILE}")
    print(f"抓取间隔：每 {CONFIG.get('fetch_interval_minutes')} 分钟")
    print(f"最低推送分数：{CONFIG.get('min_relevance_score')}")
    print(f"重点品牌数：{len(get_all_brands())}")
    print(f"企业微信：{'已配置' if CONFIG.get('wecom_webhook') else '未配置，只预览不推送'}")
    print("=" * 60)

    if "--daily-summary" in sys.argv:
        send_daily_summary()
        logger.info("每日汇总模式已完成，程序退出。")
        return

    run_once()

    if "--once" in sys.argv:
        logger.info("一次性运行模式已完成，程序退出。")
        return

    interval = int(CONFIG.get("fetch_interval_minutes", 30))
    schedule.every(interval).minutes.do(run_once)
    logger.info(f"定时任务已启动：每 {interval} 分钟执行一次")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("用户停止程序")


if __name__ == "__main__":
    main()
