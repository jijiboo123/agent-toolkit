"""接口探测：状态码、耗时、响应头、正文片段，一条命令看清接口活没活。

只用标准库，Windows 上不依赖 curl。

用法：
    python curl_probe.py https://api.example.com/health
    python curl_probe.py https://api.example.com/list?page=1 -H "Authorization: Bearer xxx"
    python curl_probe.py https://cdn.example.com/movie.mp4 --range 0-1023
    python curl_probe.py https://api.example.com/list --json

退出码：0 = 2xx，1 = 非 2xx 或请求失败。
"""

import argparse
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ProbeTool/1.0"


def build_request(url, headers, byte_range):
    merged = {"User-Agent": UA, "Accept": "*/*"}
    merged.update(headers)
    if byte_range:
        merged["Range"] = f"bytes={byte_range}"
    if not urllib.parse.urlparse(url).scheme:
        raise SystemExit(f"URL 缺少协议头：{url}")
    return urllib.request.Request(url, headers=merged)


def main():
    parser = argparse.ArgumentParser(description="接口探测")
    parser.add_argument("url")
    parser.add_argument("-H", "--header", action="append", default=[], help='请求头，形如 "Name: value"')
    parser.add_argument("--range", dest="byte_range", help="测分片下载，例如 0-1023")
    parser.add_argument("--preview", type=int, default=300, help="正文预览字符数（默认 300）")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，方便脚本消费")
    parser.add_argument("--insecure", action="store_true", help="跳过证书校验（缺 CA 或自签证书时用）")
    args = parser.parse_args()

    headers = {}
    for raw in args.header:
        if ":" not in raw:
            raise SystemExit(f"请求头格式不对：{raw}")
        name, _, value = raw.partition(":")
        headers[name.strip()] = value.strip()

    request = build_request(args.url, headers, args.byte_range)
    context = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()
    started = time.time()
    status, reason, resp_headers, body = None, "", {}, b""
    try:
        with urllib.request.urlopen(request, timeout=args.timeout, context=context) as response:
            status = response.status
            reason = response.reason or ""
            resp_headers = dict(response.headers.items())
            body = response.read()
    except urllib.error.HTTPError as err:
        status = err.code
        reason = err.reason or ""
        resp_headers = dict(err.headers.items()) if err.headers else {}
        body = err.read() or b""
    except urllib.error.URLError as err:
        reason = getattr(err, "reason", err)
        print(f"请求失败：{reason}")
        if "CERTIFICATE_VERIFY_FAILED" in str(reason) or isinstance(reason, ssl.SSLError):
            print("提示：本机 Python 缺少 CA 证书，加 --insecure 可跳过校验（仅内部/自签服务建议）")
        return 1
    elapsed = time.time() - started

    text = body.decode("utf-8", "replace")
    summary = {
        "url": args.url,
        "status": status,
        "reason": reason,
        "elapsed_ms": round(elapsed * 1000),
        "content_type": resp_headers.get("Content-Type", ""),
        "content_length": resp_headers.get("Content-Length", ""),
        "content_range": resp_headers.get("Content-Range", ""),
        "accept_ranges": resp_headers.get("Accept-Ranges", ""),
        "bytes_received": len(body),
        "preview": text[: args.preview],
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"状态    : {status} {reason}")
        print(f"耗时    : {summary['elapsed_ms']} ms")
        print(f"类型    : {summary['content_type'] or '(无)'}")
        print(f"长度    : {summary['content_length'] or '(无)'}")
        if summary["content_range"]:
            print(f"分片    : {summary['content_range']}")
        if summary["accept_ranges"]:
            print(f"支持分片: {summary['accept_ranges']}")
        print(f"收到    : {len(body)} 字节")
        print(f"预览    : {summary['preview']!r}")

    return 0 if status and 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())