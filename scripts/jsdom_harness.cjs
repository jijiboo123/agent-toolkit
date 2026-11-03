#!/usr/bin/env node
/*
 * 通用 jsdom 测试台：无浏览器也能真跑前端页面，抓运行时错误 + 做断言。
 *
 * 用法：
 *   node jsdom_harness.cjs --dir . --html index.html --js app.js \
 *        --origin http://127.0.0.1:8770/ --wait "#content" --assert asserts.cjs
 *
 * 参数：
 *   --dir      项目目录（默认当前目录）
 *   --html     页面入口（默认 index.html）
 *   --js       脚本文件（默认 app.js）；不传则只加载 HTML
 *   --origin   JSDOM 的 url，决定相对路径请求打到哪（默认 http://127.0.0.1:8080/）
 *   --wait     等这个选择器出现再继续（可选）
 *   --timeout  等待超时毫秒（默认 15000）
 *   --assert   断言模块：module.exports = async ({doc, window, sleep}) => ({...})
 *   --inline   直接把断言写成一行的函数体字符串（简单的场景用）
 *
 * 退出码：0 通过 / 2 断言返回 ok:false / 3 加载或执行异常
 *
 * 依赖：jsdom（npm i jsdom 或 pnpm add jsdom）
 */

const path = require('path');
const fs = require('fs');

function parseArgs(argv) {
  const args = { dir: '.', html: 'index.html', js: 'app.js', origin: 'http://127.0.0.1:8080/', timeout: 15000 };
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    const value = argv[i + 1];
    if (key === 'timeout') args.timeout = Number(value);
    else if (key in args || ['assert', 'wait', 'inline'].includes(key)) args[key] = value;
  }
  return args;
}

function loadJsdom() {
  // 先按普通 require，失败再试常见全局安装位置
  try {
    return require('jsdom');
  } catch (err) {
    const candidates = [
      process.env.JSDOM_DIR && path.join(process.env.JSDOM_DIR, 'node_modules', 'jsdom'),
      path.join(process.env.TEMP || '', 'jsdom-harness', 'node_modules', 'jsdom'),
    ].filter(Boolean);
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return require(candidate);
    }
    console.error('找不到 jsdom。请先安装：npm i jsdom');
    process.exit(3);
  }
}

const { JSDOM, VirtualConsole } = loadJsdom();
const args = parseArgs(process.argv.slice(2));
const dir = path.resolve(args.dir);
const errors = [];
const warns = [];

const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', (e) => errors.push('[jsdomError] ' + (e && e.message ? e.message : e)));
virtualConsole.on('error', (...a) => errors.push('[console.error] ' + a.join(' ')));
virtualConsole.on('warn', (...a) => warns.push('[console.warn] ' + a.join(' ')));

const htmlPath = path.join(dir, args.html);
if (!fs.existsSync(htmlPath)) {
  console.error('页面不存在: ' + htmlPath);
  process.exit(3);
}
const html = fs.readFileSync(htmlPath, 'utf8').replace(/<script\b[^>]*src=[^>]*><\/script>/gi, '');

const dom = new JSDOM(html, {
  url: args.origin,
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  virtualConsole,
});
const { window } = dom;
const doc = window.document;

// ---- 补齐 jsdom 缺的浏览器能力 ----
window.fetch = (input, init) => {
  const url = typeof input === 'string' ? new URL(input, args.origin) : input;
  return globalThis.fetch(url, init);
};
for (const name of ['Response', 'Request', 'Headers', 'AbortController', 'Blob', 'URL']) {
  if (!window[name] && globalThis[name]) window[name] = globalThis[name];
}
if (!window.matchMedia) {
  window.matchMedia = () => ({
    matches: false, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {},
  });
}
if (!window.ResizeObserver) window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
if (!window.IntersectionObserver) window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
window.scrollTo = () => {};
if (!window.Element.prototype.getBBox) window.Element.prototype.getBBox = () => ({ x: 0, y: 0, width: 100, height: 20 });
if (!window.Element.prototype.getScreenCTM) window.Element.prototype.getScreenCTM = () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 });
// 媒体元素在 jsdom 里没有实现，直接桩掉，避免 Not implemented 噪音
for (const method of ['load', 'play', 'pause']) {
  if (window.HTMLMediaElement) window.HTMLMediaElement.prototype[method] = function () { return Promise.resolve(); };
}

window.addEventListener('error', (e) => errors.push('[window.onerror] ' + (e.message || e.error)));
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason;
  errors.push('[unhandledRejection] ' + (reason && reason.message ? reason.message : String(reason)));
});
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(selector, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (doc.querySelector(selector)) return true;
    await sleep(100);
  }
  return false;
}

(async () => {
  // ---- 注入脚本 ----
  if (args.js) {
    const jsPath = path.join(dir, args.js);
    if (!fs.existsSync(jsPath)) {
      console.error('脚本不存在: ' + jsPath);
      process.exit(3);
    }
    const script = doc.createElement('script');
    script.textContent = fs.readFileSync(jsPath, 'utf8');
    doc.body.appendChild(script);
  }

  let waitOk = true;
  if (args.wait) waitOk = await waitFor(args.wait, args.timeout);
  await sleep(300);

  // ---- 跑断言 ----
  let result = null;
  let ok = true;
  if (args.assert) {
    const assertPath = path.resolve(args.assert);
    const mod = require(assertPath);
    result = await mod({ doc, window, sleep });
    if (result && result.ok === false) ok = false;
  } else if (args.inline) {
    const fn = new Function('doc', 'window', 'sleep', 'return (async () => {' + args.inline + '})();');
    result = await fn(doc, window, sleep);
    if (result && result.ok === false) ok = false;
  }

  console.log(JSON.stringify({ waitOk, ok, result, errors, warns: warns.slice(0, 5) }, null, 2));
  window.close();
  process.exit(ok ? 0 : 2);
})().catch((err) => {
  console.error('执行失败: ' + (err && err.stack ? err.stack : err));
  process.exit(3);
});