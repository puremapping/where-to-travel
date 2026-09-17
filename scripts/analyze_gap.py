#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析：北京景区数据的坐标缺口 + 与已有交通数据的关系

回答两个问题：
1. 有多少景区需要地理编码（有地址、无经纬度）？
2. 平台的交通数据覆盖到什么程度，高德需要补什么？
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.abspath(os.path.join(HERE, "..", ".research"))


def load_scenic():
    p = os.path.join(R, "北京市等级景区信息.csv")
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.reader(f) if any(r)]
    hdr, body = rows[0], rows[1:]
    # 列：序号, 景区名称, 等级, 所在区, 地址, 咨询电话, 邮编
    out = []
    for r in body:
        if len(r) < 5:
            continue
        out.append({
            "name": r[1].strip(),
            "level": r[2].strip(),
            "district": r[3].strip(),
            "address": r[4].strip(),
        })
    return out


def load_traffic():
    import openpyxl
    p = os.path.join(R, "等级景区交通信息.xlsx")
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb.active
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    wb.close()
    hdr = [str(c) for c in rows[0]]
    out = []
    for r in rows[1:]:
        d = {}
        for h, v in zip(hdr, r):
            d[h] = "" if v is None else str(v).strip()
        out.append(d)
    return hdr, out


def main():
    scenic = load_scenic()
    hdr, traffic = load_traffic()

    print("=" * 84)
    print("一、坐标缺口分析")
    print("=" * 84)
    print(f"等级景区总数: {len(scenic)}")
    has_addr = [s for s in scenic if s["address"]]
    print(f"有地址的:     {len(has_addr)}  ({len(has_addr)*100//len(scenic)}%)")
    print(f"无经纬度:     {len(scenic)}  (100%) ← 平台数据不含坐标，全部需地理编码")
    print()
    print("按等级分布:")
    from collections import Counter
    for lv, n in Counter(s["level"] for s in scenic).most_common():
        print(f"   {lv or '(空)'}: {n}")
    print()
    print("按区域分布（前10）:")
    for d_, n in Counter(s["district"] for s in scenic).most_common(10):
        print(f"   {d_ or '(空)'}: {n}")

    print()
    print("=" * 84)
    print("二、已有交通数据 vs 高德能力")
    print("=" * 84)
    print(f"交通表条数: {len(traffic)}   (景区表 {len(scenic)} 条，差 {abs(len(traffic)-len(scenic))})")
    print()
    print("字段填充率与可替代性:")
    body = traffic
    assessment = {
        "地铁": ("✅ 已有", "高德可补站点精确距离"),
        "公交": ("✅ 已有", "高德可补线路"),
        "依托高速公路或环路名称及距离（KM）": ("✅ 已有", "高德可补精确耗时"),
        "通达景区支线公路等级及距离（KM）": ("✅ 已有", "—"),
        "依托机场的名称及距离（KM）": ("✅ 已有", "高德可补精确路径"),
        "依托客运火车站、汽车站、码头的名称及距离（KM）": ("✅ 已有", "高德可补精确路径"),
        "依托城镇名称及距离（KM）": ("✅ 已有", "—"),
    }
    for h in hdr:
        filled = sum(1 for r in body if r.get(h))
        pct = filled * 100 // len(body) if body else 0
        note = assessment.get(h, ("", ""))
        flag = note[0] if note else ""
        print(f"   {h[:34]:<36} {filled:>3}/{len(body)} ({pct:>3}%)  {flag}")

    print()
    print("=" * 84)
    print("三、结论：高德真正不可替代的能力")
    print("=" * 84)
    print("""
平台已覆盖（不必依赖高德）:
  · 交通方式（地铁站名、公交线路）
  · 距离（公里级，官方权威）
  · 地址、电话、等级、门票价格

高德唯一不可替代:
  · 经纬度坐标 —— 地图渲染的硬前提（平台数据 0 坐标）
  · 实时路况 —— 旅程预演需要
  · 精确路径耗时 —— 分钟级
  · 前端地图 JS SDK

配额测算（个人认证）:
  · 地理编码 5000/日 → 按需使用即可，不做批量预热
  · POI 搜索 100/日  → 若用关键字搜索批量建库，100 次/日 严重不足
  · 建议：坐标「按需编码」——用到哪个景区编哪个
          POI 搜索只用于按需查询，不做批量
""".strip())

    # 输出按需编码用的地址清单（非批量任务）
    out = os.path.join(R, "geocode_todo.json")
    import json
    with open(out, "w", encoding="utf-8") as f:
        json.dump(has_addr, f, ensure_ascii=False, indent=1)
    print(f"\n地址清单已导出（按需编码时查用）: geocode_todo.json ({len(has_addr)} 条)")
    print("⚠️ 不要批量编码——配额虽够，但当前阶段无此需求")


if __name__ == "__main__":
    main()
