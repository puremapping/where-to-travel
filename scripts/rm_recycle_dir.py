#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""删除目录到回收站（英文输出，避开 PowerShell 的 GBK 解码坑）

用法: python scripts/rm_recycle_dir.py <dir> [<dir> ...]
"""
import os
import subprocess
import sys


def recycle_dir(path):
    if not os.path.exists(path):
        print(f"SKIP (not found): {path}")
        return False
    esc = path.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('{esc}',"
        "[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,"
        "[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True)
    ok = r.returncode == 0
    print(f"{'RECYCLED' if ok else 'FAIL'}: {path}")
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: rm_recycle_dir.py <dir> ...", file=sys.stderr)
        sys.exit(2)
    n = sum(1 for p in sys.argv[1:] if recycle_dir(p))
    print(f"total recycled: {n}")
