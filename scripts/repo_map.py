"""项目结构图（repo map）：把整个项目压成一张带行号的符号树，塞给模型看。

灵感来自 aider 的 repomap.py，但做了两处简化：
  - 用 Python ast + 正则提取符号，不依赖 tree-sitter（省掉 100MB 依赖）
  - PageRank 手写 20 行，不依赖 networkx

原理（和 aider 一致）：
  1. 每个文件里有哪些定义（函数 / 类 / 方法，带行号和参数）
  2. 谁引用了谁 —— 文件 A 用到文件 B 定义的符号，就连一条 A→B 的边
  3. 在文件图上跑 PageRank，被引用得多的文件排前面
  4. 按 token 预算从上往下截断，生成树状结构图

用法：
    python repo_map.py                      # 当前目录
    python repo_map.py --dir ../查询路线
    python repo_map.py --focus query_route.py,train_api.py   # 给关注的文件加权
    python repo_map.py --tokens 800         # 控制输出大小（默认 2000）
    python repo_map.py --json               # 机器可读

退出码：0 正常，1 找不到源文件。
"""

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", "_study", ".idea"}
PY_EXTS = {".py"}
JS_EXTS = {".js", ".cjs", ".mjs", ".jsx", ".ts", ".tsx"}
CHARS_PER_TOKEN = 3.5      # 粗估：代码里约 3.5 个字符一个 token
DAMPING = 0.85
ITERATIONS = 40

# 入口文件加权：人看一个项目，最先想知道"从哪开始"
ENTRY_NAMES = {
    "main.py": 4.0, "app.py": 3.0, "__main__.py": 3.0, "cli.py": 2.5,
    "index.js": 3.0, "index.cjs": 3.0, "main.js": 2.5, "server.py": 2.0,
}

