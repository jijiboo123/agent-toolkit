"""商业火车票 API 适配器（配置驱动，不绑定某一家供应商）。

为什么是"配置驱动"：不同平台的接口字段完全不同（车次叫 train_no 还是 trainCode、
站点叫 start_station 还是 from_station），把字段映射写进 api_config.json，
换供应商只改配置、不改代码。

没有 key 时一切功能保持离线，不会报错。
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "api_config.json"
CACHE_FILE = BASE / "api_cache.json"
TIMEOUT = 15

# 查询结果缓存：同一条线路同一天，6 小时内不重复请求，直接省额度
CACHE_TTL = 6 * 3600
# 额度用完时，旧缓存（多旧都用）仍可降级使用
last_from_cache = False
# 最近一次查询的入库情况，界面用来显示"已入库 N 趟（新增 x / 更新 y）"
last_persist = {"added": 0, "updated": 0}

# 聚合数据限制每秒 1 次，留点余量；连续点查询时自动间隔
MIN_INTERVAL = 1.2
_last_call = 0.0


def _throttle():
    global _last_call
    wait = MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _cache_key(from_station, to_station, travel_date):
    return f"{from_station}|{to_station}|{travel_date}"


def _load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache):
    try:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _persist(rows):
    """把查到的车次沉淀进本地库，以后这条线路不花额度也能查

    返回 (新增数, 更新数)，同时写进 last_persist 供界面显示。
    """
    global last_persist
    try:
        import train_db  # 局部导入，避免模块级循环依赖
        added, updated = train_db.upsert(rows)
        last_persist = {"added": added, "updated": updated}
        return added, updated
    except Exception as err:  # noqa: BLE001 - 落库失败不影响本次查询
        print(f"[train_api] 写入本地库失败：{err}")
        last_persist = {"added": 0, "updated": 0}
        return 0, 0


def cache_info():
    """界面用：缓存了多少条线路"""
    return len(_load_cache())

DEFAULT_CONFIG = {
    "enabled": False,
    "provider": "在这里写供应商名字，例如 聚合数据",
    "method": "GET",
    "url": "https://example.com/api/train/query",
    "key": "",
    "key_field": "key",
    "params": {
        "depart": "{from}",
        "arrive": "{to}",
        "date": "{date}",
    },
    "headers": {},
    "records_path": "result.list",
    "field_map": {
        "code": "train_no",
        "from_station": "start_station",
        "to_station": "end_station",
        "depart": "start_time",
        "arrive": "arrive_time",
        "duration": "lishi",
        "price": "price",
    },
}


def load_config():
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(data or {})
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def is_ready(config=None):
    """配置齐了没有：有 url、有 key、field_map 有内容"""
    cfg = config or load_config()
    return bool(cfg.get("url")) and bool(cfg.get("key")) and bool(cfg.get("field_map"))


def _dig(payload, path):
    """按 'a.b.c' 取嵌套字段；空路径返回原对象"""
    node = payload
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node

def _request(config, from_station, to_station, travel_date):
    """按配置发请求，返回原始 JSON（也用于『测试连接』看返回长什么样）"""
    url = config["url"]
    params = {}
    values = {"from": from_station, "to": to_station, "date": travel_date}
    for name, tpl in (config.get("params") or {}).items():
        params[name] = str(tpl).format(**values)
    key_field = config.get("key_field") or "key"
    if config.get("key"):
        params[key_field] = config["key"]

    headers = {"User-Agent": "TrafficChain/1.0"}
    headers.update(config.get("headers") or {})

    method = (config.get("method") or "GET").upper()
    if method == "GET":
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        request = urllib.request.Request(full, headers=headers)
    else:
        body = urllib.parse.urlencode(params).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers)

    _throttle()
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _raise_if_error(payload):
    """供应商返回了 error_code 就翻译成中文异常，别让界面只看到一句"取不到列表" """
    if not isinstance(payload, dict):
        return
    code = payload.get("error_code")
    if code in (None, 0, "0"):
        return
    reason = payload.get("reason") or payload.get("message") or "未知原因"
    hint = {
        10001: "key 无效：去聚合数据「我的API」确认这个 AppKey 是否属于火车票接口、是否已审核通过",
        10002: "key 无效或已停用",
        10012: "当日免费次数已用完",
        10015: "请求太快：接口限制每秒 1 次，等一秒再点",
        281701: "查询失败：站点名可能写错，或该日期没有班次",
    }.get(int(code) if str(code).isdigit() else code, "")
    raise RuntimeError(f"接口返回 {code}：{reason}" + (f"（{hint}）" if hint else ""))


def query(from_station, to_station, travel_date, config=None, use_cache=True):
    """按供应商返回的字段映射成统一结构；失败抛异常，由界面提示

    带缓存：同一线路同一天 6 小时内不重复请求；额度用完时降级用旧缓存。
    """
    global last_from_cache, last_persist
    last_from_cache = False
    last_persist = {"added": 0, "updated": 0}

    cfg = config or load_config()
    if not is_ready(cfg):
        raise RuntimeError("API 还没配置：打开 api_config.json 填 url 和 key")

    key = _cache_key(from_station, to_station, travel_date)
    cache = _load_cache() if use_cache else {}
    entry = cache.get(key) or {}

    if use_cache and entry.get("rows"):
        age = time.time() - float(entry.get("ts") or 0)
        if 0 <= age <= CACHE_TTL:
            last_from_cache = True
            return entry["rows"]

    try:
        payload = _request(cfg, from_station, to_station, travel_date)
        _raise_if_error(payload)
    except RuntimeError as err:
        # 额度用完 / 网络失败：有旧缓存就先顶上，别让用户白跑
        if entry.get("rows"):
            print(f"[train_api] {err}；改用缓存（{len(entry['rows'])} 趟）")
            last_from_cache = True
            return entry["rows"]
        raise

    records = _dig(payload, cfg.get("records_path") or "")
    if records is None:
        # 换供应商时 records_path 常写错，这里按常见位置兜一次
        for guess in ("result.list", "result.data", "result", "data.list", "data"):
            candidate = _dig(payload, guess)
            if isinstance(candidate, list) and candidate:
                records = candidate
                break
    if records is None:
        raise RuntimeError(f"按 records_path=「{cfg.get('records_path')}」没取到列表，先用『测试连接』看返回结构")
    if isinstance(records, dict):
        records = [records]

    mapping = cfg.get("field_map") or {}
    seat_name = cfg.get("price_seat") or ""
    rows = []
    for item in records:
        row = {key_: _dig(item, path) for key_, path in mapping.items()}
        # 有的接口把票价放在 prices 数组里（商务座/一等座/二等座…），
        # 按坐席名精确取，避免抓到第一个（通常是商务座，价格差好几倍）
        if seat_name:
            for seat in _dig(item, "prices") or []:
                if isinstance(seat, dict) and seat.get("seat_name") == seat_name:
                    row["price"] = seat.get("price")
                    row["seat"] = seat_name
                    break
        row = {k: ("" if v is None else str(v)) for k, v in row.items()}
        if row.get("code"):
            rows.append(row)
    rows.sort(key=lambda r: r.get("depart") or "99:99")

    if use_cache and rows:
        cache[key] = {"ts": time.time(), "rows": rows}
        _save_cache(cache)
        _persist(rows)
    return rows


def probe(from_station, to_station, travel_date, config=None):
    """测试连接：返回原始 JSON 文本，方便照着填 field_map"""
    cfg = config or load_config()
    if not cfg.get("url") or not cfg.get("key"):
        raise RuntimeError("先填 url 和 key")
    payload = _request(cfg, from_station, to_station, travel_date)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_template():
    """生成一份带注释说明的配置模板（不含注释，JSON 不支持）"""
    if CONFIG_FILE.exists():
        return False
    save_config(dict(DEFAULT_CONFIG))
    return True


if __name__ == "__main__":
    cfg = load_config()
    print("配置文件:", CONFIG_FILE)
    print("已就绪:", is_ready(cfg))
    print(json.dumps(cfg, ensure_ascii=False, indent=2))