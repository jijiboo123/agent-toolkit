"""跳转 VS Code 到指定文件的指定行，让人能实时看到 AI 在改哪里。

用法：
    python jump.py app.js:120
    python jump.py "D:\\proj\\app.py:45"

查找 VS Code 的顺序：
  1. 环境变量 VSCODE_CODE_CMD
  2. PATH 里的 code / code.cmd
  3. 常见安装路径（含非默认盘符）

找不到时不会报错退出，只提示怎么配。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# 这台机器的 VS Code 装在 D:\应用，不在默认目录，所以多试几个位置
COMMON_PATHS = [
    Path(r"C:\Program Files\Microsoft VS Code\bin\code.cmd"),
    Path(r"C:\Program Files (x86)\Microsoft VS Code\bin\code.cmd"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/bin/code.cmd",
    Path(r"D:\应用\Microsoft VS Code\bin\code.cmd"),
]


def find_code():
    """返回可执行的 code 命令路径，找不到返回 None"""
    env = os.environ.get("VSCODE_CODE_CMD")
    if env and Path(env).exists():
        return env
    name = "code.cmd" if os.name == "nt" else "code"
    found = shutil.which("code") or shutil.which(name)
    if found:
        return found
    for path in COMMON_PATHS:
        if path.exists():
            return str(path)
    return None


def main(argv):
    if len(argv) != 1 or ":" not in argv[0]:
        print("用法: python jump.py <文件>:<行号>", file=sys.stderr)
        return 2
    target = argv[0]
    code_cmd = find_code()
    if not code_cmd:
        print("找不到 VS Code 命令行。请设置环境变量 VSCODE_CODE_CMD 指向 code.cmd，", file=sys.stderr)
        print(r'例如: setx VSCODE_CODE_CMD "D:\应用\Microsoft VS Code\bin\code.cmd"', file=sys.stderr)
        return 1
    try:
        subprocess.run([code_cmd, "-g", target], check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as err:
        print(f"跳转失败: {err}", file=sys.stderr)
        return 1
    print(f"已跳转: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))