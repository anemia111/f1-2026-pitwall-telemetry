"""Single-event-loop session state. Raw packets remain the source of truth."""
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from time import monotonic

from .protocol_2026 import LABELS, MAX_CARS, Packet

ROW_FIELDS = {0: "carMotionData", 2: "lapData", 4: "participants", 5: "carSetupData",
              6: "carTelemetryData", 7: "carStatusData", 8: "classificationData",
              10: "carDamageData", 16: "carTelemetry2Data"}
AGE = {0: 1.5, 1: 2.5, 2: 1.5, 4: 16, 5: 3, 6: 1.5, 7: 1.5, 10: 1.5, 12: 5, 16: 1.5}
SAMPLE_KEYS = ("speed", "throttle", "brake", "steer", "gear", "engineRPM",
               "tyresSurfaceTemperature", "tyresInnerTemperature", "brakesTemperature", "tyresPressure")
TYRES = {7: "I", 8: "W", 16: "S", 17: "M", 18: "H", 19: "SS", 20: "S", 21: "M", 22: "H"}
MOTION_KEYS = ("worldPositionX", "worldPositionY", "worldPositionZ")
STATUS_PRIVATE = {"frontBrakeBias", "fuelInTank", "fuelCapacity", "fuelRemainingLaps", "fuelMix",
                  "ersDeployMode", "ersStoreEnergy", "ersDeployedThisLap", "ersHarvestedThisLapMGUK",
                  "ersHarvestedThisLapMGUH", "enginePowerICE", "enginePowerMGUK"}


def lap_ms(row: dict, key: str) -> int:
    return row[key + "MinutesPart"] * 60000 + row[key + "MSPart"]


def event_view(packet: Packet, elapsed: float) -> dict:
    return {"code": bytes(packet.field("eventStringCode")).decode("ascii", "replace"),
            "details": packet.field("eventDetails"), "time": elapsed, "frame": packet.header.overall}


def label(group: str, value: int | None) -> str | None:
    return LABELS[group].get(str(value))


