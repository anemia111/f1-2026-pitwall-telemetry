"""Distance-domain analysis. Never interpolate across a missing segment."""
from bisect import bisect_right
from math import isfinite
from statistics import median

CHANNELS = ("speed", "throttle", "brake", "steer", "gear", "engineRPM", "ms")


def ordered(samples: list[dict]) -> list[dict]:
    trace: list[dict] = []
    for sample in samples:
        if sample.get("d") is None or sample.get("ms") is None or not 0 <= sample["d"] <= 100_000:
            continue
        if trace and (sample["d"] <= trace[-1]["d"] or sample["ms"] <= trace[-1]["ms"]):
            continue
        trace.append(sample)
    return trace


def compare(a: list[dict], b: list[dict], step: float = 5) -> dict:
    if not isfinite(step) or step < 1:
        raise ValueError("distance step must be at least one metre")
    a, b = ordered(a), ordered(b)
    blank = {"points": [], "zones": [], "reason": "共通の走行距離サンプルが不足しています。", "step": step}
    if min(len(a), len(b)) < 2:
        return blank
    da, db = [p["d"] for p in a], [p["d"] for p in b]
    start, end = max(da[0], db[0]), min(da[-1], db[-1])
    gap = max(30, 4 * median(y - x for axis in (da, db) for x, y in zip(axis, axis[1:])))

    def at(trace: list[dict], axis: list[float], d: float) -> dict | None:
        i = min(len(axis) - 2, bisect_right(axis, d) - 1)
        x, y = trace[i], trace[i + 1]
        width = y["d"] - x["d"]
        if width > gap or y["ms"] - x["ms"] > 1000:
            return None
        weight = (d - x["d"]) / width
        return {key: (x[key] if key == "gear" else x[key] + weight * (y[key] - x[key]))
                if x.get(key) is not None and y.get(key) is not None else None for key in CHANNELS}

    points = []
    for i in range(max(0, int((end - start) / step) + 1)):
        d = start + i * step
        x, y = at(a, da, d), at(b, db, d)
        points.append({"d": d, "a": x, "b": y, "delta": (x["ms"] - y["ms"]) / 1000 if x and y else None})
    zones = []
    i = 1
    while i < len(points):
        prev, point = points[i - 1], points[i]
        if not prev["b"] or not point["b"] or prev["b"]["brake"] is None or point["b"]["brake"] is None or prev["b"]["brake"] >= .12 or point["b"]["brake"] < .12:
            i += 1
            continue
        j = i + 1
        while j < len(points) and points[j]["b"] and (points[j]["b"]["brake"] or 0) >= .08:
            j += 1
        left, right = max(0, i - round(70 / step)), min(len(points) - 1, j + round(110 / step))
        window = points[left:right + 1]
        if j - i >= 2 and all(p["a"] and p["b"] for p in window):
            one = driving_metrics(window, "a")
            two = driving_metrics(window, "b")
            if one and two:
                loss = points[right]["delta"] - points[left]["delta"]
                hint = None
                if loss > .1 and one["throttleAt"] is not None and two["throttleAt"] is not None and one["throttleAt"] - two["throttleAt"] > 10:
                    hint = "仮説：出口で姿勢が安定したら、基準ラップのアクセル再開位置を試す。"
                elif loss > .1 and one["brakeAt"] is not None and two["brakeAt"] is not None and two["brakeAt"] - one["brakeAt"] > 10:
                    hint = "仮説：基準ラップの制動開始位置を目安に、進入速度を比較する。"
                zones.append({"from": points[left]["d"], "to": points[right]["d"], "loss": loss,
                              "a": one, "b": two, "hypothesis": hint})
        i = max(i + 1, j)
    good = [p for p in points if p["delta"] is not None]
    return {"points": points, "zones": zones, "step": step, "compared": len(good),
            "reason": None if len(good) >= 2 else blank["reason"],
            "limits": "距離の線形補間。ギアは前値。1秒超または大きな距離欠損を除外。"
                      "区間は基準ラップのブレーキ入力から検出。タイム差は推定分解能に依存。"}


def driving_metrics(window: list[dict], key: str) -> dict | None:
    data = [(p["d"], p[key]) for p in window]
    if any(row.get(k) is None for _, row in data for k in ("speed", "throttle", "brake", "steer")):
        return None
    apex_i = min(range(len(data)), key=lambda i: data[i][1]["speed"])
    onset = next((i for i, (_, r) in enumerate(data) if r["brake"] >= .12), None)
    release = next((d for d, r in data[onset + 1:] if r["brake"] < .08), None) if onset is not None else None
    throttle = next((d for d, r in data[apex_i:] if r["throttle"] >= .25), None)
    return {"brakeAt": data[onset][0] if onset is not None else None, "releaseAt": release,
            "throttleAt": throttle, "entrySpeed": data[onset][1]["speed"] if onset is not None else None,
            "minSpeed": data[apex_i][1]["speed"], "exitSpeed": data[-1][1]["speed"],
            "maxBrake": max(r["brake"] for _, r in data), "maxSteer": max(abs(r["steer"]) for _, r in data),
            "throttleVariation": sum(abs(y[1]["throttle"] - x[1]["throttle"]) for x, y in zip(data, data[1:]))}
