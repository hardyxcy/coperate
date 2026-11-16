# ---
# cap: scaffold-project
# purpose: 从 templates/ 生成新项目空骨架；或用 --sync-tools 只更新已有项目的工具
# serves: M-001#reuse
# serves_version: 6
# kind: tool
# version: 15
# changed: 2026-11-15 v15 生成新项目后自动刷新本地总入口 index.html（D-026）；对齐 M-001#reuse v6
# idempotent: no
# side-effect: 创建目录与文件；刷新工作区 index.html；--sync-tools 会覆盖目标项目 coperate/ 下的启动器和根入口 AGENTS.md
# ---
"""项目脚手架。

两种用法：

    python tools/scaffold.py ../新项目                 生成空骨架
    python tools/scaffold.py ../新项目 --sync-tools    只更新工具，不动文档

为什么要分开：
    工具是代码，项目不该改它，覆盖即升级。
    文档是内容，覆盖会冲掉已填的东西，永远不能覆盖。

模板真源在 templates/，改模板不用改这个脚本。
"""

import os
import sys
import shutil
import datetime
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
TOOLS = os.path.join(ROOT, "tools")
TODAY = datetime.date.today().isoformat()

GITIGNORE = """# 派生品，随时可从源重建
BOARD.html

# Python
__pycache__/
*.pyc
*.pyo

# 工具缓存
.workbuddy/

# 系统垃圾
.DS_Store
Thumbs.db
desktop.ini
"""
GITATTR = """* text=auto eol=lf

# Windows 脚本保持 CRLF
*.bat text eol=crlf
*.cmd text eol=crlf

# 二进制，绝不转换（转错了文件会坏，且不报错）
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.webp binary
*.ico binary
*.mp3 binary
*.wav binary
*.ogg binary
*.m4a binary
*.mp4 binary
*.webm binary
*.zip binary
*.woff binary
*.woff2 binary
*.ttf binary
*.otf binary
*.pdf binary
*.xlsx binary
*.docx binary
"""

SKIP_TOOLS = {"scaffold.py"}

ROOT_AGENTS = """# 开工

这个项目的台账在 `coperate/`。动手前先读两个文件：

- `coperate/AGENTS.md` —— 动作：读规范、跑校验、重跑生成、报待办
- `coperate/docs/M-005-协作规范.md` —— 唯一约束行为的规则

在台账里跑：

```bash
cd coperate
python tools/scan.py    # 开工前
python build.py         # 改完
```

`coperate/` 之外是这个项目自己的东西，台账不看那边。
"""


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.replace("__TODAY__", TODAY))


def write_keep(path, text, label):
    """只在不存在时写。

    根上的 .gitignore / .gitattributes 很可能是项目自己早就写好的，
    --force 是「允许往非空目录里写」，不是「允许冲掉已有配置」。
    """
    if os.path.exists(path):
        print("  跳过 %s（已存在，没动它）" % label)
        return
    write(path, text)


def is_scaffold_project(dest):
    ledger = os.path.join(dest, "coperate")
    return (os.path.isdir(os.path.join(ledger, "docs"))
            and os.path.exists(os.path.join(ledger, "QUEUE.md")))


def refresh_index(dest):
    """新项目建好后刷新工作区总入口（D-026）。

    总入口靠目录扫描，不登记清单；不刷新，新项目就看不见。
    找不到生成器、或项目建在工作区之外，直接跳过——不该让生成失败。
    """
    workspace = os.path.abspath(os.path.dirname(ROOT))
    tool = os.path.join(workspace, "coperate-tools", "build_index.py")
    if not os.path.isfile(tool):
        return
    try:
        if os.path.commonpath([os.path.abspath(dest), workspace]) != workspace:
            return
    except ValueError:
        return
    r = subprocess.run([sys.executable, tool], cwd=workspace,
                       capture_output=True, text=True)
    out = (r.stdout or r.stderr or "").strip()
    if out:
        print(out)
    print("  总入口 index.html 已刷新")

def build(dest, label="生成完成"):
    bd = os.path.join(dest, "build.py")
    if not os.path.exists(bd):
        return
    r = subprocess.run([sys.executable, "build.py"], cwd=dest,
                       capture_output=True, text=True)
    out = (r.stdout or r.stderr or "").strip()
    if out:
        print(out)
    print(label)


