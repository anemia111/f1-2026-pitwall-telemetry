"""Deterministic telemetry model and seeded uncertainty simulation."""
from dataclasses import asdict, dataclass
from math import isfinite
from random import Random
from statistics import median
from typing import Iterable

from .state import TYRES


@dataclass(frozen=True)
class Assumptions:
    pit_loss: float = 23.0
    sc_loss: float = 12.0
    vsc_loss: float = 16.0
    wear_limit: float = 75.0
    simulations: int = 256


def slope(points: list[tuple[float, float]]) -> float | None:
    values = [(b - a) / (y - x) for i, (x, a) in enumerate(points)
              for y, b in points[i + 1:] if x != y]
    return median(values) if values else None


def stint_model(observed: Iterable[dict], status: dict | None, damage: dict | None, limit: float) -> dict:
    status, damage = status or {}, damage or {}
    age = status.get("tyresAgeLaps")
    tyre = status.get("visualTyreCompound")
    fresh = damage.get("tyresWear")
    wear = max(fresh) if fresh and all(x is not None and 0 <= x <= 100 for x in fresh) else None
    stint = [p for p in observed if p["age"] is not None and p["tyre"] == tyre]
    if age is not None and stint:
        # Use the contiguous suffix of the current stint. An age reset is a new set.
        current = []
        for p in reversed(stint):
            if p["age"] > age or current and p["age"] >= current[-1]["age"]:
                break
            current.append(p)
        stint = current[::-1]
    else:
        stint = []
    pace = [(p["age"], p["ms"] / 1000) for p in stint if p["valid"] and 25_000 <= p["ms"] <= 600_000]
    wear_points = [(p["age"], max(p["wear"])) for p in stint if p["wear"]
                   and all(x is not None and 0 <= x <= 100 for x in p["wear"])]
    wear_rate = slope(wear_points) if len(wear_points) >= 3 else None
    deg = slope(pace) if len(pace) >= 3 else None
    base = median([y - x * deg for x, y in pace]) if deg is not None else None
    noise = median([abs(y - (base + x * deg)) for x, y in pace]) if base is not None else None
    return {"compound": TYRES.get(tyre), "age": age, "wear": wear, "wearRate": wear_rate,
            "remaining": max(0, (limit - wear) / wear_rate) if wear is not None and wear_rate and wear_rate > .03 else None,
            "degradation": deg, "pace": pace[-1][1] if pace else None, "base": base, "noise": noise,
            "count": len(pace), "wearLimit": limit, "wearPoints": wear_points}


