import os
import json
import re
import sys
import time
import configparser
from datetime import datetime, timezone

import requests

# ─── 配置加载 ──────────────────────────────────────────────────────────────

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(os.path.dirname(__file__), "config.ini"))
    return cfg

CONFIG = load_config()

GITHUB_TOKEN = CONFIG.get("GitHub", "token", fallback="") or os.environ.get("GITHUB_TOKEN", "")

REDDIT_CLIENT_ID = CONFIG.get("Reddit", "client_id", fallback="") or os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = CONFIG.get("Reddit", "client_secret", fallback="") or os.environ.get("REDDIT_CLIENT_SECRET", "")

PROXY_HTTP = CONFIG.get("Proxy", "http", fallback="") or os.environ.get("HTTP_PROXY", "")
PROXY_HTTPS = CONFIG.get("Proxy", "https", fallback="") or os.environ.get("HTTPS_PROXY", "")

LLM_API_KEY = CONFIG.get("LLM", "api_key", fallback="") or os.environ.get("LLM_API_KEY", "")
LLM_API_BASE = CONFIG.get("LLM", "api_base", fallback="") or os.environ.get("LLM_API_BASE", "")
LLM_MODEL = CONFIG.get("LLM", "model", fallback="") or os.environ.get("LLM_MODEL", "") or "gpt-4o-mini"

LLM_BATCH_SIZE = 8

PROVIDER_HEADERS = {
    "openrouter": {
        "HTTP-Referer": "https://github.com/hkl/agent-sec-monitor",
        "X-OpenRouter-Title": "agent-sec-monitor",
    },
    "xai": {
        "HTTP-Referer": "https://github.com/hkl/agent-sec-monitor",
    },
}


def detect_provider(base_url):
    url = base_url.lower()
    if "openrouter.ai" in url:
        return "openrouter"
    if "api.openai.com" in url:
        return "openai"
    if "api.deepseek.com" in url:
        return "deepseek"
    if "api.groq.com" in url:
        return "groq"
    if "api.mistral.ai" in url:
        return "mistral"
    if "api.x.ai" in url:
        return "xai"
    if "open.bigmodel.cn" in url or "bigmodel" in url:
        return "zhipu"
    if "dashscope.aliyuncs.com" in url:
        return "qwen"
    if "api.moonshot.cn" in url:
        return "kimi"
    if ":11434" in url:
        return "ollama"
    return "openai-compatible"


