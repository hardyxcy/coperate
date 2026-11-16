#!/usr/bin/env python3
# ---
# cap: build-board-shim
# purpose: 启动器。实现在 coperate-tools/build_board.py，全 Project 共用一份
# serves: M-005#structure
# serves_version: 5
# kind: tool
# version: 5
# changed: 2026-11-13 serves 对齐 M-005#structure v5（tools/ 准入改按 kind 判）
# idempotent: yes
# side-effect: 无，转交给 coperate-tools/build_board.py
# ---
#
# 这个文件不要写逻辑。
#
# 以前每个项目根各有一份完整的 build.py，改一个 bug 要改 N 遍，
# 2026-11-13 就因为一份改了、另一份没改，candy 的看板整页漏成 JSON。
# 现在实现只有一份，这里只负责「找到它、把项目根传过去」。
#
# 用法不变：python build.py
import os
import sys
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))


def find_tool():
    """先看环境变量，再从项目根逐级往上找 coperate-tools/。

    逐级找是因为项目深度不固定：Project/coperate 是一层，
    Project/wx/candy 是两层，写死相对路径总有一个是错的。
    """
    env = os.environ.get("COPERATE_TOOLS")
    if env:
        cand = os.path.join(env, "build_board.py")
        if os.path.isfile(cand):
            return cand

    d = HERE
    while True:
        cand = os.path.join(d, "coperate-tools", "build_board.py")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


TOOL = find_tool()
if not TOOL:
    sys.exit("找不到 coperate-tools/build_board.py。"
             "设 COPERATE_TOOLS 环境变量指向工具目录，或确认项目在 Project 之下。")

sys.argv = [TOOL, "--root", HERE]
runpy.run_path(TOOL, run_name="__main__")
