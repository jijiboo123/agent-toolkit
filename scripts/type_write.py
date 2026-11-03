"""把源码逐字写入目标文件，让 VS Code 里能看见"打字"过程。

用法（从标准输入读文本）：
    $text | & $py type_write.py <目标文件> [--delay 0.03] [--newline-delay 0.15] [--no-clear]

参数：
    --delay            每个普通字符之间停多久（秒），默认 0.03
    --newline-delay    每遇到换行额外停多久，默认 0.15
    --no-clear         不清空目标文件（用于分段追加）
"""

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="逐字写入文件，制造打字效果")
    parser.add_argument("target", help="目标文件路径")
    parser.add_argument("--delay", type=float, default=0.03, help="字符间隔（秒）")
    parser.add_argument("--newline-delay", type=float, default=0.15, help="换行额外停顿（秒）")
    parser.add_argument("--no-clear", action="store_true", help="不清空目标文件，追加写入")
    parser.add_argument(
        "--from-file",
        metavar="源文件",
        help="从文件读文本而不是标准输入。需要逐字节保真时必须用这个："
        "PowerShell 走管道会额外补一个结尾换行，导致产物和预期差一个字符。",
    )
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, "r", encoding="utf-8", newline="") as source:
            text = source.read()
    else:
        text = sys.stdin.read()
    if not text:
        print("没有读到内容（标准输入和 --from-file 都是空的）", file=sys.stderr)
        return 2

    mode = "a" if args.no_clear else "w"
    written = 0
    try:
        with open(args.target, mode, encoding="utf-8", newline="") as handle:
            for ch in text:
                handle.write(ch)
                handle.flush()
                written += 1
                if ch == "\n":
                    time.sleep(args.newline_delay)
                else:
                    time.sleep(args.delay)
    except KeyboardInterrupt:
        print(f"\n已中断，写入 {written} 个字符", file=sys.stderr)
        return 130

    print(f"写入完成：{written} 个字符 -> {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
