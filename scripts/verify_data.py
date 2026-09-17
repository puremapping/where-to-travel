#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证已下载的北京数据集内容"""
import os
import glob
import csv
import sys

OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".research"))


def peek_csv(path, n=3):
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                rows = []
                for i, row in enumerate(csv.reader(f)):
                    if i >= n + 1:
                        break
                    rows.append(row)
                return enc, rows
        except Exception:
            continue
    return None, []


def peek_xlsx(path, n=3):
    try:
        import openpyxl
    except ImportError:
        return "openpyxl 未安装", []
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= n + 1:
                break
            rows.append([str(c)[:40] if c is not None else "" for c in row])
        wb.close()
        return f"sheet={ws.title}", rows
    except Exception as e:
        return f"读取失败: {e}", []


def main():
    files = sorted(set(glob.glob(os.path.join(OUT, "*.csv")) +
                       glob.glob(os.path.join(OUT, "*.xls*"))))
    # 排除测试残渣
    files = [f for f in files if os.path.basename(f) != "bj_attractions.csv"
             or os.path.getsize(f) > 1000]

    for f in files:
        b = os.path.basename(f)
        sz = os.path.getsize(f)
        print("=" * 78)
        print(f"{b}  ({sz:,} bytes)")
        print("=" * 78)
        if f.endswith(".csv"):
            enc, rows = peek_csv(f, 3)
            print(f"编码: {enc}")
        else:
            info, rows = peek_xlsx(f, 3)
            print(info)
        if not rows:
            print("  (无内容)")
            print()
            continue
        hdr = rows[0]
        print(f"列数: {len(hdr)}")
        print("表头:", " | ".join(str(h)[:18] for h in hdr[:10]))
        for r in rows[1:]:
            print("数据:", " | ".join(str(c)[:18] for c in r[:10]))
        print()


if __name__ == "__main__":
    main()
