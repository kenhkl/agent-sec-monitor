# AI Agent 安全风险监控

每日自动采集、分析主流 AI Agent 的安全漏洞与攻击手段，经 LLM 智能过滤和中文总结后，在网页面板上集中展示。

**在线体验**：https://itrustai.cn

---

## 功能特性

- **多源采集**：GitHub Issues / GitHub Advisories / OSV.dev / Hacker News 四路数据源
- **LLM 智能分析**：自动过滤噪声、生成中文摘要、提取复现步骤、判定漏洞类型与等级
- **增量更新**：每日三次自动运行，已分析条目跳过不重复扣费
- **纯前端展示**：产品筛选、类型标签、等级筛选、全文搜索、日历导航
- **零服务器**：基于 GitHub Actions + 腾讯云 COS + CDN 自动部署，无需维护云主机

---

## 监控产品

### 开源项目（通过 GitHub 定向监控）

| 产品 | 仓库 | 简介 |
|------|------|------|
| **Claude Code** | [anthropics/claude-code](https://github.com/anthropics/claude-code) | Anthropic 官方终端 AI 编程助手 |
| **OpenClaw** | [openclaw/openclaw](https://github.com/openclaw/openclaw) | 多平台 AI Agent 框架（15+ 平台）|
| **Cline** | [cline/cline](https://github.com/cline/cline) | VS Code AI 编程助手 |
| **Aider** | [Aider-AI/aider](https://github.com/Aider-AI/aider) | 终端 AI 结对编程工具 |
| **Continue** | [continuedev/continue](https://github.com/continuedev/continue) | IDE AI 代码助手 |
| **TabbyML** | [TabbyML/tabby](https://github.com/TabbyML/tabby) | 自托管 AI 编码助手 |
| **OpenCode** | [anomalyco/opencode](https://github.com/anomalyco/opencode) | 开源终端 AI 编码代理 |
| **Hermes Agent** | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | 自我进化的 AI 智能体框架 |
| **ZeroClaw** | [zeroclaw-labs/zeroclaw](https://github.com/zeroclaw-labs/zeroclaw) | Rust 实现轻量 AI 助手 |
| **NanoClaw** | [nanocoai/nanoclaw](https://github.com/nanocoai/nanoclaw) | 容器隔离安全版 OpenClaw 替代 |
| **NanoBot** | [HKUDS/nanobot](https://github.com/HKUDS/nanobot) | 超轻量 Python AI Agent |
| **PicoClaw** | [sipeed/picoclaw](https://github.com/sipeed/picoclaw) | Go 实现，$10 硬件可运行 |
| **IronClaw** | [nearai/ironclaw](https://github.com/nearai/ironclaw) | Rust + WASM 沙盒，隐私优先 Agent OS |

### 闭源产品（关键词追踪）

Cursor / Windsurf / GitHub Copilot / Devin

---

## 快速开始（本地使用）

### 1. 配置 API 密钥

```bash
cp config.ini.example config.ini  # 填写 LLM API Key 和 GitHub Token
```

`config.ini` 结构：

```ini
[GitHub]
token = ghp_xxxxxxxxxxxx       # GitHub Personal Access Token

[LLM]
api_key = sk-xxxxxxxxxxxx      # LLM API 密钥
api_base = https://api.openai.com/v1
model = gpt-4o-mini

[Proxy]
http =                         # 代理（可选）
```

支持的 LLM 提供商：OpenAI / DeepSeek / Groq / Mistral / xAI / 智谱 / 通义千问 / Kimi / Ollama 等。

### 2. 运行爬虫

```bash
python3 crawl.py               # 增量模式
python3 crawl.py --force       # 强制全量分析
```

### 3. 查看结果

直接双击 `index.html` 打开（无需 HTTP 服务器，自动加载 `data/*.js`）。

---

## 自动部署

项目使用 **GitHub Actions** 每日自动运行，上传至**腾讯云 COS + CDN**。

### 部署流程

```
GitHub Actions (定时触发)
  → python3 crawl.py（爬取 + LLM 分析）
  → 上传 data/ + index.html 到 COS
  → CDN 全球加速分发
  → https://itrustai.cn 展示
```

### 部署步骤

1. Fork 本仓库
2. 在仓库 Settings → Secrets → Actions 配置以下密钥：
   - `GH_PAT`：GitHub Personal Access Token
   - `LLM_API_KEY`、`LLM_API_BASE`、`LLM_MODEL`：大模型配置
   - `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_BUCKET`、`COS_REGION`：腾讯云 COS 凭证
3. 在腾讯云 COS 中配置静态网站托管 + CDN 加速 + 自定义域名
4. 手动触发一次 Actions 验证流程

详细教程见：**[docs/腾讯云COS+CDN静态网站正式部署文档.md](docs/腾讯云COS+CDN静态网站正式部署文档（完整可落地版）.md)**

### 通知机制

Workflow 失败时会：
- 自动发送邮件通知（GitHub Watch → All Activity）
- 支持企业微信 / 钉钉 / 飞书 Webhook 告警（配置 `ALERT_WEBHOOK_URL` Secret）

---

## 项目结构

```
.
├── crawl.py                  # 爬虫主脚本（采集 + LLM 分析 + 输出）
├── deploy.sh                 # 本地一键部署脚本（带重试 + 质量检查）
├── index.html                # 纯前端展示面板
├── config.ini                # 配置文件（不提交 Git）
├── .github/workflows/
│   └── deploy.yml            # GitHub Actions 自动部署工作流
├── data/                     # 每日数据文件
│   ├── YYYY-MM-DD.json       # 机器可读数据
│   ├── YYYY-MM-DD.js         # 前端直接加载（file:// 兼容）
│   └── manifest.json         # 可用日期清单（日历高亮用）
└── docs/                     # 部署文档
    └── 腾讯云COS+CDN静态网站正式部署文档.md
```

---

## LLM 分析字段

| 字段 | 说明 |
|------|------|
| `llm_title` | LLM 生成的中文标题 |
| `llm_summary` | 中文漏洞总结 |
| `llm_reproduction` | 可复现步骤 |
| `type` | 漏洞类型（沙箱逃逸 / 提示注入 / 供应链攻击 / RCE / 权限绕过 / 信息泄露 等） |
| `level` | 严重等级（严重 / 高危 / 中危 / 低危） |
| `product` | 归类的产品名称 |