def create(dest, force, ptype=None):
    if not os.path.isdir(TEMPLATES):
        print("找不到 templates/ 目录：%s" % TEMPLATES)
        return 1

    if os.path.exists(dest) and os.listdir(dest) and not force:
        print("目标目录非空：%s" % dest)
        print("确认要往里写，加 --force")
        return 1

    print("[scaffold.py v14 · cap=scaffold-project · tool]")
    print("生成骨架 → %s" % dest)

    # 台账进 coperate/，项目资产进同名目录（D-024）
    ledger = os.path.join(dest, "coperate")
    asset_dir = os.path.join(dest, os.path.basename(dest.rstrip("/\\")))
    os.makedirs(asset_dir, exist_ok=True)

    count = 0
    for fn in sorted(os.listdir(TEMPLATES)):
        if not fn.endswith(".md"):
            continue
        src = os.path.join(TEMPLATES, fn)
        with open(src, "r", encoding="utf-8") as f:
            text = f.read()
        target = (os.path.join(ledger, "docs", fn) if fn.startswith("M-")
                  else os.path.join(ledger, fn))
        write(target, text)
        count += 1

    # 这两个必须留在仓库根，git 只认根上的
    write_keep(os.path.join(dest, ".gitignore"), GITIGNORE, ".gitignore")
    write_keep(os.path.join(dest, ".gitattributes"), GITATTR, ".gitattributes")
    write_keep(os.path.join(dest, "AGENTS.md"), ROOT_AGENTS, "根 AGENTS.md（台账指路）")

    for d in ("decisions", "assets", "tools", "inbox", os.path.join("work", TODAY)):
        os.makedirs(os.path.join(ledger, d), exist_ok=True)
    keep = os.path.join(ledger, "inbox", ".gitkeep")
    if not os.path.exists(keep):
        open(keep, "w").close()

    src_build = os.path.join(ROOT, "build.py")
    if os.path.exists(src_build):
        shutil.copy2(src_build, os.path.join(ledger, "build.py"))
        print("  已复制 build.py（启动器）")
    else:
        print("  警告：找不到 build.py，看板不会自动生成")

    # 只复制启动器。实现在 coperate-tools/，不该进项目
    src_scan = os.path.join(TOOLS, "scan.py")
    if os.path.exists(src_scan):
        os.makedirs(os.path.join(ledger, "tools"), exist_ok=True)
        shutil.copy2(src_scan, os.path.join(ledger, "tools", "scan.py"))
        print("  已复制 tools/scan.py（启动器）")

    if ptype:
        tdir = os.path.join(TEMPLATES, ptype)
        if not os.path.isdir(tdir):
            avail = [d for d in os.listdir(TEMPLATES)
                     if os.path.isdir(os.path.join(TEMPLATES, d))]
            print("找不到类型模板：%s（可用：%s）" % (ptype, "、".join(avail) or "无"))
            return 1
        docs_dir = os.path.join(ledger, "docs")
        n = 0
        for fn in sorted(os.listdir(tdir)):
            if not (fn.startswith("M-") and fn.endswith(".md")):
                continue
            mid = fn[:5]
            for old in os.listdir(docs_dir):
                if old.startswith(mid):
                    os.remove(os.path.join(docs_dir, old))
            with open(os.path.join(tdir, fn), "r", encoding="utf-8") as f:
                write(os.path.join(docs_dir, fn), f.read())
            n += 1
        print("  套用 %s 模板 %d 份（M-005 沿用通用）" % (ptype, n))

    print("  文档 %d 份 · 空目录 4 个" % count)
    build(ledger, "")
    refresh_index(dest)
    print("")
    print("下一步：cd coperate，把 docs/ 里的「待补」填上，或者直接跟我聊。")
    return 0


def sync_tools(dest):
    ledger = os.path.join(dest, "coperate")
    if not is_scaffold_project(dest):
        print("这不是脚手架生成的项目：%s" % dest)
        print("（需要有 coperate/docs/ 和 coperate/QUEUE.md）")
        return 1

    print("[scaffold.py v14 · cap=scaffold-project · tool]")
    print("同步启动器 → %s（文档不动）" % ledger)

    n = 0
    src_build = os.path.join(ROOT, "build.py")
    if os.path.exists(src_build):
        shutil.copy2(src_build, os.path.join(ledger, "build.py"))
        print("  build.py → 已更新")
        n += 1

    src_scan = os.path.join(TOOLS, "scan.py")
    if os.path.exists(src_scan):
        os.makedirs(os.path.join(ledger, "tools"), exist_ok=True)
        shutil.copy2(src_scan, os.path.join(ledger, "tools", "scan.py"))
        print("  tools/scan.py → 已更新")
        n += 1

    agents = os.path.join(TEMPLATES, "AGENTS.md")
    if os.path.exists(agents):
        shutil.copy2(agents, os.path.join(ledger, "AGENTS.md"))
        print("  coperate/AGENTS.md → 已更新")
        n += 1

    # 根入口也归脚手架管：它只有「台账在哪」三行，被就地改坏最难发现——
    # 新会话的 AI 一进项目根就读它，指错目录等于整套规范失效。
    if os.path.isdir(dest):
        with open(os.path.join(dest, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(ROOT_AGENTS.replace("__TODAY__", TODAY))
        print("  AGENTS.md（项目根入口）→ 已更新")
        n += 1

    if n == 0:
        print("  没有可同步的文件")
        return 1

    build(ledger, "启动器已同步，文档未改动")
    return 0


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python tools/scaffold.py <目标目录>                  生成空骨架")
        print("  python tools/scaffold.py <目标目录> --type game        生成小游戏骨架")
        print("  python tools/scaffold.py <目标目录> --sync-tools      只更新工具")
        return 2

    dest = os.path.abspath(sys.argv[1])
    args = sys.argv[2:]

    if "--sync-tools" in args:
        return sync_tools(dest)

    ptype = None
    if "--type" in args:
        i = args.index("--type")
        if i + 1 < len(args):
            ptype = args[i + 1]
        else:
            print("--type 后面要跟类型名，比如 --type game")
            return 2

    return create(dest, "--force" in args, ptype)


if __name__ == "__main__":
    sys.exit(main())