def get_llm_headers():
    provider = detect_provider(LLM_API_BASE or "https://api.openai.com/v1")
    extra = PROVIDER_HEADERS.get(provider, {})
    return {**extra, "Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}

# ─── 爬虫目标 ──────────────────────────────────────────────────────────────

TARGET_REPOS = [
    "anthropics/claude-code",       # Claude Code 官方
    "openclaw/openclaw",            # OpenClaw 官方（327k stars，大量 CVE）
    "jgamblin/OpenClawCVEs",        # 第三方 OpenClaw CVE 聚合器（137个安全公告）
    "cline/cline",                  # Cline（前 Claude Dev）
    "Aider-AI/aider",               # Aider
    "continuedev/continue",         # Continue
    "TabbyML/tabby",                # TabbyML
    "anomalyco/opencode",           # OpenCode（61k+ stars，CVE-2026-22812 未认证RCE）
    "NousResearch/hermes-agent",    # Hermes Agent（43k+ stars，自我进化AI框架）
    "zeroclaw-labs/zeroclaw",       # ZeroClaw（31k+ stars，Rust 实现轻量AI助手）
    "nanocoai/nanoclaw",            # NanoClaw（28k+ stars，容器隔离安全版OpenClaw替代）
    "HKUDS/nanobot",                # NanoBot（42k+ stars，超轻量Python AI Agent 仅4k行）
    "sipeed/picoclaw",              # PicoClaw（28k+ stars，Go实现 <10MB内存 $10硬件）
    "nearai/ironclaw",              # IronClaw（12k+ stars，Rust WASM沙盒 隐私优先Agent OS）
]

CLOSED_SOURCE_TOOLS = ["Cursor", "Windsurf", "Copilot", "Devin"]

SECURITY_LABELS = ["security", "vulnerability", "sandbox", "exploit", "rce", "injection"]

REDDIT_SUBREDDITS = ["ClaudeAI", "cursor", "ChatGPTCoding", "LocalLLaMA"]

REDDIT_KEYWORDS = [
    "security vulnerability", "prompt injection", "supply chain attack",
]

HN_KEYWORDS = [
    "AI agent security vulnerability",
    "claude code cursor sandbox exploit",
    "coding agent prompt injection RCE",
    "opencode security vulnerability CVE",
    "hermes agent security exploit",
    "openclaw security vulnerability zeroclaw nanoclaw",
    "nanobot picoclaw ironclaw AI agent exploit",
]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "agent-sec-monitor/1.0",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

PROXIES = {}
if PROXY_HTTP:
    PROXIES["http"] = PROXY_HTTP
if PROXY_HTTPS:
    PROXIES["https"] = PROXY_HTTPS

DATA_DIR = "data"
NOW = datetime.now(timezone.utc)
TODAY_STR = NOW.strftime("%Y-%m-%d")
TIMESTAMP = NOW.isoformat()

# 共享 Session（连接复用，大幅加快请求速度）
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
if PROXIES:
    SESSION.proxies.update(PROXIES)
SESSION.headers.update({"Connection": "keep-alive"})


# ─── 工具函数 ─────────────────────────────────────────────────────────────

def safe_get(url, params=None, headers=None, timeout=10, source_name=""):
    try:
        h = {}
        if headers:
            h.update(headers)
        resp = SESSION.get(url, params=params, headers=h or None, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        print(f"  [!] {source_name}: 返回非 JSON 内容 (status={resp.status_code})")
        return None
    except requests.exceptions.Timeout:
        print(f"  [!] {source_name}: 请求超时 ({url[:60]}...)")
        return None
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 403:
            print(f"  [!] {source_name}: 403 — 可能触发限流")
        elif resp.status_code == 429:
            print(f"  [!] {source_name}: 429 — 限流，等待 3s")
            time.sleep(3)
        else:
            print(f"  [!] {source_name}: HTTP {resp.status_code}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  [!] {source_name}: 连接失败")
        return None
    except Exception as e:
        print(f"  [!] {source_name}: 错误 — {e}")
        return None


def safe_post(url, json_body, headers=None, timeout=10, source_name=""):
    try:
        h = {}
        if headers:
            h.update(headers)
        resp = SESSION.post(url, json=json_body, headers=h or None, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.JSONDecodeError:
        print(f"  [!] {source_name}: 返回非 JSON (status={resp.status_code})")
        return None
    except requests.exceptions.Timeout:
        print(f"  [!] {source_name}: 超时")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"  [!] {source_name}: HTTP {resp.status_code}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"  [!] {source_name}: 连接失败")
        return None
    except Exception as e:
        print(f"  [!] {source_name}: 错误 — {e}")
        return None


def detect_product(text, repo=""):
    text_lower = (text + " " + repo).lower()
    if "claude" in text_lower or "anthropics/claude" in repo:
        return "Claude Code"
    if "openclaw" in text_lower or "openclaw/openclaw" in repo:
        return "OpenClaw"
    if "openclawcve" in text_lower or "jgamblin/openclawcves" in repo:
        return "OpenClaw (CVE Tracker)"
    if "cline" in text_lower or "cline/cline" in repo:
        return "Cline"
    if "aider" in text_lower or "aider-ai/aider" in repo:
        return "Aider"
    if "continue" in text_lower or "continuedev/continue" in repo:
        return "Continue"
    if "tabby" in text_lower or "tabbyml/tabby" in repo:
        return "TabbyML"
    if "opencode" in text_lower or "anomalyco/opencode" in repo:
        return "OpenCode"
    if "hermes" in text_lower or "nousresearch/hermes-agent" in repo:
        return "Hermes Agent"
    if "zeroclaw" in text_lower or "zeroclaw-labs/zeroclaw" in repo:
        return "ZeroClaw"
    if "nanoclaw" in text_lower or "nanocoai/nanoclaw" in repo:
        return "NanoClaw"
    if "nanobot" in text_lower or "hkuds/nanobot" in repo:
        return "NanoBot"
    if "picoclaw" in text_lower or "sipeed/picoclaw" in repo:
        return "PicoClaw"
    if "ironclaw" in text_lower or "nearai/ironclaw" in repo:
        return "IronClaw"
    if "cursor" in text_lower:
        return "Cursor"
    if "windsurf" in text_lower:
        return "Windsurf"
    if "copilot" in text_lower or "github copilot" in text_lower:
        return "Copilot"
    if "devin" in text_lower:
        return "Devin"
    return "通用AI编程工具"


def classify_type(title, body_text):
    t = (title + " " + body_text).lower()
    types = []
    if any(w in t for w in ["sandbox escape", "sandbox_bypass", "沙箱逃逸", "sandbox bypass", "breakout"]):
        types.append("沙箱逃逸")
    if any(w in t for w in ["prompt injection", "提示注入", "jailbreak", "prompt injection"]):
        types.append("提示注入")
    if any(w in t for w in ["supply chain", "供应链攻击", "dependency confusion", "malicious package",
                             "typosquatting"]):
        types.append("供应链攻击")
    if any(w in t for w in ["privilege escalation", "权限绕过", "auth bypass", "authorization bypass",
                             "permission bypass", "acl bypass"]):
        types.append("权限绕过")
    if any(w in t for w in ["rce", "remote code execution", "远程代码执行", "arbitrary code execution",
                             "code injection", "command injection"]):
        types.append("远程代码执行")
    if any(w in t for w in ["information disclosure", "信息泄露", "data leak", "data exposure",
                             "information exposure", "信息泄漏"]):
        types.append("信息泄露")
    if any(w in t for w in ["not fixed", "unpatched", "未修复", "open issue", "unresolved",
                             "unfixed"]):
        types.append("未修复")
    if any(w in t for w in ["fixed", "patched", "已修复", "resolved", "closed", "fix",
                             "patch", "mitigated"]):
        types.append("已修复")
    if not types:
        if any(w in t for w in ["security", "vulnerability", "cve", "exploit", "advisory"]):
            types.append("未修复")
        else:
            types.append("未修复")
    return types


def classify_level(title, body_text, labels=None):
    t = (title + " " + body_text).lower()
    label_set = {l.lower() for l in (labels or [])}

    critical_signals = ["critical", "严重", "cve-", "rce", "remote code execution",
                        "cvss 9", "cvss 10", "zero-click", "0-click", "wormable"]
    high_signals = ["high", "高危", "privilege escalation", "sandbox escape",
                    "arbitrary code", "authentication bypass"]
    medium_signals = ["medium", "中危", "xss", "csrf", "dos", "information disclosure",
                      "path traversal", "ssrf"]
    low_signals = ["low", "低危", "minor", "cosmetic"]

    if any(w in label_set for w in ["critical", "severity/critical"]):
        return "严重"
    if any(w in label_set for w in ["high", "severity/high"]):
        return "高危"

    for s in critical_signals:
        if s in t:
            return "严重"
    for s in high_signals:
        if s in t:
            return "高危"
    for s in medium_signals:
        if s in t:
            return "中危"
    for s in low_signals:
        if s in t:
            return "低危"
    return "高危"


def is_relevant(item_text):
    t = item_text.lower()
    positive_signals = [
        "security", "vulnerability", "cve", "exploit", "advisory",
        "sandbox", "injection", "rce", "escape", "bypass",
        "malicious", "supply chain", "privilege escalation",
        "information disclosure", "arbitrary code", "patch",
        "fixed in", "披露", "漏洞", "安全", "攻击",
    ]
    return any(s in t for s in positive_signals)


def extract_cve(text):
    return re.findall(r"CVE-\d{4}-\d{4,7}", text, re.IGNORECASE)


# ─── 爬虫模块 ─────────────────────────────────────────────────────────────

def crawl_github_issues():
    items = []
    print("[GitHub Issues] 开始爬取目标仓库的 Issue...")
    base_url = "https://api.github.com/search/issues"

    for repo in TARGET_REPOS:
        # 批量搜索：将所有安全标签合并为一个查询，避免逐标签搜索耗尽限额
        labels_query = " OR ".join(f"label:{l}" for l in SECURITY_LABELS)
        query = f"repo:{repo} ({labels_query}) state:open"
        print(f"  -> 批量标签搜索: {repo}")
        data = safe_get(base_url, params={"q": query, "per_page": 30, "sort": "updated"},
                        source_name=f"GitHub Issues/{repo}/batch")

        if data:
            for issue in data.get("items", []):
                url = issue.get("html_url", "")
                title = issue.get("title", "")
                body = issue.get("body") or ""
                labels = [lb["name"] for lb in issue.get("labels", [])]

                combined = title + " " + body
                if not is_relevant(combined):
                    continue

                items.append({
                    "title": title,
                    "url": url,
                    "desc": body[:500] + "..." if len(body) > 500 else body,
                    "source": "GitHub Issues",
                    "repo": repo,
                    "product": detect_product(combined, repo),
                    "type": classify_type(title, body),
                    "level": classify_level(title, body, labels),
                    "cve": extract_cve(combined),
                    "labels": labels,
                    "created_at": issue.get("created_at", ""),
                    "updated_at": issue.get("updated_at", ""),
                    "state": issue.get("state", ""),
                })

        # 补充搜索标题中含 security 的 Issue
        query_title = f"repo:{repo} security in:title state:open"
        print(f"  -> 标题搜索: {repo}")
        data = safe_get(base_url, params={"q": query_title, "per_page": 20, "sort": "updated"},
                        source_name=f"GitHub Issues/{repo}/title")
        if data:
            for issue in data.get("items", []):
                url = issue.get("html_url", "")
                if any(it["url"] == url for it in items):
                    continue
                title = issue.get("title", "")
                body = issue.get("body") or ""
                labels = [lb["name"] for lb in issue.get("labels", [])]
                combined = title + " " + body
                if not is_relevant(combined):
                    continue
                items.append({
                    "title": title,
                    "url": url,
                    "desc": body[:500] + "..." if len(body) > 500 else body,
                    "source": "GitHub Issues",
                    "repo": repo,
                    "product": detect_product(combined, repo),
                    "type": classify_type(title, body),
                    "level": classify_level(title, body, labels),
                    "cve": extract_cve(combined),
                    "labels": labels,
                    "created_at": issue.get("created_at", ""),
                    "updated_at": issue.get("updated_at", ""),
                    "state": issue.get("state", ""),
                })

    print(f"  [OK] GitHub Issues: {len(items)} 条")
    return items


def crawl_github_security_advisories():
    items = []
    print("[GitHub Advisories] 开始爬取 GitHub Security Advisories...")

    data = safe_get("https://api.github.com/advisories",
                    params={"per_page": 100, "type": "reviewed"},
                    source_name="GitHub Advisories")
    if not data:
        print("  [!] GitHub Advisories API 返回空或失败")
        return items

    for adv in data:
        repo_name = adv.get("repository", {}).get("full_name", "") if adv.get("repository") else ""
        github_id = adv.get("ghsa_id", "")
        title = adv.get("summary", "") or adv.get("description", "") or ""
        body = adv.get("description", "") or ""
        url = adv.get("html_url", "") or adv.get("url", "")
        severity = adv.get("severity", "")
        cve_id = adv.get("cve_id", "") or ""
        published = adv.get("published_at", "")
        updated = adv.get("updated_at", "")

        identifiers = [id["value"] for id in adv.get("identifiers", []) if id.get("type") == "CVE"]
        cves = identifiers if identifiers else ([cve_id] if cve_id else [])

        combined = title + " " + body + " " + json.dumps(adv.get("vulnerabilities", []))
        product = detect_product(combined, repo_name)

        is_agent_repo = any(r in repo_name for r in TARGET_REPOS)
        is_agent_tool = any(t.lower() in combined.lower() for t in CLOSED_SOURCE_TOOLS + ["claude", "cline", "aider", "continue", "opencode", "tabby", "hermes", "zeroclaw", "nanoclaw", "nanobot", "picoclaw", "ironclaw"])

        if not is_agent_repo and not is_agent_tool:
            continue

        if not is_relevant(title + " " + body):
            continue

        level_map = {"critical": "严重", "high": "高危", "medium": "中危", "low": "低危"}
        level = level_map.get(severity.lower(), classify_level(title, body))

        items.append({
            "title": f"[GHSA] {title[:100]}",
            "url": url,
            "desc": body[:500] + "..." if len(body) > 500 else body,
            "source": "GitHub Security Advisory",
            "repo": repo_name or "unknown",
            "product": product,
            "type": classify_type(title, body) if not cves else ["已修复"],
            "level": level,
            "cve": cves,
            "ghsa_id": github_id,
            "severity": severity,
            "created_at": published,
            "updated_at": updated,
        })

    print(f"  [OK] GitHub Advisories: {len(items)} 条")
    return items


def crawl_osv():
    items = []
    print("[OSV.dev] 开始查询 OSV.dev 漏洞数据库...")

    # 只查已知存在的包名 + 生态系统组合，避免大量无效查询
    package_queries = [
        ("npm", "cline"),
        ("npm", "@cline/cline"),
        ("PyPI", "aider-chat"),
        ("npm", "aider"),
        ("npm", "continue"),
        ("npm", "@continuedev/continue"),
        ("npm", "opencode"),
        ("PyPI", "opencode"),
        ("Go", "github.com/anomalyco/opencode"),
        ("npm", "tabby"),
        ("Go", "github.com/TabbyML/tabby"),
        ("PyPI", "hermes-agent"),
        ("npm", "hermes-agent"),
        ("Go", "github.com/NousResearch/hermes-agent"),
        ("npm", "zeroclaw"),
        ("Go", "github.com/zeroclaw-labs/zeroclaw"),
        ("npm", "nanoclaw"),
        ("Go", "github.com/nanocoai/nanoclaw"),
        ("npm", "nanobot"),
        ("PyPI", "nanobot"),
        ("Go", "github.com/HKUDS/nanobot"),
        ("Go", "github.com/sipeed/picoclaw"),
        ("Go", "github.com/nearai/ironclaw"),
    ]

    for ecosystem, pkg in package_queries:
            print(f"  -> 查询: ecosystem={ecosystem}, package={pkg}")
            data = safe_post("https://api.osv.dev/v1/query",
                             json_body={"package": {"name": pkg, "ecosystem": ecosystem}},
                             source_name=f"OSV/{ecosystem}/{pkg}")
            if not data:
                continue
            vulns = data.get("vulns", [])
            for vuln in vulns:
                vuln_id = vuln.get("id", "")
                summary = vuln.get("summary", "") or vuln.get("details", "") or ""
                aliases = vuln.get("aliases", [])
                cves = [a for a in aliases if a.startswith("CVE-")]
                url = f"https://osv.dev/vulnerability/{vuln_id}"
                modified = vuln.get("modified", "")
                database_specific = vuln.get("database_specific", {}) or {}
                severity_list = vuln.get("severity", []) or []

                combined = summary + " " + json.dumps(aliases)
                if not is_relevant(combined):
                    continue

                level = "高危"
                cvss_score = None
                for sev in severity_list:
                    if "CVSS" in str(sev):
                        match = re.search(r"(\d+\.?\d*)", str(sev))
                        if match:
                            cvss_score = float(match.group(1))
                            if cvss_score >= 9.0:
                                level = "严重"
                            elif cvss_score >= 7.0:
                                level = "高危"
                            elif cvss_score >= 4.0:
                                level = "中危"
                            else:
                                level = "低危"

                items.append({
                    "title": f"[{vuln_id}] {summary[:150]}" if summary else f"[{vuln_id}] {pkg} 安全漏洞",
                    "url": url,
                    "desc": summary[:500] + "..." if len(summary) > 500 else summary,
                    "source": "OSV.dev",
                    "repo": pkg,
                    "product": detect_product(pkg + " " + summary, ""),
                    "type": classify_type(summary, ""),
                    "level": level,
                    "cve": cves,
                    "cvss_score": cvss_score,
                    "osv_id": vuln_id,
                    "aliases": aliases,
                    "created_at": modified,
                    "updated_at": modified,
                })

    print(f"  [OK] OSV.dev: {len(items)} 条")
    return items


def crawl_reddit():
    items = []
    print("[Reddit] 开始爬取 Reddit 子版块...")

    for subreddit in REDDIT_SUBREDDITS:
        for kw in REDDIT_KEYWORDS:
            print(f"  -> r/{subreddit}: \"{kw}\"")
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            data = safe_get(url, params={"q": kw, "restrict_sr": "on", "sort": "new",
                                         "limit": 10, "t": "year"},
                            headers={"User-Agent": "agent-sec-monitor/1.0 (by /u/agent-monitor)"},
                            timeout=6, source_name=f"Reddit/{subreddit}")

            if not data:
                continue

            posts = data.get("data", {}).get("children", [])
            for post in posts:
                post_data = post.get("data", {})
                title = post_data.get("title", "")
                url = post_data.get("url", "") or f"https://www.reddit.com{post_data.get('permalink', '')}"
                selftext = post_data.get("selftext", "") or ""
                score = post_data.get("score", 0)
                num_comments = post_data.get("num_comments", 0)
                created_utc = post_data.get("created_utc", 0)
                created_str = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat() if created_utc else ""

                combined = title + " " + selftext
                if not is_relevant(combined):
                    continue

                items.append({
                    "title": title[:200],
                    "url": url,
                    "desc": selftext[:500] + "..." if len(selftext) > 500 else selftext,
                    "source": f"Reddit/r/{subreddit}",
                    "repo": "",
                    "product": detect_product(combined, ""),
                    "type": classify_type(title, selftext),
                    "level": classify_level(title, selftext),
                    "cve": extract_cve(combined),
                    "reddit_score": score,
                    "num_comments": num_comments,
                    "created_at": created_str,
                    "updated_at": created_str,
                })

    print(f"  [OK] Reddit: {len(items)} 条")
    return items


def crawl_hacker_news():
    items = []
    print("[Hacker News] 开始搜索 Hacker News...")

    for keyword in HN_KEYWORDS:
        print(f"  -> 搜索: \"{keyword}\"")
        data = safe_get("https://hn.algolia.com/api/v1/search",
                        params={"query": keyword, "tags": "story", "hitsPerPage": 20},
                        source_name=f"HN/{keyword[:30]}")

        if not data:
            continue

        for hit in data.get("hits", []):
            title = hit.get("title", "")
            url = hit.get("url") or hit.get("story_url") or ""
            if not url:
                url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            points = hit.get("points", 0)
            num_comments = hit.get("num_comments", 0)
            author = hit.get("author", "")
            created_at = hit.get("created_at", "")
            object_id = hit.get("objectID", "")

            story_text = hit.get("story_text", "") or ""
            comment_text = hit.get("comment_text", "") or ""

            combined = title + " " + story_text + " " + comment_text
            if not is_relevant(combined):
                continue

            items.append({
                "title": title[:200],
                "url": url,
                "desc": (story_text or comment_text)[:500] + "..." if len(story_text or comment_text) > 500 else (story_text or comment_text),
                "source": "Hacker News",
                "repo": "",
                "product": detect_product(combined, ""),
                "type": classify_type(title, story_text + comment_text),
                "level": classify_level(title, story_text + comment_text),
                "cve": extract_cve(combined),
                "hn_id": object_id,
                "hn_points": points,
                "hn_comments": num_comments,
                "hn_author": author,
                "created_at": created_at,
                "updated_at": created_at,
            })

    print(f"  [OK] Hacker News: {len(items)} 条")
    return items


# ─── 去重与汇总 ──────────────────────────────────────────────────────────

def deduplicate(items):
    seen_urls = set()
    seen_titles = set()
    unique = []
    for item in items:
        url = item.get("url", "")
        title = item.get("title", "").strip().lower()
        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        unique.append(item)
    return unique


def build_summary(items):
    by_type = {}
    by_level = {}
    by_product = {}
    by_source = {}

    for item in items:
        for t in item.get("type", []):
            by_type[t] = by_type.get(t, 0) + 1
        lv = item.get("level", "未知")
        by_level[lv] = by_level.get(lv, 0) + 1
        pr = item.get("product", "未知")
        by_product[pr] = by_product.get(pr, 0) + 1
        src = item.get("source", "未知")
        by_source[src] = by_source.get(src, 0) + 1

    return {
        "total": len(items),
        "generated_at": TIMESTAMP,
        "date": TODAY_STR,
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_level": dict(sorted(by_level.items(), key=lambda x: -x[1])),
        "by_product": dict(sorted(by_product.items(), key=lambda x: -x[1])),
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1])),
        "target_repos": TARGET_REPOS,
        "closed_source_tools": CLOSED_SOURCE_TOOLS,
    }


