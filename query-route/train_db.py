"""车次库：把 12306 页面上复制下来的车次文本解析成结构化数据，存本地，供离线查询。

不联网、不爬取。数据来源是用户自己在 12306 官方页面查询后复制的内容（个人使用）。
"""

import json
import re
from pathlib import Path

DB_FILE = Path(__file__).resolve().parent / "车次库.json"

CAR_NO = re.compile(r"^[GDCZTKYS]\d{1,4}$")
CLOCK = re.compile(r"^(\d{1,2})[:：](\d{2})$")
NOISE = {"--", "-", "有票", "无票", "候补", "起售", "预订", "选座", "¥", "￥"}


def to_minutes(text):
    """'08:00' -> 480；解析不了返回 None"""
    match = CLOCK.match(str(text or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def to_clock(minutes):
    if minutes is None:
        return ""
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def duration_text(depart, arrive):
    """两时刻之间的历时，跨零点自动 +24h"""
    dep, arr = to_minutes(depart), to_minutes(arrive)
    if dep is None or arr is None:
        return ""
    if arr < dep:
        arr += 24 * 60
    span = arr - dep
    return f"{span // 60:02d}:{span % 60:02d}"


def _is_station(token):
    """站名特征：2-8 个字符，含中文或字母，不是车次/时刻/数字"""
    if not token or token in NOISE:
        return False
    if CAR_NO.match(token) or CLOCK.match(token):
        return False
    if len(token) < 2 or len(token) > 8:
        return False
    return bool(re.search(r"[\u4e00-\u9fa5A-Za-z]", token))


def parse_text(text):
    """解析 12306 复制的文本，返回 (车次列表, 解析说明)

    容错策略：先按制表符/换行切成 token，再以「车次号」为切分点，
    把其后的 token 依次认作：出发站、到达站、出发时刻、到达时刻、历时。
    认不出的内容记进说明，不影响已识别的字段。
    """
    tokens = []
    for chunk in re.split(r"[\t\r\n]+", text or ""):
        token = chunk.strip().strip("|").strip()
        if token and token not in NOISE:
            tokens.append(token)

    rows, notes = [], []
    index = 0
    while index < len(tokens):
        if not CAR_NO.match(tokens[index]):
            index += 1
            continue

        code = tokens[index]
        index += 1
        stations, clocks = [], []
        # 最多往回看 12 个 token，遇到下一个车次就停
        while index < len(tokens) and not CAR_NO.match(tokens[index]) and len(stations) < 2 or (
            index < len(tokens) and CLOCK.match(tokens[index])
        ):
            token = tokens[index]
            if CAR_NO.match(token):
                break
            if CLOCK.match(token):
                clocks.append(token)
            elif _is_station(token):
                stations.append(token)
            index += 1
            if len(clocks) >= 3 and len(stations) >= 2:
                break

        row = {
            "code": code,
            "from_station": stations[0] if len(stations) > 0 else "",
            "to_station": stations[1] if len(stations) > 1 else "",
            "depart": clocks[0] if len(clocks) > 0 else "",
            "arrive": clocks[1] if len(clocks) > 1 else "",
            "duration": clocks[2] if len(clocks) > 2 else duration_text(
                clocks[0] if clocks else "", clocks[1] if len(clocks) > 1 else ""
            ),
        }
        if not row["from_station"] or not row["to_station"]:
            notes.append(f"{code}：没认出出发/到达站，请手工补")
        if not row["depart"] or not row["arrive"]:
            notes.append(f"{code}：没认出时刻")
        rows.append(row)

    if not rows:
        notes.append("没找到车次号（要像 G1722、D305 这种），换一段文本试试")
    return rows, notes

def manual_row(line):
    """手工一行格式：车次 出发站 出发时刻 到达站 到达时刻 [票价]

    例：G1722 武汉站 08:00 南京南站 10:30 200
    """
    parts = [p for p in re.split(r"[\s,，]+", (line or "").strip()) if p]
    if len(parts) < 5:
        raise ValueError("至少要有 5 段：车次 出发站 出发时刻 到达站 到达时刻")
    code, from_station, depart, to_station, arrive = parts[:5]
    if not CAR_NO.match(code):
        raise ValueError(f"车次号不像车次：{code}")
    if to_minutes(depart) is None or to_minutes(arrive) is None:
        raise ValueError("时刻要写成 HH:MM")
    return {
        "code": code,
        "from_station": from_station,
        "to_station": to_station,
        "depart": depart,
        "arrive": arrive,
        "duration": duration_text(depart, arrive),
        "price": parts[5] if len(parts) > 5 else "",
    }


def load_db():
    if not DB_FILE.exists():
        return []
    try:
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_db(rows):
    DB_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(row):
    return (row.get("code", ""), row.get("from_station", ""), row.get("to_station", ""), row.get("depart", ""))


def upsert(rows):
    """按「车次+起站+终站+出发时刻」去重合并，返回 (新增数, 更新数)"""
    db = load_db()
    index = {_key(r): i for i, r in enumerate(db)}
    added = updated = 0
    for row in rows:
        key = _key(row)
        if key in index:
            db[index[key]] = row
            updated += 1
        else:
            db.append(row)
            index[key] = len(db) - 1
            added += 1
    save_db(db)
    return added, updated


def query(from_station="", to_station="", code=""):
    """按起止站（模糊包含）和车次筛选，按出发时刻排序"""
    rows = load_db()
    result = []
    for row in rows:
        if code and code.upper() not in row.get("code", "").upper():
            continue
        if from_station and from_station not in row.get("from_station", ""):
            continue
        if to_station and to_station not in row.get("to_station", ""):
            continue
        result.append(row)
    result.sort(key=lambda r: to_minutes(r.get("depart")) or 24 * 60)
    return result


def stations():
    """库里出现过的站点（供下拉提示）"""
    names = set()
    for row in load_db():
        for key in ("from_station", "to_station"):
            if row.get(key):
                names.add(row[key])
    return sorted(names)