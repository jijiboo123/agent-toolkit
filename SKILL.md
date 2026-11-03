---
name: agent-toolkit
description: Make AI code editing visible and verifiable. Use when the user wants to watch edits happen in VS Code, when changes must be shown line by line before and after, or when a frontend page needs runtime testing without a browser (jsdom harness).
---

# Agent Toolkit

让 AI 改代码的过程**对人可见、对结果可验证**。六个小工具各解决一个真实痛点：

| 工具 | 解决的痛点 |
|---|---|
| `scripts/type_write.py` | 代码"啪"地一次写进去，人根本看不清改了什么 |
| `scripts/jump.py` | 改完才说"我改了第 120 行"，人得自己去找 |
| `scripts/jsdom_harness.cjs` | 没有浏览器就没法验证前端，只能靠肉眼 |
| `scripts/route_diff.py` | 说不清"这次到底改了多少"，全凭感觉 |
| `scripts/curl_probe.py` | 接口通不通只能靠猜，不知道状态码和耗时 |
| `scripts/acl_fix.ps1` | Windows 权限异常导致沙箱起不来，只能干瞪眼 |
| `scripts/repo_map.py` | 项目一大，模型就得一个个文件读，烧上下文 |

## 什么时候用

- 用户说"我要看着你改"、"先跳过去再改"、"给我看过程"
- 改代码前需要让人知道**马上要动哪一行**
- 前端页面需要跑起来验证（点击、输入、断言），但环境里没有浏览器
- 需要证明"改完真的能跑"，而不是"看起来应该能跑"

## 工具一：type_write.py 逐字写入

让文件内容一个字符一个字符出现在编辑器里，人能看到"打字"过程。

```bash
# 从标准输入读文本，逐字写进目标文件
"print('hello')" | python scripts/type_write.py out.py --delay 0.03

# 分段追加（第 2 段起必须 --no-clear）
python scripts/type_write.py out.py --from-file part2.txt --no-clear --delay 0
```

| 参数 | 作用 | 建议 |
|---|---|---|
| `--delay` | 每字符间隔（秒） | 演示 0.03；批量 0 |
| `--newline-delay` | 换行额外停顿 | 0.15 |
| `--no-clear` | 追加而非清空 | 第 2 段起必须加 |
| `--from-file` | 从文件读，不经管道 | **需要逐字节保真时必用** |

**为什么要 `--from-file`**：PowerShell 走管道会自动补一个结尾换行，导致产物和预期差一个字符。实测两个文件 SHA256 不一致，换 `--from-file` 后一致。

## 工具二：jump.py 先跳转再改

```bash
python scripts/jump.py app.js:120
python scripts/jump.py "D:\proj\src\main.py:45"
```

查找 VS Code 的顺序：环境变量 `VSCODE_CODE_CMD` → PATH 里的 `code` → 常见安装路径（含非默认盘符）。

找不到时不会崩，会提示怎么配：

```bat
setx VSCODE_CODE_CMD "D:\应用\Microsoft VS Code\bin\code.cmd"
```

## 工具三：jsdom_harness.cjs 无浏览器测试

```bash
node scripts/jsdom_harness.cjs --dir . --html index.html --js app.js \
     --origin http://127.0.0.1:8770/ --wait "#content" --assert asserts.cjs
```

断言文件长这样：

```js
module.exports = async ({ doc, window, sleep }) => {
  const rows = doc.querySelectorAll('#list .row').length;
  return { ok: rows === 3, rows };
};
```

它已经帮你补齐了 jsdom 缺的东西：`fetch`（相对路径按 `--origin` 解析）、`matchMedia`、`ResizeObserver`、`IntersectionObserver`、`getBBox`、媒体元素的 `load/play/pause`。

退出码：`0` 通过 / `2` 断言返回 `ok:false` / `3` 加载失败。

## 推荐流程

## 工具四：route_diff.py 改动量对比

```bash
python scripts/route_diff.py old.py new.py
python scripts/route_diff.py old.py new.py --unified     # 附完整 diff
python scripts/route_diff.py --git HEAD app.py           # 对比 git 版本与工作区
```

输出：

```
行数      : 24 → 29
新增/删除 : +5 / -0
保留      : 24 行
改动率    : 20.8%
新增函数  : greet_clean
```

**用处在说完"改好了"之后**：给用户一个数字，而不是一句"我优化了代码"。
退出码 `0` 无改动、`1` 有改动，能直接接 CI。

