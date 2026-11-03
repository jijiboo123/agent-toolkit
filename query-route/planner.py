"""换乘方案计算：把「A→枢纽」和「枢纽→B」两段车次组合成中转换乘路线。

只用两段换乘（一次中转），因为再多的中转在高铁网络里意义不大、查询次数也会爆。
"""

MIN_TRANSFER = 30      # 最少换乘时间（分钟），太短赶不上
MAX_TRANSFER = 360     # 最多可接受的中转等待（分钟），超过 6 小时不如换别的走法

# 没填中转站时自动尝试的枢纽（全国换乘最常用的中间点）
DEFAULT_HUBS = ("郑州东", "武汉", "南京南")


def to_minutes(clock):
    """'07:38' -> 458；解析不了返回 None"""
    if not clock or ":" not in str(clock):
        return None
    try:
        hour, minute = str(clock).split(":")[:2]
        hour, minute = int(hour), int(minute)
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _duration_minutes(train):
    """优先用接口给的历时，没有就用两个时刻算"""
    span = to_minutes(str(train.get("duration", "")).replace(":", ":"))
    if train.get("duration") and ":" in str(train["duration"]):
        text = str(train["duration"])
        try:
            hours, minutes = text.split(":")[:2]
            return int(hours) * 60 + int(minutes)
        except ValueError:
            pass
    dep, arr = to_minutes(train.get("depart")), to_minutes(train.get("arrive"))
    if dep is None or arr is None:
        return None
    return arr - dep if arr >= dep else arr + 24 * 60 - dep


def build_plans(legs_fn, origin, target, travel_date, hubs=DEFAULT_HUBS,
                min_gap=MIN_TRANSFER, max_gap=MAX_TRANSFER, progress=None):
    """返回中转方案列表（按总耗时升序）

    legs_fn(from_station, to_station, date) -> [train, ...]
    progress(done, total) 可选回调，用于界面显示进度
    """
    plans = []
    hubs = [h for h in hubs if h and h not in (origin, target)]
    total = max(len(hubs) * 2, 1)
    done = 0

    for hub in hubs:
        try:
            first_legs = legs_fn(origin, hub, travel_date)
        except Exception:  # noqa: BLE001 - 单个枢纽失败不影响其它
            first_legs = []
        done += 1
        if progress:
            progress(done, total)
        if not first_legs:
            continue

        try:
            second_legs = legs_fn(hub, target, travel_date)
        except Exception:  # noqa: BLE001
            second_legs = []
        done += 1
        if progress:
            progress(done, total)
        if not second_legs:
            continue

        # 只有「上一段到达站 == 下一段出发站」才组合，避免让用户跨站换乘
        by_station = {}
        for train in second_legs:
            by_station.setdefault(train.get("from_station", ""), []).append(train)

        for first in first_legs:
            for second in by_station.get(first.get("to_station", ""), []):
                arrive = to_minutes(first.get("arrive"))
                depart = to_minutes(second.get("depart"))
                if arrive is None or depart is None:
                    continue
                gap = depart - arrive
                if gap < 0:
                    gap += 24 * 60
                if not (min_gap <= gap <= max_gap):
                    continue

                first_span = _duration_minutes(first) or 0
                second_span = _duration_minutes(second) or 0
                plans.append({
                    "hub": hub,
                    "first": first,
                    "second": second,
                    "gap": gap,
                    "total_minutes": first_span + gap + second_span,
                    "price": _sum_price(first, second),
                })

    plans.sort(key=lambda item: item["total_minutes"])
    return plans


def _sum_price(*trains):
    total = 0.0
    found = False
    for train in trains:
        raw = str(train.get("price") or "").strip()
        if not raw:
            continue
        try:
            total += float(raw)
            found = True
        except ValueError:
            continue
    return round(total, 1) if found else ""


def plan_text(plan):
    """一行摘要，用于表格/复制"""
    a, b = plan["first"], plan["second"]
    return (
        f"{a.get('code')} {a.get('from_station')}({a.get('depart')})→{a.get('to_station')}({a.get('arrive')})"
        f" + {b.get('code')} {b.get('from_station')}({b.get('depart')})→{b.get('to_station')}({b.get('arrive')})"
        f"　中转 {plan['gap']} 分钟"
    )
