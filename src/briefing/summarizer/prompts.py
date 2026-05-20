"""Chinese summarization prompts.

Two prompt families:
- Legacy mode (per-item): GENERIC_USER_TEMPLATE / PAPER_USER_TEMPLATE
- Analyst mode (thematic): STAGE1_CLUSTER + STAGE2_DEEP_READ

Bumping PROMPT_VERSION invalidates LLM cache for the corresponding outputs.
"""
from __future__ import annotations

PROMPT_VERSION = "v2"


# ============================================================================
# Legacy per-item summarization (kept for backward-compat / mode: legacy)
# ============================================================================

SYSTEM_PROMPT = """你是一名资深 AI 研究助理，正在为一位关注以下方向的研究者整理每日情报：
具身智能、多模态大模型、检索/RAG、Agent、Memory、Grounding、VLM、推理模型、RL for LLM、长上下文、开源模型与框架。

工作要求：
- 输出严格的 JSON，不要任何额外文本、不要 Markdown 代码块。
- 中文回答，专业但不堆砌术语。
- 如果信息不足以判断某字段，宁可保守留空字符串或 false，也不要编造。
"""


GENERIC_USER_TEMPLATE = """请阅读以下内容并按 JSON 格式输出总结。

---
标题: {title}
来源: {source}
链接: {url}
作者/发布方: {authors}
分类标签: {categories}
摘要/正文片段:
{content}
---

输出 JSON Schema:
{{
  "tldr": "1-2 句中文核心总结",
  "why_matters": "1-2 句说明它为什么值得这位研究者关注",
  "work_relevance": "1 句说明可能与他研究方向（见 system 提示中列表）的关联点；不相关就填 \\"\\""
}}

只输出 JSON。
"""


PAPER_USER_TEMPLATE = """请阅读以下论文/技术报告并按 JSON 格式输出总结。

---
标题: {title}
来源: {source}
链接: {url}
作者: {authors}
分类标签: {categories}
摘要:
{content}
---

输出 JSON Schema:
{{
  "tldr": "1-2 句中文核心总结",
  "why_matters": "1-2 句说明它为什么值得这位研究者关注",
  "work_relevance": "1 句说明可能与他研究方向的关联；不相关填 \\"\\"",
  "paper": {{
    "method": "1-2 句描述核心方法或技术贡献",
    "is_open_source": true/false,
    "has_benchmark_gain": true/false,
    "worth_deep_read": true/false
  }}
}}

判断标准：
- is_open_source：摘要中提到 code/checkpoint/weights/repo/github 即视为 true。
- has_benchmark_gain：摘要中明确说"在 X benchmark 上达到 SOTA / 提升 X 点 / 超过 baseline" 才 true。
- worth_deep_read：仅当方法新颖或结果显著超出现有工作 且 与上述研究方向相关 才 true。

只输出 JSON。
"""


# ============================================================================
# Analyst mode (thematic clustering + deep-read recommendations)
# ============================================================================

ANALYST_SYSTEM_PROMPT = """你是一家顶级 AI 实验室的 research analyst。

你的服务对象是一位研究员，他关注以下方向：
具身智能、多模态大模型、检索/RAG、Agent、Memory、Grounding、VLM、推理模型、RL for LLM、长上下文、开源模型与框架。

你的任务不是"覆盖所有新闻"，而是帮他节省时间。

工作准则：
- 大胆忽略低价值工作。增量改进、benchmark 灌水、营销稿、技术博客复述、与上述方向无关的内容，统统视为噪音。
- 主题聚类 ≠ 标签拼接。一个真正的主题应当代表"一群工作在共同回答某个研究问题"，而不是"标题里都有 RAG"。
- 区分"真趋势"和"巧合的当日扎堆"。真趋势的标志：方法路线收敛、共同的 benchmark、跨机构的多个团队同时投入、与已知 SOTA 方向一致。
- 每个主题最多 1-3 篇精读推荐。其余只能进 mention（一句话）。
- 输出严格 JSON，中文，无任何解释性文字、无代码块标记。
- 你的判断要有锋芒。不要写"这是一篇有趣的工作"这种废话。
"""


