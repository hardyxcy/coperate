# ---
# 本项目内不要手改这个文件：--sync-tools 升级会整体覆盖。
# 要改逻辑，去规范项目改，再同步过来。
# cap: build-board
# purpose: 读 docs/ decisions/ QUEUE.md TASKS.md work/ → 生成单文件 BOARD.html
# serves: M-005#structure
# serves_version: 1
# kind: tool
# version: 44
# changed: 2026-11-15 v44 项目根判定加资产目录自证（E:/Projects 也有 AGENTS.md 会误判）；getsize 与软链容错，坏文件不再炸整页
# idempotent: yes
# side-effect: 覆盖重写 BOARD.html，不改任何源文件
# ---
import os
import re
import json
import html
import datetime
import sys

def _project_root():
    """项目根：--root 显式指定 > 当前工作目录。

    这个脚本全 Project 只有一份，靠 --root 决定给哪个项目生成。
    以前是 dirname(__file__)，搬到 _tools 之后那条就不成立了。
    """
    argv = sys.argv[1:]
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            return os.path.abspath(argv[i + 1])
    return os.path.abspath(os.getcwd())


ROOT = _project_root()
DOCS = os.path.join(ROOT, "docs")
DECS = os.path.join(ROOT, "decisions")
WORK = os.path.join(ROOT, "work")
ASSETS = os.path.join(ROOT, "assets")
TOOLS = os.path.join(ROOT, "tools")
INBOX = os.path.join(ROOT, "inbox")
OUT = os.path.join(ROOT, "BOARD.html")


def _tree_root():
    """文件树的根：项目根，不是台账根。

    D-024 之后项目根分两层：`<项目>/coperate/` 是台账，`<项目>/<项目名>/`
    是项目资产。--root 拿到的是台账根，只扫它的话文件页永远看不到项目资产，
    人就又得回资源管理器——D-016 立的规矩就废了。

    判定三条一起看：
    1. 目录名是 coperate——只看这条会误伤盘根（规范项目自己就叫 coperate）
    2. 上一级有 AGENTS.md——只看前两条会误伤 `E:/Projects`，那里也躺着一份 AGENTS.md，
       结果把整个 Projects 当成项目根，扫进隔壁所有项目，还会撞 venv 里的符号链接
    3. 上一级里存在与它同名的资产目录（`candy/candy/`）——D-024 的结构自证，
       一条结构证据胜过两个命名巧合
    """
    parent = os.path.dirname(ROOT)
    if os.path.basename(ROOT) != "coperate":
        return ROOT
    if not os.path.isfile(os.path.join(parent, "AGENTS.md")):
        return ROOT
    if os.path.isdir(os.path.join(parent, os.path.basename(parent))):
        return parent
    return ROOT


TREE_ROOT = _tree_root()

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
ORPHAN_DAYS = 30


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_front(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm, parts[2]


def as_list(v):
    if not v:
        return []
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip() for x in v.split(",") if x.strip()]


def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def md2html(md):
    lines = md.splitlines()
    out = []
    i = 0
    n = len(lines)

    def flush_para(buf):
        if buf:
            out.append("<p>" + inline(" ".join(buf)) + "</p>")
            buf.clear()

    para = []
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if s.startswith("```"):
            flush_para(para)
            i += 1
            code = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            continue

        if s.startswith("|") and i + 1 < n and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            flush_para(para)
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>"]
            for h in header:
                t.append("<th>" + inline(h) + "</th>")
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>")
                for c in r:
                    t.append("<td>" + inline(c) + "</td>")
                t.append("</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            flush_para(para)
            lvl = min(len(m.group(1)) + 1, 4)
            title = re.sub(r"\s*\{#[^}]+\}\s*$", "", m.group(2))
            anchor = re.search(r"\{#([A-Za-z0-9_\-]+)(?:\s+v\d+)?\}", m.group(2))
            a = ' id="' + anchor.group(1) + '"' if anchor else ""
            out.append("<h%d%s>%s</h%d>" % (lvl, a, inline(title), lvl))
            i += 1
            continue

        if re.match(r"^[-*]\s+", s):
            flush_para(para)
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                txt = re.sub(r"^[-*]\s+", "", lines[i].strip())
                items.append("<li>" + inline(txt) + "</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        if re.match(r"^\d+\.\s+", s):
            flush_para(para)
            items = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                txt = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                items.append("<li>" + inline(txt) + "</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue

        if s.startswith(">"):
            flush_para(para)
            q = []
            while i < n and lines[i].strip().startswith(">"):
                q.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(q)) + "</blockquote>")
            continue

        if not s:
            flush_para(para)
            i += 1
            continue

        para.append(s)
        i += 1

    flush_para(para)
    return "\n".join(out)


def is_stub(body):
    """骨架未填：待补占了一半以上的章节。"""
    secs = len(re.findall(r"^##\s+", body, re.M))
    n = body.count("待补")
    if secs == 0:
        return n > 0
    return n > 0 and float(n) / secs >= 0.5


# ---------- 主文档 ----------
mains = []
if os.path.isdir(DOCS):
    for fn in sorted(os.listdir(DOCS)):
        if not fn.endswith(".md"):
            continue
        fm, body = parse_front(read(os.path.join(DOCS, fn)))
        mains.append({
            "id": fm.get("id", fn),
            "title": fm.get("title", fn[:-3]),
            "updated": fm.get("updated", ""),
            "depends_on": as_list(fm.get("depends_on", "")),
            "file": "docs/" + fn,
            "stub": is_stub(body),
            "html": md2html(body),
        })

# ---------- 决策 ----------
decisions = []
if os.path.isdir(DECS):
    for fn in sorted(os.listdir(DECS)):
        if not fn.endswith(".md"):
            continue
        fm, body = parse_front(read(os.path.join(DECS, fn)))
        decisions.append({
            "id": fm.get("id", fn),
            "title": fm.get("title", fn[:-3]),
            "status": fm.get("status", "active"),
            "target": fm.get("target", ""),
            "date": fm.get("date", ""),
            "supersedes": fm.get("supersedes", ""),
            "superseded_by": fm.get("superseded_by", ""),
            "evidence": as_list(fm.get("evidence", "")),
            "file": "decisions/" + fn,
            "html": md2html(body),
        })

dmap = {d["id"]: d for d in decisions}

# ---------- 漂移检测 ----------
drift = []
for m in mains:
    bad = [d for d in m["depends_on"] if d in dmap and dmap[d]["status"] != "active"]
    m["bad"] = bad
    if bad:
        drift.append({"main": m["id"], "title": m["title"], "bad": bad})

# ---------- 队列 ----------
queue = []
qpath = os.path.join(ROOT, "QUEUE.md")
if os.path.exists(qpath):
    text = read(qpath)
    _, body = parse_front(text)
    for block in re.split(r"\n##\s+", "\n" + body):
        block = block.strip()
        if not block:
            continue
        head, _, rest = block.partition("\n")
        m = re.match(r"^(P-\d+)\s*[·\-]?\s*(.*)$", head.strip())
        if not m:
            continue
        meta = {}
        lines = rest.splitlines()
        bi = 0
        for idx, ln in enumerate(lines):
            mm = re.match(r"^-\s*(\w+):\s*(.*)$", ln.strip())
            if mm:
                meta[mm.group(1)] = mm.group(2).strip()
                bi = idx + 1
            elif ln.strip() == "":
                continue
            else:
                break
        body_md = "\n".join(lines[bi:]).strip()
        queue.append({
            "id": m.group(1),
            "title": m.group(2).strip(),
            "target": meta.get("target", ""),
            "date": meta.get("date", ""),
            "status": meta.get("status", "open"),
            "html": md2html(body_md),
        })

# ---------- 产出 ----------
all_evidence = set()
for d in decisions:
    all_evidence.update(d["evidence"])

works = []
images = []
today = datetime.date.today()


def scan_work():
    if not os.path.isdir(WORK):
        return
    for dirpath, _, files in os.walk(WORK):
        for fn in sorted(files):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            ext = os.path.splitext(fn)[1].lower()
            dirdate = os.path.basename(os.path.basename(dirpath))
            if os.path.basename(dirpath) == "work":
                dirdate = today.isoformat()
            if ext in IMG_EXT:
                images.append({"path": rel, "name": fn, "date": dirdate})
                continue
            if ext != ".md":
                continue
            fm, body = parse_front(read(full))
            wid = fm.get("id", fn[:-3])
            try:
                age = (today - datetime.date.fromisoformat(dirdate)).days
            except Exception:
                age = 0
            works.append({
                "id": wid,
                "title": fm.get("title", fn[:-3]),
                "type": fm.get("type", "note"),
                "summary": fm.get("summary", ""),
                "date": dirdate,
                "path": rel,
                "age": age,
                "orphan": (wid not in all_evidence
                           and fm.get("type") != "report"
                           and age > ORPHAN_DAYS),
                "html": md2html(body),
            })


scan_work()

if os.path.isdir(ASSETS):
    for fn in sorted(os.listdir(ASSETS)):
        ext = os.path.splitext(fn)[1].lower()
        if ext in IMG_EXT:
            images.append({"path": "assets/" + fn, "name": fn, "date": ""})

works.sort(key=lambda w: (w["date"], w["id"]), reverse=True)

# ---------- 脚本 ----------
scripts = []


def read_script_meta(path):
    try:
        head = read(path)[:900]
    except Exception:
        return {}
    m = re.search(r"^#\s*---\s*$(.*?)^#\s*---\s*$", head, re.S | re.M)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("#").strip()
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def scan_scripts():
    for base, zone in ((TOOLS, "tool"), (WORK, "temp")):
        if not os.path.isdir(base):
            continue
        for dirpath, _, files in os.walk(base):
            for fn in sorted(files):
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                meta = read_script_meta(full)
                scripts.append({
                    "name": fn,
                    "path": rel,
                    "zone": zone,
                    "cap": meta.get("cap", ""),
                    "purpose": meta.get("purpose", ""),
                    "serves": meta.get("serves", ""),
            "serves_version": meta.get("serves_version", ""),
                    "serves_version": meta.get("serves_version", ""),
                    "kind": meta.get("kind", ""),
                    "version": meta.get("version", ""),
                    "changed": meta.get("changed", ""),
                    "idempotent": meta.get("idempotent", ""),
                    "effect": meta.get("side-effect", ""),
                    "mtime": datetime.datetime.fromtimestamp(
                        os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M"),
                    "meta_ok": bool(meta),
                })

    rb = os.path.join(ROOT, "build.py")
    if os.path.exists(rb):
        meta = read_script_meta(rb)
        scripts.append({
            "name": "build.py",
            "path": "build.py",
            "zone": "tool",
            "cap": meta.get("cap", ""),
            "purpose": meta.get("purpose", ""),
            "serves": meta.get("serves", ""),
            "serves_version": meta.get("serves_version", ""),
            "kind": meta.get("kind", ""),
            "version": meta.get("version", ""),
            "changed": meta.get("changed", ""),
            "idempotent": meta.get("idempotent", ""),
            "effect": meta.get("side-effect", ""),
            "mtime": datetime.datetime.fromtimestamp(
                os.path.getmtime(rb)).strftime("%Y-%m-%d %H:%M"),
            "meta_ok": bool(meta),
        })


scan_scripts()
scripts.sort(key=lambda s: (0 if s["zone"] == "tool" else 1, s["name"]))

# ---------- 文件树 ----------
TREE_SKIP = {".git", "__pycache__", ".workbuddy", "node_modules",
             "miniprogram_npm", ".idea", ".vscode", ".DS_Store", "Thumbs.db"}
TEXT_EXT = {".md", ".py", ".json", ".txt", ".html", ".css", ".js", ".yml", ".yaml", ".csv", ".gitignore"}
EMBED_LIMIT = 24 * 1024
NO_EMBED = {"build.py", "BOARD.html"}


def human(n):
    if n < 1024:
        return "%d B" % n
    if n < 1048576:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1048576.0)


def file_node(full, name, r, embed=True):
    """一个文件节点。embed=False 时只记结构，不读内容（资产目录走这条）。

    getsize 会失败：venv 里的符号链接在 Windows 上打不开（WinError 1920）、
    还有些文件被占用。这类节点照列结构、标成「?」，不能因为一个坏文件糊掉整个页面。
    """
    ext = os.path.splitext(name)[1].lower()
    try:
        size = os.path.getsize(full)
    except OSError:
        node = {"t": "f", "n": name, "p": r, "s": "?", "e": ext.lstrip("."), "nx": 1}
        return node
    node = {"t": "f", "n": name, "p": r, "s": human(size), "e": ext.lstrip(".")}
    if not embed:
        node["nx"] = 1
        return node
    if ext in TEXT_EXT and name not in NO_EMBED and size < EMBED_LIMIT:
        try:
            text = read(full)
            if ext == ".md":
                _fm, _body = parse_front(text)
                node["h"] = md2html(_body)
            else:
                node["x"] = text
        except Exception:
            pass
    return node


def walk_tree(path, rel="", embed=True):
    nodes = []
    try:
        names = sorted(os.listdir(path),
                       key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))
    except OSError:
        return nodes
    for name in names:
        if name in TREE_SKIP:
            continue
        full = os.path.join(path, name)
        r = (rel + "/" + name).lstrip("/")
        # 符号链接一律不跟：venv/、node_modules 里的软链可能指回上级，跟进去就是死循环
        if os.path.islink(full):
            continue
        if os.path.isdir(full):
            nodes.append({"t": "d", "n": name, "p": r, "c": walk_tree(full, r, embed)})
        else:
            nodes.append(file_node(full, name, r, embed))
    return nodes


