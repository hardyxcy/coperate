#!/usr/bin/env python3
# ---
# cap: build-project-index
# purpose: 扫描本地所有 BOARD.html，生成工作区总入口 index.html
# serves: M-003#local
# serves_version: 3
# kind: tool
# version: 3
# changed: 2026-11-16 v3 对齐 M-003#local v3（备份脚本适配 NAS 只读 object，本脚本行为不变）
# idempotent: yes
# side-effect: 覆盖重写工作区根的 index.html，不改任何项目文件
# ---
#
# 用法：
#   python coperate-tools/build_index.py              生成
#   python coperate-tools/build_index.py --check      只列会发现什么，不写文件
#
# 为什么不维护项目清单：目录扫描代替登记（D-007 的思路）。
# 新项目只要有自己的 BOARD.html，重跑一次就自动出现在总入口里。
import argparse
import datetime
import html
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.environ.get("COPERATE_WORKSPACE") or os.path.dirname(HERE)
OUT = os.path.join(WORKSPACE, "index.html")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".workbuddy",
             "coperate-tools", "#recycle", "_trash", "@eaDir"}
MAX_DEPTH = 5


def human_size(n):
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1024.0 / 1024.0)


def project_name(rel_dir):
    """台账在 coperate/ 子目录里的项目，展示名去掉那一层。"""
    parts = [p for p in rel_dir.replace("\\", "/").split("/") if p not in (".", "")]
    if len(parts) > 1 and parts[-1] == "coperate":
        parts = parts[:-1]
    return "/".join(parts) if parts else "(工作区根)"


def scan():
    found = []
    for dirpath, dirnames, filenames in os.walk(WORKSPACE, followlinks=False):
        rel = os.path.relpath(dirpath, WORKSPACE)
        depth = 0 if rel == "." else len(rel.split(os.sep))
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "BOARD.html" in filenames:
            p = os.path.join(dirpath, "BOARD.html")
            try:
                st = os.stat(p)
            except OSError:
                continue
            rel_dir = os.path.dirname(os.path.relpath(p, WORKSPACE))
            found.append({
                "name": project_name(rel_dir),
                "rel": os.path.relpath(p, WORKSPACE).replace("\\", "/"),
                "size": st.st_size,
                "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return sorted(found, key=lambda x: x["rel"].lower())


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>本地看板总入口</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
         color:#1f2328; background:#f6f8fa; }
  header { padding:14px 20px; background:#fff; border-bottom:1px solid #d8dee4;
           display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:17px; margin:0; }
  header .meta { color:#656d76; font-size:12px; }
  .wrap { display:flex; height:calc(100vh - 52px); }
  aside { width:340px; flex:none; overflow:auto; background:#fff; border-right:1px solid #d8dee4; }
  .item { padding:11px 16px; border-bottom:1px solid #eaeef2; cursor:pointer; }
  .item:hover { background:#f3f6f9; }
  .item.on { background:#ddf4ff; border-left:3px solid #0969da; padding-left:13px; }
  .item .n { font-weight:600; word-break:break-all; }
  .item .p { color:#656d76; font-size:12px; word-break:break-all; margin-top:2px; }
  .item .s { color:#656d76; font-size:11px; margin-top:3px; }
  a.open { color:#0969da; text-decoration:none; font-size:11px; }
  a.open:hover { text-decoration:underline; }
  main { flex:1; display:flex; flex-direction:column; min-width:0; }
  .bar { padding:7px 14px; background:#fff; border-bottom:1px solid #d8dee4;
         font-size:12px; color:#656d76; }
  iframe { flex:1; width:100%; border:0; background:#fff; }
  .empty { padding:40px; color:#656d76; }
</style>
</head>
<body>
<header>
  <h1>本地看板总入口</h1>
  <span class="meta">__COUNT__ 个项目 · 生成于 __TIME__ · 重跑 <code>python coperate-tools/build_index.py</code> 刷新</span>
</header>
<div class="wrap">
  <aside id="list">__ITEMS__</aside>
  <main>
    <div class="bar" id="bar">左边选一个项目。打不开就点「新窗口打开」（浏览器对 file:// 内嵌框的限制各不一样）。</div>
    <iframe id="frame" title="看板"></iframe>
  </main>
</div>
<script>
function pick(el, rel) {
  var nodes = document.querySelectorAll('.item');
  for (var i = 0; i < nodes.length; i++) nodes[i].classList.remove('on');
  el.classList.add('on');
  document.getElementById('frame').src = rel;
  document.getElementById('bar').textContent = rel;
}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check", action="store_true", help="只列发现结果，不写文件")
    args = ap.parse_args()

    print("[build_index.py v3 · cap=build-project-index · tool]")
    print("工作区 %s" % WORKSPACE)

    items = scan()
    if args.check:
        for it in items:
            print("  %-28s %s" % (it["name"], it["rel"]))
        print("共 %d 个 BOARD.html，未写文件。" % len(items))
        return 0

    rows = []
    for it in items:
        rel = html.escape(it["rel"], quote=True)
        rows.append(
            '<div class="item" onclick="pick(this, \'%s\')">'
            '<div class="n">%s</div>'
            '<div class="p">%s</div>'
            '<div class="s">%s · %s · <a class="open" href="%s" target="_blank" '
            'onclick="event.stopPropagation()">新窗口打开</a></div>'
            '</div>'
            % (rel, html.escape(it["name"]), rel, it["mtime"],
               human_size(it["size"]), rel)
        )

    page = (PAGE.replace("__ITEMS__", "".join(rows) or '<div class="empty">没找到 BOARD.html</div>')
                .replace("__COUNT__", str(len(items)))
                .replace("__TIME__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)

    print("已生成 %s（%d 个项目）" % (OUT, len(items)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