# ─── LLM 智能分析 ────────────────────────────────────────────────────────

LLM_BATCH_SIZE = 4

ANALYSIS_PROMPT = """你是一个 AI 编程代理安全分析专家。请分析以下来自网络的安全条目，判断它们是否真正与 AI 编程代理（如 Claude Code、Cursor、Cline、OpenClaw、Aider 等）的安全漏洞、攻击或风险相关。

条目列表（JSON 格式）：
{items_json}

请严格按照以下 JSON 格式返回分析结果（只返回 JSON，不要其他内容）：
```json
{{
  "results": [
    {{
      "index": 0,
      "is_relevant": true,
      "product": "Claude Code",
      "type": ["提示注入", "沙箱逃逸"],
      "level": "高危",
      "title_cn": "Claude Code /proc/self/root 沙箱路径绕过逃逸",
      "summary_cn": "中文摘要，2-3句话说明安全问题是什么",
      "reproduction": "如果可以复现，描述复现步骤；否则填'暂无'"
    }}
  ]
}}
```

规则：
- is_relevant: 只有真正关于 AI agent 安全漏洞/攻击的才标 true。如果是普通 Show HN 展示帖、工具介绍、非安全相关的 PR，标 false
- product: 从 ["Claude Code", "OpenClaw", "Cline", "Aider", "Continue", "TabbyML", "Cursor", "Windsurf", "Copilot", "Devin", "通用AI编程工具"] 中选择最准确的
- title_cn: 用中文生成一个精炼的标题（≤20字），格式如"产品名 + 漏洞类型 + 关键词"，例如"Claude Code 会话钩子供应链投毒"
- type: 从 ["未修复", "已修复", "沙箱逃逸", "提示注入", "供应链攻击", "权限绕过", "远程代码执行", "信息泄露"] 中选择
- level: 从 ["严重", "高危", "中危", "低危"] 中选择
- summary_cn: 用中文写出安全问题的核心要点
- reproduction: 如果原始内容中包含复现步骤，用中文描述；否则填"暂无"
"""


