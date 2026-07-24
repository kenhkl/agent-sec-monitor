#!/usr/bin/env python3
"""
Agent 痛点日报 - 每日爬取全网 Agent 真实痛点，排名 Top 10 并深度分析。
输出到 data/YYYY-MM-DD-pain.json，与安全监控数据共存于同一 data/ 目录。
"""

import os, sys, json, re, time, configparser
from datetime import datetime, timezone, timedelta
from collections import Counter
import requests

# ============================================================
# 配置加载（复用 config.ini）
# ============================================================

CONFIG = configparser.ConfigParser()
CONFIG.read("config.ini")

def _cfg(section, key, env_key=None, default=""):
    if env_key and os.getenv(env_key):
        return os.getenv(env_key)
    return CONFIG.get(section, key, fallback=default)

GH_TOKEN = _cfg("GitHub", "token", "GH_PAT")
LLM_API_KEY = _cfg("LLM", "api_key", "LLM_API_KEY")
LLM_API_BASE = _cfg("LLM", "api_base", "LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_MODEL = _cfg("LLM", "model", "LLM_MODEL", "deepseek-chat")
PROXY_HTTP = _cfg("Proxy", "http", "PROXY_HTTP")
PROXY_HTTPS = _cfg("Proxy", "https", "PROXY_HTTPS")

PROXIES = {}
if PROXY_HTTP:
    PROXIES["http"] = PROXY_HTTP
if PROXY_HTTPS:
    PROXIES["https"] = PROXY_HTTPS

# LLM Provider 检测
def detect_provider(api_base):
    ab = api_base.lower()
    if "openrouter" in ab: return "openrouter"
    if "openai" in ab: return "openai"
    if "deepseek" in ab: return "deepseek"
    if "groq" in ab: return "groq"
    if "mistral" in ab: return "mistral"
    if "x.ai" in ab or "xai" in ab: return "xai"
    if "bigmodel" in ab or "zhipu" in ab: return "zhipu"
    if "dashscope" in ab or "qwen" in ab: return "qwen"
    if "moonshot" in ab or "kimi" in ab: return "kimi"
    if "ollama" in ab: return "ollama"
    return "openai"

LLM_PROVIDER = detect_provider(LLM_API_BASE)
PROVIDER_HEADERS = {}
if LLM_PROVIDER == "openrouter":
    PROVIDER_HEADERS["HTTP-Referer"] = "https://agent-pain-points.local"
    PROVIDER_HEADERS["X-Title"] = "Agent Pain Points Monitor"

# ============================================================
# 目标定义
# ============================================================

TARGET_REPOS = [
    "langchain-ai/langchain", "Significant-Gravitas/AutoGPT",
    "crewAIInc/crewAI", "microsoft/autogen", "langgenius/dify",
    "n8n-io/n8n", "run-llama/llama_index", "BerriAI/litellm",
    "agno-agi/agno", "meta-llama/llama-stack",
    "openai/openai-agents-python", "google/adk-python",
    "anthropics/claude-code", "cline/cline", "RooVetGit/Roo-Code",
    "aider-ai/aider", "composiohq/composio", "browser-use/browser-use",
    "camel-ai/camel", "OpenBMB/ChatDev",
]

REDDIT_SUBREDDITS = [
    "ClaudeAI", "OpenAI", "LocalLLaMA", "MachineLearning",
    "ChatGPTCoding", "ChatGPT", "artificial", "singularity",
    "AI_Agents", "LangChain", "AutoGPT",
]

REDDIT_KEYWORDS = [
    "agent fail", "agent issue", "agent problem", "agent limitation",
    "agent struggle", "agent broke", "agent bug", "agent not working",
    "agent hallucination", "agent context", "agent cost", "agent slow",
    "agent timeout", "agent loop", "agent stuck", "agent unreliable",
    "LLM agent pain", "AI agent challenge", "agent tool error",
    "agent memory issue", "agent planning fail",
]

HN_KEYWORDS = [
    "AI agent fail", "LLM agent limitation", "agent framework problem",
    "AI agent reliability", "agent hallucination", "agent context window",
    "agent cost too high", "agent tool use fail", "agent infinite loop",
    "agent deployment challenge", "multi-agent problem", "agent evaluation",
    "AI agent pain point", "agent not production ready", "agent security",
    "agent prompt injection", "agent memory limitation",
]

ARXIV_KEYWORDS = [
    "agent limitation", "agent failure", "LLM agent challenge",
    "agent evaluation", "agent reliability", "multi-agent challenge",
    "agent hallucination", "agent planning limitation",
    "agent tool use error", "agent safety",
]

PAIN_POINT_CATEGORIES = {
    "可靠性": ["幻觉", "任务未完成", "中途迷失", "输出不一致", "目标漂移"],
    "工具使用": ["选错工具", "死循环调用", "参数错误", "工具描述误解", "权限不足"],
    "上下文管理": ["遗忘上下文", "窗口溢出", "长对话退化", "注意力分散", "信息压缩失真"],
    "成本": ["Token消耗过高", "API费用失控", "推理成本高", "缓存命中率低"],
    "性能": ["延迟高", "并发差", "吞吐瓶颈", "资源占用大"],
    "安全性": ["提示注入", "数据泄露", "权限滥用", "越狱攻击", "间接注入"],
    "多Agent协作": ["通信失败", "任务分配混乱", "死锁", "状态不一致", "角色冲突"],
    "评测": ["难以评估", "缺乏基准", "回归测试困难", "指标不全面", "人工评估成本高"],
    "部署运维": ["监控困难", "版本管理", "回滚复杂", "环境依赖", "扩展性差"],
    "用户体验": ["输出不可控", "交互不自然", "学习成本高", "反馈不及时", "透明度不足"],
}

# ============================================================
# HTTP 工具
# ============================================================

session = requests.Session()
if PROXIES:
    session.proxies.update(PROXIES)

def safe_get(url, headers=None, params=None, timeout=30, retries=2):
    for attempt in range(retries + 1):
        try:
            r = session.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code in (403, 404):
                return None
            if r.status_code == 429:
                time.sleep(3)
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except:
            pass
    return None

# ============================================================
# 爬虫
# ============================================================

def crawl_reddit():
    print("[Reddit] 开始爬取...")
    items = []
    headers = {"User-Agent": "agent-pain-points/1.0"}
    for subreddit in REDDIT_SUBREDDITS[:6]:  # 限制子版块数量
        for keyword in REDDIT_KEYWORDS[:2]:  # 限制关键词减少请求
            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {"q": keyword, "sort": "new", "limit": 10, "restrict_sr": "on"}
            data = safe_get(url, headers=headers, params=params, timeout=8)
            if not data:
                continue
            for post in data.get("data", {}).get("children", []):
                p = post["data"]
                title = p.get("title", "")
                selftext = p.get("selftext", "")
                if not is_agent_relevant(f"{title} {selftext}"):
                    continue
                items.append({
                    "title": title,
                    "url": f"https://www.reddit.com{p.get('permalink', '')}",
                    "source": "Reddit", "source_detail": f"r/{subreddit}",
                    "desc": selftext[:500] if selftext else title,
                    "score": p.get("score", 0),
                    "num_comments": p.get("num_comments", 0),
                    "created_at": datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc).isoformat(),
                    "product": detect_product(title, subreddit),
                    "category": classify_pain_category(title, selftext),
                    "severity": classify_severity(title, selftext),
                    "labels": [],
                })
                if len(items) >= 200: break
            if len(items) >= 200: break
        if len(items) >= 200: break
    print(f"[Reddit] 爬取完成，共 {len(items)} 条")
    return items

