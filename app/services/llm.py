#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 客户端封装（GLM-4 Flash，OpenAI 兼容）"""
import json
import re
from typing import Any

from openai import OpenAI

from app.core.config import GLM_API_KEY, GLM_BASE_URL, GLM_MODEL, GLM_MODEL_FALLBACK


class LLM:
    def __init__(self):
        if not GLM_API_KEY:
            raise RuntimeError("未设置 GLM_API_KEY")
        self.client = OpenAI(api_key=GLM_API_KEY, base_url=GLM_BASE_URL)
        self.model = GLM_MODEL

    def chat(self, messages, temperature=0.3, model=None) -> str:
        r = self.client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
        )
        return r.choices[0].message.content or ""

    def json_chat(self, messages, temperature=0.1) -> Any:
        """要求返回 JSON，并做健壮解析（LLM 常包 ```json ```）"""
        text = self.chat(messages, temperature=temperature)
        return parse_json(text)


def parse_json(text: str) -> Any:
    """从 LLM 输出里抠出 JSON。

    GLM 常见返回形式：
      1. 纯 JSON
      2. ```json ... ``` 包裹
      3. 前后带说明文字
    """
    if not text:
        return None
    t = text.strip()

    # 剥 Markdown 代码块
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()

    # 直接试
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # 抠第一个 { ... } 或 [ ... ]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = t.find(open_c)
        end = t.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None