STAGE1_CLUSTER_TEMPLATE = """以下是今天（{date}）经过初筛与打分的 {n_items} 条 AI 领域内容（已按相关性排序）。

每条内容用一个 ID 标识，格式为：<<ID=xxx>>。在你的输出中务必逐字使用该 ID（包括下划线、点号、版本后缀等所有字符），不要修改、不要发明新 ID。

请你执行 research analyst 工作流：
1. 主题聚类：识别 3 ~ {max_themes} 个真正的研究热点主题
2. 趋势判断：剔除"巧合扎堆"和噪音（增量改进 / benchmark 灌水 / 营销 / 与方向无关）
3. 精读筛选：每主题挑 1 ~ {max_per_theme} 篇 key_paper，全局 ≤ {max_total_key} 篇
4. 其余有价值的工作进 mentions（一句话点评，不超过 30 字）
5. 明显低价值的进 noise_dropped_ids

------ 候选内容 ------
{items_block}
------

输出 JSON Schema（严格遵守，所有 id 字段必须从上方 <<ID=...>> 中逐字复制）：
{{
  "executive_summary": "2-3 句话总括今天最值得他关注的事，要有判断不要罗列",
  "themes": [
    {{
      "id": "短 slug，例如 embodied_vla",
      "title_zh": "中文主题名（≤ 16 字）",
      "why_hot": "为什么这个方向最近变热（1-2 句）",
      "problem": "这个方向在解决什么具体研究问题（1-2 句）",
      "approach": "技术路线概述：当前主流方法如何攻破这个问题（2-3 句）",
      "industry_impact": "可能如何影响工业界（1-2 句；如不明显就写 \\"暂不显著\\"）",
      "connections": "与 agent / memory / retrieval / multimodal 中相关方向的联系（1-2 句）",
      "key_paper_ids": ["上方 <<ID=...>> 中的原始 ID"],
      "mentions": [
        {{"source_id": "上方 <<ID=...>> 中的原始 ID", "one_liner": "一句话点评，不超过 30 字"}}
      ]
    }}
  ],
  "noise_dropped_ids": ["上方 <<ID=...>> 中的原始 ID"]
}}

硬约束：
- themes 数量必须在 3 到 {max_themes} 之间
- 全部 themes 的 key_paper_ids 总数 ≤ {max_total_key}
- 每个 ID 只能出现一次（key_papers / mentions / noise_dropped 互斥）
- 所有 ID 必须严格来自上方 <<ID=...>> 列表，原样复制
- 所有字段必须是中文，executive_summary 要直接给判断而不是流水账

只输出 JSON，无任何额外文字、无 Markdown 代码块。
"""


STAGE2_DEEP_READ_TEMPLATE = """请对以下被选中的精读论文/工作做一份深度卡片。

---
标题: {title}
来源: {source}
链接: {url}
作者: {authors}
摘要 / 内容:
{content}
所属主题: {theme_title}
---

输出 JSON Schema:
{{
  "tldr": "1-2 句中文，直击核心贡献",
  "method": "2-3 句描述核心方法/技术路线，避免空话",
  "novelty": "1-2 句说明它的新颖之处（vs 现有 SOTA 或同主题前作）",
  "is_open_source": true/false,
  "has_benchmark_gain": true/false,
  "read_priority": "high 或 medium"
}}

判断标准：
- is_open_source：摘要中提到 code / checkpoint / weights / repo / github 即视为 true，否则 false
- has_benchmark_gain：明确给出 benchmark 数字提升或 SOTA 才 true
- read_priority: high — 方法新颖且实验扎实；medium — 不错但偏增量

只输出 JSON。
"""
