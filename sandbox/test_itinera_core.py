#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 ITINERA 的非 LLM 部分能否在本机 Python 3.13 跑通。

分三步：
  1. 数据加载（CSV + NPY）
  2. 空间聚类（spatial.py，不调 LLM）
  3. TSP 排序（python_tsp，不调 LLM）

这些跑通 = 核心算法可用；剩下要验证的只有 LLM 调用。
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))       # sandbox/
ITINERA_DIR = os.path.join(HERE, "ITINERA")
os.chdir(ITINERA_DIR)
sys.path.insert(0, ITINERA_DIR)

import numpy as np
import pandas as pd

CITY = "shanghai"
TYPE = "zh"

print("=" * 84)
print("ITINERA 非 LLM 部分验证")
print("=" * 84)
print(f"Python: {sys.version.split()[0]}")
print(f"工作目录: {os.getcwd()}")
print()

# ---- 1. 数据加载 ----
print("--- 1. 数据加载 ---")
try:
    csv_path = f"model/data/{CITY}_{TYPE}.csv"
    npy_path = f"model/data/{CITY}_{TYPE}.npy"
    data = pd.read_csv(csv_path)
    emb = np.load(npy_path)
    print(f"  ✓ CSV  {csv_path}")
    print(f"    形状: {data.shape}  列: {list(data.columns)}")
    print(f"  ✓ NPY  {npy_path}")
    print(f"    形状: {emb.shape}   dtype: {emb.dtype}")
    if len(data) != len(emb):
        print(f"  ⚠ 行数不匹配: CSV {len(data)} vs NPY {len(emb)}")
except Exception as e:
    print(f"  ✗ 失败: {e}")
    traceback.print_exc()
    sys.exit(1)
print()

# ---- 2. 空间聚类 ----
print("--- 2. 空间聚类（SpatialHandler）---")
try:
    from model.spatial import SpatialHandler
    # 注意：get_clusters 接收的是 DataFrame 的 index 标签，
    # 不是 id 列的值。真实调用链是 i2r[poi_id] → 行号。
    data = data.reset_index(drop=True)          # 与 get_user_data_embedding 一致
    handler = SpatialHandler(
        data=data, min_clusters=2, min_pois=9,
        citywalk=True, citywalk_thresh=5000)
    row_indices = list(data.index)              # 0..N-1
    clusters = handler.get_clusters(row_indices, thresh=5000)
    print(f"  ✓ 聚类成功")
    print(f"    簇数: {len(clusters)}")
    for i, c in enumerate(clusters):
        names = [data.loc[r, 'name'] for r in c if r in data.index]
        print(f"    簇{i}: {len(c)} 个 → {names[:4]}")
except Exception as e:
    print(f"  ✗ 失败: {type(e).__name__}: {e}")
    traceback.print_exc()
print()

# ---- 3. TSP 排序 ----
print("--- 3. TSP 路径排序（模拟退火）---")
try:
    from python_tsp.heuristics import solve_tsp_simulated_annealing
    import scipy.spatial.distance as sd

    coords = data[["x", "y"]].astype(float).to_numpy()
    dist = sd.cdist(coords, coords)
    np.fill_diagonal(dist, 1e9)
    perm, cost = solve_tsp_simulated_annealing(dist)
    print(f"  ✓ TSP 求解成功")
    print(f"    访问顺序: {perm}")
    print(f"    总距离: {cost:.1f} (投影坐标单位)")
    print(f"    路径: {' → '.join(data['name'].iloc[i][:8] for i in perm)}")
except Exception as e:
    print(f"  ✗ 失败: {type(e).__name__}: {e}")
    traceback.print_exc()
print()

# ---- 4. 坐标转换 ----
print("--- 4. GCJ-02 → WGS-84 坐标转换 ---")
try:
    from xyconvert import gcj2wgs
    gcj = data[["lon", "lat"]].to_numpy()
    wgs = gcj2wgs(gcj[:3])
    print(f"  ✓ 转换成功")
    for i in range(min(3, len(gcj))):
        print(f"    {data['name'].iloc[i][:12]:<14} "
              f"GCJ02({gcj[i][0]:.6f},{gcj[i][1]:.6f}) → "
              f"WGS84({wgs[i][0]:.6f},{wgs[i][1]:.6f})")
except Exception as e:
    print(f"  ✗ 失败: {type(e).__name__}: {e}")
    traceback.print_exc()

print()
print("=" * 84)
print("验证完成")
print("=" * 84)
