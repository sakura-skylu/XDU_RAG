from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse


NAVIGATION_PHRASES = {
    "书记信箱",
    "校长信箱",
    "学生邮件",
    "教工邮件",
    "一网通办",
    "信息公开",
    "综合信息网",
    "教师主页",
    "学校概况",
    "机构设置",
    "教育教学",
    "合作交流",
    "招生就业",
    "办学资源",
    "查看更多",
    "常用系统",
    "访问量",
    "官方微博",
    "校园网流量",
    "学院概况",
    "要闻速递",
    "讲座报告",
    "通知 公告",
    "专题推荐",
}

HOME_PAGE_TITLES = {
    "西安电子科技大学",
    "西安电子科技大学新闻网",
    "西安电子科技大学本科招生信息网",
}

HOME_PAGE_PATHS = {"", "/", "/index.html", "/index.htm", "/index.jsp", "/index.php"}


def navigation_noise_score(text: str) -> float:
    clean = " ".join(text.split())
    if not clean:
        return 1.0

    nav_hits = sum(1 for phrase in NAVIGATION_PHRASES if phrase in clean)
    units = [unit for unit in re.split(r"\s+", clean) if unit]
    repeated_units = sum(count - 1 for count in Counter(units).values() if count > 1)
    sentence_marks = sum(clean.count(mark) for mark in "。！？；：")

    score = 0.0
    if nav_hits >= 4:
        score += 0.35
    if nav_hits >= 8:
        score += 0.25
    if units and repeated_units / len(units) > 0.18:
        score += 0.2
    if len(clean) > 350 and sentence_marks <= 2:
        score += 0.25
    if nav_hits >= 4 and sentence_marks <= 1:
        score += 0.3
    if nav_hits >= 3 and ("查看更多" in clean or "更多" in clean):
        score += 0.2
    return min(score, 1.0)


def _is_homepage_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return path in HOME_PAGE_PATHS


def is_navigation_index_page(title: str, content: str, url: str = "") -> bool:
    clean_title = " ".join(title.split())
    clean_content = " ".join(content.split())
    score = navigation_noise_score(clean_content)

    if score >= 0.95:
        return True

    if clean_title in HOME_PAGE_TITLES and (_is_homepage_url(url) or len(clean_content) >= 1000):
        return True

    return False