def crawl_hacker_news():
    print("[HackerNews] 开始爬取...")
    items = []
    for keyword in HN_KEYWORDS[:3]:
        url = "https://hn.algolia.com/api/v1/search"
        params = {"query": keyword, "tags": "story", "hitsPerPage": 10}
        data = safe_get(url, params=params, timeout=15)
        if not data: continue
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            if not is_agent_relevant(title): continue
            items.append({
                "title": title,
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "source": "Hacker News", "source_detail": f"hn:{hit.get('objectID')}",
                "desc": hit.get("story_text", "")[:500] or title,
                "hn_points": hit.get("points", 0),
                "hn_comments": hit.get("num_comments", 0),
                "created_at": hit.get("created_at", ""),
                "product": detect_product(title, ""),
                "category": classify_pain_category(title, ""),
                "severity": classify_severity(title, ""),
                "labels": [],
            })
    print(f"[HackerNews] 爬取完成，共 {len(items)} 条")
    return items

def crawl_github_issues():
    print("[GitHub] 开始爬取...")
    items = []
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    pain_keywords = ["fail", "error", "problem", "limitation", "not working",
                     "bug", "slow", "cost", "context", "hallucination",
                     "loop", "stuck", "timeout", "memory", "unreliable"]
    for repo in TARGET_REPOS[:8]:
        for kw in pain_keywords[:2]:
            url = "https://api.github.com/search/issues"
            query = f"repo:{repo} {kw} in:title state:open"
            params = {"q": query, "sort": "updated", "order": "desc", "per_page": 5}
            data = safe_get(url, headers=headers, params=params, timeout=15)
            if not data: continue
            for issue in data.get("items", []):
                title = issue.get("title", "")
                body = issue.get("body", "") or ""
                items.append({
                    "title": title, "url": issue.get("html_url", ""),
                    "source": "GitHub Issues", "source_detail": repo,
                    "desc": body[:500] if body else title, "repo": repo,
                    "product": detect_product(title, repo),
                    "category": classify_pain_category(title, body),
                    "severity": classify_severity(title, body),
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "created_at": issue.get("created_at", ""),
                    "updated_at": issue.get("updated_at", ""),
                    "state": issue.get("state", "open"),
                    "comments": issue.get("comments", 0),
                    "reactions": issue.get("reactions", {}).get("total_count", 0),
                })
    print(f"[GitHub] 爬取完成，共 {len(items)} 条")
    return items

