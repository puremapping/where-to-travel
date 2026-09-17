#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北京市公共数据开放平台 - 旅游数据集批量抓取

调用方式：通过 curl 子进程发起请求（Python 的 urllib 在该站会 403，
curl 正常。原因未完全定位，疑似 TLS/HTTP 栈差异，实测 curl 稳定）。
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

# key 从环境变量读取，不写死在脚本里（凭证不入库）
#
# ⚠️ key 是滚动值，旧值会立即失效（实测存活 5-10 分钟）。
#    每次打开个人中心「我的唯一码」页面都会生成新 key 并使旧值作废。
#    用前必须刷新，或确保在一次会话内完成全部下载。
#    自动获取见 fetch_key_via_browser()。
KEY = os.environ.get("BJ_OPEN_DATA_KEY")
if not KEY:
    print("错误：未设置环境变量 BJ_OPEN_DATA_KEY", file=sys.stderr)
    print("  git-bash:  export BJ_OPEN_DATA_KEY=<唯一标识码>", file=sys.stderr)
    print("  或 source .env", file=sys.stderr)
    print("  ⚠️ key 会滚动失效，用前请从个人中心页面重新获取", file=sys.stderr)
    sys.exit(2)

BASE = "https://data.beijing.gov.cn"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", ".research"))
os.makedirs(OUT, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CURL = ["curl", "-sL", "--compressed", "--max-time", "30",
        "--noproxy", "*", "--ssl-no-revoke", "-A", UA]


def get_text(url):
    r = subprocess.run(CURL + [url], capture_output=True)
    return r.stdout.decode("utf-8", errors="replace")


def get_json(url):
    t = get_text(url)
    try:
        return json.loads(t)
    except Exception:
        return {"_raw": t[:500], "_error": "not json"}


def download(url, path):
    r = subprocess.run(CURL + ["-o", path, url], capture_output=True)
    return os.path.exists(path) and os.path.getsize(path) > 0


def list_datasets(department=None, subject=None, page_size=500):
    p = {"pageSize": page_size, "curPage": 1}
    if department:
        p["department"] = department
    if subject:
        p["subject"] = subject
    url = BASE + "/cms/web/search?" + urllib.parse.urlencode(p)
    return get_json(url)


def resolve_file_ids(content_id):
    """从 dataDoc.jsp 说明文档解析「文件编号」

    该页面是一张表格：名称 | 格式 | 更新时间 | 文件编号
    文件编号 = 32位 hash + 5位内容ID，例如
      0265524c802846b29fa4132aa12a12f186307

    注意：详情页里的 downloadResource/<32位hash> 是 resourceId，
    不能直接喂给 userApply.jsp（会报 code:3）。
    """
    url = f"{BASE}/cms/web/bjdata/api/dataDoc.jsp?contentID={content_id}"
    html = get_text(url)
    # 抓表格里的 <td> 行，最后一个是文件编号
    rows = re.findall(
        r'<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td>([0-9a-f]{32}\d{5})</td>',
        html)
    out = []
    for name, fmt, upd, fid in rows:
        out.append({"name": name.strip(), "format": fmt.strip(),
                    "update": upd.strip(), "file_id": fid.strip()})
    return out


def fetch_file_info(file_id):
    """文件编号 -> 真实下载地址"""
    url = f"{BASE}/cms/web/bjdata/api/userApply.jsp?id={file_id}&key={KEY}"
    return get_json(url)


def main():
    print("=== 1. 拉取市文化和旅游局数据集清单 ===")
    d = list_datasets(department="市文化和旅游局")
    if d.get("status") != 200:
        print("失败:", json.dumps(d, ensure_ascii=False)[:300])
        return 1
    docs = d["object"]["docs"]
    print(f"共 {len(docs)} 条\n")

    with open(os.path.join(OUT, "manifest_wlj.json"), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=1)

    # 目标数据集（旅游核心）
    targets = [
        "北京市等级景区信息",
        "等级景区门票信息",
        "等级景区交通信息",
        "重点景区饱和指数(全市4A级以上景区饱和指数)",
        "星级饭店信息",
        "旅行社信息",
        "红色旅游景区",
        "全国乡村旅游重点村",
        "展览信息",
        "活动信息",
        "图书馆信息1",
        "文化场馆",
    ]

    print("=== 2. 解析并下载目标数据集 ===")
    results = []
    for doc in docs:
        name = doc["name"]
        if name not in targets:
            continue
        print(f"\n[{name}]")
        files = resolve_file_ids(doc["id"])
        if not files:
            print("  ✗ 未解析到文件编号")
            results.append({"name": name, "status": "no_file_id"})
            continue

        got = None
        for f in files:
            fmt = f["format"].lower()
            # 只要表格数据，跳过图片
            if fmt in ("png", "jpg", "jpeg"):
                continue
            info = fetch_file_info(f["file_id"])
            if info.get("code") != "0":
                print(f"  - {f['file_id'][:12]}... [{fmt}] {info.get('reason')}")
                continue
            res = info["result"]
            addr = res["address"]
            ext = os.path.splitext(addr)[1].lower() or "." + fmt
            safe = re.sub(r'[\\/:*?"<>|]', "_", name)
            local = os.path.join(OUT, safe + ext)
            if download(addr, local):
                sz = os.path.getsize(local)
                print(f"  ✓ [{fmt}] {sz} bytes  {res.get('update_date')}")
                got = {"name": name, "file": local, "size": sz,
                       "format": fmt, "update": res.get("update_date"),
                       "source_name": res.get("name"), "address": addr}
                break
            else:
                print(f"  ✗ 下载失败: {addr}")
            time.sleep(0.3)

        results.append(got or {"name": name, "status": "failed"})
        time.sleep(0.5)

    print("\n=== 3. 汇总 ===")
    ok = [r for r in results if r and r.get("file")]
    print(f"成功 {len(ok)} / 目标 {len(targets)}")
    for r in results:
        if r and r.get("file"):
            print(f"  ✓ {r['name']:<40} {r['size']:>8} bytes  {r['update']}")
        elif r:
            print(f"  ✗ {r['name']:<40} {r.get('status','?')}")

    with open(os.path.join(OUT, "download_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