def analyze_with_llm(items, force=False):
    if not LLM_API_KEY:
        print("\n⚠️  未配置 LLM API Key，跳过智能分析")
        return items

    print(f"\n{'='*60}")
    print(f"  🧠 LLM 智能分析中...")
    print(f"  模型: {LLM_MODEL}")
    print(f"  条目数: {len(items)}")
    print(f"  每批: {LLM_BATCH_SIZE} 条")
    if force:
        print(f"  模式: 强制全量分析")
    else:
        print(f"  模式: 增量（跳过已分析）")

    # 增量模式：过滤出未分析的条目
    new_items = items
    already_done = []
    if not force:
        new_items = []
        for item in items:
            if item.get("llm_summary"):
                already_done.append(item)
            else:
                new_items.append(item)
        if already_done:
            print(f"  已分析: {len(already_done)} 条（跳过）")
            print(f"  待分析: {len(new_items)} 条")

    if not new_items:
        print(f"  ✅ 无需分析")
        return items

    api_base = LLM_API_BASE or "https://api.openai.com/v1"
    url = api_base.rstrip("/") + "/chat/completions"

    total = len(new_items)
    max_retries = 3

    # ── 第一轮：逐批分析 ──
    batch_results = {}
    failed_indices = []
    for batch_start in range(0, total, LLM_BATCH_SIZE):
        batch_end = min(batch_start + LLM_BATCH_SIZE, total)
        batch = new_items[batch_start:batch_end]

        success = _process_batch(url, batch, batch_start, batch_results)
        if success:
            print(f"  [{batch_end}/{total}] 已分析")
        else:
            failed_indices.append(batch_start)

    # ── 重试失败批次 ──
    if failed_indices:
        print(f"\n  ⚠️  {len(failed_indices)} 批失败，开始重试...")
        for retry in range(1, max_retries + 1):
            still_failed = []
            for batch_start in failed_indices:
                wait = 2 ** retry
                print(f"  ↻ 重试批次 {batch_start} (第{retry}次, 等待{wait}s)")
                time.sleep(wait)
                batch_end = min(batch_start + LLM_BATCH_SIZE, total)
                batch = new_items[batch_start:batch_end]

                success = _process_batch(url, batch, batch_start, batch_results)
                if success:
                    print(f"    ✅ 重试成功")
                else:
                    still_failed.append(batch_start)

            failed_indices = still_failed
            if not failed_indices:
                break

    # ── 汇总结果 ──
    analyzed = list(already_done)
    irrelevant_count = 0
    failed_count = 0

    for i in range(total):
        result = batch_results.get(i)
        if result is None:
            analyzed.append(new_items[i])
            failed_count += 1
        elif result.get("is_relevant"):
            item = new_items[i]
            # 产品标签：关键词识别结果优先（基于repo/URL精确匹配），LLM结果仅作为补充
            kw_product = item.get("product", "")
            llm_product = result.get("product", "")
            if kw_product and kw_product != "通用AI编程工具":
                item["product"] = kw_product
            elif llm_product and llm_product != "通用AI编程工具":
                item["product"] = llm_product
            else:
                item["product"] = kw_product or llm_product or "通用AI编程工具"
            item["type"] = result.get("type", item.get("type", []))
            item["level"] = result.get("level", item.get("level", ""))
            item["llm_title"] = result.get("title_cn", "")
            item["llm_summary"] = result.get("summary_cn", "")
            item["llm_reproduction"] = result.get("reproduction", "暂无")
            if result.get("reproduction") and result.get("reproduction") != "暂无":
                if "可复现" not in item["type"]:
                    item["type"].append("可复现")
            analyzed.append(item)
        else:
            irrelevant_count += 1

    if failed_count:
        print(f"  ⚠️  {failed_count} 条分析失败，保留原始分类")
    print(f"  ✅ 分析完成: 保留 {len(analyzed)} 条, 过滤 {irrelevant_count} 条噪声\n")
    return analyzed


