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

## 已知限制

- `jump.py` 依赖 VS Code 的 `code` 命令行；其它编辑器需要改一行。
- `jsdom_harness` 不渲染真实像素，**看不出配色和布局**，只能验证逻辑与 DOM 状态。
- 逐字写入在文件很大时非常慢，别对几百行的文件用它。

## License

MIT