@dataclass
class LiveState:
    uid: int | None = None
    run: str | None = None
    source: str = "LIVE"
    epoch: int = 0
    player: int = 255
    last: float = -1e9
    started: float = 0
    latest: dict[tuple[int, int], tuple[Packet, float]] = field(default_factory=dict)
    events: deque[dict] = field(default_factory=lambda: deque(maxlen=80))
    frames: OrderedDict[int, dict[int, Packet]] = field(default_factory=OrderedDict)
    sample_at: float = -1e9
    sampled_frame: int = -1
    last_frame: int = -1
    observed_laps: dict[int, dict[int, dict]] = field(default_factory=dict)
    previous_laps: dict[int, dict] = field(default_factory=dict)
    track: dict[int, tuple[float, float]] = field(default_factory=dict)
    counts: dict = field(default_factory=lambda: {"valid": 0, "invalid": 0, "ignored": 0, "late": 0, "frameGaps": 0})
    ended: bool = False
    red: bool = False
    safety_override: tuple[int, int, float] | None = None

    def reset(self, packet: Packet, now: float) -> None:
        self.uid, self.run, self.started = packet.header.uid, None, now
        self.events.clear()
        self.epoch, self.last_frame = 0, -1
        self.ended = self.red = False
        self.safety_override = None
        self.reset_epoch()

    def reset_epoch(self) -> None:
        self.latest.clear()
        self.frames.clear()
        self.observed_laps.clear()
        self.previous_laps.clear()
        self.track.clear()
        self.sample_at = -1e9
        self.sampled_frame = -1
        self.ended = self.red = False
        self.safety_override = None

    def ingest(self, packet: Packet, now: float) -> tuple[dict | None, list[tuple[int, int, dict]]]:
        h = packet.header
        self.last = now
        if h.player < MAX_CARS:
            self.player = h.player
        event = None
        if h.kind == 3:
            event = event_view(packet, now - self.started)
            if self.events and (event["frame"], event["code"], event["details"]) == (
                self.events[0]["frame"], self.events[0]["code"], self.events[0]["details"]
            ):
                return None, []
            if event["code"] == "FLBK":
                self.epoch += 1
                self.reset_epoch()
            elif event["code"] == "RDFL":
                self.red = True
            elif event["code"] == "SCAR":
                kind = event["details"].get("safetyCarType")
                action = event["details"].get("eventType")
                if action == 0 and kind in (1, 2, 3):
                    self.safety_override = kind, h.overall, now
                elif action in (2, 3):
                    self.safety_override = 0, h.overall, now
            elif event["code"] in ("LGOT", "SSTA") and not self.ended:
                self.red = False
            elif event["code"] == "SEND":
                self.ended = True
            self.events.appendleft(event)
            return event, []

        if h.kind == 8:
            self.ended = True
        car = packet.field("carIdx") if h.kind in (11, 12) else -1
        key = h.kind, car
        previous = self.latest.get(key)
        if previous and h.overall <= previous[0].header.overall:
            self.counts["late"] += 1
            return None, []
        self.latest[key] = packet, now
        if h.kind == 6:
            if self.last_frame >= 0 and h.overall > self.last_frame + 1:
                self.counts["frameGaps"] += h.overall - self.last_frame - 1
            self.last_frame = h.overall
        if h.kind not in (0, 2, 6):
            return None, []
        frame = self.frames.setdefault(h.overall, {})
        frame[h.kind] = packet
        if len(self.frames) > 16:
            self.frames.popitem(last=False)
        if now - self.sample_at < .095:
            return None, []
        if not (h.overall > self.sampled_frame and {0, 2, 6} <= frame.keys()):
            frame = next((packets for number, packets in reversed(self.frames.items())
                          if self.sampled_frame < number < h.overall - 1 and {2, 6} <= packets.keys()), {})
        if not frame:
            return None, []
        self.sample_at = now
        self.sampled_frame = frame[2].header.overall
        return None, self.sample(frame[2], frame[6], now, frame.get(0))

    def get(self, kind: int, now: float, car: int = -1) -> Packet | None:
        stored = self.latest.get((kind, car))
        if stored and now - stored[1] <= AGE.get(kind, float("inf")):
            return stored[0]
        return None

    def is_public(self, car: int, p: dict | None, s: dict | None) -> bool:
        return car == self.player or bool(p and p.get("yourTelemetry") == 1) or bool(s and s.get("networkGame") == 0)

    def session(self, now: float) -> dict | None:
        packet = self.get(1, now)
        if not packet:
            return None
        body = packet.decode()
        body.pop("header")
        for field, count in (("marshalZones", "numMarshalZones"), ("drsZones", "numDRSZones"),
                             ("activeAeroZonesFull", "numActiveAeroZonesFull"),
                             ("activeAeroZonesPartial", "numActiveAeroZonesPartial"),
                             ("weatherForecastSamples", "numWeatherForecastSamples")):
            body[field] = body[field][:body[count]]
        body["trackName"] = label("track", body["trackId"])
        if self.safety_override:
            safety, frame, received = self.safety_override
            if now - received < 1.5 and packet.header.overall <= frame:
                body["safetyCarStatus"] = safety
        return body

    def cars(self, now: float, session: dict | None) -> list[dict]:
        packets = {k: p for k in ROW_FIELDS if (p := self.get(k, now))}
        participants = packets.get(4)
        active = participants.field("numActiveCars") if participants else 0
        classification = packets.get(8)
        result_count = classification.field("numCars") if classification else 0
        cars = []
        for i in range(MAX_CARS):
            lap = packets[2].row("lapData", i) if 2 in packets else None
            if lap and not (lap["currentLapNum"] or lap["carPosition"] or lap["resultStatus"]):
                lap = None
            result = classification.row("classificationData", i) if classification and i < result_count else None
            if i != self.player and i >= active and not result and not (lap and lap["carPosition"] and lap["resultStatus"] > 1):
                continue
            p = participants.row("participants", i) if participants and i < active else None
            public = self.is_public(i, p, session)
            status = packets[7].row("carStatusData", i) if 7 in packets else None
            if status and not public:
                status = {k: v for k, v in status.items() if k not in STATUS_PRIVATE}
            hist = self.get(11, now, i)
            best = None
            if hist:
                n = hist.field("bestLapTimeLapNum")
                if 1 <= n <= hist.field("numLaps"):
                    row = hist.row("lapHistoryData", n - 1)
                    if row["lapValidBitFlags"] & 1:
                        best = row["lapTimeInMS"] or None
                if lap and 1 < lap["currentLapNum"] <= hist.field("numLaps") + 1:
                    previous = hist.row("lapHistoryData", lap["currentLapNum"] - 2)
                    if previous["lapTimeInMS"] == lap["lastLapTimeInMS"]:
                        lap["previousSector3"] = lap_ms(previous, "sector3Time") or None
            if not best:
                best = min((v["ms"] for v in self.observed_laps.get(i, {}).values() if v["valid"]),
                           default=None)
            if result and result["bestLapTimeInMS"]:
                best = result["bestLapTimeInMS"]
            if lap and lap["carPosition"]:
                lap["frontGap"] = (lap_ms(lap, "deltaToCarInFront") or None) if lap["carPosition"] > 1 else None
                lap["leaderGap"] = (lap_ms(lap, "deltaToRaceLeader") or None) if lap["carPosition"] > 1 else 0
                lap["sector1"] = lap_ms(lap, "sector1Time") or None
                lap["sector2"] = lap_ms(lap, "sector2Time") or None
            aero = packets[16].row("carTelemetry2Data", i) if 16 in packets else None
            car = {"id": i, "name": ((p["name"] or label("driver", p["driverId"])) if p else None),
                   "team": label("team", p["teamId"]) if p else None, "participant": p,
                   "lap": lap, "status": status, "best": best, "result": result, "aero": aero,
                   "telemetry": packets[6].row("carTelemetryData", i) if 6 in packets else None,
                   "damage": packets[10].row("carDamageData", i) if public and 10 in packets else None,
                   "motion": packets[0].row("carMotionData", i, MOTION_KEYS) if 0 in packets else None,
                   "tyre": TYRES.get(status["visualTyreCompound"]) if status else None}
            cars.append(car)
        cars.sort(key=lambda car: (car["result"] or car["lap"] or {}).get("position")
                  or (car["lap"] or {}).get("carPosition") or 99)
        by_position = {c["lap"]["carPosition"]: c["lap"] for c in cars if c["lap"] and c["lap"]["carPosition"]}
        for c in cars:
            if c["lap"]:
                c["lap"]["rearGap"] = by_position.get(c["lap"]["carPosition"] + 1, {}).get("frontGap")
        return cars

    def sample(self, lap: Packet, telemetry: Packet, now: float, motion: Packet | None) -> list[tuple[int, int, dict]]:
        p = self.get(4, now)
        active = p.field("numActiveCars") if p else 0
        session = self.get(1, now)
        network = session.field("networkGame") if session else None
        status = self.get(7, now)
        damage = self.get(10, now)
        elapsed = now - self.started
        rows = []
        for i in range(MAX_CARS):
            l = lap.row("lapData", i)
            if l["resultStatus"] not in (2, 3) or not l["currentLapNum"] or l["lapDistance"] is None or not 0 <= l["lapDistance"] <= 100_000:
                continue
            if i >= active and i != self.player and not l["carPosition"]:
                continue
            t = telemetry.row("carTelemetryData", i, SAMPLE_KEYS)
            if not all(t[k] is not None for k in ("throttle", "brake", "steer")):
                continue
            public = i == self.player or network == 0 or bool(p and i < active and p.row("participants", i, ("yourTelemetry",))["yourTelemetry"] == 1)
            s = status.row("carStatusData", i, ("tyresAgeLaps", "visualTyreCompound", "ersStoreEnergy",
                           "ersDeployedThisLap", "ersHarvestedThisLapMGUK", "fuelInTank")) if status else {}
            if not public:
                s = {k: v for k, v in s.items() if k not in STATUS_PRIVATE}
            d = damage.row("carDamageData", i, ("tyresWear",)) if damage and public else {}
            n = l["currentLapNum"]
            valid = (not l["currentLapInvalid"] and not l["pitStatus"] and
                     (not session or not session.field("safetyCarStatus")) and not self.red)
            previous = self.previous_laps.get(i)
            if previous and n == previous["n"] + 1 and l["lastLapTimeInMS"]:
                self.observed_laps.setdefault(i, {})[previous["n"]] = {
                    "ms": l["lastLapTimeInMS"], "valid": previous["valid"] and not l["pitStatus"],
                    "age": previous["age"], "tyre": previous["tyre"], "wear": previous["wear"],
                    "lap": previous["n"], "pit": previous["pit"] or bool(l["pitStatus"]),
                }
            wear = d.get("tyresWear")
            self.previous_laps[i] = {"n": n, "valid": valid and (not previous or previous["n"] != n or previous["valid"]),
                                     "age": s.get("tyresAgeLaps"), "tyre": s.get("visualTyreCompound"), "wear": wear,
                                     "pit": bool(l["pitStatus"]) or bool(previous and previous["n"] == n and previous["pit"])}
            point = {}
            if motion:
                point = motion.row("carMotionData", i, MOTION_KEYS)
                x, z = point["worldPositionX"], point["worldPositionZ"]
                if i == self.player and valid and x is not None and z is not None and (x or z):
                    self.track[min(2000, int(l["lapDistance"] // 5))] = (round(x, 2), round(z, 2))
            rows.append((i, n, {**t, **s, **d, **point, "t": round(elapsed, 6), "gameTime": lap.header.time,
                                 "d": l["lapDistance"], "ms": l["currentLapTimeInMS"], "valid": valid,
                                 "lastMs": l["lastLapTimeInMS"], "pit": l["pitStatus"], "sector": l["sector"]}))
        return rows

    def snapshot(self, now: float | None = None) -> dict:
        now = monotonic() if now is None else now
        session = self.session(now)
        return {"source": self.source, "run": self.run, "uid": str(self.uid) if self.uid is not None else None,
                "epoch": self.epoch, "player": self.player, "online": now - self.last <= 1.5,
                "age": round(now - self.last, 3) if self.uid is not None else None,
                "clock": round(max(0, self.last - self.started), 3) if self.uid is not None else 0,
                "session": session, "cars": self.cars(now, session), "events": list(self.events),
                "track": [[d * 5, *self.track[d]] for d in sorted(self.track)],
                "ended": self.ended, "red": self.red, "counts": dict(self.counts)}
