"""交通串联器：把一段段车次串成完整路线，算换乘缓冲、标中转站、给风险提示。

用途：高铁 / 飞机 / 地铁 / 公交 / 大巴 / 步行 的分段行程，
     自己填班次（数据来自 12306、航司等官方渠道），程序只负责拼装与校验。
运行：双击 启动.bat，或 python traffic_chain.py
"""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

APP_TITLE = "查询路线 · 分段行程拼装与换乘校验"
TYPES = ["高铁", "动车", "火车", "飞机", "大巴", "地铁", "公交", "步行", "自驾"]
DATA_FILE = Path(__file__).resolve().parent / "我的行程.json"

# 建议的最小换乘缓冲（分钟）
BUFFER_SAME_STATION = 15     # 同一个车站换乘，走站内通道
BUFFER_OTHER_STATION = 60    # 同城不同站，要坐地铁/打车过去
BUFFER_AIRPORT = 120         # 换乘飞机，要值机安检


def parse_hm(text):
    """'08:30' -> 510 分钟；空值返回 None"""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    match = re.fullmatch(r"(\d{1,2})[:：](\d{2})", raw)
    if not match:
        raise ValueError(f"时间格式应为 HH:MM，收到：{raw}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"时间超出范围：{raw}")
    return hour * 60 + minute


def fmt_hm(minutes):
    """510 -> '08:30'"""
    if minutes is None:
        return ""
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_duration(minutes):
    """280 -> '4小时40分'"""
    if minutes is None:
        return "—"
    minutes = int(round(minutes))
    hours, mins = divmod(abs(minutes), 60)
    sign = "-" if minutes < 0 else ""
    if hours and mins:
        return f"{sign}{hours}小时{mins}分"
    if hours:
        return f"{sign}{hours}小时"
    return f"{sign}{mins}分"


def segment_duration(seg):
    """单段耗时（分钟），时间不全则返回 None；跨零点按次日算"""
    try:
        dep = parse_hm(seg.get("depart"))
        arr = parse_hm(seg.get("arrive"))
    except ValueError:
        return None
    if dep is None or arr is None:
        return None
    if arr < dep:
        arr += 24 * 60
    return arr - dep

def transfer_gap(prev, cur):
    """上一段到达 到 下一段出发 的间隔（分钟）；时间不全返回 None，负数为时间冲突"""
    try:
        arr = parse_hm(prev.get("arrive"))
        dep = parse_hm(cur.get("depart"))
    except ValueError:
        return None
    if arr is None or dep is None:
        return None
    gap = dep - arr
    if gap < 0:
        # 只把"像跨零点"的间隔算作次日：否则（比如 09:40 到达、09:30 出发）
        # 加 24 小时会变成"等 23 小时"，把录入错误误判成合格
        overnight = gap + 24 * 60
        gap = overnight if overnight <= 12 * 60 else gap
    return gap


def suggested_buffer(prev, cur):
    """按换乘类型给出建议缓冲与理由"""
    if cur.get("type") == "飞机":
        return BUFFER_AIRPORT, "换乘航班需要值机与安检"
    same_station = (prev.get("to_station") or "").strip() == (cur.get("from_station") or "").strip()
    if same_station and prev.get("to_station"):
        return BUFFER_SAME_STATION, "同站换乘，走站内通道"
    return BUFFER_OTHER_STATION, "不同车站，要留出市内移动时间"


def analyze(segments):
    """返回统计与告警，供界面和导出共用"""
    warnings = []
    transfers = []

    for i in range(1, len(segments)):
        prev, cur = segments[i - 1], segments[i]
        gap = transfer_gap(prev, cur)
        need, reason = suggested_buffer(prev, cur)
        item = {
            "index": i,
            "from_station": prev.get("to_station") or "",
            "to_station": cur.get("from_station") or "",
            "gap": gap,
            "need": need,
            "reason": reason,
            "ok": True,
        }
        if gap is not None:
            if gap < 0:
                item["ok"] = False
                warnings.append(f"第 {i}-{i + 1} 段时间冲突：到达晚于下一段出发")
            elif gap == 0:
                item["ok"] = False
                warnings.append(f"第 {i}-{i + 1} 段没有换乘时间")
            elif gap < need:
                item["ok"] = False
                warnings.append(
                    f"第 {i}-{i + 1} 段缓冲只有 {gap} 分钟，建议至少 {need} 分钟（{reason}）"
                )
        transfers.append(item)

    durations = [segment_duration(s) for s in segments]
    if segments and all(d is not None for d in durations):
        first_dep = parse_hm(segments[0].get("depart"))
        last_arr = parse_hm(segments[-1].get("arrive"))
        total = last_arr - first_dep
        if total < 0:
            total += 24 * 60
    else:
        total = None

    prices = []
    for seg in segments:
        raw = str(seg.get("price") or "").strip()
        if raw:
            try:
                prices.append(float(raw))
            except ValueError:
                warnings.append(f"票价「{raw}」不是数字，已忽略")

    return {
        "count": len(segments),
        "transfers": transfers,
        "warnings": warnings,
        "total_minutes": total,
        "total_price": sum(prices) if prices else None,
        "has_unknown_time": any(d is None for d in durations),
    }

def route_text(start, end, travel_date, segments, info):
    """生成可复制、可保存的纯文本路线"""
    lines = []
    head = f"{start or '起点'} → {end or '终点'}"
    if travel_date:
        head += f"　日期 {travel_date}"
    lines.append(head)
    lines.append("=" * 46)

    for i, seg in enumerate(segments, 1):
        dep = seg.get("depart") or "--:--"
        arr = seg.get("arrive") or "--:--"
        code = seg.get("code") or ""
        price = seg.get("price") or ""
        dur = fmt_duration(segment_duration(seg))
        extra = " ".join(x for x in (code, f"￥{price}" if price else "", dur if dur != "—" else "") if x)
        lines.append(
            f"{i}. [{seg.get('type', '')}] {seg.get('from_station', '')} {dep} → "
            f"{seg.get('to_station', '')} {arr}"
            + (f"　{extra}" if extra else "")
        )
        if i <= len(info["transfers"]):
            t = info["transfers"][i - 1]
            gap = "时间未知" if t["gap"] is None else f"缓冲 {t['gap']} 分钟"
            flag = "" if t["ok"] else "  ⚠ 风险"
            a, b = t["from_station"] or "?", t["to_station"] or "?"
            where = f"{a} 站内换乘" if a == b else f"{a} → {b}"
            lines.append(f"   ↳ 中转：{where}　{gap}{flag}")

    lines.append("-" * 46)
    total = fmt_duration(info["total_minutes"])
    price = f"￥{info['total_price']:.0f}" if info["total_price"] else "—"
    lines.append(f"全程 {total}　总票价 {price}　{info['count']} 段　{max(info['count'] - 1, 0)} 次换乘")
    if info["has_unknown_time"]:
        lines.append("（有段没填出发/到达时间，全程耗时按已知段计算）")
    for warn in info["warnings"]:
        lines.append(f"⚠ {warn}")
    return "\n".join(lines)


# ---------------- 界面层 ----------------
# tkinter 放在这里导入：上面的逻辑函数可以在无界面环境单独测试
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    HAS_TK = True
except Exception:  # noqa: BLE001 - 某些精简 Python 不带 tkinter
    HAS_TK = False

try:
    import planner
    import train_api
    import train_db
except ImportError:  # 直接双击运行时，模块就在同目录
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import planner
    import train_api
    import train_db


class App:
    """一个窗口办完所有事：查询（直达/中转）→ 选车次 → 拼行程"""

    def __init__(self, root):
        self.root = root
        self.segments = []
        self.direct = []
        self.plans = []
        self.tally = {"added": 0, "updated": 0}
        root.title(APP_TITLE)
        root.geometry("1060x760")
        root.minsize(920, 640)

        self.v_from = tk.StringVar(value="武汉")
        self.v_to = tk.StringVar(value="上海")
        self.v_date = tk.StringVar(value=date.today().isoformat())
        self.v_hub = tk.StringVar()
        self.v_free = tk.BooleanVar(value=True)   # 免费优先：先查本地库，没有再走接口
        self.src = {"api": 0, "local": 0}

        self._build_query()
        self._build_results()
        self._build_route()
        self.refresh_station_hints()
        self.refresh()

    # ---------- 顶部查询条 ----------
    def _build_query(self):
        bar = ttk.Frame(self.root, padding=(12, 12, 12, 6))
        bar.pack(fill="x")

        ttk.Label(bar, text="起点").pack(side="left")
        self.from_box = ttk.Combobox(bar, textvariable=self.v_from, width=12)
        self.from_box.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="终点").pack(side="left")
        self.to_box = ttk.Combobox(bar, textvariable=self.v_to, width=12)
        self.to_box.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="日期").pack(side="left")
        ttk.Entry(bar, textvariable=self.v_date, width=11).pack(side="left", padx=(4, 10))
        ttk.Checkbutton(bar, text="免费优先", variable=self.v_free).pack(side="left", padx=(0, 10))

        ttk.Button(bar, text="查询", command=self.do_search).pack(side="right")
        ttk.Button(bar, text="导入车次", command=self.open_import).pack(side="right", padx=6)

        self.status = ttk.Label(self.root, text="填好起终点后点「查询」", foreground="#2c3e50", padding=(14, 0, 14, 6))
        self.status.pack(fill="x")

    # ---------- 结果区（直达 / 中转） ----------
    def _build_results(self):
        box = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        box.pack(fill="both", expand=True)

        self.book = ttk.Notebook(box)
        self.book.pack(fill="both", expand=True)

        # 直达
        page1 = ttk.Frame(self.book)
        self.book.add(page1, text="直达")
        self.tree_direct = self._make_tree(
            page1,
            (("code", "车次", 78), ("from", "出发站", 110), ("to", "到达站", 110),
             ("depart", "出发", 66), ("arrive", "到达", 66), ("duration", "历时", 66),
             ("price", "二等座", 76)),
        )
        self.tree_direct.pack(fill="both", expand=True)
        self.tree_direct.bind("<Double-1>", lambda _e: self.add_direct())

        # 中转（按需触发，避免每次查询都烧额度）
        page2 = ttk.Frame(self.book)
        self.book.add(page2, text="中转")

        bar2 = ttk.Frame(page2, padding=(0, 6))
        bar2.pack(fill="x")
        ttk.Label(bar2, text="中转站").pack(side="left")
        ttk.Entry(bar2, textvariable=self.v_hub, width=12).pack(side="left", padx=4)
        ttk.Label(bar2, text="（留空自动试 郑州东/武汉/南京南）", foreground="#7f8c8d").pack(side="left")
        ttk.Button(bar2, text="查找中转方案", command=self.find_transfers).pack(side="right")

        self.tree_plan = self._make_tree(
            page2,
            (("first", "第一程", 210), ("second", "第二程", 210), ("hub", "中转站", 92),
             ("gap", "换乘", 62), ("total", "总耗时", 78), ("price", "票价", 62)),
        )
        self.tree_plan.pack(fill="both", expand=True)
        self.tree_plan.bind("<Double-1>", lambda _e: self.add_plan())

        tip = ttk.Label(
            self.root,
            text="提示：双击表格里的车次即可加入下方行程；中转方案会一次加入两段。",
            foreground="#7f8c8d", padding=(14, 4, 14, 0),
        )
        tip.pack(fill="x")

    def _make_tree(self, parent, columns):
        tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", height=8)
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="center")
        return tree

    # ---------- 行程区 ----------
    def _build_route(self):
        box = ttk.LabelFrame(self.root, text="已选行程", padding=8)
        box.pack(fill="both", expand=False, padx=12, pady=(8, 10))

        self.tree = self._make_tree(
            box,
            (("no", "序号", 44), ("type", "方式", 58), ("from", "出发站", 108),
             ("to", "到达站", 108), ("depart", "出发", 62), ("arrive", "到达", 62),
             ("code", "班次", 78), ("price", "票价", 58), ("gap", "换乘缓冲", 120)),
        )
        self.tree.configure(height=6)
        self.tree.pack(fill="both", expand=True)

        actions = ttk.Frame(box)
        actions.pack(fill="x", pady=(6, 0))
        for text, cmd in (
            ("删除选中", self.delete_selected),
            ("上移", lambda: self.move(-1)),
            ("下移", lambda: self.move(1)),
            ("清空行程", self.clear_all),
            ("复制路线", self.copy_route),
            ("保存", self.save_file),
            ("载入", self.load_file),
        ):
            ttk.Button(actions, text=text, command=cmd).pack(side="left", padx=2)

        self.stats = ttk.Label(self.root, text="", foreground="#2c3e50", padding=(14, 0, 14, 10))
        self.stats.pack(fill="x")

    # ---------- 数据沉淀与站名提示 ----------
    def reset_tally(self):
        self.tally = {"added": 0, "updated": 0}
        self.src = {"api": 0, "local": 0}
        return self.tally

    def source_note(self):
        """告诉用户这次数据从哪来、花没花额度"""
        api, local = self.src.get("api", 0), self.src.get("local", 0)
        if api and local:
            return f"　｜　接口 {api} 次 + 本地库 {local} 趟"
        if api:
            return f"　｜　接口 {api} 次（花了额度）"
        if local:
            return f"　｜　本地库 {local} 趟（免费，0 消耗）"
        return ""

    def tally_note(self):
        """把「本次入库」拼成一句人话"""
        added, updated = self.tally.get("added", 0), self.tally.get("updated", 0)
        if not added and not updated:
            return ""
        return f"　｜　已入库 新增 {added} / 更新 {updated}"

    def refresh_station_hints(self):
        """站名下拉用本地库累积的站，用得越久越准"""
        stations = train_db.stations()
        self.from_box.config(values=stations)
        self.to_box.config(values=stations)
        return len(stations)

    # ---------- 查询 ----------
    def _legs(self, frm, to, travel_date):
        """数据来源顺序：本地库（免费）→ 接口（花额度）→ 本地库兜底"""
        if self.v_free.get():
            local = train_db.query(frm, to)
            if local:
                self.src["local"] += len(local)
                return local
        if train_api.is_ready():
            rows = train_api.query(frm, to, travel_date)
            self.src["api"] += 1
            # 累计本次查询的入库情况，供状态栏显示
            self.tally["added"] += train_api.last_persist.get("added", 0)
            self.tally["updated"] += train_api.last_persist.get("updated", 0)
            return rows
        local = train_db.query(frm, to)
        self.src["local"] += len(local)
        return local

    def do_search(self):
        origin, target = self.v_from.get().strip(), self.v_to.get().strip()
        travel_date = self.v_date.get().strip()
        if not origin or not target:
            messagebox.showinfo("缺少条件", "出发站和到达站都要填。")
            return
        if origin == target:
            messagebox.showinfo("条件不对", "出发站和到达站不能一样。")
            return

        self.status.config(text="正在查询直达…")
        self.root.update()
        note = ""

        train_api.last_from_cache = False
        self.reset_tally()
        try:
            self.direct = self._legs(origin, target, travel_date)
            if train_api.last_from_cache:
                note = "　（用的是 6 小时内缓存，没花额度）"
        except Exception as err:  # noqa: BLE001 - 查询失败不能让窗口崩
            self.direct = train_db.query(origin, target)
            note = f"　（API 失败：{err}；已用本地车次库）"
            if not self.direct:
                self.plans = []
                self._fill_direct()
                self._fill_plans()
                self.status.config(text=f"查询失败：{err}（可点「查找中转方案」或「导入车次」）")
                return

        # 中转改成按需：切到「中转」标签后点按钮才查，避免每次查询多花 6 次额度
        self.plans = []
        self._fill_direct()
        self._fill_plans()
        banks = self.refresh_station_hints()
        self.status.config(
            text=(
                f"直达 {len(self.direct)} 趟{note}{self.source_note()}{self.tally_note()}"
                f"　｜　中转按需点标签页按钮　｜　本地库已攒 {banks} 个站"
            )
        )

    def find_transfers(self):
        """按需查中转：只有点这个按钮才消耗额度"""
        origin, target = self.v_from.get().strip(), self.v_to.get().strip()
        travel_date = self.v_date.get().strip()
        if not origin or not target:
            messagebox.showinfo("缺少条件", "先填出发站和到达站。")
            return

        hubs = [h.strip() for h in self.v_hub.get().replace("，", ",").split(",") if h.strip()]
        if not hubs:
            hubs = list(planner.DEFAULT_HUBS)
        cost = len([h for h in hubs if h not in (origin, target)]) * 2
        if not messagebox.askyesno(
            "确认查询", f"将查询 {len(hubs)} 个中转站，最多消耗 {cost} 次接口额度。\n继续吗？"
        ):
            return

        def progress(done, total):
            self.status.config(text=f"正在找中转方案…（{done}/{total} 次查询）")
            self.root.update()

        self.reset_tally()
        self.status.config(text="正在找中转方案…")
        self.root.update()
        try:
            self.plans = planner.build_plans(
                self._legs, origin, target, travel_date, hubs, progress=progress
            )
        except Exception as err:  # noqa: BLE001
            self.plans = []
            self._fill_plans()
            self.status.config(text=f"中转查询失败：{err}")
            return

        self._fill_plans()
        self.book.select(1)
        self.status.config(
            text=f"中转方案 {len(self.plans)} 个（双击一行加入两段）{self.source_note()}{self.tally_note()}"
        )

    def _fill_direct(self):
        for item in self.tree_direct.get_children():
            self.tree_direct.delete(item)
        for t in self.direct:
            self.tree_direct.insert("", "end", values=(
                t.get("code", ""), t.get("from_station", ""), t.get("to_station", ""),
                t.get("depart", ""), t.get("arrive", ""), t.get("duration", ""), t.get("price", ""),
            ))
        self.book.tab(0, text=f"直达（{len(self.direct)}）")

    def _fill_plans(self):
        for item in self.tree_plan.get_children():
            self.tree_plan.delete(item)
        for plan in self.plans:
            a, b = plan["first"], plan["second"]
            self.tree_plan.insert("", "end", values=(
                f"{a.get('code', '')} {a.get('from_station', '')} {a.get('depart', '')}→{a.get('arrive', '')}",
                f"{b.get('code', '')} {b.get('from_station', '')} {b.get('depart', '')}→{b.get('arrive', '')}",
                plan["hub"], f"{plan['gap']}分",
                fmt_duration(plan["total_minutes"]) if plan.get("total_minutes") else "—",
                plan.get("price", ""),
            ))
        self.book.tab(1, text=f"中转（{len(self.plans)}）")

    # ---------- 选车次加入行程 ----------
    @staticmethod
    def _to_segment(train):
        code = train.get("code", "")
        kind = ("高铁" if code.startswith("G") else
                "动车" if code.startswith("D") else
                "城际" if code.startswith("C") else "火车")
        return {
            "type": kind,
            "from_station": train.get("from_station", ""),
            "to_station": train.get("to_station", ""),
            "depart": train.get("depart", ""),
            "arrive": train.get("arrive", ""),
            "code": code,
            "price": train.get("price", ""),
        }

    def add_direct(self):
        picked = self.tree_direct.selection()
        if not picked:
            messagebox.showinfo("没有选中", "先在直达表格里点一趟车。")
            return
        index = self.tree_direct.index(picked[0])
        self.segments.append(self._to_segment(self.direct[index]))
        self.refresh()
        self.root.lift()
        self.status.config(text=f"已加入：{self.direct[index].get('code')}")

    def add_plan(self):
        picked = self.tree_plan.selection()
        if not picked:
            messagebox.showinfo("没有选中", "先在中转表格里点一个方案。")
            return
        plan = self.plans[self.tree_plan.index(picked[0])]
        self.segments.append(self._to_segment(plan["first"]))
        self.segments.append(self._to_segment(plan["second"]))
        self.refresh()
        self.root.lift()
        self.status.config(text=f"已加入中转：{plan['first'].get('code')} + {plan['second'].get('code')}")

    # ---------- 行程操作 ----------
    def _selected_index(self):
        picked = self.tree.selection()
        if not picked:
            messagebox.showinfo("没有选中", "先在行程表格里点一行。")
            return None
        return int(self.tree.item(picked[0], "values")[0]) - 1

    def delete_selected(self):
        index = self._selected_index()
        if index is None:
            return
        del self.segments[index]
        self.refresh()

    def move(self, delta):
        picked = self.tree.selection()
        if not picked:
            return
        index = int(self.tree.item(picked[0], "values")[0]) - 1
        target = index + delta
        if 0 <= target < len(self.segments):
            self.segments[index], self.segments[target] = self.segments[target], self.segments[index]
            self.refresh()
            children = self.tree.get_children()
            if target < len(children):
                self.tree.selection_set(children[target])

    def clear_all(self):
        if self.segments and not messagebox.askyesno("确认", "清空整条行程？"):
            return
        self.segments.clear()
        self.refresh()

    def _route_payload(self):
        info = analyze(self.segments)
        text = route_text(self.v_from.get(), self.v_to.get(), self.v_date.get(), self.segments, info)
        return info, text

    def copy_route(self):
        if not self.segments:
            messagebox.showinfo("行程是空的", "先选几趟车。")
            return
        _, text = self._route_payload()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("已复制", "完整路线已复制到剪贴板。")

    def save_file(self):
        if not self.segments:
            messagebox.showinfo("行程是空的", "先选几趟车。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="我的行程.json",
            filetypes=[("行程 JSON", "*.json")],
        )
        if not path:
            return
        payload = {
            "start": self.v_from.get(), "end": self.v_to.get(),
            "date": self.v_date.get(), "segments": self.segments,
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("已保存", path)

    def load_file(self):
        path = filedialog.askopenfilename(filetypes=[("行程 JSON", "*.json")])
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            messagebox.showerror("载入失败", str(err))
            return
        self.v_from.set(payload.get("start", ""))
        self.v_to.set(payload.get("end", ""))
        self.v_date.set(payload.get("date", date.today().isoformat()))
        self.segments = payload.get("segments", [])
        self.refresh()

    # ---------- 刷新 ----------
    def refresh(self):
        info = analyze(self.segments)
        for row in self.tree.get_children():
            self.tree.delete(row)

        gap_map = {t["index"]: t for t in info["transfers"]}
        for i, seg in enumerate(self.segments, 1):
            gap = gap_map.get(i)
            gap_text = ""
            if gap is not None:
                gap_text = "时间未知" if gap["gap"] is None else f"{gap['gap']} 分（建议{gap['need']}）"
            self.tree.insert("", "end", values=(
                i, seg.get("type", ""), seg.get("from_station", ""), seg.get("to_station", ""),
                seg.get("depart", ""), seg.get("arrive", ""), seg.get("code", ""),
                seg.get("price", ""), gap_text,
            ), tags=("warn",) if (gap and not gap["ok"]) else ())
        self.tree.tag_configure("warn", foreground="#c0392b")

        total = fmt_duration(info["total_minutes"])
        price = f"￥{info['total_price']:.0f}" if info["total_price"] else "—"
        warn = f"　⚠ {len(info['warnings'])} 处风险" if info["warnings"] else "　✓ 换乘时间充裕"
        self.stats.config(
            text=f"共 {info['count']} 段 · {max(info['count'] - 1, 0)} 次换乘 · 全程 {total} · 总票价 {price}{warn}"
        )

    # ---------- 导入车次（离线库） ----------
    def open_import(self):
        ImportDialog(self)


class ImportDialog(tk.Toplevel):
    """粘贴 12306 结果 → 解析 → 存本地库（API 不可用时的备用数据源）"""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("导入车次到本地库")
        self.geometry("760x480")
        self.parsed = []

        ttk.Label(self, text="把 12306 页面上复制的车次文本粘到下面，然后点「解析并入库」。",
                  padding=8).pack(anchor="w")

        self.paste = tk.Text(self, height=12, wrap="none", font=("Consolas", 9))
        self.paste.pack(fill="both", expand=True, padx=8)

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="从剪贴板粘贴", command=self.paste_clipboard).pack(side="left")
        ttk.Button(bar, text="解析并入库", command=self.do_import).pack(side="left", padx=6)
        ttk.Label(bar, text="支持：表格复制（制表符）、每格一行、或「车次 出发站 08:00 到达站 10:30」",
                  foreground="#7f8c8d").pack(side="left", padx=8)

        self.hint = ttk.Label(self, text=f"本地库现有 {len(train_db.load_db())} 趟", padding=(8, 0, 8, 8))
        self.hint.pack(anchor="w")

    def paste_clipboard(self):
        """一键把剪贴板内容贴进来（从 12306 页面 Ctrl+C 后直接点）"""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("剪贴板是空的", "先在 12306 页面复制车次列表。", parent=self)
            return
        self.paste.delete("1.0", "end")
        self.paste.insert("1.0", text)

    def do_import(self):
        rows, notes = train_db.parse_text(self.paste.get("1.0", "end"))
        if not rows:
            messagebox.showinfo("没解析出车次", "；".join(notes) or "换一段文本试试", parent=self)
            return
        added, updated = train_db.upsert(rows)
        self.hint.config(text=f"已入库：新增 {added} / 更新 {updated}；本地库共 {len(train_db.load_db())} 趟")
        messagebox.showinfo("完成", f"新增 {added} 条，更新 {updated} 条。", parent=self)


def main():
    if not HAS_TK:
        print("这个 Python 没有 tkinter，无法打开窗口。请改用系统自带的 Python 3.13 运行。")
        return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