JS_PATTERNS = [
    (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
    (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("), "function"),
    (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>"), "function"),
]
IDENT = re.compile(r"[A-Za-z_][\w]*")


def iter_source_files(root, extra_skip=()):
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in extra_skip:
            continue
        if path.suffix.lower() in PY_EXTS | JS_EXTS:
            yield path
def _signature(node):
    """把函数参数拼成 (self, a, b=1) 这种短签名"""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""
    names = [a.arg for a in node.args.args]
    if node.args.vararg:
        names.append("*" + node.args.vararg.arg)
    return "(" + ", ".join(names[:6]) + (", …)" if len(names) > 6 else ")")


def parse_python(path):
    """返回 [(名字, 行号, 类型, 签名)]，只取模块级和类方法"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((node.name, node.lineno, "def", _signature(node)))
        elif isinstance(node, ast.ClassDef):
            found.append((node.name, node.lineno, "class", ""))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append((f"{node.name}.{child.name}", child.lineno, "method", _signature(child)))
    return found


def parse_js(path):
    """JS/TS 没有 ast 可用，按常见定义形态做行级正则"""
    found = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for number, line in enumerate(lines, 1):
        if len(line) > 300:
            continue
        for pattern, kind in JS_PATTERNS:
            match = pattern.match(line)
            if match:
                found.append((match.group(1), number, kind, ""))
                break
    return found


def collect(root, focus=()):
    """扫描项目：每个文件定义了哪些符号"""
    files = []
    for path in iter_source_files(root):
        rel = path.relative_to(root).as_posix()
        parser = parse_python if path.suffix.lower() in PY_EXTS else parse_js
        defs = parser(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append({
            "path": rel,
            "lines": text.count("\n") + 1,
            "defs": defs,
            "idents": set(IDENT.findall(text)),
            "focus": rel in focus,
            # 入口识别：Python 看 __main__ 守卫，JS 看是不是 index/main/app
            # 入口识别：要有 __main__ 守卫，并且真的定义了 main()
            # （只有 __main__ 的是"可执行脚本"，不等于项目入口）
            "entry": (
                "__main__" in text and "def main(" in text
            ) if path.suffix.lower() in PY_EXTS else False,
        })
    return files
def build_graph(files):
    """文件名 → PageRank 分数。边 = 引用了别的文件里定义的符号"""
    owner = {}
    for item in files:
        for name, _line, _kind, _sig in item["defs"]:
            short = name.split(".")[-1]
            owner.setdefault(short, set()).add(item["path"])

    edges = {}
    for item in files:
        targets = defaultdict(int)
        for ident in item["idents"]:
            for other in owner.get(ident, ()):
                if other != item["path"]:
                    targets[other] += 1
        edges[item["path"]] = dict(targets)

    paths = [item["path"] for item in files]
    count = len(paths)
    if not count:
        return {}
    weight = 100.0 / count
    personal = {}
    for item in files:
        # 入口文件天然重要（人看项目先看它），给一点加权免得被工具模块淹没
        entry_boost = ENTRY_NAMES.get(Path(item["path"]).name.lower(), 1.0)
        if item.get("entry"):
            entry_boost = max(entry_boost, 4.0)   # 有 __main__ 守卫，就是入口
        personal[item["path"]] = weight * entry_boost * (3 if item["focus"] else 1)

    rank = dict(personal)
    for _ in range(ITERATIONS):
        total_no_out = 0.0
        for path in paths:
            if not edges[path]:
                total_no_out += rank[path]
        updated = {}
        base = (1 - DAMPING) / count
        base_dangling = DAMPING * total_no_out / count
        for path in paths:
            incoming = base + base_dangling + DAMPING * personal[path]
            for source in paths:
                if path in edges.get(source, {}):
                    incoming += DAMPING * rank[source] * edges[source][path] / sum(edges[source].values())
            updated[path] = incoming
        rank = updated
    return rank


def render(files, rank, char_budget):
    """按排名铺开符号树，超预算就停"""
    # 入口文件强制排最前（PageRank 天然把入口排在后面，因为它没有入度），
    # 其余按被引用程度排序
    ordered = sorted(
        files,
        key=lambda f: (0 if f.get("entry") else 1, -rank.get(f["path"], 0), f["path"]),
    )
    out, used, shown = [], 0, 0
    for item in ordered:
        if not item["defs"]:
            continue
        header = f"{item['path']}  ({item['lines']} 行)"
        block = [header]
        for name, line, kind, sig in item["defs"]:
            prefix = "    " if kind == "method" else "  "
            label = f"{name}{sig}" if sig else name
            block.append(f"{prefix}{label}  :{line}")
        text = "\n".join(block)
        if used + len(text) > char_budget and shown > 0:
            out.append(f"... 还有 {len(ordered) - shown} 个文件被省略（调大 --tokens 可展开）")
            break
        out.append(text)
        used += len(text)
        shown += 1
    return "\n".join(out), shown
def main():
    parser = argparse.ArgumentParser(description="项目结构图")
    parser.add_argument("--dir", default=".", help="项目根目录")
    parser.add_argument("--focus", default="", help="重点关注的文件，逗号分隔（会加权排序）")
    parser.add_argument("--tokens", type=int, default=2000, help="输出 token 预算（默认 2000）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    root = Path(args.dir).resolve()
    if not root.is_dir():
        print(f"目录不存在: {root}", file=sys.stderr)
        return 1

    focus = {f.strip() for f in args.focus.split(",") if f.strip()}
    files = collect(root, focus)
    if not files:
        print("没有找到 .py / .js 源文件", file=sys.stderr)
        return 1

    rank = build_graph(files)
    text, shown = render(files, rank, int(args.tokens * CHARS_PER_TOKEN))

    if args.json:
        payload = {
            "root": str(root),
            "files": len(files),
            "shown": shown,
            "ranked": [
                {"path": f["path"], "lines": f["lines"], "score": round(rank.get(f["path"], 0), 4),
                 "symbols": [{"name": n, "line": l, "kind": k} for n, l, k, _s in f["defs"]]}
                for f in sorted(files, key=lambda x: -rank.get(x["path"], 0))
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"# 项目结构：{root.name}（{len(files)} 个源文件，显示前 {shown} 个）\n")
    print(text)
    approx = len(text) / CHARS_PER_TOKEN
    note = ""
    if approx > args.tokens * 1.2:
        note = "　← 单个入口文件就超预算了，为了可用性完整显示"
    print(f"\n# 约 {approx:.0f} tokens（预算 {args.tokens}）{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())