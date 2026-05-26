STAGE1_PROMPT = """你是一个极为挑剔的计算机顶会资深审稿人与跨界创新专家。请评估下方论文是否对用户的研究方向具有跨界借鉴价值。

=== 用户研究背景 ===

{research_profile}

=== 任务 ===

请逐篇阅读论文标题和摘要，给出 1-10 的 suitability_score。
应用场景不相关不代表无价值；请重点判断底层方法、数学机制、训练策略、模型架构是否可以迁移到用户研究问题中。

请严格输出合法 JSON，格式如下。必须覆盖输入里的每个 id，不能新增或遗漏 id。

{{
  "results": [
    {{
      "id": "论文ID",
      "application_domain": "一句话概括原应用场景",
      "method_core": "一句话提炼核心方法或机制",
      "transferability_analysis": "结合用户研究背景分析迁移价值；无价值请直说",
      "suitability_score": 1
    }}
  ]
}}

=== 打分参考 ===

- 1-4：方法和应用都基本无关
- 5-7：有一定启发，但迁移关系间接或方法较普通
- 8-10：核心机制强相关，值得进入精读候选

=== 待评估论文 JSON ===

{papers_json}
"""


STAGE2_PROMPT = """你是一个极为严苛的顶级实验室 PI。请从候选论文中选出最值得精读的 {selection_min} 到 {selection_max} 篇。

=== 用户研究背景 ===

{research_profile}

=== 任务 ===

候选论文列表是 JSON 数组。请根据候选质量选择 {selection_min} 到 {selection_max} 篇。其余全部列入 rejected_papers，不能遗漏。

优先级：

1. 直击用户核心痛点
2. 跨界迁移后有明显 novelty
3. 方法通用、优雅、不是 trick 堆砌

请严格输出合法 JSON：

{{
  "selected_papers": [
    {{
      "id": "选中的论文ID",
      "selection_reason": "为什么它比同组其他论文更值得精读"
    }}
  ],
  "rejected_papers": [
    {{
      "id": "淘汰论文ID",
      "rejection_reason": "为什么不如选中的论文"
    }}
  ]
}}

=== 候选论文 JSON ===

{batch_papers}
"""
