---
name: agent-toolkit
description: Make AI code editing visible and verifiable. Use when the user wants to watch edits happen in VS Code, when changes must be shown line by line before and after, or when a frontend page needs runtime testing without a browser (jsdom harness).
---

# Agent Toolkit

让 AI 改代码的过程**对人可见、对结果可验证**。三件工具解决三个真实痛点：

| 工具 | 解决的痛点 |
|---|---|
| `scripts/type_write.py` | 代码"啪"地一次写进去，人根本看不清改了什么 |
| `scripts/jump.py` | 改完才说"我改了第 120 行"，人得自己去找 |
| `scripts/jsdom_harness.cjs` | 没有浏览器就没法验证前端，只能靠肉眼 |

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

1. **`jump.py` 跳到要改的行**（人看得见落点）
2. 改（小改动用 `type_write`，大改动分段写）
3. **`jump.py` 再跳到改完的行**
4. `node --check` / `python -m py_compile`
5. `jsdom_harness` 或真实运行验证
6. 把验证结果贴给用户

## 常见坑

| 现象 | 原因 | 解法 |
|---|---|---|
| `jump.py` 说找不到 VS Code | 装在非默认路径 | 设 `VSCODE_CODE_CMD` |
| 逐字写出来的文件末尾多一行 | PowerShell 管道补换行 | 用 `--from-file` |
| 编辑器不刷新 | 文件监视器有延迟 | 点一下文件标签页强制重读 |
| jsdom 报 `Not implemented` | 媒体/布局 API 缺失 | harness 已桩掉；其它按需补 |
| 断言"通过"但页面实际是错的 | 用 `textContent` 判断，把隐藏元素也算进去了 | 改判 `hidden` 属性或 `getComputedStyle` |