def crawl_arxiv():
    print("[arXiv] 开始爬取...")
    items = []
    for keyword in ARXIV_KEYWORDS[:3]:
        url = "http://export.arxiv.org/api/query"
        params = {"search_query": f"all:{keyword}", "start": 0, "max_results": 10,
                  "sortBy": "submittedDate", "sortOrder": "descending"}
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code != 200: continue
            entries = re.findall(r"<entry>(.*?)</entry>", r.text, re.DOTALL)
            for entry in entries:
                t = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                s = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                l = re.search(r'<id>(.*?)</id>', entry, re.DOTALL)
                p = re.search(r"<published>(.*?)</published>", entry)
                title = t.group(1).strip() if t else ""
                summary = s.group(1).strip() if s else ""
                if not is_agent_relevant(f"{title} {summary}"): continue
                items.append({
                    "title": title, "url": l.group(1).strip() if l else "",
                    "source": "arXiv", "source_detail": "学术论文",
                    "desc": summary[:500] if summary else title,
                    "created_at": p.group(1).strip() if p else "",
                    "product": "学术研究",
                    "category": classify_pain_category(title, summary),
                    "severity": classify_severity(title, summary),
                    "labels": ["academic"],
                })
        except Exception as e:
            print(f"  [WARN] arXiv error: {e}")
    print(f"[arXiv] 爬取完成，共 {len(items)} 条")
    return items

# ============================================================
# 分类与过滤
# ============================================================

def is_agent_relevant(text):
    text_lower = text.lower()
    agent_signals = ["agent", "ai agent", "llm agent", "autonomous agent",
        "langchain", "autogpt", "crewai", "autogen", "dify",
        "claude code", "claude-code", "cursor", "copilot",
        "chatgpt agent", "gpt agent", "multi-agent", "agentic",
        "tool calling", "function calling", "tool use",
        "claude", "gpt-4", "gpt4", "chatgpt", "llm"]
    if not any(s in text_lower for s in agent_signals):
        return False
    pain_signals = ["fail", "error", "bug", "issue", "problem", "limitation",
        "not work", "broke", "struggle", "pain", "challenge",
        "hallucinat", "context", "slow", "cost", "expensiv",
        "loop", "stuck", "timeout", "unreliable", "inconsistent",
        "memory", "leak", "security", "inject",
        "tool call", "function call", "planning fail",
        "not production", "not ready", "can't", "cannot",
        "doesn't work", "don't work", "won't work",
        "difficult", "hard to", "complex", "confus"]
    return any(s in text_lower for s in pain_signals)

