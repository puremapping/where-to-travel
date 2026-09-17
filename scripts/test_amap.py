#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高德地图 Web 服务 API 实测

用途：验证 PRD 依赖的四个接口在个人认证配额下是否可用、返回结构如何。
用法：
    export AMAP_KEY=<你的key>
    python scripts/test_amap.py

接口与个人认证日配额（官方文档）：
    地理编码/逆地理编码   5000/日
    驾车/公交/步行/骑行路径规划  5000/日
    距离测量              5000/日
    关键字/周边/多边形搜索  100/日   ← 注意：这是最紧的配额
    输入提示              100/日
    天气查询              5000/日（按城市编码，非经纬度）

官方端点：https://restapi.amap.com
本脚本共消耗配额：约 10 次（远低于任一限额）
"""
import json
import os
import subprocess
import sys
import time

KEY = os.environ.get("AMAP_KEY")
if not KEY:
    print("错误：未设置环境变量 AMAP_KEY", file=sys.stderr)
    print("  git-bash:  export AMAP_KEY=<你的key>", file=sys.stderr)
    sys.exit(2)

BASE = "https://restapi.amap.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 高德的错误码
ERRORS = {
    "10000": "OK 请求正常",
    "10001": "INVALID_USER_KEY key不正确或过期",
    "10002": "SERVICE_NOT_AVAILABLE 没有权限使用该服务",
    "10003": "DAILY_QUERY_OVER_LIMIT 超出日访问量",
    "10004": "ACCESS_TOO_FREQUENT 单位时间访问过于频繁",
    "10005": "INVALID_USER_IP IP白名单出错",
    "10006": "INVALID_USER_DOMAIN 绑定域名无效",
    "10009": "USERKEY_PLAT_NOMATCH key与绑定平台不符",
    "10010": "IP_QUERY_OVER_LIMIT IP访问超限",
    "10012": "INSUFFICIENT_PRIVILEGES 权限不足",
    "10013": "USER_KEY_RECYCLED key被删除",
}

# 实测目标：只测本项目实际需要的两个接口
#
# 需要地理编码 —— 平台数据 0 坐标，地图渲染是硬前提
# 需要路径规划 —— 旅程预演要真实耗时
#
# 明确不测：
#   POI 搜索（配额仅 100/日，且平台已有 212 条景区数据，不需要批量搜）
#   天气（PRD 计划用和风，不由高德承担）
#   行政区/距离测量等（无当前需求）
TEST_CASES = [
    ("地理编码",
     "/v3/geocode/geo?address=故宫博物院&city=北京",
     "地址 -> 经纬度（地图渲染前提，5000/日）"),
    ("驾车路径规划",
     "/v3/direction/driving?origin=116.397128,39.916527&destination=116.407526,39.904030",
     "旅程预演耗时（5000/日）"),
]


def call(path, params=None):
    """调高德 REST API，path 里可带查询串"""
    sep = "&" if "?" in path else "?"
    url = f"{BASE}{path}{sep}key={KEY}"
    if params:
        url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
    r = subprocess.run(
        ["curl", "-sL", "--compressed", "--max-time", "20",
         "--noproxy", "*", "--ssl-no-revoke", "-A", UA, url],
        capture_output=True)
    try:
        return json.loads(r.stdout.decode("utf-8", errors="replace"))
    except Exception as e:
        return {"_parse_error": str(e),
                "_raw": r.stdout.decode("utf-8", errors="replace")[:300]}


def show(name, d, note):
    info = d.get("info", "")
    code = d.get("infocode", "")
    status = d.get("status", "?")
    ok = (status == "1" or info == "OK")
    mark = "✓" if ok else "✗"
    print(f"\n{mark} 【{name}】{note}")
    print(f"   status={status} info={info} infocode={code}")
    if not ok:
        print(f"   → {ERRORS.get(code, '未知错误')}")
        return False
    # 按接口类型显示关键字段
    if "geocodes" in d:
        for g in d["geocodes"][:2]:
            print(f"   {g.get('formatted_address')} | {g.get('location')}")
    elif "regeocode" in d:
        rg = d["regeocode"]
        print(f"   {rg.get('formatted_address')}")
    elif "pois" in d:
        print(f"   共 {d.get('count')} 条")
        for p in d["pois"][:3]:
            print(f"   {p.get('name')} | {p.get('location')} | {p.get('type', '')[:30]}")
    elif "route" in d:
        paths = d["route"].get("paths", [])
        if paths:
            p = paths[0]
            print(f"   距离 {p.get('distance')}m  耗时 {p.get('duration')}s")
    elif "results" in d:
        for r_ in d["results"][:3]:
            print(f"   距离 {r_.get('distance')}m  耗时 {r_.get('duration')}s")
    elif "lives" in d or "forecasts" in d:
        arr = d.get("lives") or d.get("forecasts") or []
        if arr:
            f = arr[0]
            print(f"   {f.get('province')}{f.get('city')} {f.get('weather')} {f.get('temperature')}℃")
    elif "districts" in d:
        for x in d["districts"][:1]:
            print(f"   {x.get('name')} | adcode={x.get('adcode')} | 中心={x.get('center')}")
    return True


def main():
    print("=" * 80)
    print("高德地图 Web 服务 API 实测")
    print(f"key: {KEY[:6]}...{KEY[-4:]}  (长度 {len(KEY)})")
    print("=" * 80)

    results = {"ok": [], "fail": []}
    for name, path, note in TEST_CASES:
        d = call(path)
        if show(name, d, note):
            results["ok"].append(name)
        else:
            results["fail"].append((name, d.get("infocode"), d.get("info")))
        time.sleep(0.4)   # 避免触发 10004 频率限制

    print("\n" + "=" * 80)
    print(f"结果：成功 {len(results['ok'])} / {len(TEST_CASES)}")
    if results["fail"]:
        print("\n失败项：")
        for n, c, i in results["fail"]:
            print(f"  ✗ {n}: {c} {i}  ({ERRORS.get(c, '')})")
    print("=" * 80)

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", ".research", "amap_test.json"), "w",
              encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
