# AI Paper Selector

AI Paper Selector 是一个面向科研选题和文献调研的论文筛选工具。它把大型 accepted paper 列表分阶段压缩成少量值得精读的论文，适合处理 ICLR、NeurIPS、ICML 等会议论文列表。

核心流程分三步：

1. `Select1_Eval.py`：读取论文标题和摘要，根据研究画像批量打分。
2. `Select1_Filter.py`：按分数阈值过滤候选，不重新调用 API。
3. `Select2_PK.py`：对候选论文做分组横向比较，逐轮淘汰。

本仓库内置 `Raw_Dataset/iclr2026.json`，可直接用于 ICLR 2026 accepted papers 的筛选。

## 目录结构

```text
AI_Paper_Selector/
├── src/
│   ├── Collect_Paper.py          # 从 OpenReview 采集 accepted papers
│   ├── Select1_Eval.py           # Stage 1：批量评估，写 JSONL checkpoint
│   ├── Select1_Filter.py         # Stage 1：按阈值过滤，生成 JSON
│   ├── Select2_PK.py             # Stage 2：分组 PK / 淘汰式终筛
│   └── common/                   # 通用 IO、LLM 调用和 prompts
├── Raw_Dataset/
│   └── iclr2026.json             # ICLR 2026 accepted papers
└── Select_Results/
    └── Example_Project/
        ├── Research_Profile/
        │   ├── Select1_Standard.md
        │   └── Select2_Standard.md
        └── Select_Results/
            ├── Select1_Eval/
            ├── Select1_Filter/
            ├── Select2_PK1/
            ├── Select2_PK2/
            └── Select2_PK3/
```

## 安装

推荐使用 conda 管理环境：

```bash
conda create -n ai_paper_selector python=3.11 -y
conda activate ai_paper_selector
pip install -r requirements.txt
```

如果只使用已有 JSON 数据，主要依赖是 `openai`。如果需要重新从 OpenReview 采集论文，还需要 `openreview-py`，已包含在 `requirements.txt` 中。

## API 配置

本项目使用 OpenAI-compatible Chat Completions API。运行筛选脚本前设置：

```bash
export OPENAI_API_KEY="your-api-key"
```

如果使用中转站或自建网关：

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-relay.example.com/v1"
```

默认不启用 JSON Mode，以兼容更多 OpenAI-compatible 网关。如果你的 API 支持 JSON Mode，可以在运行脚本时加入 `--json-mode`。

## 数据格式

`Raw_Dataset/iclr2026.json` 是 JSON 数组，每条论文至少包含：

```json
[
  {
    "id": "paper_id",
    "title": "Paper Title",
    "abstract": "Paper abstract"
  }
]
```

你可以替换成自己的会议数据，只要保留 `id/title/abstract` 三个字段。

## 0. 可选：采集论文

仓库已经内置 ICLR 2026 数据，通常不需要重新采集。如果要从 OpenReview 重新拉取：

```bash
python src/Collect_Paper.py \
  --venue-id ICLR.cc/2026/Conference \
  --output Raw_Dataset/iclr2026.json
```

## 1. Stage 1 Eval：批量评估

先编辑：

```text
Select_Results/Example_Project/Research_Profile/Select1_Standard.md
```

然后运行：

```bash
python src/Select1_Eval.py \
  --papers Raw_Dataset/iclr2026.json \
  --profile Select_Results/Example_Project/Research_Profile/Select1_Standard.md \
  --output Select_Results/Example_Project/Select_Results/Select1_Eval/stage1_results.jsonl \
  --log-file Select_Results/Example_Project/Select_Results/Select1_Eval/run.log \
  --model gpt-5.5 \
  --batch-size 10