## 工具五：curl_probe.py 接口探测

```bash
python scripts/curl_probe.py https://api.example.com/health
python scripts/curl_probe.py https://api.example.com/list -H "Authorization: Bearer xxx" --json
python scripts/curl_probe.py https://cdn.example.com/movie.mp4 --range 0-1023
python scripts/curl_probe.py https://self-signed.local/api --insecure
```

输出状态码、耗时、类型、长度、分片支持、正文预览。退出码 `0` = 2xx。

**两个真实坑**（都已在脚本里处理）：

| 现象 | 原因 | 脚本行为 |
|---|---|---|
| `CERTIFICATE_VERIFY_FAILED` | 精简版 Python 缺 CA 证书 | 提示加 `--insecure` |
| 视频不能拖动进度条 | 服务端没回 `Accept-Ranges` | `--range` 一测就知道 |

## 工具六：acl_fix.ps1 Windows 权限诊断

```powershell
.\scripts\acl_fix.ps1 -Path "D:\work\proj"          # 只诊断
.\scripts\acl_fix.ps1 -Path "D:\work\proj" -Fix     # 真去改
```

症状：某目录里跑东西报 `SetNamedSecurityInfoW failed (Win32 5)`，或沙箱建不起来。
根因通常是目录缺 `WRITE_OWNER`。

脚本会打印**原始 SDDL**（回滚用）、列出当前用户的显式权限，`-Fix` 才动手，动手后复核。

> 注意两条：脚本内有 `exit`，**用子进程跑**（`powershell -File ...`），别在交互式 shell 里 dot-source；
> `.ps1` 必须存成 **UTF-8 带 BOM**，否则 PowerShell 5.1 会把中文注释读成乱码并报语法错。

## 工具七：repo_map.py 项目结构图

```bash
python scripts/repo_map.py                                    # 当前目录
python scripts/repo_map.py --dir ../查询路线 --tokens 2000
python scripts/repo_map.py --focus query_route.py --json
```

把整个项目压成一张带行号的符号树，丢给模型看。思路借鉴 [aider](https://github.com/Aider-AI/aider) 的 `repomap.py`，
但去掉了 tree-sitter / networkx / diskcache 三个重依赖——**只用标准库**。

原理三步：

1. **提符号**：Python 用 `ast` 拿模块级函数和类方法（带签名和行号）；JS/TS 用行级正则匹配 `function`/`class`/`const = () =>`
2. **建文件图**：文件 A 用到文件 B 定义的符号，就连一条 A→B 的边
3. **PageRank + 预算截断**：被引用得多的文件排前面；入口文件（有 `__main__` 守卫且定义了 `main()`）强制排第一

实测（查询路线，1277 行 Python）：

```
# 项目结构：查询路线（4 个源文件）
query_route.py  (720 行)
  App  :225
    App.do_search(self)  :405
    App.find_transfers(self)  :447
    ...
# 约 697 tokens（预算 2000）
```

**1277 行 → 697 tokens**，压缩比约 1:12。改代码前先跑一遍，就不用把文件一个个读进上下文。

> 为什么入口文件不靠 PageRank：入口没有入度（没人 import 它），PageRank 天然把它排最后。
> 我自己试过加权，得加到 20 倍才压得过工具模块，不如直接排序。

## 推荐流程

1. **`repo_map.py` 先看全局**（项目大时尤其必要）
2. **`jump.py` 跳到要改的行**（人看得见落点）
3. 改（小改动用 `type_write`，大改动分段写）
4. **`jump.py` 再跳到改完的行**
5. `node --check` / `python -m py_compile`
6. `jsdom_harness` 或真实运行验证
7. **`route_diff.py` 给出改动量数字**（改了几行、动了哪些函数）
8. 把验证结果贴给用户

## 常见坑

| 现象 | 原因 | 解法 |
|---|---|---|
| `jump.py` 说找不到 VS Code | 装在非默认路径 | 设 `VSCODE_CODE_CMD` |
| 逐字写出来的文件末尾多一行 | PowerShell 管道补换行 | 用 `--from-file` |
| 编辑器不刷新 | 文件监视器有延迟 | 点一下文件标签页强制重读 |
| jsdom 报 `Not implemented` | 媒体/布局 API 缺失 | harness 已桩掉；其它按需补 |
| 断言"通过"但页面实际是错的 | 用 `textContent` 判断，把隐藏元素也算进去了 | 改判 `hidden` 属性或 `getComputedStyle` |