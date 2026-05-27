# 计划书：把 ai-daily-briefing + 读论文 打包成 Claude Code Skills

**起草日期**：2026-05-22
**状态**：待用户审阅 / 未实施

---

## 1. 目标

把两个工作流封装成 Claude Code 可以直接路由的 skill：

1. **生成 / 重渲染 AI 日报**（已有 CLI，封装即可）
2. **按 ⭐ 模板读 arxiv 论文做中文笔记**（新功能）

让用户在 Claude Code 任意会话里说"今天的 AI 日报"或"读一下 2501.12345"就能触发，无需手敲 CLI。

---

## 2. 范围

**包含**：
- 在 `~/.claude/skills/` 下创建两个 user-level skill 目录
- 在 `ai-daily-briefing/` 下新建 `papers/` 子目录及 10 个分类子目录 + `_inbox/`
- 把 `learning-material-agent/resources/papers/_template.md` 复制到 `ai-daily-briefing/papers/_template.md`
- 写两份 `SKILL.md`（YAML frontmatter + 中文正文指令）
- 写一份 `papers/README.md` 说明分类规则

**不包含**：
- 修改 `briefing` Python 包源码
- 触碰 `learning-material-agent/` 任何内容（只复制一次模板）
- 调度 / 自动化（cron、任务计划程序）
- PDF 下载（见 §3.5 决策）

---

## 3. 设计决策

### 3.1 拆成两个 skill 而非一个

Skill 路由完全靠 `description` 字段。日报和读论文触发场景无交集，合并会让 description 模糊、路由不准。两个独立 skill 共享一个父目录最清爽。

### 3.2 装在 user 级（`~/.claude/skills/`）

- `briefing` CLI 通过 conda env 全局调用，不依赖 cwd
- 读论文功能在任何项目下都可能想用
- project 级（`ai-daily-briefing/.claude/skills/`）只在该 repo 下生效，限制太大

### 3.3 笔记落地到 `ai-daily-briefing/papers/`

让这个 repo 同时承载"日报"和"论文笔记"两类输出，统一管理，VSCode 一个 workspace 看完。

### 3.4 路径硬编码 vs 环境变量

**默认推荐：硬编码绝对路径** `c:/Users/Yan Lijun/Desktop/ai-daily-briefing/papers/`。

- 用户当前单机使用，硬编码最简单
- 未来换机器时改两个 `SKILL.md` 文件即可（一次性成本低）
- 引入环境变量会让 skill 多一步"如果未设置则报错"的逻辑，复杂度不划算

如果用户后续需要跨机器同步，再改成 `$AI_BRIEFING_HOME` 环境变量。

### 3.5 模板：复制不软链

- 复制保证 skill 自包含，`learning-material-agent` 那边改了不会污染这边
- Windows 软链需要管理员权限，体验差
- 模板内容稳定，复制一次即可；若未来想同步更新由用户手动 diff

### 3.6 不自动下载 PDF

- arxiv HTML 版（`arxiv.org/html/{id}`）已能拿到正文，配合 abstract 足够填模板
- 下载 PDF 会让 skill 跨越"读 / 写文件"边界，且每篇论文几 MB，一年下来占空间
- 模板里 `[{pdf_filename}]({pdf_filename})` 这一行改成 PDF 外链 `https://arxiv.org/pdf/{id}`，需要时点开下载

---

## 4. 目录结构（最终态）

```
~/.claude/skills/
├── ai-briefing/
│   └── SKILL.md
└── read-paper/
    └── SKILL.md

c:\Users\Yan Lijun\Desktop\ai-daily-briefing\
├── reports/                    # 已有，不动
├── papers/                     # 新建
│   ├── _template.md            # 从 learning-material-agent 复制
│   ├── README.md               # 分类规则 + 命名约定
│   ├── _inbox/                 # 分类不确定时的暂存区
│   ├── agent-foundations/
│   ├── embodied-agents/
│   ├── llm-infra/
│   ├── memory/
│   ├── multimodal-models/
│   ├── planning/
│   ├── reasoning/
│   ├── retrieval/
│   └── tool-use/
├── src/, tests/, ...           # 已有，不动
└── SKILL_PLAN.md               # 本文件，实施完成后可删
```

---

## 5. Skill 1 设计 — `ai-briefing`

### 5.1 Frontmatter

```yaml
---
name: ai-briefing
description: Generate or re-render the daily AI news briefing using the local
  `briefing` CLI in conda env `ai-briefing`. Use when the user asks for
  "today's AI briefing", "今日 AI 日报", "重新渲染 X 日的日报", or wants to
  inspect collector status / DB stats.
---
```

### 5.2 正文（中文指令骨架）

- **触发场景示例**：列 3-5 句典型用户话术
- **核心命令表**：
  | 用户意图 | 命令 |
  |---|---|
  | 跑今天的完整日报 | `conda run -n ai-briefing briefing run` |
  | 重渲染历史日报 | `conda run -n ai-briefing briefing render --date YYYY-MM-DD` |
  | 只采集不总结 | `conda run -n ai-briefing briefing run --no-summarize --no-render` |
  | 单源调试 | `conda run -n ai-briefing briefing test-source <name> --limit 5` |
  | DB 状态 | `conda run -n ai-briefing briefing db stats` |
