#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行程叙述 + 可解释推荐

把结构化的行程数据交给 LLM，生成：
  1. 行程叙述（人话）
  2. 每条推荐的可解释理由（自然语言）
  3. 整体评估（强度、风险、建议）

设计参考 ITINERA 的 Prompt 范式（docs/research/arxiv-findings.md）：
  - 角色设定 + 任务概述 + 输出规范
  - 强制 JSON 输出，禁止多余解释
"""
from app.services.llm import LLM

NARRATIVE_PROMPT = """你是旅行规划助手。用户告诉我这次旅行的动机和行程安排，你负责把它讲成一段自然、有画面感的叙述。

要求：
1. 用第二人称"你"，像朋友在给建议
2. 结合动机解释"为什么这条路线适合你"
3. 提到具体的景点名和时间点
4. 指出需要注意的地方（人流、交通）
5. 150-250 字，不要用 Markdown 标记，纯文本

只返回叙述文本，不要任何前缀或解释。
"""

ASSESS_PROMPT = """你是旅行规划助手。根据给出的行程，给出简短评估。

只返回 JSON，格式：
{"intensity":"低/中/高","strength":"整体强度一句话","suggestion":"一条最实用的建议"}

不要任何解释。"""


def narrate(itinerary_dict: dict, motivation: str, llm=None) -> str:
    """生成行程叙述"""
    llm = llm or LLM()

    stops_desc = "\n".join(
        f"{s['arrive']} {s['name']}（{s['level']}，{s['district']}）"
        + (f"，人流指数 {s['crowd']:.0f}" if s.get("crowd") is not None else "")
        for s in itinerary_dict["stops"]
    )

    risks = "；".join(itinerary_dict.get("risks", [])) or "无明显风险"

    user = f"""旅行动机：{motivation}
行程时长：{itinerary_dict['hours']} 小时
总距离：{itinerary_dict['total_distance_km']} 公里

行程安排：
{stops_desc}

风险提示：{risks}

请把这条行程讲给用户听。"""

    return llm.chat([
        {"role": "system", "content": NARRATIVE_PROMPT},
        {"role": "user", "content": user},
    ], temperature=0.7).strip()


def assess(itinerary_dict: dict, llm=None) -> dict:
    """行程强度评估"""
    llm = llm or LLM()
    n = len(itinerary_dict["stops"])
    km = itinerary_dict["total_distance_km"]
    hours = itinerary_dict["hours"]

    user = (f"行程共 {n} 个景点，{hours} 小时，总距离 {km} 公里。"
            f"站点：{'、'.join(s['name'] for s in itinerary_dict['stops'])}")

    d = llm.json_chat([
        {"role": "system", "content": ASSESS_PROMPT},
        {"role": "user", "content": user},
    ])
    if isinstance(d, dict):
        return {
            "intensity": d.get("intensity", "中"),
            "strength": d.get("strength", ""),
            "suggestion": d.get("suggestion", ""),
        }
    return {"intensity": "中", "strength": "", "suggestion": ""}


EXPLAIN_PROMPT = """你是推荐解释助手。用户有明确的旅行动机，系统推荐了这些景点。

你的任务：为每个景点写一句推荐理由，说明它为什么契合用户动机。

要求：
1. 每条不超过 40 字
2. 结合动机，不要泛泛而谈
3. 如果已知人流数据，可以提及

只返回 JSON 数组，格式：["理由1","理由2",...]
不要任何解释。"""


def explain(pois: list, motivation: str, llm=None) -> list:
    """为一批景点生成可解释理由"""
    llm = llm or LLM()
    if not pois:
        return []

    lines = "\n".join(
        f"{i+1}. {p['name']}（{p.get('level','')}，{p.get('district','')}）"
        for i, p in enumerate(pois)
    )

    d = llm.json_chat([
        {"role": "system", "content": EXPLAIN_PROMPT},
        {"role": "user", "content": f"用户动机：{motivation}\n\n推荐景点：\n{lines}"},
    ])
    if isinstance(d, list):
        return [str(x) for x in d][:len(pois)]
    return [p.get("reasons", [""])[0] if p.get("reasons") else "" for p in pois]