def detect_product(title, repo_or_sub):
    text = (title + " " + repo_or_sub).lower()
    product_map = {
        "langchain": "LangChain", "autogpt": "AutoGPT", "crewai": "CrewAI",
        "autogen": "AutoGen", "dify": "Dify", "n8n": "n8n",
        "llama_index": "LlamaIndex", "llama-index": "LlamaIndex",
        "litellm": "LiteLLM", "agno": "Agno",
        "llama-stack": "Llama Stack", "llama stack": "Llama Stack",
        "openai-agents": "OpenAI Agents SDK", "adk": "Google ADK",
        "claude code": "Claude Code", "claude-code": "Claude Code",
        "cline": "Cline", "roo-code": "Roo Code", "roo code": "Roo Code",
        "aider": "Aider", "composio": "Composio",
        "browser-use": "Browser Use", "browser use": "Browser Use",
        "camel": "CAMEL", "chatdev": "ChatDev",
        "cursor": "Cursor", "windsurf": "Windsurf",
        "copilot": "GitHub Copilot", "devin": "Devin",
        "claude": "Claude", "openai": "OpenAI", "chatgpt": "ChatGPT", "gpt": "GPT",
    }
    for key, product in product_map.items():
        if key in text: return product
    return "通用 AI Agent"

def classify_pain_category(title, body):
    text = (title + " " + (body or "")).lower()
    scores = {}
    for cat, subcats in PAIN_POINT_CATEGORIES.items():
        score = sum(1 for sub in subcats if sub.lower() in text)
        if score > 0: scores[cat] = score
    if "安全" in text or "secur" in text or "inject" in text or "leak" in text:
        scores["安全性"] = scores.get("安全性", 0) + 2
    if "cost" in text or "token" in text or "pric" in text or "expens" in text:
        scores["成本"] = scores.get("成本", 0) + 2
    if "slow" in text or "latency" in text or "performance" in text:
        scores["性能"] = scores.get("性能", 0) + 2
    if "context" in text or "memory" in text or "forget" in text or "window" in text:
        scores["上下文管理"] = scores.get("上下文管理", 0) + 2
    if "tool" in text or "function call" in text:
        scores["工具使用"] = scores.get("工具使用", 0) + 2
    if "hallucinat" in text or "wrong" in text or "incorrect" in text:
        scores["可靠性"] = scores.get("可靠性", 0) + 2
    if "multi" in text or "collaborat" in text or "coordinat" in text:
        scores["多Agent协作"] = scores.get("多Agent协作", 0) + 2
    if "evaluat" in text or "benchmark" in text or "test" in text:
        scores["评测"] = scores.get("评测", 0) + 2
    if "deploy" in text or "monitor" in text or "product" in text:
        scores["部署运维"] = scores.get("部署运维", 0) + 2
    if "ux" in text or "user" in text or "interact" in text or "experien" in text:
        scores["用户体验"] = scores.get("用户体验", 0) + 2
    return max(scores, key=scores.get) if scores else "可靠性"

def classify_severity(title, body):
    text = (title + " " + (body or "")).lower()
    severity_map = {
        "严重": ["production", "critical", "blocker", "data loss", "security breach",
                 "completely broken", "unusable", "severe", "catastrophic"],
        "高": ["major", "significant", "failed", "broken", "unreliable",
               "high cost", "serious", "blocking"],
        "中": ["moderate", "issue", "problem", "limitation", "concern",
               "annoying", "inconsistent", "slow"],
        "低": ["minor", "nice to have", "cosmetic", "edge case", "rare"],
    }
    scores = {}
    for level, keywords in severity_map.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0: scores[level] = score
    return max(scores, key=scores.get) if scores else "中"

# ============================================================
# 去重与汇总
# ============================================================

def deduplicate(items):
    seen_urls, seen_titles = set(), set()
    result = []
    for item in items:
        url = item.get("url", "")
        title = item.get("title", "").lower().strip()
        if url in seen_urls or title in seen_titles: continue
        if url: seen_urls.add(url)
        if title: seen_titles.add(title)
        result.append(item)
    return result

def build_summary(items):
    return {
        "total": len(items),
        "by_category": dict(Counter(i.get("category", "未知") for i in items).most_common()),
        "by_severity": dict(Counter(i.get("severity", "中") for i in items)),
        "by_product": dict(Counter(i.get("product", "未知") for i in items).most_common(10)),
        "by_source": dict(Counter(i.get("source", "未知") for i in items)),
    }

# ============================================================
# LLM 智能分析
# ============================================================

LLM_BATCH_SIZE = 8

