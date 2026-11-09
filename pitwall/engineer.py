"""Priority radio and local evidence-grounded Japanese answers."""
from collections import deque
from time import monotonic

from .strategy import Assumptions, forecast

LEVELS = {"CRITICAL": 4, "HIGH": 3, "NORMAL": 2, "LOW": 1}


class Engineer:
    def __init__(self) -> None:
        self.radio: deque[dict] = deque(maxlen=50)
        self.strategy: dict | None = None
        self.signatures: dict[str, float] = {}
        self.revision: dict | None = None
        self.seq = 0
        self.last_at = -1e9
        self.last_level = 0
        self.last_lap = None
        self.last_weather = None
        self.last_pits: dict[int, int] = {}
        self.last_recommendation: tuple | None = None
        self.last_plan_key: tuple | None = None
        self.last_gap: tuple[int, int] | None = None
        self.last_wear: float | None = None
        self.last_ers: float | None = None

    def emit(self, snap: dict, priority: str, topic: str, message: str,
             evidence: dict, now: float, cooldown: float = 20) -> dict | None:
        level = LEVELS[priority]
        if not snap["online"] or snap["ended"]:
            return None
        if now - self.signatures.get(topic, -1e9) < cooldown:
            return None
        if now - self.last_at < 4 and level <= self.last_level and level < 4:
            return None
        self.seq += 1
        car = next((c for c in snap["cars"] if c["id"] == snap["player"]), {})
        item = {"id": self.seq, "priority": priority, "topic": topic, "message": message,
                "time": snap["clock"], "lap": (car.get("lap") or {}).get("currentLapNum"),
                "evidence": evidence, "confidence": "条件付き推定" if topic == "strategy" else "受信値",
                "reason": evidence.get("reason", message), "selectedPlan": None, "outcome": None}
        self.signatures[topic] = self.last_at = now
        self.last_level = level
        self.radio.appendleft(item)
        return item

    def update(self, snap: dict, observed: dict, sets: list[dict] | None,
               config: Assumptions, event: dict | None, now: float | None = None) -> list[dict]:
        now = monotonic() if now is None else now
        self.strategy = forecast(snap, observed, sets, config)
        s = snap.get("session") or {}
        car = next((c for c in snap["cars"] if c["id"] == snap["player"]), {})
        lap, damage, aero = car.get("lap") or {}, car.get("damage") or {}, car.get("aero") or {}
        sent = []
        def say(priority: str, topic: str, text: str, evidence: dict, cooldown: float = 20) -> None:
            if item := self.emit(snap, priority, topic, text, evidence, now, cooldown):
                sent.append(item)
        if event:
            code, data = event["code"], event["details"]
            if code == "SCAR" and data.get("eventType") == 0 and data.get("safetyCarType") in (1, 2):
                name = "セーフティカー" if data["safetyCarType"] == 1 else "VSC"
                say("CRITICAL", f"flag-{name}", f"{name}導入。ピット候補を再評価します。", data, 5)
            elif code == "RDFL":
                say("CRITICAL", "red", "赤旗。ゲームの指示に従ってください。戦略判断を停止します。", data, 5)
            elif code == "PENA" and data.get("vehicleIdx") == snap["player"]:
                say("HIGH", "penalty", "ペナルティ通知。詳細を確認してください。", data, 5)
        if snap["red"] or s.get("gamePaused") or s.get("isSpectating") or not snap["online"]:
            self.last_gap = self.last_wear = self.last_ers = None
            return sent
        if damage.get("engineBlown") or damage.get("engineSeized"):
            say("CRITICAL", "engine", "エンジンに重大な異常。車両状態を確認。", damage, 30)
        if aero.get("drivingWrongWay"):
            say("CRITICAL", "direction", "逆走警告。進行方向を確認。", aero, 12)
        wings = [damage.get(k, 0) for k in ("frontLeftWingDamage", "frontRightWingDamage")]
        if max(wings) >= 30:
            say("HIGH", "wing", "フロントウイングにダメージ。バランスに注意。", {"wingPct": wings}, 45)
        weather = s.get("weather")
        if weather is not None and self.last_weather is not None and weather != self.last_weather:
            say("HIGH", "weather", "天候が変化。タイヤ条件を確認。", {"before": self.last_weather, "after": weather}, 10)
        if weather is not None:
            self.last_weather = weather
        for rival in self.strategy["rivals"]:
            rid = rival["id"]
            other = next((c["lap"] for c in snap["cars"] if c["id"] == rid), None) or {}
            pit = other.get("pitStatus")
            if pit is not None and pit and self.last_pits.get(rid) == 0:
                say("HIGH", f"rival-pit-{rid}", f"P{rival['position']}の車両がピットへ。", {"car": rid, "pitStatus": pit})
            if pit is not None:
                self.last_pits[rid] = pit
        model = self.strategy["model"]
        wear = model["wear"]
        if wear is not None and self.last_wear is not None and wear - self.last_wear >= 4:
            say("HIGH", "wear-jump", f"タイヤ摩耗が急増。現在の最大摩耗は{wear:.0f}パーセント。", model, 30)
        self.last_wear = wear
        gap, position = lap.get("frontGap"), lap.get("carPosition")
        if gap is not None and position:
            if self.last_gap and self.last_gap[0] == position and abs(gap - self.last_gap[1]) >= 1500:
                say("HIGH", "gap-change", f"前方との差が変化。現在{gap / 1000:.2f}秒。", {
                    "beforeMs": self.last_gap[1], "currentMs": gap, "position": position}, 25)
            self.last_gap = position, gap
        else:
            self.last_gap = None
        energy = (car.get("status") or {}).get("ersStoreEnergy")
        if energy is not None and self.last_ers is not None and energy < 500000 <= self.last_ers:
            say("NORMAL", "energy", f"ERS蓄電が{energy / 1000:.0f}キロジュールに低下。使用量を確認。", {
                "joules": energy, "threshold": 500000}, 60)
        self.last_ers = energy
        if model["wear"] is not None and model["wear"] >= config.wear_limit:
            say("HIGH", "wear", f"最大摩耗{model['wear']:.0f}パーセント。設定した閾値に達しました。", model, 45)
        best = next((p for p in self.strategy["plans"] if p["id"] == self.strategy["recommended"]), None)
        plan_key = (best["id"], best["pitLap"], best["pitLoss"]) if best else None
        if plan_key != self.last_plan_key:
            previous = self.last_recommendation
            self.revision = {"previous": previous, "current": plan_key, "time": snap["clock"],
                             "reason": self.strategy["reason"]}
            if best:
                evidence = {
                    "previous": previous, "recommendation": best, "plans": self.strategy["plans"], "model": model,
                    "inputs": self.strategy["input"], "assumptions": self.strategy["assumptions"],
                    "reason": self.strategy["reason"],
                }
                item = self.emit(snap, "HIGH", "strategy",
                                 f"条件付きでプラン{best['id']}。{best['pitLap']}周目を候補に。", evidence, now, 10)
                sent.append(item or {"topic": "strategy", "time": snap["clock"], "lap": lap.get("currentLapNum"),
                                     "evidence": evidence, "reason": self.strategy["reason"],
                                     "confidence": "条件付き推定", "selectedPlan": None, "outcome": None})
            elif previous and snap["online"]:
                say("HIGH", "strategy-unavailable", "戦略候補を保留。条件が変わりました。", self.strategy, 10)
            self.last_plan_key = plan_key
            self.last_recommendation = plan_key
        n = lap.get("currentLapNum")
        if n and self.last_lap is not None and n != self.last_lap and lap.get("lastLapTimeInMS"):
            pace = lap["lastLapTimeInMS"] / 1000
            say("NORMAL", "pace", f"前のラップ、{pace:.3f}秒。", {"seconds": pace})
        if n:
            self.last_lap = n
        return sent