def _process_batch(url, batch, batch_start, batch_results):
    batch_info = []
    for local_idx, item in enumerate(batch):
        batch_info.append({
            "index": local_idx,
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("source", ""),
            "desc_preview": (item.get("desc", "") or "")[:600],
        })

    try:
        resp = SESSION.post(
            url,
            headers=get_llm_headers(),
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": ANALYSIS_PROMPT.format(items_json=json.dumps(batch_info, ensure_ascii=False))}],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"]
        if not content:
            return False
        content = content.strip()

        # 处理 reasoning 模型（输出可能包含思考过程前缀）
        if content.startswith("思考"):
            content = content[2:].strip()
        if "</think>\n" in content.lower():
            content = content.split(" response\n", 1)[-1].strip()

        # 提取 JSON（兼容被 markdown 包裹或 reasoning 污染的响应）
        json_content = content
        if "```json" in json_content:
            json_content = json_content.split("```json", 1)[1]
            if "```" in json_content:
                json_content = json_content.split("```", 1)[0]
        elif "```" in json_content:
            json_content = json_content.split("```", 1)[1]
            if "```" in json_content:
                json_content = json_content.split("```", 1)[0]
        elif "{\n  \"results\"" in json_content:
            json_content = json_content[json_content.index("{"):]
            # 找到匹配的结束 }
            brace_count = 0
            end_idx = len(json_content)
            for idx, ch in enumerate(json_content):
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = idx + 1
                        break
            json_content = json_content[:end_idx]
        json_content = json_content.strip()
        analysis = json.loads(json_content)

        for r in analysis.get("results", []):
            global_idx = batch_start + r["index"]
            batch_results[global_idx] = r
        return True

    except requests.exceptions.Timeout:
        return False
    except Exception as e:
        print(f"  [!] 批次 {batch_start} 错误: {e}")
        return False