ANALYSIS_SYSTEM_PROMPT = """你是一个 AI Agent 领域的资深研究分析师。从收集到的 Agent 痛点数据中提取、分类、排名并深度分析 Top 10 痛点。

## 第一步：提取痛点信息
对每条数据判断是否是真实痛点，提取核心描述，分类，评估严重度（严重/高/中/低）和热度。

## 第二步：综合排名
综合严重度、热度、普遍性、趋势性，选出 Top 10。

## 第三步：对 Top 10 深度分析
对每个 Top 10 痛点提供：痛点标题、综合评分（1-10）、问题描述（200-300字）、根因分析（150-200字）、至少2-3个解决方案（含难度和周期）、产业界预期收益、学术界预期收益、相关来源链接。

## 输出格式
严格输出 JSON，不要包含其他内容：

```json
{
  "top10": [
    {
      "rank": 1,
      "title": "痛点标题",
      "category": "可靠性",
      "severity": "严重",
      "score": 9.5,
      "hotness": "高",
      "description": "详细描述...",
      "root_cause": "根因分析...",
      "solutions": [
        {"title": "方案1", "description": "描述...", "difficulty": "低/中/高", "timeframe": "短期/中期/长期"}
      ],
      "industry_benefit": "产业界收益...",
      "academia_benefit": "学术界收益...",
      "sources": ["url1", "url2"],
      "affected_products": ["产品A", "产品B"]
    }
  ],
  "trend_summary": "总体趋势总结（100字以内）",
  "category_distribution": {"可靠性": 3, "工具使用": 2}
}
```"""

def analyze_with_llm(items, force=False):
    if not LLM_API_KEY:
        print("[LLM] 未配置 API Key，跳过分析")
        return None
    if not items:
        print("[LLM] 没有数据需要分析")
        return None
    if not force:
        pending = [i for i in items if not i.get("llm_analysis")]
        print(f"[LLM] 增量模式：{len(items)} 条中 {len(pending)} 条待分析")
        if not pending:
            print("[LLM] 全部已分析，跳过")
            return None
        items_to_analyze = pending
    else:
        items_to_analyze = items
        print(f"[LLM] 强制模式：分析全部 {len(items)} 条")

    all_pain_points = []
    for i in range(0, len(items_to_analyze), LLM_BATCH_SIZE):
        batch = items_to_analyze[i:i + LLM_BATCH_SIZE]
        print(f"[LLM] 批次 {i // LLM_BATCH_SIZE + 1}/{(len(items_to_analyze) - 1) // LLM_BATCH_SIZE + 1}...")
        result = _process_batch(batch)
        if result: all_pain_points.extend(result)

    if all_pain_points:
        print(f"[LLM] 提取到 {len(all_pain_points)} 个痛点，开始综合排名和深度分析...")
        top10_result = _rank_and_analyze(all_pain_points)
        if top10_result:
            for item in items:
                item["llm_analysis"] = "done"
            return top10_result
    return None

def _process_batch(batch):
    items_json = []
    for idx, item in enumerate(batch):
        items_json.append({
            "id": idx, "title": item.get("title", ""),
            "description": item.get("desc", "")[:300],
            "source": item.get("source", ""),
            "source_detail": item.get("source_detail", ""),
            "product": item.get("product", ""),
            "category": item.get("category", ""),
            "severity": item.get("severity", ""),
            "url": item.get("url", ""),
            "score": item.get("score", item.get("hn_points", 0)),
            "comments": item.get("num_comments", item.get("hn_comments", item.get("comments", 0))),
            "reactions": item.get("reactions", 0),
        })
    return _call_llm(f"""从以下数据中提取所有有效的 Agent 痛点。每个痛点提取：pain_point, category, severity, hotness_score, affected_products, source_urls。

数据：{json.dumps(items_json, ensure_ascii=False, indent=2)}

只输出 JSON 数组，不要其他内容。""", expect_array=True)

def _rank_and_analyze(pain_points):
    return _call_llm(f"""以下是 {len(pain_points)} 个 Agent 痛点，请综合排名选出 Top 10 并深度分析（含问题描述、根因、解决方案、产业界和学术界收益）。只输出 JSON。

{json.dumps(pain_points, ensure_ascii=False, indent=2)}""", expect_array=False)