```

`stage1_results.jsonl` 是断点续传 checkpoint。每篇论文评分成功后会立即追加一行；中断后重新运行同一命令，会自动跳过已处理的 `id`。

常用参数：

```text
--batch-size 10          每次请求放几篇论文
--sleep-seconds 1        每次成功请求后的休眠秒数
--max-retries 5          API 报错最多重试次数
--limit 100              只测试前 100 篇
--json-mode              启用 OpenAI JSON Mode
--restart                删除旧 checkpoint 后重跑
```

## 2. Stage 1 Filter：阈值过滤

Stage 1 的打分和过滤是解耦的。改阈值不需要重新调用 API。

```bash
python src/Select1_Filter.py \
  --results Select_Results/Example_Project/Select_Results/Select1_Eval/stage1_results.jsonl \
  --output Select_Results/Example_Project/Select_Results/Select1_Filter/stage1_filtered.json \
  --log-file Select_Results/Example_Project/Select_Results/Select1_Filter/run.log \
  --threshold 8
```

如果想更严格，可以把 `--threshold` 改成 `9`。

## 3. Stage 2 PK：淘汰式终筛

Stage 2 会读取候选论文，但只把 `id/title/abstract` 传给模型，不会把 Stage 1 的分数和评价传入 prompt。

先编辑：

```text
Select_Results/Example_Project/Research_Profile/Select2_Standard.md
```

运行第一轮：

```bash
python src/Select2_PK.py \
  --candidates Select_Results/Example_Project/Select_Results/Select1_Filter/stage1_filtered.json \
  --profile Select_Results/Example_Project/Research_Profile/Select2_Standard.md \
  --output-dir Select_Results/Example_Project/Select_Results/Select2_PK1 \
  --final-output Select_Results/Example_Project/Select_Results/Select2_PK1/final_output.json \
  --log-file Select_Results/Example_Project/Select_Results/Select2_PK1/run.log \
  --model gpt-5.5 \
  --batch-size 15 \
  --selection-target 2 \
  --max-rounds 1
```

`--selection-target 2` 表示每组选择 1 到 3 篇；脚本会自动使用 `{selection_target-1}` 到 `{selection_target+1}` 的范围。

如果第一轮输出仍然较多，可以把上一轮的 `round1_output.json` 作为下一轮输入：

```bash
python src/Select2_PK.py \
  --candidates Select_Results/Example_Project/Select_Results/Select2_PK1/round1_output.json \
  --profile Select_Results/Example_Project/Research_Profile/Select2_Standard.md \
  --output-dir Select_Results/Example_Project/Select_Results/Select2_PK2 \
  --log-file Select_Results/Example_Project/Select_Results/Select2_PK2/run.log \
  --model gpt-5.5 \
  --batch-size 20 \
  --selection-target 2 \
  --max-rounds 1 \
  --start-round 2
```

每一轮只保留两个核心文件：

```text
round{x}_output.json    # 本轮完整输出，包含 batch 决策和 selected_candidates
run.log                 # 本轮运行日志
```

`round{x}_output.json` 使用缩进格式，便于人工查看；其中 `selected_papers` 和 `rejected_papers` 使用论文标题展示。

## 隐私与 Git

真实的研究画像、筛选结果和日志可能包含个人研究偏好、API 报错信息或中转站信息。仓库默认忽略真实生成文件：

```text
Select_Results/**
*.log
```

只保留 `Example_Project` 里的通用模板、`.gitkeep` 和 `*_sample.json`。如果你创建自己的项目分支，建议不要把真实 `Research_Profile`、`stage1_results.jsonl`、`round{x}_output.json` 或日志提交到公开仓库。

## 推荐工作流

1. 修改 `Select1_Standard.md`，写宽松的初筛标准。
2. 跑 `Select1_Eval.py`，得到完整评分 JSONL。
3. 跑 `Select1_Filter.py`，用不同阈值控制候选规模。
4. 人工浏览过滤结果，排除不想继续探索的方向。
5. 修改 `Select2_Standard.md`，写更严格的终筛标准。
6. 跑一轮或多轮 `Select2_PK.py`，得到最终精读列表。