- **输出位置**：`c:/Users/Yan Lijun/Desktop/ai-daily-briefing/reports/YYYY-MM-DD.md`，完成后用 markdown 链接给用户点开
- **故障排查顺序**：API key 缺失 → 看 `.env` / `db stats` → 单源 `test-source` 复现
- **已知约束**：Windows 控制台默认 GBK，CLI 已自处理，不要在 skill 里加 `print` 中文 emoji

---

## 6. Skill 2 设计 — `read-paper`

### 6.1 Frontmatter

```yaml
---
name: read-paper
description: Read an arxiv paper (by ID or abs/pdf URL) and write a structured
  Chinese reading note using the ⭐ template, saving it to
  ai-daily-briefing/papers/{category}/. Use when the user gives an arxiv ID,
  arxiv URL, or asks to "读一下 / 精读 / 笔记 这篇论文".
---
```

### 6.2 正文（中文指令骨架）

1. **输入归一化**：解析以下形式为标准 arxiv ID
   - `2501.12345` / `2501.12345v2`
   - `https://arxiv.org/abs/2501.12345`
   - `https://arxiv.org/pdf/2501.12345.pdf`

2. **抓取顺序**：
   - 第一步：`WebFetch https://arxiv.org/abs/{id}` 拿标题、作者、abstract、提交日期
   - 第二步：`WebFetch https://arxiv.org/html/{id}` 拿正文（method / experiment 细节）
   - 失败回退：HTML 版不存在的老论文，提示用户给本地 PDF 路径，用 Read 工具读

3. **分类决策树**（10 个目录映射）：
   - 具身 / robot / VLA / manipulation → `embodied-agents`
   - VLM / image-text / video → `multimodal-models`
   - RAG / retriever / dense passage → `retrieval`
   - chain-of-thought / o1-like / RL for reasoning → `reasoning`
   - tool calling / function call / agent benchmark → `tool-use`
   - long-term memory / context compression → `memory`
   - planner / world model → `planning`
   - serving / vLLM / quantization / kernel → `llm-infra`
   - ReAct 类 / agent harness 综述 → `agent-foundations`
   - **不确定** → `_inbox/`，并在笔记开头加一行 `> ⚠️ 待分类，请人工移动`

4. **填模板规则**：
   - 复制 `papers/_template.md` 内容作为骨架
   - ⭐ 段必填，不能写"待补充"占位
   - 🔹 段按论文性质判断：survey / benchmark / 方法论文 各有不同
   - §3 方法部分严禁压缩（template 自身有强约束，照办）
   - PDF 字段填外链 `https://arxiv.org/pdf/{id}`

5. **命名 & 落盘**：
   - 文件名：`{arxiv_id}-{slug}.md`，slug 由标题去停用词、kebab-case，最长 8 词
   - 例：`2501.12345-code-as-agent-harness.md`
   - 用 Write 工具写到对应分类目录

6. **完成后**：返回 markdown 链接给用户点开校对

---

## 7. 实施步骤（待批准后按序执行）

1. 在 `ai-daily-briefing/` 新建 `papers/` + 10 个分类子目录 + `_inbox/`
2. 复制 `learning-material-agent/resources/papers/_template.md` → `papers/_template.md`
3. 写 `papers/README.md`（分类规则 + 命名约定，~30 行）
4. 在 `~/.claude/skills/ai-briefing/` 写 `SKILL.md`
5. 在 `~/.claude/skills/read-paper/` 写 `SKILL.md`
6. **冒烟测试**：
   - 重启 / `/help` 确认两个 skill 在用户可用列表里
   - 试触发 `ai-briefing`：让 Claude 跑 `briefing db stats`
   - 试触发 `read-paper`：给一个最近的 arxiv ID，看能不能完整生成笔记
7. 实施完成后删除本 `SKILL_PLAN.md`

---

## 8. 验收标准

- [ ] `~/.claude/skills/ai-briefing/SKILL.md` 存在，frontmatter 合法
- [ ] `~/.claude/skills/read-paper/SKILL.md` 存在，frontmatter 合法
- [ ] `papers/_template.md` 与原模板字节一致
- [ ] 10 个分类目录 + `_inbox/` 都创建（即使是空目录，可放 `.gitkeep`）
- [ ] 在新会话里说"跑下今天的日报"能正确路由到 `ai-briefing`
- [ ] 在新会话里说"读一下 arxiv 2501.xxxxx"能正确路由到 `read-paper` 并生成结构完整的笔记

---

## 9. 风险 & 已知约束

| 风险 | 缓解 |
|---|---|
| Skill description 写得不够具体导致路由失败 | 实施时多列触发例句，冒烟测试时用真实话术验证 |
| arxiv HTML 版对老论文（2022 年前）覆盖不全 | 回退到提示用户给本地 PDF |
| 分类决策树模糊地带（例：VLA = embodied? multimodal?） | 引入 `_inbox/` 兜底，不强求一次到位 |
| 用户换机器后绝对路径失效 | 一次性改两个 SKILL.md；后续如频繁换机再考虑环境变量 |
| 长论文 WebFetch 截断 | HTML 版按章节 fetch，必要时分两次拿 method 和 experiment |

---

## 10. 后续可扩展（不在本次范围）

- `read-paper` 增加"批量精读模式"：给一个论文列表，串行生成
- `ai-briefing` 增加"只挑某个分类的日报"参数
- 把 `papers/` 用 git submodule 挂到 `learning-material-agent` 实现笔记同步
- 加 `digest-paper` 第三个 skill：从已有笔记里提取"延伸问题"做下一步阅读规划