def forecast(snapshot: dict, observed: dict, sets: list[dict] | None, config: Assumptions) -> dict:
    s = snapshot.get("session") or {}
    car = next((c for c in snapshot["cars"] if c["id"] == snapshot["player"]), {})
    lap, status = car.get("lap") or {}, car.get("status") or {}
    player_laps = observed.get(snapshot["player"], {})
    last_stint = sorted(player_laps.values(), key=lambda p: p["lap"])
    model = stint_model(last_stint, status, car.get("damage"), config.wear_limit)
    n, total, sc = lap.get("currentLapNum"), s.get("totalLaps"), s.get("safetyCarStatus")
    rivals = []
    position = lap.get("carPosition")
    for rival in snapshot["cars"]:
        rl = rival.get("lap") or {}
        if position and rl.get("carPosition") in (position - 1, position + 1) and rl.get("carPosition"):
            recent = [x["ms"] / 1000 for x in observed.get(rival["id"], {}).values() if x["valid"]][-3:]
            rivals.append({"name": rival.get("name"), "id": rival["id"], "position": rl["carPosition"],
                           "pace": median(recent) if recent else None})
    base = {"model": model, "plans": [], "recommended": None, "reason": None,
            "assumptions": asdict(config), "rivals": rivals, "input": {
                "lap": n, "total": total, "safety": sc, "weather": s.get("weather"), "position": position,
                "aheadMs": lap.get("frontGap"), "behindMs": lap.get("rearGap"),
                "penalties": lap.get("penalties"), "compoundsAvailable": sorted({
                    TYRES[x["visualTyreCompound"]] for x in sets or [] if x["available"] and not x["fitted"]
                    and x["visualTyreCompound"] in TYRES}),
            }}
    labels = ("A", "B", "C")
    def insufficient(reason: str) -> dict:
        base["reason"] = reason
        base["plans"] = [{"id": k, "pitLap": None, "remainingTime": None, "raceTime": None, "rejoin": None,
                          "finishWear": None, "interval": None, "winRate": None, "risk": reason} for k in labels]
        return base

    if not snapshot["online"] or snapshot["ended"] or snapshot["red"] or s.get("gamePaused") or s.get("isSpectating"):
        return insufficient("ライブ判断を停止中。受信・セッション状態を確認してください。")
    if s.get("sessionType") not in (15, 16, 17) or not n or not total or n >= total or lap.get("resultStatus") != 2:
        return insufficient("レース残周回を取得できません。")
    if lap.get("pitStatus") or sc == 3:
        return insufficient("ピット走行中またはフォーメーションラップです。")
    if s.get("weather") not in (0, 1, 2) or model["compound"] not in ("S", "M", "H"):
        return insufficient("ドライタイヤのペースモデルに適用できない条件です。")
    if model["base"] is None or model["age"] is None or not isfinite(model["base"]):
        return insufficient("現スティントの有効ラップが3周以上必要です。")
    same = [x for x in sets or [] if x["available"] and not x["fitted"] and x["wear"] <= 10 and
            x["visualTyreCompound"] == status.get("visualTyreCompound") and x["actualTyreCompound"] == status.get("actualTyreCompound")]
    if not same:
        return insufficient("同一コンパウンドの使用可能な低摩耗セットを確認できません。")
    selected = min(same, key=lambda x: x["wear"])
    ideal = min(total - 1, max(n, s.get("pitStopWindowIdealLap") or n + 2))
    targets = (ideal, max(n, ideal - 2), min(total - 1, ideal + 2))
    current_green = s.get("safetyCarStatus") == 0
    loss_now = {1: config.sc_loss, 2: config.vsc_loss}.get(sc, config.pit_loss)
    deg = max(0., model["degradation"])
    remaining = total - n + 1
    elapsed_lap = (lap.get("currentLapTimeInMS") or 0) / 1000
    has_elapsed = all(i in player_laps and player_laps[i]["ms"] > 0 for i in range(1, n))
    elapsed_race = sum(player_laps[i]["ms"] / 1000 for i in range(1, n)) + elapsed_lap if has_elapsed else None
    pace_start = model["base"]
    rng = Random(2026)
    sims = [[] for _ in labels]
    wins = [0.] * 3
    for _ in range(config.simulations):
        pace = max(25., pace_start + rng.gauss(0, max(.35, model["noise"])))
        decay = max(0., deg + rng.gauss(0, max(.1, deg * .25)))
        loss_error = rng.gauss(0, 1.6)
        results = []
        for i, pit in enumerate(targets):
            before = pit - n + 1
            after = remaining - before
            age_sum = before * model["age"] + before * (before - 1) / 2 + after * (after - 1) / 2
            loss = loss_now if pit == n else config.pit_loss
            seconds = max(0., remaining * pace + age_sum * decay + max(0., loss + loss_error) - elapsed_lap)
            results.append(seconds)
            sims[i].append(seconds)
        best = min(results)
        tied = [i for i, value in enumerate(results) if abs(value - best) < 1e-9]
        for i in tied:
            wins[i] += 1 / len(tied)
    plans = []
    for i, (key, pit) in enumerate(zip(labels, targets)):
        series = sorted(sims[i])
        loss = loss_now if pit == n else config.pit_loss
        gap = 0
        rejoin = None
        if pit == n and current_green and position:
            order = sorted((c["lap"] for c in snapshot["cars"] if c["lap"] and
                            c["lap"]["carPosition"] > position and c["lap"]["resultStatus"] == 2),
                           key=lambda row: row["carPosition"])
            for r in order:
                if r["carPosition"] != position + 1 + (0 if rejoin is None else rejoin - position):
                    rejoin = None
                    break
                if not r.get("frontGap") or r["currentLapNum"] != n:
                    rejoin = None
                    break
                gap += r["frontGap"]
                if gap >= loss * 1000:
                    rejoin = r["carPosition"] - 1
                    break
                rejoin = r["carPosition"]
        rate = model["wearRate"]
        finish = min(100, selected["wear"] + rate * (total - pit)) if rate and rate > 0 else None
        risk = "同一コンパウンド仮定。燃料・交通・タイヤ使用義務は未反映。"
        if finish is not None and finish >= config.wear_limit:
            risk += " 交換後の摩耗が設定閾値に達する推定。"
        if model["remaining"] is not None and pit - n >= model["remaining"]:
            risk += " 交換前に摩耗閾値へ達する可能性。"
        if sc in (1, 2):
            risk += " SC/VSC割引は今周のみ仮定。隊列ペース未モデル化。"
        expected = median(series)
        plans.append({"id": key, "pitLap": pit, "remainingTime": expected,
                      "raceTime": expected + elapsed_race if elapsed_race is not None else None,
                      "interval": [series[int(.1 * len(series))], series[int(.9 * len(series))]],
                      "rejoin": rejoin, "finishWear": finish, "winRate": wins[i] / len(series),
                      "risk": risk, "pitLoss": loss, "compound": model["compound"]})
    eligible = [p for p in plans if (p["finishWear"] is None or p["finishWear"] < config.wear_limit) and
                (model["remaining"] is None or p["pitLap"] - n < model["remaining"])]
    best = min(eligible, key=lambda p: p["remainingTime"]) if eligible else None
    base["plans"] = plans
    base["recommended"] = best["id"] if best else None
    base["reason"] = ("条件付きの比較。推定残り時間が最短の候補です。"
                      if best else "設定した摩耗閾値を満たす候補を確認できません。")
    return base
