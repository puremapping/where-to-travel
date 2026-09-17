#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理 Where to Travel 调研过程文件（移入回收站，非永久删除）

用 PowerShell 的 Microsoft.VisualBasic 走回收站。
脚本本身用英文注释与输出，避免 PS 5.1 的 GBK 编码坑。
"""
import os
import subprocess

DIR = r"D:\fs\workspace\projects\where_to_travel\.research"

# Process artifacts: login-wall HTML, probe samples, duplicate file
TARGETS = [
    "test_0265524c802846b29fa4132aa12a12f1",  # not-logged-in redirect HTML
    "test_15eede45d4d4458b91fe47657dbbad58",
    "test_333ec11c44a4408e948f694160fa1f43",
    "api_nokey.txt",                          # no-key response doc
    "probe.json",                             # subject probe sample
    "bj_travel.json",                         # sample when keyword seemed to work
    "bj_attractions.csv",                     # duplicate of 北京市等级景区信息.csv (same MD5)
    "detail_19605.html",                      # detail page (API docs already extracted)
]


def delete_to_recycle(path):
    # Escape single quotes for PowerShell literal string
    esc = path.replace("'", "''")
    ps = f"""
Add-Type -AssemblyName Microsoft.VisualBasic
[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
    '{esc}',
    [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
    [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or "").strip()


def main():
    moved = 0
    for name in TARGETS:
        p = os.path.join(DIR, name)
        if not os.path.exists(p):
            print(f"  [skip]    {name}")
            continue
        ok, err = delete_to_recycle(p)
        if ok:
            print(f"  [recycle] {name}")
            moved += 1
        else:
            print(f"  [FAIL]    {name}  {err[:100]}")
    print(f"\nMoved to recycle bin: {moved}")


if __name__ == "__main__":
    main()