def walk_project():
    """项目根的树：coperate/ 内嵌内容，项目资产只列结构。

    资产目录（`<项目名>/`）里有几百个源码文件，全内嵌能把 BOARD.html 撑到
    好几 M——而那边的内容在编辑器里看更合适，看板只需要「有这个文件、
    路径能复制」。台账不一样：md 就是给人读的，必须内嵌。
    """
    if TREE_ROOT == ROOT:
        return walk_tree(ROOT)
    nodes = []
    try:
        names = sorted(os.listdir(TREE_ROOT),
                       key=lambda x: (not os.path.isdir(os.path.join(TREE_ROOT, x)), x.lower()))
    except OSError:
        return nodes
    for name in names:
        if name in TREE_SKIP:
            continue
        full = os.path.join(TREE_ROOT, name)
        if os.path.islink(full):
            continue
        if os.path.isdir(full):
            nodes.append({"t": "d", "n": name, "p": name,
                          "c": walk_tree(full, name, embed=(name == "coperate"))})
        else:
            nodes.append(file_node(full, name, name, embed=True))
    return nodes


ROLE = {
    "coperate": ("台账", "ledger"),
    "docs": ("本项目", "bd"),
    "decisions": ("本项目", "bd"),
    "work": ("本项目", "bd"),
    "inbox": ("本项目", "bd"),
    "assets": ("本项目", "bd"),
    "templates": ("模具", "mold"),
    "tools": ("工具", "mold"),
}

tree = walk_project()


def decorate(ns, in_ledger=False, top=False):
    """给树上的目录挂角色标签。

    ROLE 只在 coperate/ 内部生效：项目资产目录里叫 tools、docs 的文件夹
    是项目自己的东西，贴「工具」「本项目」是错的。
    顶层只认两个：coperate/（台账）和与项目同名的资产目录（D-024）。
    """
    asset_name = os.path.basename(TREE_ROOT)
    for n in ns:
        if n["t"] != "d":
            continue
        if not in_ledger and n["n"] == "coperate":
            n["role"], n["rolek"] = ROLE["coperate"]
            decorate(n["c"], True)
        elif top and n["n"] == asset_name:
            n["role"], n["rolek"] = ("项目资产", "bd")
            decorate(n["c"], False)
        else:
            if in_ledger and n["n"] in ROLE:
                n["role"], n["rolek"] = ROLE[n["n"]]
            decorate(n["c"], in_ledger)


decorate(tree, in_ledger=(TREE_ROOT == ROOT), top=(TREE_ROOT != ROOT))


def count_files(ns):
    n = 0
    for x in ns:
        if x["t"] == "d":
            n += count_files(x["c"])
        else:
            n += 1
    return n

# ---------- 投递区 ----------
inbox_items = []
if os.path.isdir(INBOX):
    for fn in sorted(os.listdir(INBOX)):
        if fn == ".gitkeep":
            continue
        full = os.path.join(INBOX, fn)
        if not os.path.isfile(full):
            continue
        inbox_items.append({
            "name": fn,
            "size": os.path.getsize(full),
            "mtime": datetime.datetime.fromtimestamp(
                os.path.getmtime(full)).strftime("%m-%d %H:%M"),
        })

# ---------- 任务 ----------
tasks = {"blocked": [], "doing": [], "todo": [], "done": []}
tpath = os.path.join(ROOT, "TASKS.md")
if os.path.exists(tpath):
    text = read(tpath)
    _, body = parse_front(text)
    cur = None
    label_map = {"阻塞": "blocked", "进行中": "doing", "待办": "todo", "已完成": "done"}
    for ln in body.splitlines():
        s = ln.strip()
        mh = re.match(r"^##+\s+(.*)$", s)
        if mh:
            cur = label_map.get(mh.group(1).strip())
            continue
        mt = re.match(r"^-\s*\[( |x|X)\]\s*(?:([A-Z]+-\d+)\s+)?(.*)$", s)
        if mt and cur:
            tid = mt.group(2) or ""
            raw = mt.group(3).strip()
            am = re.search(r"@(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", raw)
            dm = re.search(r"\u2192\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)", raw)
            start = am.group(1) if am else ""
            done_at = dm.group(1) if dm else ""
            if dm:
                raw = raw[:dm.start()].strip()
            if am:
                raw = raw[:am.start()].strip()
            tasks[cur].append({
                "tid": tid,
                "text": raw.strip(),
                "done": mt.group(1).lower() == "x",
                "start": start,
                "done_at": done_at,
                "stale": False,
                "elapsed": "",
            })

def parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def fmt_delta(td):
    secs = int(td.total_seconds())
    if secs < 0:
        return ""
    mins = secs // 60
    if mins < 60:
        return "%d 分钟" % mins
    h = mins // 60
    m = mins % 60
    if h < 24:
        return ("%d 小时 %d 分" % (h, m)) if m else ("%d 小时" % h)
    return "%d 天 %d 小时" % (h // 24, h % 24)


STALE_TASK_DAYS = 5
_now = datetime.datetime.now()
stale_tasks = 0
for _grp in ("doing", "todo", "done"):
    for t in tasks[_grp]:
        st = parse_dt(t["start"])
        dn = parse_dt(t["done_at"])
        if st and dn:
            t["elapsed"] = fmt_delta(dn - st)
        elif st:
            t["elapsed"] = fmt_delta(_now - st)
        if _grp == "doing" and st and (_now - st).days > STALE_TASK_DAYS:
            t["stale"] = True
            stale_tasks += 1

# ---------- 汇总 ----------
active_d = [d for d in decisions if d["status"] == "active"]
health = {
    "mains": len(mains),
    "decisions": len(active_d),
    "queue": len([q for q in queue if q["status"] == "open"]),
    "works": len(works) + len(images),
    "drift": len(drift),
    "stubs": len([m for m in mains if m["stub"]]),
    "orphan": len([w for w in works if w["orphan"]]),
    "tasks_open": len(tasks["doing"]) + len(tasks["todo"]) + len(tasks["blocked"]),
    "scripts": len(scripts),
    "scripts_bad": len([s for s in scripts if not s["meta_ok"]]),
    "stale_tasks": stale_tasks,
    "inbox": len(inbox_items),
    "files": count_files(tree),
}

def project_title():
    """看板抬头用的项目名。

    优先读 M-001 frontmatter 的 project:，没有再退回目录名。
    目录名通常是英文 slug，不该直接当人看的标题。
    """
    if os.path.isdir(DOCS):
        for fn in sorted(os.listdir(DOCS)):
            if fn.startswith("M-001") and fn.endswith(".md"):
                fm, _ = parse_front(read(os.path.join(DOCS, fn)))
                name = (fm.get("project") or "").strip()
                if name:
                    return name
    return os.path.basename(ROOT)


DATA = {
    "project": project_title(),
    "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "health": health,
    "drift": drift,
    "mains": mains,
    "decisions": decisions,
    "queue": queue,
    "works": works,
    "images": images,
    "scripts": scripts,
    "tree": tree,
    "root": os.path.abspath(ROOT).replace("\\", "/"),
    "treeroot": os.path.abspath(TREE_ROOT).replace("\\", "/"),
    "inbox": inbox_items,
    "tasks": tasks,
}

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__PROJECT__ · 协作看板</title>
<style>
:root{
  --bg:#F7F6F3;--card:#FFFFFF;--line:rgba(0,0,0,.08);--line2:rgba(0,0,0,.16);
  --t1:#2C2C2A;--t2:#5F5E5A;--t3:#888780;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--t1);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  font-size:14px;line-height:1.68;-webkit-font-smoothing:antialiased}
.wrap{max-width:min(1280px,94vw);margin:0 auto;padding:36px 32px 120px}
.grid2{display:grid;grid-template-columns:1fr;gap:8px}
.grid2 .item{margin-bottom:0}
.item .body>p,.item .body>ul,.item .body>ol,.item .body>blockquote{max-width:74ch}
h1{font-size:22px;font-weight:600;margin:0 0 4px;letter-spacing:-.01em}
.sub{font-size:12px;color:var(--t3);margin-bottom:16px}
.health{display:none;align-items:center;gap:8px;background:#FCEBEB;border:1px solid #F2D6D6;
  border-radius:10px;padding:9px 14px;margin-bottom:10px;font-size:12.5px;color:#A32D2D}
.health.on{display:flex}
.bar{display:flex;gap:8px;align-items:center;margin-bottom:22px;flex-wrap:wrap}
.btn{appearance:none;font-family:inherit;font-size:12.5px;padding:6px 13px;border-radius:7px;
  border:1px solid var(--line2);background:#fff;color:var(--t1);cursor:pointer}
.btn:hover{background:#F0EFEA}
.btn.pri{background:#2C2C2A;color:#fff;border-color:#2C2C2A}
.btn.pri:hover{background:#1a1a19}
.pend{margin-left:auto;font-size:12px;color:#854F0B;background:#FAEEDA;padding:4px 11px;border-radius:20px}
nav{display:flex;gap:3px;border-bottom:1px solid var(--line);margin-bottom:24px;overflow-x:auto}
nav button{appearance:none;background:none;border:none;border-bottom:2px solid transparent;
  padding:8px 13px 10px;margin-bottom:-1px;font-size:13px;color:var(--t2);cursor:pointer;
  font-family:inherit;white-space:nowrap}
nav button:hover{color:var(--t1);background:rgba(0,0,0,.03)}
nav button.on{color:var(--t1);border-bottom-color:var(--t1);font-weight:500}
nav .n{font-family:var(--mono);font-size:11px;color:var(--t3);margin-left:5px}
section{display:none}
section.on{display:block}
.hint{font-size:12px;color:var(--t3);margin:0 0 16px;padding:10px 14px;
  background:rgba(0,0,0,.025);border-radius:8px;line-height:1.7}
.item{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:8px;overflow:hidden}
.item:hover{border-color:var(--line2)}
.item.open{border-color:var(--line2)}
.item.drift{border-left:3px solid #E24B4A}
.row{display:flex;align-items:baseline;gap:10px;padding:13px 16px 8px;cursor:pointer;user-select:none}
.id{font-family:var(--mono);font-size:11px;color:var(--t2);background:rgba(0,0,0,.05);
  padding:2px 7px;border-radius:5px;flex:none;margin-top:2px;letter-spacing:.02em}
.ttl{font-size:14px;font-weight:500;flex:1;min-width:0}
.chev{flex:none;width:8px;height:8px;border-right:1.5px solid var(--t3);border-bottom:1.5px solid var(--t3);
  transform:rotate(45deg);margin-left:6px;margin-bottom:4px;transition:transform .15s}
.item.open .chev{transform:rotate(-135deg);margin-bottom:0;margin-top:4px}
.badge{flex:none;font-size:11px;padding:2px 8px;border-radius:20px;display:inline-flex;
  align-items:center;gap:5px;margin-top:2px;white-space:nowrap}
.badge i{width:5px;height:5px;border-radius:50%;display:block}
.b-active{background:#E1F5EE;color:#085041}.b-active i{background:#0F6E56}
.b-pending{background:#FAEEDA;color:#633806}.b-pending i{background:#BA7517}
.b-dead{background:#F1EFE8;color:#5F5E5A}.b-dead i{background:#888780}
.b-orphan{background:#FAECE7;color:#712B13}.b-orphan i{background:#993C1D}
.b-drift{background:#FCEBEB;color:#A32D2D}.b-drift i{background:#E24B4A}
.b-stub{background:#F1EFE8;color:#888780}.b-stub i{background:#B4B2A9}
.pathline{display:flex;align-items:center;gap:9px;padding:7px 16px 0;min-width:0}
.pathline code{font-family:var(--mono);font-size:11px;color:var(--t2);background:rgba(0,0,0,.035);padding:2px 6px;border-radius:4px;user-select:all;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pathline .pathline .btn.ok{background:#E1F5EE;color:#085041}
.pathline .fullpath{font-family:var(--mono);font-size:11px;color:var(--t2);background:#E1F5EE;padding:2px 6px;border-radius:4px;user-select:all;flex-basis:100%}
.digest{padding:0 16px 12px;font-size:13px;color:var(--t2);margin:0}
.deps{padding:0 16px 13px;display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.deps .k{font-size:11px;color:var(--t3)}
.dep{font-family:var(--mono);font-size:10.5px;padding:1px 6px;border-radius:4px;
  background:rgba(0,0,0,.045);color:var(--t2)}
.dep.bad{background:#FCEBEB;color:#A32D2D}
.body{display:none;border-top:1px solid var(--line);padding:18px 20px;background:#FCFCFA}
.item.open .body{display:block}
.body h2{font-size:15px;font-weight:600;margin:22px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.body h2:first-child{margin-top:0}
.body h3{font-size:14px;font-weight:600;margin:18px 0 6px}
.body h4{font-size:13px;font-weight:600;margin:16px 0 6px;color:var(--t2)}
.body p{margin:0 0 11px;font-size:13.5px}
.body ul,.body ol{margin:0 0 12px;padding-left:22px;font-size:13.5px}
.body li{margin-bottom:4px}
.body code{font-family:var(--mono);font-size:12px;background:rgba(0,0,0,.05);padding:1px 5px;border-radius:4px}
.body pre{background:#F4F3EF;border:1px solid var(--line);border-radius:8px;padding:12px 14px;
  overflow-x:auto;margin:0 0 12px}
.body pre code{background:none;padding:0;font-size:12px;line-height:1.6}
.body blockquote{margin:0 0 12px;padding:2px 0 2px 12px;border-left:2px solid var(--line2);
  color:var(--t2);font-size:12.5px}
.body table{border-collapse:collapse;width:100%;margin:0 0 12px;font-size:12.5px}
.body th{text-align:left;font-weight:500;background:#F4F3EF;padding:6px 10px;border:1px solid var(--line)}
.body td{padding:6px 10px;border:1px solid var(--line);vertical-align:top}
.annot{border-top:1px dashed var(--line2);margin-top:16px;padding-top:14px}
.annot .lbl{font-size:11px;color:var(--t3);letter-spacing:.06em;margin:0 0 8px;font-weight:500}
.acts{display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.act{font-size:12px;padding:4px 11px;border-radius:6px;border:1px solid var(--line2);
  background:#fff;cursor:pointer;font-family:inherit;color:var(--t2)}
.act:hover{background:#F0EFEA}
.act.on{background:#2C2C2A;color:#fff;border-color:#2C2C2A}
.act.on.no{background:#A32D2D;border-color:#A32D2D}
.act.on.hold{background:#854F0B;border-color:#854F0B}
.ta{width:100%;min-height:52px;resize:vertical;border:1px solid var(--line2);border-radius:7px;
  padding:8px 10px;font-family:inherit;font-size:13px;color:var(--t1);background:#fff;line-height:1.6}
.ta:focus{outline:none;border-color:#888780}
.saved{font-size:11.5px;color:#0F6E56;margin-top:6px;display:none}
.saved.show{display:block}
.done-mark{font-size:11.5px;color:var(--t3);margin-top:6px}
.imgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.imgcell{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff}
.imgcell img{width:100%;height:110px;object-fit:cover;display:block;cursor:zoom-in;background:#F1EFE8}
.imgcell .cap{font-size:11px;color:var(--t3);padding:6px 9px;font-family:var(--mono);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.imggrp{margin-bottom:18px}
.dgrp{margin-bottom:16px}
.imggrp-h{display:flex;align-items:center;gap:9px;margin:0 0 9px;flex-wrap:wrap}
.imggrp-h code{font-family:var(--mono);font-size:12px;font-weight:500;color:var(--t1);background:#F1EFE8;
  border:1px solid var(--line);padding:4px 9px;border-radius:6px;user-select:all}
.imggrp-n{font-size:11px;color:var(--t3)}
.scr{background:#fff;border:1px solid var(--line);border-radius:10px;padding:11px 14px;margin-bottom:7px}
.scr.bad{border-left:3px solid #E24B4A}
.scr-h{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sname{font-family:var(--mono);font-size:12.5px;font-weight:500}
.tag{font-size:10.5px;padding:1px 7px;border-radius:20px;white-space:nowrap}
.t-tool{background:#E1F5EE;color:#085041}
.t-temp{background:#FAEEDA;color:#633806}
.t-warn{background:#FCEBEB;color:#A32D2D}
.t-bad{background:#A32D2D;color:#fff}
.smtime{font-family:var(--mono);font-size:11px;color:var(--t3);margin-left:auto}
.t-ver{background:#EEEDFE;color:#3C3489}
.sid{display:flex;gap:14px;flex-wrap:wrap;margin-top:5px;font-family:var(--mono);font-size:11px;color:var(--t3)}
.sid b{color:var(--t2);font-weight:500}
.sch{font-size:11.5px;color:var(--t3);margin-top:4px}
.sp{font-size:13px;color:var(--t2);margin-top:6px;line-height:1.6}
.se{font-size:12px;color:#854F0B;margin-top:3px;line-height:1.6}
.spath{font-family:var(--mono);font-size:11px;color:var(--t3);margin-top:5px}
.troot{display:flex;align-items:center;gap:10px;padding:9px 12px;background:#fff;border:1px solid var(--line);border-radius:9px;margin-bottom:12px}
.troot code{font-family:var(--mono);font-size:12px;color:var(--t2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn.mini{font-size:10.5px;padding:3px 8px;border-radius:5px;flex:none;white-space:nowrap}
.tnode .tw{display:flex;align-items:center;gap:8px;padding:5px 10px;border-radius:6px;cursor:pointer;font-size:13px;user-select:none}
.tnode .tw:hover{background:rgba(0,0,0,.035)}
.tnode.dir>.tw{font-weight:500}
.caret{width:10px;font-size:10px;color:var(--t3);flex:none;transition:transform .12s}
.tnode.open>.tw .caret{transform:rotate(90deg)}
.tchildren{display:none}
.tnode.open+.tchildren{display:block}
.ticon{font-family:var(--mono);font-size:9.5px;padding:1px 5px;border-radius:4px;flex:none;min-width:28px;text-align:center;background:rgba(0,0,0,.05);color:var(--t3)}
.ticon.e-md{background:#E1F5EE;color:#085041}
.ticon.e-py{background:#E6F1FB;color:#0C447C}
.ticon.e-png,.ticon.e-jpg,.ticon.e-jpeg,.ticon.e-gif,.ticon.e-webp,.ticon.e-svg{background:#FAEEDA;color:#633806}
.ticon.e-json,.ticon.e-yml,.ticon.e-yaml{background:#EEEDFE;color:#3C3489}
.ticon.e-none{background:transparent}
.tname{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tcount,.tsize{font-family:var(--mono);font-size:10.5px;color:var(--t3);flex:none}
.trole{font-size:10px;padding:1px 6px;border-radius:20px;flex:none;margin-left:2px}
.r-bd{background:#E1F5EE;color:#085041}
.r-ledger{background:#E6F1FB;color:#0C447C}
.r-mold{background:#EEEDFE;color:#3C3489}
.pvhead{display:flex;align-items:center;gap:10px;padding:8px 12px;background:#F4F3EF;border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0}
.pvhead code{font-family:var(--mono);font-size:11.5px;color:var(--t2);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mdbody{background:#fff;border:1px solid var(--line);border-radius:0 0 8px 8px;padding:16px 18px;max-height:560px;overflow:auto}
.mdbody h2{font-size:14px;font-weight:600;margin:18px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--line)}
.mdbody h2:first-child{margin-top:0}
.mdbody h3,.mdbody h4{font-size:13px;font-weight:600;margin:14px 0 6px;color:var(--t2)}
.mdbody p{margin:0 0 10px;font-size:13px}
.mdbody ul,.mdbody ol{margin:0 0 10px;padding-left:20px;font-size:13px}
.mdbody table{border-collapse:collapse;width:100%;margin:0 0 10px;font-size:12px}
.mdbody th{text-align:left;font-weight:500;background:#F4F3EF;padding:5px 8px;border:1px solid var(--line)}
.mdbody td{padding:5px 8px;border:1px solid var(--line)}
.mdbody pre{background:#F4F3EF;border-radius:6px;padding:10px 12px;overflow-x:auto;font-size:11.5px}
.mdbody code{font-family:var(--mono);font-size:11.5px;background:rgba(0,0,0,.05);padding:1px 4px;border-radius:3px}
.mdbody blockquote{margin:0 0 10px;padding-left:10px;border-left:2px solid var(--line2);color:var(--t2);font-size:12.5px}
.raw{margin:0;background:#fff;border:1px solid var(--line);border-radius:0 0 8px 8px;padding:12px 14px;font-family:var(--mono);font-size:11.5px;line-height:1.6;max-height:560px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.ovh{font-size:14px;font-weight:600;margin:24px 0 10px;display:flex;align-items:baseline;gap:8px}
.ovh:first-child{margin-top:0}
.ovn{font-family:var(--mono);font-size:12px;color:var(--t3);font-weight:400}
.ovsub{font-size:11.5px;color:var(--t3);font-weight:400}
.airow{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--t3);margin:26px 0 0;padding-top:14px;border-top:1px solid var(--line)}
.airow b{font-weight:500;color:var(--t2)}
.arch{margin-top:18px;border:1px solid var(--line);border-radius:10px;padding:0 14px;background:#FBFAF7}
.arch>summary{cursor:pointer;padding:11px 2px;font-size:13px;color:var(--t2);user-select:none}
.arch>summary b{font-family:var(--mono);color:var(--t1)}
.arch[open]>summary{border-bottom:1px solid var(--line);margin-bottom:10px}
.archgrp{padding-bottom:8px}
.archdate{font-family:var(--mono);font-size:11px;color:var(--t3);padding:6px 2px}
.pickbtn{position:absolute;display:none;transform:translateX(-50%);z-index:60;
  background:#1F1D19;color:#fff;border:none;border-radius:16px;padding:5px 13px;font-size:12px;
  cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.18);white-space:nowrap;font-family:inherit}
.pickbtn.show{display:block}
.pickbtn.warn{background:#8A3B12}
.pick{background:#fff;border:1px solid var(--line);border-left:3px solid #BA7517;border-radius:10px;
  padding:12px 14px;margin-bottom:8px}
.pickhead{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.pickid{font-family:var(--mono);font-size:11px;background:#FAEEDA;color:#854F0B;padding:1px 6px;border-radius:4px}
.picktarget{font-family:var(--mono);font-size:11px;color:var(--t3)}
.pickdel{margin-left:auto;background:none;border:none;color:var(--t3);font-size:11px;cursor:pointer;font-family:inherit}
.pickdel:hover{color:#A32D2D}
.pickquote{margin:0 0 8px;padding:6px 10px;border-left:2px solid var(--line2);background:#FAFAF7;
  color:var(--t2);font-size:12.5px;line-height:1.65;white-space:pre-wrap}
.picknote{width:100%;min-height:52px;box-sizing:border-box}
.qh{font-size:14px;font-weight:600;margin:22px 0 10px;display:flex;align-items:center}
.picknew{display:inline-block;font-size:11px;color:#854F0B;background:#FAEEDA;padding:1px 7px;border-radius:10px;margin-left:6px}
.taskgrp{margin-bottom:18px}
.taskh{font-size:12px;color:var(--t2);font-weight:500;margin:0 0 8px;display:flex;align-items:center;gap:8px}
.taskh .dot{width:6px;height:6px;border-radius:50%}
.titem{display:flex;gap:9px;padding:8px 14px;background:#fff;border:1px solid var(--line);
  border-radius:9px;margin-bottom:6px;font-size:13.5px;align-items:flex-start}
.titem .bx{width:14px;height:14px;border:1.5px solid var(--t3);border-radius:4px;flex:none;margin-top:3px}
.titem.done .bx{background:#0F6E56;border-color:#0F6E56}
.titem.done .tx{color:var(--t3);text-decoration:line-through}
.titem .tx{flex:1}
.tid{font-family:var(--mono);font-size:10.5px;color:var(--t2);background:rgba(0,0,0,.05);padding:1px 6px;border-radius:4px;flex:none;margin-top:2px}
.tmeta{font-family:var(--mono);font-size:11px;color:var(--t3);flex:none;margin-left:10px;display:inline-flex;gap:6px;align-items:center;white-space:nowrap}
.empty{color:var(--t3);font-size:13px;padding:28px 0;text-align:center}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;
  justify-content:center;padding:24px;z-index:50}
.modal.show{display:flex}
.modal img{max-width:100%;max-height:100%;border-radius:8px}
.mwrap{display:flex;flex-direction:column;gap:10px;align-items:center;max-height:100%;min-height:0}
/* 图别把底部路径条挤出屏幕：留出 padding + 路径条的高度 */
.mwrap img{min-height:0;max-height:calc(100vh - 150px);object-fit:contain}
.mfoot{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:center;
  background:rgba(0,0,0,.5);padding:6px 10px;border-radius:8px}
.mfoot code{font-family:var(--mono);font-size:11px;color:#fff;
  padding:0;background:transparent;user-select:all;max-width:70vw;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.exp{display:none;margin-top:14px}
.exp.show{display:block}
.exp textarea{width:100%;height:170px;font-family:var(--mono);font-size:12px;padding:11px;
  border:1px solid var(--line2);border-radius:8px;background:#fff;color:var(--t1);line-height:1.6}
.foot{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);font-size:12px;color:var(--t3);line-height:1.9}
.foot code{font-family:var(--mono);background:rgba(0,0,0,.05);padding:1px 5px;border-radius:4px;font-size:11.5px}
</style>
</head>
<body>
<div class="wrap">
  <h1>__PROJECT__</h1>
  <div class="sub" id="sub"></div>
  <div class="health" id="health"></div>
  <div class="bar">
    <button class="btn pri" id="expBtn">导出批示</button>
    <button class="btn" id="clrBtn">清空本机批示</button>
    <span class="pend" id="pend"></span>
  </div>
  <div class="exp" id="expBox">
    <textarea id="expArea" readonly></textarea>
    <div style="font-size:11.5px;color:#0F6E56;margin-top:6px" id="expMsg"></div>
  </div>
  <nav id="nav"></nav>
  <section id="s-mains" class="on"></section>
  <section id="s-decisions"></section>
  <section id="s-queue"></section>
  <section id="s-works"></section>
  <section id="s-tree"></section>
  <section id="s-scripts"></section>
  <section id="s-tasks"></section>
  <div class="foot">
    由 <code>build.py</code> 从 <code>docs/</code> <code>decisions/</code> <code>QUEUE.md</code> <code>TASKS.md</code> <code>work/</code> 生成，不是手写的。<br>
    批注存在浏览器本机，点击「导出批示」后粘贴回对话框即可落盘。
  </div>
</div>
<div class="modal" id="modal"><div class="mwrap"><img id="modalImg" alt=""><div class="mfoot"><code id="modalPath"></code><button class="btn mini" id="modalCopy">复制完整路径</button></div></div></div>
<button id="pickBtn" class="pickbtn"></button>

<script>
const DATA = __DATA__;
const KEY = "coperate-notes-v1";
let notes = {};
try { notes = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch(e) { notes = {}; }

const BADGE = {
  active:{c:"b-active",t:"生效"}, pending:{c:"b-pending",t:"待确认"},
  dead:{c:"b-dead",t:"已失效"}, superseded:{c:"b-dead",t:"已失效"},
  orphan:{c:"b-orphan",t:"孤儿"}, drift:{c:"b-drift",t:"待同步"},
  open:{c:"b-pending",t:"待定"}
};

function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }

function badge(k){
  const b = BADGE[k] || BADGE.dead;
  return '<span class="badge '+b.c+'"><i></i>'+b.t+'</span>';
}

function annotHtml(id, o){
  const cur = notes[id] || {};
  const mk = (v,l,cls) => '<button class="act'+(cur.action===v?' on '+cls:'')+'" data-id="'+id+'" data-act="'+v+'">'+l+'</button>';
  const noActs = !!(o && o.noActs);
  const acts = noActs ? '' : '<div class="acts">'+mk('yes','采纳','')+mk('no','否决','no')+mk('hold','待定','hold')+'</div>';
  const lbl = noActs ? '你的修改意见' : '你的批示';
  const ph = (o && o.ph) ? o.ph : '补充说明（可选）：哪里不对、要改成什么';
  return '<div class="annot">'
    + '<p class="lbl">'+lbl+'</p>'
    + acts
    + '<textarea class="ta" data-id="'+id+'" placeholder="'+esc(ph)+'">'+esc(cur.note||'')+'</textarea>'
    + '<div class="saved'+(cur.saved?' show':'')+'" id="sv-'+id+'">已存在本机，记得点顶部「导出批示」</div>'
    + '</div>';
}

function item(o){
  const st = o.status || "active";
  const cls = (st==="drift"||(o.bad&&o.bad.length)) ? " drift" : "";
  let deps = "";
  if(o.depends_on && o.depends_on.length){
    deps = '<div class="deps"><span class="k">依赖</span>';
    o.depends_on.forEach(d=>{
      const bad = (o.bad||[]).indexOf(d)>-1;
      deps += '<span class="dep'+(bad?' bad':'')+'">'+d+'</span>';
    });
    deps += '</div>';
  }
  let meta = "";
  // target 和 file 常常是同一个路径（工作稿就是），别显示两遍
  if(o.target && o.target !== o.file) meta += '<span class="dep">→ '+o.target+'</span> ';
  if(o.date) meta += '<span class="k" style="font-size:11px;color:var(--t3);margin-left:4px">'+o.date+'</span>';
  const metaLine = meta ? '<div class="deps">'+meta+'</div>' : "";
  const pathLine = o.file
    ? '<div class="pathline"><code>'+esc(o.file)+'</code>'
      + '<button class="btn mini pathcopy" data-p="'+esc(o.file)+'">复制完整路径</button></div>'
    : "";

  return '<article class="item'+cls+'" data-id="'+o.id+'">'
    + '<div class="row"><span class="id">'+o.id+'</span><span class="ttl">'+esc(o.title)+'</span>'
    + badge(o.badge||st) + '<span class="chev"></span></div>'
    + pathLine
    + (o.summary?'<p class="digest">'+esc(o.summary)+'</p>':'')
    + deps + metaLine
    + '<div class="body">'+(o.html||'')+(o.noAnnot ? '' : annotHtml(o.id, o))+'</div>'
    + '</article>';
}

function bind(scope){
  scope.querySelectorAll(".row").forEach(r=>{
    r.onclick = e => { if(e.target.closest(".badge")) return; r.parentElement.classList.toggle("open"); };
  });
  scope.querySelectorAll(".act").forEach(b=>{
    b.onclick = e => {
      e.stopPropagation();
      const id=b.dataset.id, act=b.dataset.act;
      notes[id] = notes[id]||{};
      notes[id].action = (notes[id].action===act? "" : act);
      notes[id].time = new Date().toLocaleString();
      save();
      const box=b.parentElement;
      box.querySelectorAll(".act").forEach(x=>x.classList.remove("on","no","hold"));
      if(notes[id].action){
        b.classList.add("on");
        if(act==="no") b.classList.add("no");
        if(act==="hold") b.classList.add("hold");
      }
      flash(id);
    };
  });
  scope.querySelectorAll(".ta").forEach(t=>{
    t.oninput = () => {
      const id=t.dataset.id;
      notes[id]=notes[id]||{};
      notes[id].note=t.value;
      notes[id].time=new Date().toLocaleString();
      if(!t.value.trim() && !notes[id].action){ delete notes[id]; }
      save();
      flash(id);
    };
  });
  scope.querySelectorAll(".imgcell img").forEach(im=>{
    im.onclick = () => {
      const full = im.dataset.full;
      document.getElementById("modalImg").src = full;
      document.getElementById("modalPath").textContent = DATA.root + "/" + full;
      document.getElementById("modalCopy").onclick = function (ev) {
        ev.stopPropagation();
        copyFull(full);
      };
      document.getElementById("modal").classList.add("show");
    };
  });
  scope.querySelectorAll(".grpcopy").forEach(b=>{
    b.onclick = function (ev) {
      ev.stopPropagation();
      copyFull(b.dataset.d);
      b.textContent = "已复制 \u2713";
      setTimeout(function () { b.textContent = "复制目录"; }, 2000);
    };
  });
}

function flash(id){
  const el=document.getElementById("sv-"+id);
  if(el && notes[id]) el.classList.add("show");
  renderPend();
}

function save(){
  try{ localStorage.setItem(KEY, JSON.stringify(notes)); }catch(e){}
}

function knownIds(){
  // 只有带批示区的条目才算——主文档走选区，不再有备注框
  const s = new Set();
  [...DATA.decisions, ...DATA.queue, ...DATA.works].forEach(x=>s.add(x.id));
  return s;
}

function noteCount(){
  const ids = knownIds();
  return Object.keys(notes).filter(k=>ids.has(k) && notes[k] && (notes[k].action || (notes[k].note||"").trim())).length;
}

function staleCount(){
  const ids = knownIds();
  return Object.keys(notes).filter(k=>!ids.has(k) && notes[k] && (notes[k].action || (notes[k].note||"").trim())).length;
}

function renderPend(){
  const n=noteCount();
  const el=document.getElementById("pend");
  const total = n + picks.length;
  const st = staleCount();
  let txt = total ? total+" 条待提交" : "暂无批示";
  if (st) txt += " · " + st + " 条已失效";
  el.textContent = txt;
  el.style.background = n ? "#FAEEDA" : "#F1EFE8";
  el.style.color = n ? "#854F0B" : "#888780";
}

/* ---------- 选区异议（D-018 / T-014） ---------- */
const PICK_KEY = "coperate-picks-v1";
let picks = [];
try {
  picks = JSON.parse(localStorage.getItem(PICK_KEY) || "[]");
  if (!Array.isArray(picks)) picks = [];
} catch (e) { picks = []; }

function savePicks() {
  try { localStorage.setItem(PICK_KEY, JSON.stringify(picks)); } catch (e) {}
}

function pickId() {
  let max = 0;
  picks.forEach(function (p) {
    const m = /^PX-(\d+)$/.exec(p.id || "");
    if (m) max = Math.max(max, parseInt(m[1], 10));
  });
  return "PX-" + (max + 1);
}

function blockOf(node) {
  const el = node && node.nodeType === 1 ? node : (node ? node.parentElement : null);
  return el ? el.closest("p,li,td,th,h3,h4,blockquote") : null;
}

function nearestAnchor(el) {
  const body = el.closest(".body");
  if (!body) return "";
  if (el.id) return el.id;
  const heads = body.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id]");
  let found = "";
  for (let i = 0; i < heads.length; i++) {
    const h = heads[i];
    if (h === el) { found = h.id; break; }
    if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) found = h.id;
    else break;
  }
  return found;
}

function targetOf(el) {
  const card = el.closest(".item");
  const mid = card && card.dataset.id ? card.dataset.id : "M-000";
  const anchor = nearestAnchor(el);
  return mid + (anchor ? "#" + anchor : "");
}

const pickBtnEl = document.getElementById("pickBtn");
let pickCtx = null;

function hidePickBtn() {
  pickBtnEl.classList.remove("show", "warn");
  pickCtx = null;
}

function onPickUp() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) { hidePickBtn(); return; }
  const text = sel.toString().trim();
  if (text.length < 4) { hidePickBtn(); return; }

  const range = sel.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  if (!rect.width && !rect.height) { hidePickBtn(); return; }

  pickBtnEl.style.top = (window.scrollY + rect.top - 40) + "px";
  pickBtnEl.style.left = (window.scrollX + rect.left + rect.width / 2) + "px";

  const a = blockOf(sel.anchorNode), b = blockOf(sel.focusNode);
  if (!a || !b || a !== b) {
    pickCtx = null;
    pickBtnEl.textContent = "跨段了，请只选一段";
    pickBtnEl.classList.add("show", "warn");
    return;
  }
  pickCtx = { quote: text, target: targetOf(a) };
  pickBtnEl.textContent = "拉进待定";
  pickBtnEl.classList.remove("warn");
  pickBtnEl.classList.add("show");
}

pickBtnEl.onclick = function () {
  if (!pickCtx) { hidePickBtn(); return; }
  picks.push({
    id: pickId(),
    target: pickCtx.target,
    quote: pickCtx.quote,
    note: "",
    date: DATA.generated.slice(0, 10)
  });
  savePicks();
  hidePickBtn();
  const sel = window.getSelection();
  if (sel) sel.removeAllRanges();
  renderQueue();
  switchTab("queue");
  renderPend();
};

document.addEventListener("mouseup", function (ev) {
  if (!ev.target.closest("#s-mains")) return;
  if (ev.target.closest("#pickBtn")) return;
  setTimeout(onPickUp, 0);
});

document.addEventListener("mousedown", function (ev) {
  if (!ev.target.closest("#pickBtn")) hidePickBtn();
});

function switchTab(key) {
  document.querySelectorAll("#nav button").forEach(function (x) {
    x.classList.toggle("on", x.dataset.tab === key);
  });
  document.querySelectorAll("section").forEach(function (x) {
    x.classList.toggle("on", x.id === "s-" + key);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderQueue() {
  let q = "";
  if (picks.length) {
    q += '<h2 class="qh">页面内新增<span class="picknew">' + picks.length + '</span></h2>';
    q += '<p class="hint">框选原文拉进来的异议。导出后我会写成 P-xxx 落盘；导出前只存在这台机器上。</p>';
    picks.forEach(function (p) {
      q += '<div class="pick">'
        + '<div class="pickhead"><span class="pickid">' + esc(p.id) + '</span>'
        + '<span class="picktarget">' + esc(p.target) + '</span>'
        + '<button class="pickdel" data-pid="' + esc(p.id) + '">删除</button></div>'
        + '<blockquote class="pickquote">' + esc(p.quote) + '</blockquote>'
        + '<textarea class="ta picknote" data-pid="' + esc(p.id) + '" placeholder="哪里不对、要改成什么">' + esc(p.note || "") + '</textarea>'
        + '</div>';
    });
  }
  q += '<h2 class="qh">待定项<span class="picknew" style="background:#F1EFE8;color:#5F5E5A">'
     + DATA.queue.length + '</span></h2>';
  q += DATA.queue.length
    ? DATA.queue.map(function (x) {
        return item({ id: x.id, title: x.title, status: "open", target: x.target, date: x.date, html: x.html });
      }).join("")
    : '<p class="empty">暂无</p>';
  document.getElementById("s-queue").innerHTML = q;

  document.querySelectorAll("#s-queue .pickdel").forEach(function (b) {
    b.onclick = function () {
      picks = picks.filter(function (p) { return p.id !== b.dataset.pid; });
      savePicks();
      renderQueue();
      renderPend();
    };
  });
  document.querySelectorAll("#s-queue .picknote").forEach(function (el) {
    el.oninput = function () {
      const p = picks.find(function (x) { return x.id === el.dataset.pid; });
      if (p) { p.note = el.value; savePicks(); }
    };
  });
}

function buildExport(){
  const lines=["以下是看板上的批示，请据此更新决策与主文档：",""];
  const actName={yes:"采纳",no:"否决",hold:"待定"};
  const all = [...DATA.mains,...DATA.decisions,...DATA.queue,...DATA.works];
  const ids = knownIds();
  Object.keys(notes).forEach(id=>{
    const n=notes[id]; if(!n) return;
    if(!ids.has(id)) return;
    if(!n.action && !(n.note||"").trim()) return;
    const o = all.find(x=>x.id===id) || {};
    lines.push("- "+id+" "+(o.title||"")+" → "+(actName[n.action]||"仅备注"));
    if((n.note||"").trim()) lines.push("  备注："+n.note.trim());
  });
  picks.forEach(function(p){
    lines.push("");
    lines.push("- "+p.id+"（页面选区）"+p.target);
    lines.push("  原文：「"+p.quote+"」");
    if((p.note||"").trim()) lines.push("  备注："+p.note.trim());
  });
  return lines.join("\n");
}

const FILEMAP = {};
(function walkMap(ns) {
  ns.forEach(function (n) { FILEMAP[n.p] = n; if (n.c) walkMap(n.c); });
})(DATA.tree);

function treeHtml(ns, depth) {
  let out = "";
  ns.forEach(function (nd) {
    const pad = 8 + depth * 15;
    if (nd.t === "d") {
      let cnt = 0;
      (function c2(x) { x.forEach(function (y) { if (y.t === "d") c2(y.c); else cnt++; }); })(nd.c);
      var rt = nd.role ? '<span class="trole r-' + esc(nd.rolek) + '">' + esc(nd.role) + '</span>' : '';
      out += '<div class="tnode dir" data-p="' + esc(nd.p) + '"><span class="tw" style="padding-left:' + pad + 'px">'
        + '<span class="caret">\u25b8</span><span class="tname">' + esc(nd.n) + '</span>' + rt
        + '<span class="tcount">' + cnt + '</span></span></div>'
        + '<div class="tchildren">' + treeHtml(nd.c, depth + 1) + '</div>';
    } else {
      const e = nd.e || "none";
      out += '<div class="tnode file" data-p="' + esc(nd.p) + '"><span class="tw" style="padding-left:' + (pad + 18) + 'px">'
        + '<span class="ticon e-' + esc(e) + '">' + esc(e === "none" ? "\u00b7" : e) + '</span>'
        + '<span class="tname">' + esc(nd.n) + '</span>'
        + '<span class="tsize">' + esc(nd.s) + '</span></span></div>'
        + '<div class="tprev"></div>';
    }
  });
  return out;
}

function copyFull(rel, base) {
  // base 默认台账根：卡片里的 docs/xxx 都是相对台账的。
  // 文件树的节点相对项目根，调用时必须显式传 DATA.treeroot。
  const r = base || DATA.root;
  const full = rel ? r + "/" + rel : r;
  copyText(full).then(function (ok) {
    alert(ok ? "已复制路径：\n" + full + "\n\n粘到资源管理器地址栏可直接打开。"
              : "剪贴板不可用，请手动复制下面这段路径：\n\n" + full);
  });
}

function fallbackCopy(s) {
  try {
    const ta = document.createElement("textarea");
    ta.value = s;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, s.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (e) { return false; }
}

function copyText(s) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(s)
      .then(function () { return true; })
      .catch(function () { return fallbackCopy(s); });
  }
  return Promise.resolve(fallbackCopy(s));
}

function bindPathCopy() {
  document.querySelectorAll(".pathcopy").forEach(function (btn) {
    btn.onclick = function (ev) {
      ev.stopPropagation();
      const full = DATA.root + "/" + btn.dataset.p;
      const line = btn.parentElement;

      // 不依赖剪贴板：无论成败都把绝对路径摆出来并选中，用户一定能拿到。
      let box = line.querySelector(".fullpath");
      if (!box) {
        box = document.createElement("code");
        box.className = "fullpath";
        box.textContent = full;
        line.appendChild(box);
      }
      const sel = window.getSelection();
      const rg = document.createRange();
      rg.selectNodeContents(box);
      sel.removeAllRanges();
      sel.addRange(rg);

      copyText(full).then(function (ok) {
        btn.textContent = ok ? "已复制 \u2713" : "剪贴板不可用：路径已选中，按 Ctrl+C";
        if (ok) btn.classList.add("ok");
        else btn.classList.remove("ok");
        setTimeout(function () {
          btn.textContent = "复制完整路径";
          btn.classList.remove("ok");
        }, 2600);
      });
      return false;
    };
  });
}

function bindTree() {
  document.querySelectorAll("#s-tree .tnode.dir > .tw").forEach(function (w) {
    w.onclick = function () { w.parentElement.classList.toggle("open"); };
  });
  document.querySelectorAll("#s-tree .tnode.file > .tw").forEach(function (w) {
    w.onclick = function () {
      const node = w.parentElement;
      const pv = node.nextElementSibling;
      if (pv.innerHTML) { pv.innerHTML = ""; return; }
      const nd = FILEMAP[node.dataset.p];
      if (!nd) return;
      let body;
      if (nd.h) body = '<div class="mdbody">' + nd.h + '</div>';
      else if (nd.x) body = '<pre class="raw">' + esc(nd.x) + '</pre>';
      else if (nd.nx) body = '<div class="mdbody" style="color:#888780;font-size:13px">'
        + '资产目录只列结构，不内嵌内容（几百个源码文件嵌进来会把页面撑到几 M）。'
        + '点「复制路径」拿去编辑器里打开。</div>';
      else body = '<div class="mdbody" style="color:#888780;font-size:13px">这个文件没有内嵌内容（二进制或过大），路径见上方。</div>';
      pv.innerHTML = '<div class="pvhead"><code>' + esc(nd.p) + '</code>'
        + '<button class="btn mini pvcopy">复制路径</button></div>' + body;
      pv.querySelector(".pvcopy").onclick = function (ev) { ev.stopPropagation(); copyFull(nd.p, DATA.treeroot); };
    };
  });
  const cr = document.getElementById("copyRoot");
  if (cr) cr.onclick = function () { copyFull("", DATA.treeroot); };
}

function render(){
  const h=DATA.health;
  var gd = new Date(DATA.generated.replace(/-/g, "/"));
  var ageMin = Math.floor((Date.now() - gd.getTime()) / 60000);
  var staleTag = "";
  if (ageMin >= 180) {
    var ageStr = ageMin >= 60 ? Math.floor(ageMin / 60) + " 小时" : ageMin + " 分钟";
    staleTag = ' · <span style="color:#A32D2D">数据是 ' + ageStr + '前生成的，可能已过期，重跑 build.py</span>';
  }
  document.getElementById("sub").innerHTML = "更新于 " + DATA.generated + staleTag;

var issues = [
    h.drift ? h.drift + ' 份主文档待同步' : '',
    h.scripts_bad ? h.scripts_bad + ' 个脚本缺元信息' : '',
    h.stale_tasks ? h.stale_tasks + ' 个任务可能已完成未勾' : '',
    h.inbox ? h.inbox + ' 个文件待接收' : '',
    h.stubs ? h.stubs + ' 份主文档未填' : ''
  ].filter(Boolean);
  var hb = document.getElementById("health");
  if (issues.length) {
    hb.innerHTML = '<span>\u26a0 ' + issues.join(' · ') + '</span>';
    hb.classList.add("on");
  } else {
    hb.innerHTML = "";
    hb.classList.remove("on");
  }

  const tabs=[
    ["mains","Docs",h.mains],["decisions","Decisions",h.decisions],
    ["queue","Pending",h.queue],["works","Drafts",h.works],["tree","Files",h.files],
    ["scripts","Tools",h.scripts],["tasks","ToDo",h.tasks_open]
  ];
  document.getElementById("nav").innerHTML = tabs.map((t,i)=>
    '<button data-tab="'+t[0]+'" class="'+(i===0?"on":"")+'">'+t[1]+
    (t[2]!==""?'<span class="n">'+t[2]+'</span>':'')+'</button>').join("");
  document.querySelectorAll("#nav button").forEach(b=>{
    b.onclick=()=>{
      document.querySelectorAll("#nav button").forEach(x=>x.classList.remove("on"));
      document.querySelectorAll("section").forEach(x=>x.classList.remove("on"));
      b.classList.add("on");
      document.getElementById("s-"+b.dataset.tab).classList.add("on");
      window.scrollTo({top:0,behavior:"smooth"});
    };
  });

  // 概览

  // 主文档
  document.getElementById("s-mains").innerHTML =
    '<p class="hint">项目的固定骨架，永远只有这几份。左边红条 = 它依赖的决策变了，但正文还没跟上。</p>' +
    '<div class="grid2">' +
    DATA.mains.map(m=>item({
      id:m.id,title:m.title,status:m.bad.length?"drift":"active",stub:m.stub,
      file:m.file,depends_on:m.depends_on,bad:m.bad,date:m.updated,html:m.html,
      noAnnot:true
    })).join("") + '</div>';

  // 决策
  const act = DATA.decisions.filter(d=>d.status==="active");
  const dead = DATA.decisions.filter(d=>d.status!=="active");
  document.getElementById("s-decisions").innerHTML =
    '<p class="hint">当前唯一有效的依据。失效的留在下面，用来回溯当初为什么这么定。</p>' +
    act.map(d=>item({id:d.id,title:d.title,status:"active",target:d.target,date:d.date,html:d.html})).join("")
    + (dead.length?'<h2 style="font-size:14px;font-weight:600;margin:26px 0 12px">已失效</h2>'
      + dead.map(d=>item({id:d.id,title:d.title,status:"dead",target:d.target,date:d.date,html:d.html})).join(""):"");

  // 待定
  renderQueue();

  // 工作稿
  let wk = "";
  wk += '<p class="hint"><b>工作稿</b>指 <code>work/</code> 下的过程产物（' + DATA.works.length
     + ' 篇）和素材图（' + DATA.images.length + ' 张）。它们记录的是「当时怎么想的」，<b>不构成任何依据</b>。'
     + '主文档、决策、脚本各有自己的页；项目共 <b>' + h.files + '</b> 个文件，完整清单见「文件」页。</p>';
  if (DATA.inbox.length) {
    wk += '<div class="hint" style="background:#FCEBEB;color:#A32D2D">'
       + '<b>' + DATA.inbox.length + ' 个文件在 inbox/ 待接收</b> —— 外部丢进来的素材，还没归类。'
       + '在你确认前，它们不构成任何依据。</div>';
  }
  if(DATA.images.length){
    wk += '<h2 style="font-size:14px;font-weight:600;margin:4px 0 12px">图片（'+DATA.images.length+'）</h2>';
    // 按所在目录分组：每组上方一行目录，图不用点开就知道在哪（兄弟 2026-11-13）
    const gmap = {}, gorder = [];
    DATA.images.forEach(im=>{
      const i = im.path.lastIndexOf("/");
      const dir = i > -1 ? im.path.slice(0, i) : "(台账根)";
      if (!gmap[dir]) { gmap[dir] = []; gorder.push(dir); }
      gmap[dir].push(im);
    });
    gorder.sort(function(a,b){ return a < b ? 1 : a > b ? -1 : 0; });  // 新日期在前，assets 沉底
    gorder.forEach(function(dir){
      const list = gmap[dir];
      wk += '<div class="imggrp"><div class="imggrp-h"><code>'+esc(dir)+'</code>'
          + '<span class="imggrp-n">'+list.length+' 张</span>'
          + '<button class="btn mini grpcopy" data-d="'+esc(dir)+'">复制目录</button></div>';
      wk += '<div class="imgrid">';
      list.forEach(function(im){
        wk += '<div class="imgcell"><img src="'+im.path+'" data-full="'+esc(im.path)+'" alt="'+esc(im.name)+'" loading="lazy" title="'+esc(im.path)+'">'
            + '<div class="cap" title="'+esc(im.path)+'">'+esc(im.name)+'</div></div>';
      });
      wk += '</div></div>';
    });
  } else {
    wk += '<p class="hint">还没有图片。以后生成的截图、示意图放进 <code>assets/</code> 或 <code>work/日期/</code>，重跑脚本就会出现在这里。</p>';
  }
  var normalW = DATA.works.filter(function(w){ return !w.orphan; });
  var orphanW = DATA.works.filter(function(w){ return w.orphan; });

  wk += '<h2 style="font-size:14px;font-weight:600;margin:20px 0 12px">文档（'+normalW.length+'）</h2>';
  if (normalW.length) {
    // 和图片一样按目录分组：组头就是「这篇稿子在哪个目录」，不用点开才知道
    var dmap = {}, dorder = [];
    normalW.forEach(function(w){
      var i = w.path.lastIndexOf("/");
      var dir = i > -1 ? w.path.slice(0, i) : "(台账根)";
      if (!dmap[dir]) { dmap[dir] = []; dorder.push(dir); }
      dmap[dir].push(w);
    });
    dorder.sort(function(a,b){ return a < b ? 1 : a > b ? -1 : 0; });
    dorder.forEach(function(dir){
      var list = dmap[dir];
      wk += '<div class="dgrp"><div class="imggrp-h"><code>'+esc(dir)+'</code>'
          + '<span class="imggrp-n">'+list.length+' 篇</span>'
          + '<button class="btn mini grpcopy" data-d="'+esc(dir)+'">复制目录</button></div>';
      wk += list.map(function(w){
        return item({id:w.id,title:w.title,status:"active",summary:w.summary,date:w.date,target:w.path,file:w.path,html:w.html});
      }).join("");
      wk += '</div>';
    });
  } else {
    wk += '<p class="empty">暂无</p>';
  }

  if (orphanW.length) {
    var byDate = {};
    orphanW.forEach(function(w){ (byDate[w.date] = byDate[w.date] || []).push(w); });
    wk += '<details class="arch"><summary>归档候选 <b>'+orphanW.length+'</b> 篇 —— 未被任何决策引用，且超过 30 天</summary>';
    Object.keys(byDate).sort().reverse().forEach(function(d){
      wk += '<div class="archgrp"><div class="archdate">'+esc(d)+' · '+byDate[d].length+' 篇</div>';
      wk += byDate[d].map(function(w){
        return item({id:w.id,title:w.title,status:"orphan",summary:w.summary,date:w.date,target:w.path,file:w.path,html:w.html});
      }).join("");
      wk += '</div>';
    });
    wk += '</details>';
  }
  document.getElementById("s-works").innerHTML = wk;

  // 文件树
  const treeNote = (DATA.treeroot !== DATA.root)
    ? '<p class="hint">这是<b>项目根</b>，不是台账根。'
      + '<span class="trole r-ledger" style="margin:0 3px">台账</span>是 <code>coperate/</code>（docs、decisions、work 都在里面），'
      + '<span class="trole r-bd" style="margin:0 3px">项目资产</span>是项目自己的代码和资源。'
      + '台账点开就能读内容；资产只列结构、不内嵌，点文件复制路径去编辑器里看。</p>'
    : '<p class="hint">点目录展开，点文件在下面直接看内容。'
      + '<span class="trole r-bd" style="margin:0 3px">本项目</span>是本项目的内容，'
      + '<span class="trole r-mold" style="margin:0 3px">模具</span>是给新项目用的模板和工具——'
      + '新项目不在这里，建了会在 <code>E:/Projects/新项目名</code> 平级目录。</p>';
  let tr = treeNote;
  tr += '<div class="troot"><code>' + esc(DATA.treeroot) + '</code>'
    + '<button class="btn mini" id="copyRoot">复制根路径</button></div>';
  tr += treeHtml(DATA.tree, 0);
  document.getElementById("s-tree").innerHTML = tr;

  // 工具与脚本
  let sc = '<p class="hint">tools/ 下是会反复用的工具，work/ 下是跑完的临时脚本。'
    + '头部元信息缺失的会标红——那是黑户，我不知道它干什么、能不能重跑。</p>';
  const mkScr = (arr, title, desc) => {
    if (!arr.length) return "";
    let s = '<h2 style="font-size:14px;font-weight:600;margin:6px 0 10px">' + title
      + ' <span style="color:var(--t3);font-weight:400;font-size:12px">' + desc + '</span></h2>';
    arr.forEach(x => {
      const noIdem = (x.idempotent || "").toLowerCase() === "no";
      const bad = !x.meta_ok;
      s += '<div class="scr' + (bad ? " bad" : "") + '">'
        + '<div class="scr-h"><span class="sname">' + esc(x.name) + '</span>'
        + (x.version ? '<span class="tag t-ver">v' + esc(x.version) + '</span>' : '')
        + (x.kind ? '<span class="tag ' + (x.kind === "tool" ? "t-tool" : "t-temp") + '">' + x.kind + '</span>' : '')
        + (noIdem ? '<span class="tag t-warn">不可重跑</span>' : '')
        + (bad ? '<span class="tag t-bad">缺元信息</span>' : '')
        + '<span class="smtime">' + esc(x.mtime) + '</span></div>'
        + (x.purpose ? '<div class="sp">' + esc(x.purpose) + '</div>' : '')
        + (x.cap || x.serves
            ? '<div class="sid">'
              + (x.cap ? '<span>cap <b>' + esc(x.cap) + '</b></span>' : '')
              + (x.serves ? '<span>服务于 ' + esc(x.serves) + (x.serves_version ? ' @v' + esc(x.serves_version) : '') + '</span>' : '')
              + '</div>'
            : '')
        + (x.changed ? '<div class="sch">' + esc(x.changed) + '</div>' : '')
        + (x.effect ? '<div class="se">副作用：' + esc(x.effect) + '</div>' : '')
        + '<div class="spath">' + esc(x.path) + '</div>'
        + '</div>';
    });
    return s;
  };
  sc += mkScr(DATA.scripts.filter(x => x.zone === "tool"), "工具", "长期保留，可反复运行");
  sc += mkScr(DATA.scripts.filter(x => x.zone === "temp"), "临时脚本", "跑完即弃，随日期沉积");
  if (!DATA.scripts.length) sc += '<p class="empty">暂无脚本</p>';
  document.getElementById("s-scripts").innerHTML = sc;

  // 任务
  const groups=[["blocked","阻塞","#E24B4A"],["doing","进行中","#BA7517"],["todo","待办","#888780"],["done","已完成","#0F6E56"]];
  let tk="";
  groups.forEach(g=>{
    const arr=DATA.tasks[g[0]];
    if(!arr || !arr.length) return;
    tk += '<div class="taskgrp"><p class="taskh"><span class="dot" style="background:'+g[2]+'"></span>'
        + g[1]+' <span style="color:var(--t3);font-weight:400">'+arr.length+'</span></p>';
    arr.forEach(t=>{
      const sh = s => s ? s.replace(/^\d{4}-/, "") : "";
      let meta = "";
      if (t.start && t.done_at) {
        meta = sh(t.start) + " → " + sh(t.done_at) + (t.elapsed ? " · " + t.elapsed : "");
      } else if (t.start) {
        meta = sh(t.start) + (t.elapsed ? " · 已挂 " + t.elapsed : "");
      }
      const tag = t.stale ? '<span class="tag t-warn">可能已完成未勾</span>' : '';
      const tid = t.tid ? '<span class="tid">'+esc(t.tid)+'</span>' : '';
      tk += '<div class="titem'+(t.done?" done":"")+'"><span class="bx"></span>'+tid+'<span class="tx">'+esc(t.text)+'</span>'
          + '<span class="tmeta">'+esc(meta)+tag+'</span></div>';
    });
    tk += '</div>';
  });
  document.getElementById("s-tasks").innerHTML =
    '<p class="hint">动作清单。只写做什么，不写为什么。完成超过 7 天的应清理。</p>' + (tk || '<p class="empty">暂无</p>');

  bind(document);
  bindTree();
  bindPathCopy();
  renderPend();
}

document.getElementById("expBtn").onclick = () => {
  const txt = buildExport();
  const box = document.getElementById("expBox");
  box.classList.add("show");
  const ta = document.getElementById("expArea");
  ta.value = txt;
  ta.select();
  let msg = "";
  try {
    navigator.clipboard.writeText(txt).then(()=>{
      document.getElementById("expMsg").textContent = "已复制到剪贴板，直接粘贴回对话框即可。";
    }).catch(()=>{
      document.getElementById("expMsg").textContent = "已生成，请手动全选复制（Ctrl+C）。";
    });
    msg = "已复制";
  } catch(e) {
    document.getElementById("expMsg").textContent = "已生成，请手动全选复制（Ctrl+C）。";
  }
  document.getElementById("expMsg").textContent = msg ? "已复制到剪贴板，直接粘贴回对话框即可。" : "";
};
document.getElementById("clrBtn").onclick = () => {
  if(!confirm("清空本机所有批示和页面内新增？导出前不要清。")) return;
  notes = {}; save();
  picks = []; savePicks();
  document.querySelectorAll(".act").forEach(x=>x.classList.remove("on","no","hold"));
  document.querySelectorAll(".ta").forEach(x=>x.value="");
  document.querySelectorAll(".saved").forEach(x=>x.classList.remove("show"));
  renderQueue();
  renderPend();
};
document.getElementById("modal").onclick = () => {
  document.getElementById("modal").classList.remove("show");
};
render();
</script>
</body>
</html>
"""

html_out = (TEMPLATE
            .replace("__PROJECT__", DATA["project"])
            # JSON 塞进 <script> 里，必须把 </ 转成 <\/。
            # 否则内嵌的文件内容里只要出现一次 </script>，浏览器就认为脚本结束，
            # 后面的 JSON 全变成页面正文——2026-11-13 candy 的看板就是这么烂的。
            # JSON 里 \/ 等价于 /，parse 结果不变。
            .replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("</", "<\\/")))
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write(html_out)

print("[build_board.py v44 · cap=build-board · tool]")
print("BOARD.html 已生成")
print("  主文档 %d · 决策 %d（生效 %d）· 待拍板 %d · 工作稿 %d（孤儿 %d）· 脚本 %d · 漂移 %d"
      % (health["mains"], len(decisions), health["decisions"], health["queue"],
         health["works"], health["orphan"], health["scripts"], health["drift"]))
if drift:
    for d in drift:
        print("  ! 待同步：%s（依赖 %s）" % (d["main"], ", ".join(d["bad"])))
