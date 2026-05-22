# AI Daily Briefing

每天自动抓取 → 过滤去噪 → LLM 中文总结 → 生成 Markdown 日报。专为关注 **具身智能 / 多模态 / RAG / Agent / Memory / Grounding / VLM / 推理 / RL for LLM / 长上下文 / 开源模型** 的研究者设计。

## 功能概览

- **多源采集**：arXiv · HuggingFace（Daily Papers + 模型 trending）· GitHub Trending · Hacker News · Reddit · 通用 RSS（OpenAI / Anthropic / DeepMind / Meta / PWC 等）
- **关键词分类 + 启发式打分**：按你关心的主题加权，时间衰减，源权重，社区信号（stars/upvotes/score）
- **可切换 LLM**：Claude / OpenAI / DeepSeek / Ollama（本地），通过 `config.yaml` 切换
- **中文总结**：对每条内容产出 TL;DR · 为什么重要 · 与你工作的关联点；论文额外产出 核心方法 / 是否开源 / Benchmark 提升 / 是否值得精读
- **SQLite 存储 + LLM 缓存**：重跑不会重复花 token；可重渲染历史日报
- **Markdown 日报**：写到 `reports/YYYY-MM-DD.md`，直接在 VSCode 阅读

## 环境准备

本项目使用 conda 管理 Python 环境。

```bash
# 1. 创建并激活环境
conda create -n ai-briefing python=3.11 -y
conda activate ai-briefing

# 2. 安装项目（editable）
cd ai-daily-briefing
pip install -e .

# （可选）安装开发依赖
pip install -e ".[dev]"
```

## 初始化

```bash
briefing init
```

会在当前目录创建：
- `config.yaml`（从 `config.example.yaml` 复制）
- `.env`（从 `.env.example` 复制）
- `data/briefing.db`（SQLite，schema 自动建好）
- `reports/`

然后编辑：
- `.env`：填入你启用的 provider 的 API key
  - `ANTHROPIC_API_KEY` — 使用 Claude
  - `OPENAI_API_KEY` — 使用 OpenAI
  - `DEEPSEEK_API_KEY` — 使用 DeepSeek（兼容 OpenAI 协议）
  - `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — 使用 Reddit 源
- `config.yaml`：调整兴趣关键词、各 collector 开关、LLM 模型、`top_n_to_summarize` 等

## 日常使用

```bash
# 完整流程：采集 → 分类+打分 → 总结 → 渲染
briefing run

# 周末跳过后，周一回溯更长窗口（覆盖 arxiv / reddit 的 lookback_hours）
briefing run -L 84            # 等价于 --lookback-hours 84

# 只跑某一步
briefing collect              # 只抓取（也支持 -L / --lookback-hours）
briefing summarize            # 只对已抓到的 top-N 跑 LLM
briefing render               # 只渲染已总结的 item
briefing render --date 2026-05-19   # 重渲染历史日报

# 调试
briefing list-sources                  # 列出已注册的 collector
briefing test-source arxiv --limit 5   # 单源 dry-run，不写库
briefing db stats                      # 看看 DB 里各状态的数量
```

## 跳过 LLM 跑通流程

如果还没 API key，可以先验证采集 + 分类 + 打分链路：

```bash
briefing run --no-summarize --no-render
briefing db stats
```

## 输出形式

每日报告示例（`reports/2026-05-19.md`）：

```markdown
# AI Daily Briefing — 2026-05-19

> 共 30 条 · 分组方式：category · 生成时间 2026-05-19 17:39

## 具身智能 (8)

### Code as Agent Harness
- **TL;DR**：…
- **为什么重要**：…
- **与我研究的关联**：…
- **核心方法**：…
- **开源**：是 · **Benchmark 提升**：是 · **值得精读**：★ 是
- **来源**：`arxiv` · A. Author 等 · 标签：具身智能 / Agent
- **链接**：<http://arxiv.org/abs/...>
```

## 目录结构

```
src/briefing/
├── cli.py                 # typer 入口
├── config.py              # pydantic-settings 配置模型
├── models.py              # Item / Summary
├── db.py                  # SQLite (sqlite-utils)
├── pipeline.py            # 编排
├── collectors/            # 数据源插件
│   ├── arxiv.py
│   ├── huggingface.py
│   ├── github_trending.py
│   ├── hackernews.py
│   ├── reddit.py
│   └── rss.py
├── filters/
│   ├── classifier.py      # 关键词 → 主题
│   ├── ranker.py          # 启发式打分
│   └── dedup.py           # 跨源去重
├── llm/                   # provider 抽象
│   ├── claude.py
│   ├── openai.py
│   └── ollama.py
├── summarizer/            # LLM 总结
└── renderer/              # Markdown 模板渲染
```

## 加一个新数据源

1. 在 `src/briefing/collectors/` 新建一个文件，例如 `bilibili.py`
2. 继承 `BaseCollector`，实现 `async def collect()` 返回 `list[Item]`，并用 `@register_collector` 装饰类
3. 在 `config.py` 里加上对应的 `XxxCollectorConfig` pydantic 模型，挂到 `CollectorsConfig`
4. 在 `config.yaml` 里加上对应的开关

`pipeline._load_all_collector_modules()` 会自动发现并注册它。

## 切换 LLM provider

编辑 `config.yaml`：

```yaml
llm:
  provider: claude              # claude | openai | ollama | deepseek
  model: claude-opus-4-5        # 或 gpt-4o / qwen2.5:32b / deepseek-chat / deepseek-reasoner
```

确保对应的 `.env` 凭据存在。

DeepSeek 兼容 OpenAI 协议，复用 `openai` SDK，base_url 默认指向 `https://api.deepseek.com`。可选模型：
- `deepseek-chat`：通用，质量稳定，支持 JSON 输出模式
- `deepseek-reasoner`：R1 推理模型，输出会包含 `reasoning_content`，本工具自动跳过 `response_format` 参数

## 测试

```bash
pytest tests/
```

## 后续可加

- X / Twitter 接入（需决策 API / Nitter / 跳过）
- 会议 collector（CVPR / NeurIPS / ICLR / ACL accepted papers）
- HTTP 缓存层（hishel）+ 增量 cursor（已留好 `source_state` 表）
- Web UI（FastAPI + 简单前端浏览历史日报）
- 推送（邮件 / Telegram bot）

## 调度自动化（可选）

完成 MVP 后可以让它每天自动跑：

**Windows 任务计划程序**：
```cmd
schtasks /create /tn "AI Daily Briefing" /tr "C:\Users\<you>\anaconda3\envs\ai-briefing\python.exe -m briefing.cli run" /sc daily /st 08:00 /sd 01/01/2026 /f
```

**Linux/macOS cron**：
```cron
0 8 * * * cd /path/to/ai-daily-briefing && /path/to/conda/envs/ai-briefing/bin/python -m briefing.cli run >> logs.txt 2>&1
```
