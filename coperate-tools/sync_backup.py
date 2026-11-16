#!/usr/bin/env python3
# ---
# cap: sync-to-nas
# purpose: 本地工作区单向备份到备份盘，增量、默认不删远端
# serves: M-003#local
# serves_version: 3
# kind: tool
# version: 3
# changed: 2026-11-16 v3 NAS 上 git object 是 0444 只读：同名同大小直接判一致，真要覆盖才临时清只读位；对齐 M-003#local v3
# idempotent: yes
# side-effect: 写备份盘 对应目录（--check 时只读）
# ---
#
# 用法：
#   python coperate-tools/sync_backup.py --check    只报告，不动文件
#   python coperate-tools/sync_backup.py            真同步
#   python coperate-tools/sync_backup.py --prune    额外删除远端多余文件
#
# 单向：本地 → 群晖。禁止在备份盘上改源文件，改动会被下一次同步覆盖。
# .git 是故意保留的：备份要能恢复版本历史，不只是恢复文件。
import argparse
import json
import os
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.environ.get("COPERATE_WORKSPACE") or os.path.dirname(HERE)

# 发行包里不写死任何路径：配置读同目录的 config.json（模板见 config.example.json）
_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
try:
    with open(_CFG, encoding="utf-8") as _f:
        _cfg = json.load(_f)
except (OSError, ValueError):
    _cfg = {}

TARGETS = _cfg.get("backup_targets", [])
PROJECTS = _cfg.get("backup_projects", [])
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".workbuddy",
             "#recycle", "_trash", "@eaDir"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
SKIP_EXT = {".pyc", ".tmp"}
# SMB 上文件时间精度与时区不总一致，差 2 秒内视为相同
MTIME_TOLERANCE = 2.0


def pick_target():
    for t in TARGETS:
        if os.path.isdir(t):
            return t
    return None


def walk(src):
    """产出 (相对路径, 绝对路径)，排除可再生目录。.git 保留。"""
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            full = os.path.join(dirpath, fn)
            yield os.path.relpath(full, src).replace("\\", "/"), full


def same(src, dst):
    if not os.path.isfile(dst):
        return False
    try:
        a, b = os.stat(src), os.stat(dst)
    except OSError:
        return False
    if a.st_size != b.st_size:
        return False
    # git object 按内容寻址：同名同大小即同内容。NAS 上这些文件是 0444 只读，
    # 只因 mtime 不同就去覆盖会 PermissionError，而且本来也没必要覆盖。
    if "/.git/objects/" in src.replace("\\", "/"):
        return True
    return abs(a.st_mtime - b.st_mtime) <= MTIME_TOLERANCE


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy2(src, dst)   # 保留 mtime，下次才不会一直判为「不同」
    except PermissionError:
        # NAS 上 git object 是 0444 只读。确实需要覆盖时才临时清只读位。
        if os.path.isfile(dst):
            os.chmod(dst, os.stat(dst).st_mode | stat.S_IWRITE)
        shutil.copy2(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check", action="store_true", help="只报告，不写任何文件")
    ap.add_argument("--prune", action="store_true", help="删除远端多余文件（默认不删）")
    ap.add_argument("--target", default="", help="指定备份根，默认自动探测")
    args = ap.parse_args()

    print("[sync_backup.py v3 · cap=sync-to-nas · tool]")
    dst_root = args.target or pick_target()
    if not dst_root:
        print("找不到备份目标：在 config.json 的 backup_targets 里填，或用 --target 指定。")
        return 1
    print("源    %s" % SRC_ROOT)
    print("目标  %s" % dst_root)
    print("范围  %s" % "、".join(PROJECTS))
    print()

    totals = {"new": 0, "update": 0, "same": 0, "prune": 0}
    for proj in PROJECTS:
        src_base = os.path.join(SRC_ROOT, proj)
        dst_base = os.path.join(dst_root, proj)
        if not os.path.isdir(src_base):
            print("[跳过] 源不存在：%s" % src_base)
            continue

        src_files = {}
        for rel, full in walk(src_base):
            src_files[rel] = full

        n = {"new": 0, "update": 0, "same": 0}
        for rel, full in sorted(src_files.items()):
            dst = os.path.join(dst_base, *rel.split("/"))
            if same(full, dst):
                n["same"] += 1
                continue
            kind = "new" if not os.path.isfile(dst) else "update"
            n[kind] += 1
            if args.check:
                print("  %-7s %s/%s" % (kind, proj, rel))
            else:
                copy(full, dst)

        if args.prune and os.path.isdir(dst_base):
            for dirpath, dirnames, filenames in os.walk(dst_base, followlinks=False):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, dst_base).replace("\\", "/")
                    if rel in src_files:
                        continue
                    totals["prune"] += 1
                    if args.check:
                        print("  prune   %s/%s" % (proj, rel))
                    else:
                        os.remove(full)

        print("  %-18s 新增 %d · 更新 %d · 一致 %d" % (proj, n["new"], n["update"], n["same"]))
        for k in ("new", "update", "same"):
            totals[k] += n[k]

    print()
    if args.check:
        print("预演：新增 %d · 更新 %d · 一致 %d · 待删 %d。未写任何文件。"
              % (totals["new"], totals["update"], totals["same"], totals["prune"]))
        return 0
    print("已同步：新增 %d · 更新 %d · 一致 %d · 删除 %d。"
          % (totals["new"], totals["update"], totals["same"], totals["prune"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