def _call_llm(prompt, expect_array=False):
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    headers.update(PROVIDER_HEADERS)
    payload = {"model": LLM_MODEL, "messages": [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}],
        "temperature": 0.3, "max_tokens": 8192}
    for attempt in range(3):
        try:
            r = session.post(f"{LLM_API_BASE}/chat/completions", headers=headers, json=payload, timeout=120)
            if r.status_code != 200:
                print(f"  [LLM ERROR] HTTP {r.status_code}: {r.text[:200]}")
                if attempt < 2: time.sleep(2 ** attempt)
                continue
            content = r.json()["choices"][0]["message"]["content"]
            result = _extract_json(content, expect_array)
            if result: return result
            print(f"  [LLM WARN] JSON 解析失败，重试...")
            if attempt < 2: time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  [LLM ERROR] {e}")
            if attempt < 2: time.sleep(2 ** attempt)
    return None

def _extract_json(text, expect_array=False):
    if "```json" in text:
        m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if m: text = m.group(1)
    elif "```" in text:
        m = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if m: text = m.group(1)
    start = text.find("[") if expect_array else text.find("{")
    end = text.rfind("]") if expect_array else text.rfind("}")
    if start >= 0 and end > start:
        try: return json.loads(text[start:end + 1])
        except json.JSONDecodeError: pass
    return None

# ============================================================
# 搜索已有解决方案 & 相关论文
# ============================================================

def search_existing_solutions(pain_points):
    """对每个 Top 10 痛点，搜索网上已有的解决方案和相关论文"""
    if not pain_points:
        return pain_points
    
    print(f"\n[搜索] 为 {len(pain_points)} 个痛点搜索已有方案和论文...")
    enriched = []
    for i, pp in enumerate(pain_points):
        title = pp.get("title", "")
        print(f"  [{i+1}/{len(pain_points)}] 搜索: {title[:50]}...")
        
        papers = _search_arxiv(title)
        solutions = _search_github_solutions(title)
        web_results = _search_web(title)
        
        pp["related_papers"] = papers[:5] if papers else []
        pp["web_solutions"] = solutions[:5] if solutions else []
        pp["web_discussions"] = web_results[:5] if web_results else []
        enriched.append(pp)
        time.sleep(0.2)  # 避免请求过快
    
    print(f"[搜索] 完成，开始 LLM 总结已有方案...")
    enriched = _summarize_findings(enriched)
    return enriched

def _search_arxiv(title):
    """搜索 arXiv 相关论文"""
    papers = []
    keywords = _extract_keywords(title, 3)
    for kw in keywords[:2]:
        url = "http://export.arxiv.org/api/query"
        params = {"search_query": f"all:{kw}", "start": 0, "max_results": 3,
                  "sortBy": "relevance", "sortOrder": "descending"}
        try:
            r = session.get(url, params=params, timeout=5)
            if r.status_code != 200: continue
            entries = re.findall(r"<entry>(.*?)</entry>", r.text, re.DOTALL)
            for entry in entries:
                t = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                s = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                l = re.search(r'<id>(.*?)</id>', entry, re.DOTALL)
                authors = re.findall(r'<name>(.*?)</name>', entry)
                published = re.search(r"<published>(.*?)</published>", entry)
                papers.append({
                    "title": t.group(1).strip() if t else "",
                    "summary": (s.group(1).strip() if s else "")[:300],
                    "url": l.group(1).strip() if l else "",
                    "authors": authors[:3] if authors else [],
                    "published": published.group(1).strip()[:10] if published else "",
                })
        except Exception as e:
            print(f"    arXiv search error: {e}")
    return papers

def _search_github_solutions(title):
    """搜索 GitHub 上的相关 Issue/PR/讨论"""
    solutions = []
    if not GH_TOKEN:
        return solutions
    headers = {"Accept": "application/vnd.github.v3+json", "Authorization": f"token {GH_TOKEN}"}
    keywords = _extract_keywords(title, 2)
    for kw in keywords[:2]:
        url = "https://api.github.com/search/issues"
        query = f"{kw} solution OR fix OR workaround OR resolved"
        params = {"q": query, "sort": "reactions", "order": "desc", "per_page": 3}
        try:
            r = session.get(url, headers=headers, params=params, timeout=8)
            if r.status_code != 200: continue
            for issue in r.json().get("items", []):
                solutions.append({
                    "title": issue.get("title", ""),
                    "url": issue.get("html_url", ""),
                    "state": issue.get("state", "open"),
                    "repo": issue.get("repository_url", "").replace("https://api.github.com/repos/", ""),
                    "comments": issue.get("comments", 0),
                    "reactions": issue.get("reactions", {}).get("total_count", 0),
                })
        except Exception as e:
            print(f"    GitHub search error: {e}")
    return solutions

