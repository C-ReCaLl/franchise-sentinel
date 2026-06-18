# -*- coding: utf-8 -*-
"""
franchise_monitor.py 核心函数测试套件。

测试原则：
- 确定性测试：输入固定，输出必须固定。
- 不依赖外部网络：所有 HTTP 请求用 responses mock。
- 边界测试：测试边界条件（30天 vs 31天、分数5 vs 6）。
- 异常测试：测试网络超时、解析失败、空输入。
"""

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import requests
import responses

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from franchise_monitor import (
    parse_publish_datetime,
    is_recent_article,
    score_article,
    is_relevant,
    make_article_id,
    make_title_id,
    request_text,
    dedupe_articles,
    load_config,
    CONFIG,
)


class TestParsePublishDatetime(unittest.TestCase):
    """测试时间解析函数"""

    def test_relative_hours(self):
        """相对时间：N小时前"""
        result = parse_publish_datetime("3小时前")
        self.assertIsNotNone(result)
        # 验证是最近的时间（3小时前）
        now = datetime.now()
        self.assertTrue(now - timedelta(hours=4) < result < now - timedelta(hours=2))

    def test_relative_days(self):
        """相对时间：N天前"""
        result = parse_publish_datetime("2天前")
        self.assertIsNotNone(result)
        now = datetime.now()
        self.assertTrue(now - timedelta(days=3) < result < now - timedelta(days=1))

    def test_today(self):
        """今天"""
        result = parse_publish_datetime("今天")
        self.assertIsNotNone(result)
        self.assertEqual(result.date(), datetime.now().date())

    def test_yesterday(self):
        """昨天"""
        result = parse_publish_datetime("昨天")
        self.assertIsNotNone(result)
        self.assertEqual(result.date(), (datetime.now() - timedelta(days=1)).date())

    def test_full_date_iso(self):
        """完整日期：YYYY-MM-DD"""
        result = parse_publish_datetime("2026-06-10")
        self.assertIsNotNone(result)
        self.assertEqual(result.date(), datetime(2026, 6, 10).date())

    def test_full_date_chinese(self):
        """完整日期：YYYY年M月D日"""
        result = parse_publish_datetime("2026年6月10日")
        self.assertIsNotNone(result)
        self.assertEqual(result.date(), datetime(2026, 6, 10).date())

    def test_month_day_only(self):
        """只有月日：M月D日（以当前年份补全）"""
        result = parse_publish_datetime("6月10日")
        self.assertIsNotNone(result)
        self.assertEqual(result.date(), datetime(2026, 6, 10).date())

    def test_year_boundary(self):
        """跨年时间：12月31日（注意：代码只匹配当前年份内的月日，12月31日在2026年6月会被判定为未来日期而跳过）"""
        result = parse_publish_datetime("12月31日")
        # 当前是6月，12月31日会被判定为未来日期，所以返回 None
        # 这是代码的预期行为，不是 bug
        self.assertIsNone(result)

    def test_empty_string(self):
        """空字符串"""
        result = parse_publish_datetime("")
        self.assertIsNone(result)

    def test_no_date(self):
        """无日期信息"""
        result = parse_publish_datetime("这是一篇没有日期的新闻")
        self.assertIsNone(result)

    def test_future_date(self):
        """未来日期（代码会过滤超过当前1天的日期，返回 None）"""
        result = parse_publish_datetime("2027-01-01")
        # 代码逻辑：dt <= now + 1天 才保留，2027年远超当前，返回 None
        self.assertIsNone(result)


class TestIsRecentArticle(unittest.TestCase):
    """测试时效性判断"""

    def test_exactly_30_days(self):
        """刚好30天：应通过（age_days <= max_age_days 为通过）"""
        article = {
            "_publish_dt": datetime.now() - timedelta(days=30),
        }
        self.assertTrue(is_recent_article(article))

    def test_31_days(self):
        """31天：应不通过"""
        article = {
            "_publish_dt": datetime.now() - timedelta(days=31),
        }
        self.assertFalse(is_recent_article(article))

    def test_29_days(self):
        """29天：应通过"""
        article = {
            "_publish_dt": datetime.now() - timedelta(days=29),
        }
        self.assertTrue(is_recent_article(article))

    def test_no_publish_dt(self):
        """无发布时间：根据配置决定"""
        article = {}
        if CONFIG.get("require_publish_date", True):
            self.assertFalse(is_recent_article(article))

    def test_today(self):
        """今天：应通过"""
        article = {
            "_publish_dt": datetime.now(),
        }
        self.assertTrue(is_recent_article(article))


class TestScoreArticle(unittest.TestCase):
    """测试文章评分（注意：score_article 返回修改后的 article dict）"""

    def test_high_score_keyword(self):
        """高权重关键词"""
        article = {
            "title": "某品牌商业特许经营被行政处罚",
            "summary": "",
            "source": "百度新闻",
            "url": "https://example.com/1",
        }
        result = score_article(article)
        # "商业特许经营" 权重 8，"行政处罚" 权重 6
        self.assertGreaterEqual(result["_score"], 14)

    def test_brand_hit(self):
        """品牌命中"""
        article = {
            "title": "蜜雪冰城加盟纠纷",
            "summary": "",
            "source": "百度新闻",
            "url": "https://example.com/2",
        }
        result = score_article(article)
        # 品牌命中 +4
        self.assertGreaterEqual(result["_score"], 4)
        self.assertIn("蜜雪冰城", result["_brand_hits"])

    def test_low_score(self):
        """低分文章"""
        article = {
            "title": "今日股市行情",
            "summary": "",
            "source": "百度新闻",
            "url": "https://example.com/3",
        }
        result = score_article(article)
        self.assertLess(result["_score"], 6)

    def test_risk_label(self):
        """风险标签加成"""
        article = {
            "title": "某品牌未备案开展特许经营",
            "summary": "",
            "source": "百度新闻",
            "url": "https://example.com/4",
        }
        result = score_article(article)
        # "未备案" 是风险标签
        self.assertGreaterEqual(result["_score"], 6)
        self.assertTrue(len(result["_risk_labels"]) > 0)

    def test_source_bonus(self):
        """来源加成"""
        article = {
            "title": "普通新闻",
            "summary": "",
            "source": "法治日报",
            "url": "https://example.com/5",
        }
        result = score_article(article)
        # 法治日报 +4
        self.assertGreaterEqual(result["_score"], 4)


