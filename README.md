# agent-toolkit

让 AI 改代码的过程**对人可见、对结果可验证**。三个小工具，解决三个真实痛点。

## 为什么做这个

我用 AI 辅助写代码时，反复遇到三件事：

1. **改了什么看不出来** —— 代码"啪"地一次写进去，我根本不知道它动了哪几行。
2. **改完才告诉我行号** —— 等我想看的时候早就改完了，得自己翻。
3. **"应该能跑"不等于能跑** —— 没有浏览器环境时，只能靠肉眼判断前端对不对。

这三个工具就是针对这三点做的。都用 Python / Node 标准写法，没有框架依赖。

## 工具一：`scripts/type_write.py` —— 逐字写入，看得见打字过程

```bash
python scripts/type_write.py out.py --from-file part1.txt --delay 0.03
python scripts/type_write.py out.py --from-file part2.txt --no-clear --delay 0
```

文件内容一个字符一个字符出现在 VS Code 里。适合演示、教学、让人确认逻辑顺序。

**实测**（同一段 37 行 / 811 字符）：

| 方式 | 耗时 | 速度 |
|---|---|---|
| 逐字写入 | 29.2 秒 | 28 字符/秒 |
| 一次写入 | 0.003 秒 | 约 26 万字符/秒 |

差 9280 倍，所以我的实际用法是**混合**：小文件（≤60 行）逐字，大文件分段写、每段停 1 秒。

`--from-file` 是为了逐字节保真：PowerShell 管道会自动补一个结尾换行，实测会让产物 SHA256 与预期不一致。

## 工具二：`scripts/jump.py` —— 先跳转，再改

```bash
python scripts/jump.py app.js:120
```

让 VS Code 光标跳到指定行。这样改之前人就知道"要动这里"，改完再跳一次就知道"动的是这里"。

查找顺序：`VSCODE_CODE_CMD` 环境变量 → PATH → 常见安装路径。装在非默认盘符（比如 `D:\应用\Microsoft VS Code`）也能找到。

## 工具三：`scripts/jsdom_harness.cjs` —— 没有浏览器也能测页面

```bash
node scripts/jsdom_harness.cjs --dir . --html index.html --js app.js \
     --origin http://127.0.0.1:8770/ --wait "#content" --assert asserts.cjs
```

断言文件：

```js
module.exports = async ({ doc, window, sleep }) => {
  const cards = doc.querySelectorAll('.card').length;
  const hidden = doc.getElementById('content').hasAttribute('hidden');
  return { ok: cards === 19 && !hidden, cards, hidden };
};
```

它已经补齐了 jsdom 缺的：`fetch`（相对路径按 `--origin` 解析）、`matchMedia`、`ResizeObserver`、`IntersectionObserver`、`getBBox`、媒体元素的 `load/play/pause`。

退出码 `0` 通过、`2` 断言失败、`3` 加载失败，可以直接接 CI。

## 工具四：`scripts/route_diff.py` —— 用数字说"我改了多少"

```bash
python scripts/route_diff.py old.py new.py
python scripts/route_diff.py --git HEAD app.js --unified
```

```
行数      : 24 → 29
新增/删除 : +5 / -0
保留      : 24 行
改动率    : 20.8%
新增函数  : greet_clean
```

改完代码说"我优化了一下"，跟贴出上面这张表，可信度完全不同。退出码 `0` 无改动、`1` 有改动。

## 工具五：`scripts/curl_probe.py` —— 接口探测

```bash
python scripts/curl_probe.py https://api.example.com/health
python scripts/curl_probe.py https://api.example.com/list -H "Authorization: Bearer xxx" --json
python scripts/curl_probe.py https://cdn.example.com/movie.mp4 --range 0-1023
```

```
状态    : 206 Partial Content
耗时    : 673 ms
类型    : text/html; charset=utf-8
长度    : 100
收到    : 100 字节
```

`--range` 用来验证服务端是否支持分片（视频能不能拖进度条就靠这个）。

**实测踩的两个坑**，脚本里都处理了：

- 精简版 Python 常常 `CERTIFICATE_VERIFY_FAILED`（缺 CA 证书）→ 提示加 `--insecure`
- 有些服务端不返回 `Accept-Ranges`，前端进度条就会失效 → 一测便知

## 工具六：`scripts/acl_fix.ps1` —— Windows 权限诊断

```powershell
.\scripts\acl_fix.ps1 -Path "D:\work\proj"          # 只诊断，不动权限
.\scripts\acl_fix.ps1 -Path "D:\work\proj" -Fix     # 真去修
```

针对 Windows 上 `SetNamedSecurityInfoW failed (Win32 5)` 这类"目录权限不足导致沙箱起不来"的问题。会打印原始 SDDL（回滚用）、当前用户的显式权限，`-Fix` 之后还会复核。

> 两个注意点：脚本内有 `exit`，用 `powershell -File` 子进程跑；`.ps1` 要存成 **UTF-8 带 BOM**，否则 PowerShell 5.1 把中文注释读成乱码直接报语法错（这个坑我踩了）。

## 安装

**方式一：当技能用**（支持 Skill 的 agent）

```bash
git clone <this repo> ~/.agents/skills/agent-toolkit
```

**方式二：当独立脚本用**，需要 Node ≥ 18 和 Python ≥ 3.9：

```bash
npm i jsdom        # 只有 harness 需要
```

## 推荐流程

```
jump.py 跳到位置 → 改（小改动逐字 / 大改动分段）→ jump.py 再跳 → 语法检查 → jsdom 验证 → 贴结果
```

## 用这套工具做出来的东西：`query-route/`

仓库里还有一个完整项目 **`query-route/`**（🚄 查询路线），是用上面这套流程写出来的：

| 能力 | 说明 |
|---|---|
| 直达查询 | 起终点 + 日期 → 车次、站点、时刻、历时、二等座票价 |
| 中转换乘 | 自动试枢纽站，把两段车次配对成中转方案，按总耗时排序 |
| 换乘校验 | 同站 ≥15 分钟、异站 ≥60 分钟、换机 ≥120 分钟，不够标红 |
| 省额度 | 本地库优先（0 调用）→ 6 小时缓存 → 接口，额度用完用旧缓存兜底 |

1277 行 Python，只用标准库 + tkinter，不依赖任何第三方包。详见 [`query-route/README.md`](query-route/README.md)。

## 已知限制

- `jump.py` 依赖 VS Code 的 `code` 命令行；其它编辑器需要改一行。
- `jsdom_harness` 不渲染真实像素，**看不出配色和布局**，只能验证逻辑与 DOM 状态。
- 逐字写入在文件很大时非常慢，别对几百行的文件用它。

## License

MIT