def _search_web(title):
    """通用网页搜索（DuckDuckGo HTML）"""
    results = []
    keywords = _extract_keywords(title, 2)
    query = f"agent {keywords[0] if keywords else title} solution OR fix OR paper"
    url = "https://html.duckduckgo.com/html/"
    try:
        r = session.post(url, data={"q": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code != 200: return results
        # 简单解析 HTML 搜索结果
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r.text, re.DOTALL):
            href = m.group(1)
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if text and href.startswith("http"):
                results.append({"title": text[:200], "url": href})
        # 也尝试提取摘要
        snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', r.text, re.DOTALL)
        for j, snippet in enumerate(snippets):
            if j < len(results):
                results[j]["snippet"] = re.sub(r'<[^>]+>', '', snippet).strip()[:300]
    except Exception as e:
        print(f"    Web search error: {e}")
    return results

def _extract_keywords(title, n=3):
    """从标题中提取关键词"""
    # 移除常见停用词
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
                 "have", "has", "had", "do", "does", "did", "will", "would", "could",
                 "should", "may", "might", "can", "shall", "to", "of", "in", "for",
                 "on", "with", "at", "by", "from", "as", "into", "through", "during",
                 "and", "but", "or", "not", "no", "if", "then", "else", "when",
                 "agent", "ai", "llm", "problem", "issue", "fail", "error", "bug",
                 "this", "that", "it", "its", "they", "them", "their"}
    words = re.findall(r'[a-zA-Z\u4e00-\u9fff]+', title.lower())
    keywords = [w for w in words if w not in stopwords and len(w) > 2]
    return keywords[:n]

def _summarize_findings(pain_points):
    """用 LLM 总结搜索结果"""
    if not LLM_API_KEY:
        return pain_points
    
    print(f"[LLM] 总结已有方案和论文...")
    for i, pp in enumerate(pain_points):
        papers = pp.get("related_papers", [])
        solutions = pp.get("web_solutions", [])
        discussions = pp.get("web_discussions", [])
        
        if not papers and not solutions and not discussions:
            pp["existing_solutions_summary"] = "暂无找到相关已有方案或论文。"
            pp["existing_solutions"] = []
            continue
        
        context = f"""痛点：{pp.get('title', '')}

相关论文（arXiv）：{json.dumps(papers, ensure_ascii=False) if papers else '无'}
相关解决方案（GitHub）：{json.dumps(solutions, ensure_ascii=False) if solutions else '无'}
相关讨论（Web）：{json.dumps(discussions, ensure_ascii=False) if discussions else '无'}

请总结以上搜索结果中对该痛点的已有解决方案和研究成果。按以下格式输出 JSON：
{{
  "existing_solutions": [
    {{"title": "方案名称", "description": "方案描述（100字以内）", "source_type": "论文/开源项目/社区方案", "source_url": "链接"}}
  ],
  "research_status": "学术界研究现状（50字以内）",
  "industry_status": "产业界解决现状（50字以内）"
}}"""
        
        result = _call_llm_simple(context)
        if result:
            pp["existing_solutions"] = result.get("existing_solutions", [])
            pp["research_status"] = result.get("research_status", "")
            pp["industry_status"] = result.get("industry_status", "")
        else:
            pp["existing_solutions"] = []
            pp["research_status"] = ""
            pp["industry_status"] = ""
        
        time.sleep(0.3)
    
    return pain_points

def _call_llm_simple(prompt):
    """简化的 LLM 调用"""
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    headers.update(PROVIDER_HEADERS)
    payload = {"model": LLM_MODEL, "messages": [
        {"role": "user", "content": prompt}],
        "temperature": 0.3, "max_tokens": 2048}
    for attempt in range(2):
        try:
            r = session.post(f"{LLM_API_BASE}/chat/completions", headers=headers, json=payload, timeout=60)
            if r.status_code != 200:
                if attempt < 1: time.sleep(1)
                continue
            content = r.json()["choices"][0]["message"]["content"]
            result = _extract_json(content, expect_array=False)
            if result: return result
            if attempt < 1: time.sleep(1)
        except Exception as e:
            print(f"    [LLM SIMPLE ERROR] {e}")
            if attempt < 1: time.sleep(1)
    return None