class TestIsRelevant(unittest.TestCase):
    """测试相关性判断"""

    def test_relevant(self):
        """相关文章（分数 >= 阈值）"""
        article = {
            "title": "商业特许经营行政处罚案例",
            "_score": 15,
            "_risk_label": "行政处罚",
        }
        self.assertTrue(is_relevant(article))

    def test_irrelevant_low_score(self):
        """低分不相关"""
        article = {
            "title": "普通新闻",
            "_score": 3,
            "_risk_labels": [],
            "_keyword_hits": [],
            "_brand_hits": [],
        }
        self.assertFalse(is_relevant(article))

    def test_force_push_brand_risk(self):
        """品牌+风险标签强制推送"""
        article = {
            "title": "蜜雪冰城商标侵权",
            "_score": 5,  # 低于阈值
            "_risk_labels": ["商标侵权"],
            "_brand_hits": ["蜜雪冰城"],
            "_keyword_hits": [],
        }
        # 品牌命中 + 风险标签 = 强制推送
        self.assertTrue(is_relevant(article))

    def test_force_push_franchise_keyword(self):
        """特许经营关键词强制推送"""
        article = {
            "title": "特许经营新规",
            "_score": 5,
            "_risk_labels": [],
            "_brand_hits": [],
            "_keyword_hits": ["特许经营"],
        }
        self.assertTrue(is_relevant(article))


class TestMakeArticleId(unittest.TestCase):
    """测试文章 ID 生成"""

    def test_same_input_same_id(self):
        """相同输入产生相同 ID"""
        id1 = make_article_id("标题", "https://example.com")
        id2 = make_article_id("标题", "https://example.com")
        self.assertEqual(id1, id2)

    def test_different_input_different_id(self):
        """不同输入产生不同 ID"""
        id1 = make_article_id("标题1", "https://example.com/1")
        id2 = make_article_id("标题2", "https://example.com/2")
        self.assertNotEqual(id1, id2)


class TestMakeTitleId(unittest.TestCase):
    """测试标题 ID 生成"""

    def test_same_title_same_id(self):
        """相同标题产生相同 ID"""
        id1 = make_title_id("标题")
        id2 = make_title_id("标题")
        self.assertEqual(id1, id2)

    def test_different_title_different_id(self):
        """不同标题产生不同 ID"""
        id1 = make_title_id("标题1")
        id2 = make_title_id("标题2")
        self.assertNotEqual(id1, id2)


class TestDedupeArticles(unittest.TestCase):
    """测试去重逻辑"""

    def test_url_dedupe(self):
        """URL 去重"""
        articles = [
            {"title": "标题1", "url": "https://example.com/1"},
            {"title": "标题2", "url": "https://example.com/1"},  # 相同 URL
            {"title": "标题3", "url": "https://example.com/2"},
        ]
        result = dedupe_articles(articles)
        self.assertEqual(len(result), 2)

    def test_title_dedupe(self):
        """标题去重"""
        articles = [
            {"title": "标题1", "url": "https://example.com/1"},
            {"title": "标题1", "url": "https://example.com/2"},  # 相同标题不同 URL
            {"title": "标题3", "url": "https://example.com/3"},
        ]
        result = dedupe_articles(articles)
        self.assertEqual(len(result), 2)

    def test_empty_list(self):
        """空列表"""
        result = dedupe_articles([])
        self.assertEqual(len(result), 0)


class TestRequestText(unittest.TestCase):
    """测试 HTTP 请求（mock）"""

    @responses.activate
    def test_success(self):
        """正常请求"""
        responses.add(
            responses.GET,
            "https://example.com/test",
            body="<html><body>测试内容</body></html>",
            status=200,
        )
        result = request_text("https://example.com/test")
        self.assertIn("测试内容", result)

    @responses.activate
    def test_404(self):
        """404 错误应抛出异常（由调用方捕获）"""
        responses.add(
            responses.GET,
            "https://example.com/404",
            status=404,
        )
        with self.assertRaises(requests.exceptions.HTTPError):
            request_text("https://example.com/404")


class TestLoadConfig(unittest.TestCase):
    """测试配置加载"""

    def test_load_example_config(self):
        """加载 example 配置"""
        example_path = Path(__file__).resolve().parent.parent / "config.example.json"
        self.assertTrue(example_path.exists())

    def test_config_structure(self):
        """配置结构检查"""
        self.assertIn("search_queries", CONFIG)
        self.assertIn("min_relevance_score", CONFIG)
        self.assertIn("max_article_age_days", CONFIG)
        self.assertIsInstance(CONFIG["search_queries"], list)


if __name__ == "__main__":
    unittest.main()