# ─── 主流程 ──────────────────────────────────────────────────────────────

def crawl_all(force=False):
    print(f"\n{'='*60}")
    print(f"  AI Agent 安全风险监控爬虫")
    print(f"  运行时间: {TIMESTAMP}")
    print(f"  目标仓库: {', '.join(TARGET_REPOS)}")
    print(f"  闭源工具: {', '.join(CLOSED_SOURCE_TOOLS)}")
    print(f"{'─'*60}")
    has_token = bool(GITHUB_TOKEN)
    if has_token:
        print(f"  GitHub Token: ✅ 已设置（30次/分钟，5000次/小时）")
    else:
        print(f"  GitHub Token: ❌ 未设置（仅10次/分钟，建议申请）")
    if PROXIES:
        print(f"  Proxy:        ✅ 已设置")
    print(f"{'─'*60}")
    print(f"  数据源:")
    print(f"    [1] GitHub Issues           搜索 7 个仓库的安全 Issue")
    print(f"    [2] GitHub Advisories       查询官方安全公告")
    print(f"    [3] OSV.dev                 查询开源漏洞数据库")
    print(f"    [4] Hacker News             搜索安全相关新闻")
    print(f"{'='*60}\n")

    all_items = []
    crawlers = [
        ("GitHub Issues", crawl_github_issues),
        ("GitHub Security Advisories", crawl_github_security_advisories),
        ("OSV.dev", crawl_osv),
        ("Hacker News", crawl_hacker_news),
    ]

    for name, crawler_fn in crawlers:
        try:
            print(f"\n>>> [{name}] 开始爬取...")
            t0 = time.time()
            items = crawler_fn()
            elapsed = time.time() - t0
            print(f"<<< [{name}] 完成，获取 {len(items)} 条（耗时 {elapsed:.1f}s）")
            all_items.extend(items)
        except Exception as e:
            print(f"<<< [{name}] 爬取出错（已跳过）: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n>>> 去重前总计: {len(all_items)} 条")
    all_items = deduplicate(all_items)
    print(f">>> 去重后总计: {len(all_items)} 条")

    # 合并今日已有数据（增量模式）
    today_file = os.path.join(DATA_DIR, f"{TODAY_STR}.json")
    if not force and os.path.exists(today_file):
        try:
            with open(today_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_items = existing.get("items", []) if isinstance(existing, dict) else existing
            # 用 URL 去重，合并已有分析结果
            existing_urls = {e.get("url"): e for e in existing_items}
            merged = []
            for item in all_items:
                old = existing_urls.get(item.get("url"))
                if old and old.get("llm_summary"):
                    merged.append(old)
                else:
                    merged.append(item)
            # 保留旧数据中今天没扫到的条目
            new_urls = {m.get("url") for m in merged}
            for old in existing_items:
                if old.get("url") not in new_urls:
                    merged.append(old)
            all_items = merged
            print(f">>> 合并已有数据后: {len(all_items)} 条")
        except Exception as e:
            print(f">>> 合并已有数据失败: {e}")
            force = True

    # LLM 智能分析
    if LLM_API_KEY:
        all_items = analyze_with_llm(all_items, force=force)

    summary = build_summary(all_items)
    output = {
        "summary": summary,
        "items": all_items,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, f"{TODAY_STR}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 同时生成 .js 文件，支持本地 file:// 协议直接打开 HTML
    js_filepath = os.path.join(DATA_DIR, f"{TODAY_STR}.js")
    with open(js_filepath, "w", encoding="utf-8") as f:
        f.write("// 自动生成，请勿手动编辑\n")
        f.write("(function(){ window.__agentSecData = ")
        json.dump(output, f, ensure_ascii=False)
        f.write("; })();\n")

    print(f"\n{'='*60}")
    print(f"  ✅ 数据已保存: {filepath}")
    print(f"  ✅ JS 已生成:  {js_filepath}")
    print(f"  📊 汇总:")
    print(f"     总计: {summary['total']} 条")
    print(f"     类型分布: {summary['by_type']}")
    print(f"     级别分布: {summary['by_level']}")
    print(f"     产品分布: {summary['by_product']}")
    print(f"     来源分布: {summary['by_source']}")
    print(f"{'='*60}\n")

    return output


if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    crawl_all(force=force)