# ============================================================
# 主流程
# ============================================================

def crawl_all(force=False):
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  Agent 痛点日报 - {today}")
    print(f"{'='*60}\n")

    all_items = []
    crawlers = [
        ("Reddit", crawl_reddit), ("Hacker News", crawl_hacker_news),
        ("GitHub Issues", crawl_github_issues), ("arXiv", crawl_arxiv),
    ]
    for name, crawler in crawlers:
        try:
            items = crawler()
            all_items.extend(items)
        except Exception as e:
            print(f"[ERROR] {name} 爬取失败: {e}")

    all_items = deduplicate(all_items)
    print(f"\n[总计] 去重后共 {len(all_items)} 条原始数据")

    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)
    today_file = os.path.join(data_dir, f"{today}-pain.json")
    today_js = os.path.join(data_dir, f"{today}-pain.js")
    # 沙箱环境回退到 /tmp
    try:
        with open(today_file, "a") as _test:
            pass
    except PermissionError:
        data_dir = "/tmp/agent-pain-data"
        os.makedirs(data_dir, exist_ok=True)
        today_file = os.path.join(data_dir, f"{today}-pain.json")
        today_js = os.path.join(data_dir, f"{today}-pain.js")
        print(f"[WARN] data/ 不可写，输出到 {data_dir}/")

    existing_items = []
    if os.path.exists(today_file) and not force:
        try:
            with open(today_file, "r") as f:
                existing_items = json.load(f).get("items", [])
            print(f"[增量] 已有 {len(existing_items)} 条数据")
        except: pass

    existing_urls = {i.get("url", "") for i in existing_items}
    new_items = [i for i in all_items if i.get("url", "") not in existing_urls]
    merged_items = existing_items + new_items
    print(f"[合并] 新增 {len(new_items)} 条，共 {len(merged_items)} 条")

    top10_result = None
    if LLM_API_KEY and new_items:
        top10_result = analyze_with_llm(merged_items, force=force)

    # 搜索已有解决方案和论文
    top10_list = top10_result.get("top10", []) if top10_result else []
    if top10_list:
        try:
            top10_list = search_existing_solutions(top10_list)
        except Exception as e:
            print(f"[搜索] 搜索已有方案失败: {e}，跳过")
        if top10_result:
            top10_result["top10"] = top10_list

    summary = build_summary(merged_items)
    output = {
        "date": today,
        "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "summary": summary,
        "total_items": len(merged_items),
        "items": merged_items,
        "top10": top10_list,
        "trend_summary": top10_result.get("trend_summary", "") if top10_result else "",
        "category_distribution": top10_result.get("category_distribution", {}) if top10_result else {},
    }

    with open(today_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[输出] {today_file}")

    today_js = os.path.join(data_dir, f"{today}-pain.js")
    with open(today_js, "w", encoding="utf-8") as f:
        f.write(f"(function(){{ window.__agentPainData = {json.dumps(output, ensure_ascii=False)}; }})();\n")
    print(f"[输出] {today_js}")

    _update_manifest(data_dir)

    print(f"\n{'='*60}")
    print(f"  Top 10 痛点:")
    for item in output.get("top10", []):
        print(f"  #{item.get('rank', '?')} [{item.get('category', '?')}] {item.get('title', '?')} (评分: {item.get('score', '?')})")
    print(f"{'='*60}\n")
    return output

def _update_manifest(data_dir):
    dates = []
    for f in sorted(os.listdir(data_dir)):
        if f.endswith("-pain.json") and f != "manifest-pain.json":
            dates.append(f.replace("-pain.json", ""))
    manifest = {
        "available_dates": sorted(dates),
        "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }
    with open(os.path.join(data_dir, "manifest-pain.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    with open(os.path.join(data_dir, "manifest-pain.js"), "w", encoding="utf-8") as f:
        f.write(f"(function(){{ window.__agentPainManifest = {json.dumps(manifest, ensure_ascii=False)}; }})();\n")

if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    crawl_all(force=force)