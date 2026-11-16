# ---
# 本项目内不要手改这个文件：--sync-tools 升级会整体覆盖。
# 要改逻辑，去规范项目改，再同步过来。
# cap: verify-ledger
# purpose: 校验台账完整性——锚点断链、主文档漂移、孤儿产出、脚本元信息与能力重复
# serves: M-005#structure
# serves_version: 1
# kind: tool
# version: 12
# changed: 2026-11-13 写报告强制 LF
# idempotent: yes
# side-effect: 只读，除生成一份校验报告外不改任何文件
# ---
"""机械校验器。

设计原则：所有检查都不依赖任何人（包括 AI）的记忆。
跑一遍就知道哪里断了。

用法：python tools/scan.py
"""

import os
import re
import sys
import datetime

def _project_root():
    """项目根：--root 显式指定 > 当前工作目录。"""
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
TOOLS = os.path.join(ROOT, "tools")
ORPHAN_DAYS = 30
SCRIPT_STALE_DAYS = 7


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def parse_front(text):
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def as_list(v):
    if not v:
        return []
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip() for x in v.split(",") if x.strip()]


def load_mains():
    out = {}
    if not os.path.isdir(DOCS):
        return out
    for fn in os.listdir(DOCS):
        if not fn.endswith(".md"):
            continue
        full = os.path.join(DOCS, fn)
        txt = read(full)
        fm = parse_front(txt)
        anchors = {}
        body = re.sub(r"```.*?```", "", txt, flags=re.S)
        for am in re.finditer(r"\{#([A-Za-z0-9_\-]+)(?:\s+v(\d+))?\}", body):
            anchors[am.group(1)] = int(am.group(2)) if am.group(2) else 0
        out[fm.get("id", fn)] = {
            "file": "docs/" + fn,
            "fm": fm,
            "anchors": anchors,
        }
    return out


def load_decs():
    out = {}
    if not os.path.isdir(DECS):
        return out
    for fn in os.listdir(DECS):
        if not fn.endswith(".md"):
            continue
        fm = parse_front(read(os.path.join(DECS, fn)))
        out[fm.get("id", fn)] = fm
    return out


def script_meta(path):
    """读脚本头部元信息块。"""
    try:
        head = read(path)[:800]
    except Exception:
        return None
    m = re.search(r"^#\s*---\s*$(.*?)^#\s*---\s*$", head, re.S | re.M)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("#").strip()
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta


def main():
    problems = []
    warnings = []

    mains = load_mains()
    decs = load_decs()

    active = {k for k, v in decs.items() if v.get("status", "active") == "active"}

    # 1. 决策 target 断链
    for did, fm in sorted(decs.items()):
        target = fm.get("target", "")
        if not target:
            continue
        if "#" not in target:
            warnings.append("%s target 缺少锚点：%s" % (did, target))
            continue
        mid, anchor = target.split("#", 1)
        if mid not in mains:
            problems.append("%s 指向不存在的主文档：%s" % (did, target))
        elif anchor not in mains[mid]["anchors"]:
            problems.append("%s 锚点断链：%s 里没有 #%s" % (did, target, anchor))

    # 2. 主文档漂移
    for mid, m in mains.items():
        for d in as_list(m["fm"].get("depends_on", "")):
            if d in decs and decs[d].get("status", "active") != "active":
                problems.append("%s 依赖的 %s 已失效，正文需同步" % (mid, d))

    # 3. 孤儿产出
    evidence = set()
    for fm in decs.values():
        evidence.update(as_list(fm.get("evidence", "")))

    today = datetime.date.today()
    if os.path.isdir(WORK):
        for dirpath, _, files in os.walk(WORK):
            dirdate = os.path.basename(dirpath)
            d = None
            try:
                d = datetime.date.fromisoformat(dirdate)
            except ValueError:
                pass

            for fn in files:
                if not fn.endswith(".md"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                fm = parse_front(read(full))
                if fm.get("type") == "report":
                    continue
                wid = fm.get("id", fn[:-3])
                if wid not in evidence:
                    age = (today - d).days if d else 999
                    if age > ORPHAN_DAYS:
                        warnings.append("孤儿产出（%d 天未被引用，阈值 %d 天）：%s"
                                        % (age, ORPHAN_DAYS, rel))

    # 4. 脚本：身份、归属、唯一性
    scripts = []

    def collect(base, zone):
        if not os.path.isdir(base):
            return
        for dirpath, _, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                scripts.append({
                    "path": os.path.relpath(full, ROOT).replace("\\", "/"),
                    "zone": zone,
                    "meta": script_meta(full) or {},
                    "mtime": datetime.date.fromtimestamp(os.path.getmtime(full)),
                })

    collect(TOOLS, "tool")
    collect(WORK, "temp")
    rb = os.path.join(ROOT, "build.py")
    if os.path.exists(rb):
        scripts.append({
            "path": "build.py",
            "zone": "tool",
            "meta": script_meta(rb) or {},
            "mtime": datetime.date.fromtimestamp(os.path.getmtime(rb)),
        })

    caps = {}
    for s in scripts:
        meta = s["meta"]
        p = s["path"]

        if not meta:
            problems.append("脚本缺元信息块：%s" % p)
            continue

        cap = meta.get("cap", "")
        if not cap:
            problems.append("脚本缺 cap：%s（无法判断是否与别的脚本重复）" % p)
        else:
            caps.setdefault(cap, []).append(s)

        if not meta.get("version"):
            problems.append("脚本缺 version：%s" % p)
        if not meta.get("serves"):
            problems.append("脚本缺 serves：%s（不知道它服务于哪件事）" % p)
        else:
            serves = meta["serves"]
            if "#" not in serves:
                warnings.append("%s serves 缺锚点：%s" % (p, serves))
            else:
                mid, anchor = serves.split("#", 1)
                if mid not in mains:
                    problems.append("%s serves 指向不存在的主文档：%s" % (p, serves))
                elif anchor not in mains[mid]["anchors"]:
                    problems.append("%s serves 锚点断链：%s 里没有 #%s" % (p, serves, anchor))
                else:
                    av = mains[mid]["anchors"][anchor]
                    sv_raw = meta.get("serves_version", "")
                    if not sv_raw:
                        problems.append(
                            "%s 缺 serves_version：%s 当前是 v%d，应写 serves_version: %d"
                            % (p, serves, av, av))
                    else:
                        try:
                            sv = int(sv_raw)
                        except ValueError:
                            problems.append("%s serves_version 不是数字：%s" % (p, sv_raw))
                            sv = None
                        if sv is not None and sv != av:
                            if av > sv:
                                warnings.append(
                                    "%s 服务的 %s 已升到 v%d，脚本记录的是 v%d —— "
                                    "确认行为仍匹配后把 serves_version 改成 %d"
                                    % (p, serves, av, sv, av))
                            else:
                                warnings.append(
                                    "%s 记录的 serves_version 是 v%d，但文档只有 v%d —— "
                                    "文档漏改了，需补写内容并涨版本" % (p, sv, av))

        if meta.get("kind") == "onetime" and meta.get("idempotent", "").lower() == "no":
            if (today - s["mtime"]).days > SCRIPT_STALE_DAYS:
                warnings.append("非幂等一次性脚本超过 7 天未清理：%s" % p)

        if s["zone"] == "tool" and meta.get("kind") != "tool":
            warnings.append("tools/ 下放了非 tool 类脚本：%s（应移到 work/日期/）" % p)

    for cap, arr in caps.items():
        if len(arr) < 2:
            continue
        in_tools = [s for s in arr if s["zone"] == "tool"]
        if len(in_tools) > 1:
            problems.append(
                "cap 重复实现 [%s]：%s —— 同一件事只允许一个可执行版本"
                % (cap, " / ".join(s["path"] for s in in_tools)))
        else:
            warnings.append(
                "cap [%s] 存在历史副本：%s —— tools/ 那份是当前版本，work/ 下的可删"
                % (cap, " / ".join(s["path"] for s in arr if s["zone"] == "temp")))

    # 5. 外来文件检查
    ROOT_OK_FILES = {"AGENTS.md", "QUEUE.md", "TASKS.md", "build.py",
                     "BOARD.html", ".gitignore", ".gitattributes", ".scanignore"}
    ROOT_OK_DIRS = {"docs", "decisions", "work", "assets", "tools",
                    "templates", "inbox", ".workbuddy", ".git", "__pycache__"}

    # 项目可以在根的 .scanignore 里声明「这些名字本来就该在根目录」，
    # 每行一个，# 开头是注释。既有项目搬进 coperate 时，
    # 不必为了通过校验而把原有目录结构搬走。
    extra_ok = set()
    ignore_path = os.path.join(ROOT, ".scanignore")
    if os.path.isfile(ignore_path):
        for line in read(ignore_path).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                extra_ok.add(line)
    ROOT_OK_FILES |= extra_ok
    ROOT_OK_DIRS |= extra_ok

    if os.path.isdir(ROOT):
        for name in sorted(os.listdir(ROOT)):
            full = os.path.join(ROOT, name)
            if os.path.isdir(full):
                if name not in ROOT_OK_DIRS:
                    problems.append("根目录出现未知目录：%s —— 该放哪？见 M-003#inbox" % name)
            elif name not in ROOT_OK_FILES:
                problems.append("根目录出现未知文件：%s —— 该进 inbox/ 还是 assets/？" % name)

    if os.path.isdir(DOCS):
        for fn in sorted(os.listdir(DOCS)):
            if not fn.endswith(".md"):
                problems.append("docs/ 下有非 md 文件：%s（素材请放 inbox/ 或 assets/）" % fn)
                continue
            if not re.match(r"^M-\d{3}-", fn):
                problems.append("docs/ 下有不符命名的文件：%s（主文档应为 M-001-xxx.md）" % fn)
                continue
            fm = parse_front(read(os.path.join(DOCS, fn)))
            if not fm.get("id"):
                problems.append("docs/%s 缺 front matter，无法识别" % fn)

    inbox_dir = os.path.join(ROOT, "inbox")
    if os.path.isdir(inbox_dir):
        items = [x for x in sorted(os.listdir(inbox_dir)) if x != ".gitkeep"]
        if items:
            warnings.append("inbox/ 有 %d 个待接收文件：%s —— 需要读一下并分流"
                            % (len(items), "、".join(items[:5])))

    # 6. 模板与主文档的节版本对齐
    tpl_root = os.path.join(ROOT, "templates")
    if os.path.isdir(tpl_root):
        def tpl_anchors(path):
            txt = read(path)
            fm = parse_front(txt)
            body = re.sub(r"```.*?```", "", txt, flags=re.S)
            anchors = {}
            for am in re.finditer(r"\{#([A-Za-z0-9_\-]+)(?:\s+v(\d+))?\}", body):
                anchors[am.group(1)] = int(am.group(2)) if am.group(2) else 0
            return fm.get("id"), anchors

        # 只查通用模板（根层）；templates/<type>/ 是另一套骨架，不绑定本项目文档版本
        for fn in sorted(os.listdir(tpl_root)):
            if not (fn.endswith(".md") and fn.startswith("M-")):
                continue
            mid, tpl_a = tpl_anchors(os.path.join(tpl_root, fn))
            if mid not in mains:
                continue
            m = mains[mid]
            for anchor, ver in tpl_a.items():
                if anchor not in m["anchors"]:
                    continue
                dv = m["anchors"][anchor]
                if dv != ver:
                    problems.append(
                        "模板版本不一致：templates/%s 的 #%s 是 v%d，但 %s 是 v%d"
                        " —— 改主文档某节时，模板同名节必须一起涨版本"
                        % (fn, anchor, ver, m["file"], dv))
    # 输出
    print("=" * 62)
    print("[scan_ledger.py v12 · cap=verify-ledger · tool]")
    print("台账校验 · %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 62)
    print("主文档 %d · 决策 %d（生效 %d）" % (len(mains), len(decs), len(active)))
    print()

    if problems:
        print("[必须修] %d 项" % len(problems))
        for p in problems:
            print("  x " + p)
        print()
    else:
        print("[必须修] 0 项 —— 引用体系完整")
        print()

    if warnings:
        print("[建议处理] %d 项" % len(warnings))
        for w in warnings:
            print("  - " + w)
        print()
    else:
        print("[建议处理] 0 项")
        print()

    # 写报告
    d = datetime.date.today().isoformat()
    rdir = os.path.join(WORK, d)
    os.makedirs(rdir, exist_ok=True)
    rpath = os.path.join(rdir, "note-校验报告.md")
    lines = [
        "---",
        "id: W-%s-VERIFY" % d.replace("-", "")[4:],
        "title: 台账校验报告",
        "type: report",
        "status: active",
        "summary: 自动生成，problems %d 项 / warnings %d 项" % (len(problems), len(warnings)),
        "evidence_for: []",
        "---",
        "",
        "# 台账校验报告",
        "",
        "生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "",
        "## 必须修（%d）" % len(problems),
        "",
    ]
    lines += ["- " + p for p in problems] or ["_无_"]
    lines += ["", "## 建议处理（%d）" % len(warnings), ""]
    lines += ["- " + w for w in warnings] or ["_无_"]
    with open(rpath, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("报告已写入：" + os.path.relpath(rpath, ROOT).replace("\\", "/"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
