"""改动量对比：回答"这次改到底动了多少"。

用途：AI 改完代码后，用数字说明改动面——改了几行、保留了多少、动了哪些函数。

用法：
    python route_diff.py old.py new.py
    python route_diff.py old.py new.py --unified      # 附带完整 diff
    python route_diff.py --git HEAD app.py            # 对比 git 里的版本与工作区
    python route_diff.py old.py new.py --json         # 机器可读

输出：行数变化、新增/删除/保留行数、改动率、被增删的函数名。
退出码：0 = 无改动，1 = 有改动（方便接 CI）。
"""

import argparse
import difflib
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEF_PATTERN = re.compile(r"^\s*(?:async\s+)?(?:def|class|function|func)\s+([A-Za-z_][\w]*)")


def read_lines(path):
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


GIT_CANDIDATES = [
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
]


def _git_exe():
    """优先 PATH 里的 git；没有就用已知安装路径（子系统 shell 常读不到系统 PATH）"""
    found = shutil.which("git")
    if found:
        return found
    for candidate in GIT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("找不到 git：请安装 Git，或设置环境变量 GIT_EXE 指向 git.exe")


def read_from_git(revision, path):
    """从 git 里读某个版本的文件内容"""
    result = subprocess.run(
        [_git_exe(), "show", f"{revision}:{path}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git show 失败：{result.stderr.strip()}")
    return result.stdout.splitlines()


def summarise(old_lines, new_lines):
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added = removed = kept = 0
    added_defs, removed_defs = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            kept += i2 - i1
        elif tag == "insert":
            added += j2 - j1
            added_defs += _defs(new_lines[j1:j2])
        elif tag == "delete":
            removed += i2 - i1
            removed_defs += _defs(old_lines[i1:i2])
        else:
            added += j2 - j1
            removed += i2 - i1
            added_defs += _defs(new_lines[j1:j2])
            removed_defs += _defs(old_lines[i1:i2])
    base = max(len(old_lines), 1)
    return {
        "old_lines": len(old_lines),
        "new_lines": len(new_lines),
        "added": added,
        "removed": removed,
        "kept": kept,
        "changed_ratio": round((added + removed) / base * 100, 1),
        "added_defs": added_defs,
        "removed_defs": removed_defs,
    }


def _defs(lines):
    names = []
    for line in lines:
        match = DEF_PATTERN.match(line)
        if match:
            names.append(match.group(1))
    return names
def main():
    parser = argparse.ArgumentParser(description="改动量对比")
    parser.add_argument("old", nargs="?", help="旧文件")
    parser.add_argument("new", nargs="?", help="新文件")
    parser.add_argument("--git", metavar="REV", help="旧版本用 git 里的这个版本（如 HEAD）")
    parser.add_argument("--unified", action="store_true", help="附带完整 diff")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    if args.git:
        # --git 模式下第一个位置参数就是工作区文件
        target = args.new or args.old
        if not target:
            raise SystemExit("用 --git 时要指定工作区文件，例如：python route_diff.py --git HEAD app.py")
        old_lines = read_from_git(args.git, target)
        new_lines = read_lines(target)
        old_label, new_label = f"{args.git}:{target}", f"工作区:{target}"
    else:
        if not args.old or not args.new:
            raise SystemExit("用法：python route_diff.py old.py new.py")
        old_lines, new_lines = read_lines(args.old), read_lines(args.new)
        old_label, new_label = args.old, args.new

    info = summarise(old_lines, new_lines)
    info["old_label"], info["new_label"] = old_label, new_label

    if args.json:
        print(json_dumps(info))
        return 1 if (info["added"] or info["removed"]) else 0

    print(f"{old_label}  →  {new_label}")
    print(f"  行数      : {info['old_lines']} → {info['new_lines']}")
    print(f"  新增/删除 : +{info['added']} / -{info['removed']}")
    print(f"  保留      : {info['kept']} 行")
    print(f"  改动率    : {info['changed_ratio']}%")
    if info["added_defs"]:
        print(f"  新增函数  : {', '.join(info['added_defs'])}")
    if info["removed_defs"]:
        print(f"  删除函数  : {', '.join(info['removed_defs'])}")

    if args.unified:
        print()
        diff = difflib.unified_diff(old_lines, new_lines, fromfile=old_label, tofile=new_label, lineterm="")
        for line in diff:
            print(line)

    return 1 if (info["added"] or info["removed"]) else 0


def json_dumps(payload):
    import json
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())