#!/usr/bin/env python3
# ---
# cap: verify-ledger-shim
# purpose: 启动器。实现在 coperate-tools/scan_ledger.py，全 Project 共用一份
# serves: M-005#daily
# serves_version: 3
# kind: tool
# version: 1
# changed: 2026-11-13 首版：只做转发，不含校验逻辑；serves 指向 M-005#daily（各项目都有）
# idempotent: yes
# side-effect: 无，转交给 coperate-tools/scan_ledger.py
# ---
#
# 和根目录的 build.py 一样，这里只转发。
# 校验逻辑只有一份，否则同一条规则在不同项目里会得出不同结论。
import os
import sys
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)


def find_tool():
    env = os.environ.get("COPERATE_TOOLS")
    if env:
        cand = os.path.join(env, "scan_ledger.py")
        if os.path.isfile(cand):
            return cand

    d = PROJECT
    while True:
        cand = os.path.join(d, "coperate-tools", "scan_ledger.py")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


TOOL = find_tool()
if not TOOL:
    sys.exit("找不到 coperate-tools/scan_ledger.py。"
             "设 COPERATE_TOOLS 环境变量指向工具目录，或确认项目在 Project 之下。")

sys.argv = [TOOL, "--root", PROJECT]
runpy.run_path(TOOL, run_name="__main__")
