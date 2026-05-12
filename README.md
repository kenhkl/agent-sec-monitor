# AI Agent 安全风险监控

每日自动搜索、分析主流 AI Agent 的安全漏洞、可复现攻击手段与未修复问题，通过大模型智能过滤和中文总结，在网页面板上集中展示。

监控范围不限于编程场景，涵盖代码生成、消息平台接入、终端工具调用、浏览器自动化等各类 AI Agent 的安全威胁。

## 监控产品

### 开源项目（通过 GitHub 仓库定向监控）

**AI 编码 Agent**

| 产品 | GitHub 仓库 | 简介 | 已知安全事件 |
|------|------------|------|-------------|
| **Claude Code** | [anthropics/claude-code](https://github.com/anthropics/claude-code) | Anthropic 官方终端 AI 编程助手 | prompt 注入、沙箱逃逸、未经授权的文件访问 |
| **Cline** | [cline/cline](https://github.com/cline/cline) | VS Code AI 编程助手（前 Claude Dev） | MCP 配置注入、文件系统遍历、终端命令执行 |
| **Aider** | [Aider-AI/aider](https://github.com/Aider-AI/aider) | 终端内 AI 结对编程工具 | prompt 注入、代码执行沙箱绕过 |
| **Continue** | [continuedev/continue](https://github.com/continuedev/continue) | IDE AI 代码助手 | 凭证泄露、模型 API 滥用 |
| **TabbyML** | [TabbyML/tabby](https://github.com/TabbyML/tabby) | 自托管 AI 编码助手 | API 认证缺陷、模型服务安全 |
| **OpenCode** | [anomalyco/opencode](https://github.com/anomalyco/opencode) | 开源模型无关的终端 AI 编码代理，61k+ stars | **CVE-2026-22812**：未认证 RCE（CVSS 8.8），恶意 registry 重定向，分享功能安全问题 |

**通用 AI Agent / 智能体框架**

| 产品 | GitHub 仓库 | 简介 | 已知安全事件 |
|------|------------|------|-------------|
| **OpenClaw** | [openclaw/openclaw](https://github.com/openclaw/openclaw) | 多平台 AI Agent 框架（Telegram/WhatsApp/Slack/Discord 等 15+ 平台），327k+ stars | 大量 CVE 记录、消息平台注入、凭证泄露、沙箱逃逸 |
| **OpenClaw (CVE Tracker)** | [jgamblin/OpenClawCVEs](https://github.com/jgamblin/OpenClawCVEs) | 第三方 OpenClaw CVE 聚合仓库，137+ 安全公告 | 集中追踪 OpenClaw 相关所有 CVE |
| **Hermes Agent** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | 自我进化的 AI 智能体框架，记忆+技能学习+16 平台接入，43k+ stars | 220+ 安全 Issue：凭证泄露、路径遍历绕过、prompt 注入、MCP 服务安全、SSRF、SMS RCE 修复 |

**OpenClaw 衍生 / 轻量级版本**

| 产品 | GitHub 仓库 | 简介 | 已知安全事件 |
|------|------------|------|-------------|
| **ZeroClaw** | [zeroclaw-labs/zeroclaw](https://github.com/zeroclaw-labs/zeroclaw) | Rust 实现，3.4MB 二进制，全平台自主 AI 助手，31k+ stars | 8 个安全 Issue：TOTP 命令门控、Rust 依赖漏洞（4 个 RUSTSEC）、技能权限控制 |
| **NanoClaw** | [nanocoai/nanoclaw](https://github.com/nanocoai/nanoclaw) | 容器隔离安全版 OpenClaw 替代，28k+ stars | 23 个安全 Issue：Agent 间授权、挂载安全策略、Webhook 请求体限制、可信通道校验 |
| **NanoBot** | [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | 超轻量 Python AI Agent（~4k 行代码），42k+ stars | 16 个安全 Issue：ToolGuard 中间件、Tirith 命令扫描、浏览器 CSRF、SSRF 检测 |
| **PicoClaw** | [sipeed/picoclaw](https://github.com/sipeed/picoclaw) | Go 实现，<10MB 内存，$10 硬件可运行，28k+ stars | 1 个安全 Issue：`find /` 可枚举沙箱外路径 |
| **IronClaw** | [nearai/ironclaw](https://github.com/nearai/ironclaw) | Rust + WASM 沙盒，隐私优先 Agent OS，12k+ stars | 12 个安全 Issue：Tirith 预执行扫描、HMAC 验证、WASM 信任策略、间接 prompt 注入防护 |

### 闭源产品（通过 Advisories / Hacker News 关键词追踪）

| 产品 | 追踪方式 | 简介 |
|------|---------|------|
| **Cursor** | GitHub Advisories + Hacker News 关键词 | AI-first IDE（AI 编码） |
| **Windsurf** | GitHub Advisories + Hacker News 关键词 | AI 原生 IDE（原 Codeium，AI 编码） |
| **GitHub Copilot** | GitHub Advisories + Hacker News 关键词 | GitHub 官方 AI 编码助手 |
| **Devin** | GitHub Advisories + Hacker News 关键词 | Cognition AI 自主编码代理 |

---

## 数据来源

### 1. GitHub Issues（开源仓库安全 Issue）

- **覆盖**：14 个开源 Agent 仓库
- **搜索策略**：
  - 批量标签搜索：`label:security OR label:vulnerability OR label:sandbox OR label:exploit OR label:rce OR label:injection`
  - 标题关键词搜索：`security in:title`
- **频率限制**：无 Token 10次/分钟，有 Token 30次/分钟
- **优势**：直接来自开发者社区的实时问题报告

### 2. GitHub Security Advisories（官方安全公告）

- **覆盖**：全球 GitHub 安全公告数据库
- **过滤条件**：匹配 TARGET_REPOS 仓库名称 或 CLOSED_SOURCE_TOOLS 关键词
- **来源**：[https://api.github.com/advisories](https://api.github.com/advisories)
- **优势**：经过审核的安全漏洞，含 CVE 编号和 CVSS 评分

### 3. OSV.dev（开源漏洞数据库）

- **覆盖**：9 个包名 x 3 类生态系统（npm / PyPI / Go）
- **来源**：[https://api.osv.dev/v1/query](https://api.osv.dev/v1/query)
- **优势**：跨生态系统统一漏洞索引，含上游 CVE 映射

### 4. Hacker News（安全资讯）

- **来源**：[https://hn.algolia.com/api/v1/search](https://hn.algolia.com/api/v1/search)（Algolia HN API）
- **搜索关键词**：
  - `AI agent security vulnerability`
  - `claude code cursor sandbox exploit`
  - `coding agent prompt injection RCE`
  - `opencode security vulnerability CVE`
  - `hermes agent security exploit`
- **优势**：获取社区讨论的最新安全动态和漏洞曝光

---

## 架构说明

```
crawl.py                  # 爬虫主脚本
├── GitHub Issues API     # 定向搜索 9 个仓库的安全 Issue
├── GitHub Advisories API # 查询官方安全公告
├── OSV.dev API           # 查询开源漏洞数据库
└── Hacker News API       # 搜索安全相关新闻
        │
        ▼
   初筛 + 关键词过滤 + 去重
        │
        ▼
   LLM 智能分析（OpenAI 兼容接口）
   ├── 过滤不相关条目
   ├── 生成中文标题和摘要
   ├── 判断是否可复现及复现步骤
   ├── 产品归类 / 漏洞类型分类 / 严重等级判定
        │
        ▼
   输出 data/{date}.json + data/{date}.js
        │
        ▼
   index.html（纯前端展示面板）
   ├── 产品筛选 / 类型标签 (AND 逻辑) / 严重等级筛选
   ├── 全文搜索 / 日历导航
   ├── LLM 生成的精炼中文标题和摘要
   └── 复现步骤展示 / 来源日期标签
```

---

## 快速开始

### 1. 配置 API 密钥

复制并编辑配置文件：

```bash
cp config.ini.example config.ini
```

`config.ini` 结构：

```ini
[GitHub]
token = ghp_xxxxxxxxxxxx    # GitHub Personal Access Token（可选，无 Token 频率限制更低）

[LLM]
api_key = sk-xxxxxxxxxxxx   # LLM API 密钥
api_base = https://api.openai.com/v1   # API 地址（兼容 OpenAI 接口规范）
model = gpt-4o-mini         # 模型名称

[Proxy]
http =                     # HTTP 代理（可选）
https =                    # HTTPS 代理（可选）
```

**支持的 LLM 提供商**：OpenAI / DeepSeek / Groq / Mistral / xAI / 智谱 GLM / 通义千问 / Kimi / OpenRouter / Ollama / 其他 OpenAI 兼容接口

### 2. 运行爬虫

```bash
# 增量模式（仅分析新增条目）
python3 crawl.py

# 强制全量重新分析
python3 crawl.py --force
```

### 3. 查看结果

- **命令行**：查看 `data/{date}.json` 文件
- **本地浏览器**：直接双击打开 `index.html`（无需 HTTP 服务器，自动加载 data/*.js 数据文件）

---

## 部署到 GitHub Pages

```bash
git add .
git commit -m "update"
git push origin master
```

在仓库 Settings → Pages 中：
- Source: **Deploy from a branch**
- Branch: **master**
- Folder: **/ (root)**
- 点击 **Save**

部署后访问：`https://<username>.github.io/<repo>/`

> 注意：`config.ini` 已在 `.gitignore` 中排除，不会上传到公开仓库。`data/` 目录会随推送更新。

---

## LLM 分析能力

每条原始数据经过大模型分析后，生成以下字段：

| 字段 | 说明 |
|------|------|
| `llm_title` | LLM 生成的精炼中文标题 |
| `llm_summary` | LLM 生成的中文漏洞总结 |
| `llm_reproduction` | 可复现步骤（如有） |
| `llm_type` | 漏洞类型（可复现 / 远程代码执行 / 权限绕过 / 信息泄露 / 提示注入 / 供应链攻击 / 沙箱逃逸 / 未修复 / 已修复） |
| `llm_level` | 严重等级（严重 / 高危 / 中危 / 低危） |
| `llm_product` | 归类的产品名称 |
| `llm_is_relevant` | 是否与 Agent 安全相关（不相关条目将被丢弃） |

---

## 设计原则

- **零 HTTP 服务器依赖**：`index.html` 可直接通过 `file://` 协议双击打开
- **增量分析**：已通过 LLM 分析的条目不会重复分析，节省 Token
- **多 Provider 适配**：自动检测 API 类型并添加对应 Provider Header
- **数据可离线**：每天生成独立 JSON 文件，网页端无需联网