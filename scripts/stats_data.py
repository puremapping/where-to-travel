#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计已下载的北京旅游数据集"""
import os
import glob
import csv
import json

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".research"))


def count_csv(path):
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = [r for r in csv.reader(f) if any(c.strip() for c in r)]
            return len(rows) - 1  # 去表头
        except Exception:
            continue
    return -1


def count_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    n = 0
    for r in ws.iter_rows(values_only=True):
        if any(c is not None for c in r):
            n += 1
    wb.close()
    return n - 1


def main():
    stats = []
    for f in sorted(glob.glob(os.path.join(OUT, "*.csv")) +
                    glob.glob(os.path.join(OUT, "*.xlsx"))):
        b = os.path.basename(f)
        sz = os.path.getsize(f)
        try:
            n = count_csv(f) if f.endswith(".csv") else count_xlsx(f)
        except Exception as e:
            n = f"err:{e}"
        stats.append({"file": b, "rows": n, "bytes": sz})

    print(f"{'文件':<48} {'数据行':>8} {'大小':>12}")
    print("-" * 72)
    for s in sorted(stats, key=lambda x: -(x["rows"] if isinstance(x["rows"], int) else 0)):
        print(f"{s['file']:<48} {str(s['rows']):>8} {s['bytes']:>12,}")

    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