TOPICS = ("gap", "pace", "tyres", "plan_a", "plan_b", "plan_c", "pit", "coach", "energy")


def identify(text: str) -> str | None:
    t = text.lower()
    for i, k in enumerate(("a", "b", "c")):
        if f"プラン{k}" in t or f"plan {k}" in t or f"プラン {k}" in t or f"プラン{'ａｂｃ'[i]}" in t:
            return "plan_" + k
    for topic, keys in (
        ("gap", ("ギャップ", "車との差", "前の車", "後ろの車", "gap")),
        ("tyres", ("タイヤ", "持つ", "tyre", "摩耗")),
        ("coach", ("コーナー", "改善", "ブレーキ", "coaching")),
        ("pit", ("ピット", "戦略", "pit", "strategy")),
        ("energy", ("ers", "エネルギー", "バッテリー")),
        ("pace", ("ペース", "ラップ", "pace")),
    ):
        if any(k in t for k in keys):
            return topic
    return None


def answer(topic: str | None, snap: dict, strategy: dict, text: str = "", coaching: str | None = None) -> str:
    if not snap["online"] or snap["ended"] or snap["red"] or (snap.get("session") or {}).get("gamePaused"):
        return "ライブ判断は停止中です。受信とセッション状態を確認してください。"
    car = next((c for c in snap["cars"] if c["id"] == snap["player"]), {})
    lap, status = car.get("lap") or {}, car.get("status") or {}
    if topic == "gap":
        key = "rearGap" if "後" in text else "frontGap"
        gap = lap.get(key)
        direction = "後方" if key == "rearGap" else "前方"
        return f"{direction}との差、{gap / 1000:.3f}秒。" if gap is not None else f"{direction}のギャップは取得できていません。"
    if topic == "pace":
        pace = lap.get("lastLapTimeInMS")
        return f"前のラップは{pace / 1000:.3f}秒。" if pace else "前周のタイムはまだ取得できていません。"
    if topic == "tyres":
        m = strategy["model"]
        if m["remaining"] is not None:
            if "最後" in text or "ゴール" in text:
                n, total = strategy["input"].get("lap"), strategy["input"].get("total")
                if n and total and total >= n:
                    left = total - n + 1
                    status = "今周を含む残り周回以上" if m["remaining"] >= left else "今周を含む残り周回を下回る"
                    return f"摩耗閾値まで約{m['remaining']:.1f}周。推定寿命は{status}見込みです。"
            return f"最大摩耗{m['wear']:.0f}パーセント。現在の摩耗率では設定閾値まで約{m['remaining']:.1f}周です。"
        return f"最大摩耗{m['wear']:.0f}パーセント。残り寿命は推定できません。" if m["wear"] is not None else "タイヤ摩耗と残り寿命は取得できていません。"
    if topic and (topic == "pit" or topic.startswith("plan_")):
        key = strategy["recommended"] if topic == "pit" else topic[-1].upper()
        plan = next((p for p in strategy["plans"] if p["id"] == key and p["pitLap"]), None)
        return (f"条件付きのプラン{key}は{plan['pitLap']}周目に交換。推定ピットロス{plan['pitLoss']:.1f}秒。"
                if plan else strategy["reason"] or "戦略の計算に必要なデータが不足しています。")
    if topic == "energy":
        energy = status.get("ersStoreEnergy")
        return f"ERS蓄電量は{energy / 1000:.0f}キロジュール。" if energy is not None else "ERSデータは取得できていません。"
    if topic == "coach":
        return coaching or "比較可能な完了ラップとコーナー区間が不足しています。"
    return "ペース、ギャップ、タイヤ、ピット、プランA・B・C、ERS、走行改善について質問できます。"
