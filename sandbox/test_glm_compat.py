#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 ITINERA 的 LLM 调用能否切到 GLM-4。

ITINERA 用 `openai` SDK + 硬编码 model 名。GLM-4 提供 OpenAI 兼容端点，
理论上只需改 base_url + model 名。本脚本验证：
  1. openai SDK 版本兼容性
  2. chat 调用签名是否可用
  3. 是否能构造出 ITINERA 期望的调用形式

不实际消耗配额——只验证接口构造，除非设置了 GLM_API_KEY 才真调。
"""
import os
import sys
import inspect

HERE = os.path.dirname(os.path.abspath(__file__))
ITINERA_DIR = os.path.join(HERE, "ITINERA")
os.chdir(ITINERA_DIR)
sys.path.insert(0, ITINERA_DIR)

print("=" * 84)
print("ITINERA → GLM-4 兼容性验证")
print("=" * 84)

# ---- 1. openai SDK ----
print("--- 1. openai SDK ---")
try:
    import openai
    print(f"  ✓ openai {openai.__version__}")
except ImportError as e:
    print(f"  ✗ {e}")
    sys.exit(1)

# ---- 2. 复现 ITINERA 的调用形式 ----
print()
print("--- 2. ITINERA 的调用签名 ---")
import inspect
from openai import OpenAI
sig = inspect.signature(OpenAI.__init__)
print(f"  OpenAI(...) 参数: {list(sig.parameters)[:8]}")

# ITINERA 的实际调用（proxy_call.py）
code = inspect.getsource(
    __import__('model.utils.proxy_call', fromlist=['OpenaiCall']).OpenaiCall
)
print("  proxy_call.py 用到的 API:")
for line in code.splitlines():
    if 'client.' in line or 'model=' in line:
        print("    " + line.strip())

# ---- 3. 构造 GLM-4 客户端 ----
print()
print("--- 3. GLM-4 客户端构造（OpenAI 兼容模式）---")
GLM_KEY = os.environ.get("GLM_API_KEY") or os.environ.get("ZHIPUAI_API_KEY")
print(f"  GLM_API_KEY 环境变量: {'已设置' if GLM_KEY else '未设置'}")

try:
    client = OpenAI(
        api_key=GLM_KEY or "dummy-for-construction-test",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )
    print("  ✓ 客户端构造成功（base_url 指向智谱）")
    print(f"     chat.completions.create 可调用: "
          f"{callable(client.chat.completions.create)}")
    print(f"     embeddings.create 可调用: "
          f"{callable(client.embeddings.create)}")
except Exception as e:
    print(f"  ✗ 构造失败: {type(e).__name__}: {e}")

# ---- 4. 改造方案 ----
print()
print("--- 4. 改造方案（改 proxy_call.py，一个文件）---")
print("""
  import os
  from openai import OpenAI

  class OpenaiCall:
      def __init__(self):
          # 改这里：指向智谱 OpenAI 兼容端点
          self.client = OpenAI(
              api_key=os.getenv("GLM_API_KEY"),
              base_url="https://open.bigmodel.cn/api/paas/v4/",
          )

      def chat(self, messages, model="glm-4-flash", temperature=0):
          response = self.client.chat.completions.create(
              model=model, messages=messages, temperature=temperature)
          return response.choices[0].message.content

      def embedding(self, input_data):
          # GLM 的 embedding 模型名与 OpenAI 不同，需替换
          response = self.client.embeddings.create(
              input=input_data, model="embedding-3")
          return response
""")

# ---- 5. 若真有 key，做一次最小调用 ----
print("--- 5. 最小连通测试 ---")
if GLM_KEY:
    try:
        client = OpenAI(api_key=GLM_KEY,
                        base_url="https://open.bigmodel.cn/api/paas/v4/")
        r = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{"role": "user",
                       "content": '只返回 JSON：{"ok":true}'}],
            temperature=0)
        print(f"  ✓ GLM-4 调用成功")
        print(f"    响应: {r.choices[0].message.content[:100]}")
    except Exception as e:
        print(f"  ✗ 调用失败: {type(e).__name__}: {e}")
else:
    print("  跳过（未设置 GLM_API_KEY）")
    print("  设置后可执行： export GLM_API_KEY=<智谱key>")

print()
print("=" * 84)
print("结论：改造点集中在 proxy_call.py 一个文件")
print("=" * 84)
