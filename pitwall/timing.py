"""Reconstruct lap records from the immutable UDP archive."""
from bisect import bisect_right
from dataclasses import dataclass, field
from sqlite3 import Connection

from .protocol_2026 import MAX_CARS, Packet, parse

MINIS_PER_SECTOR = 10
LAP_KEYS = ("currentLapNum", "resultStatus", "lapDistance",
            "currentLapTimeInMS", "lastLapTimeInMS", "currentLapInvalid", "sector",
            "sector1TimeMSPart", "sector1TimeMinutesPart", "sector2TimeMSPart", "sector2TimeMinutesPart")
SEGMENTS = 3 + 3 * MINIS_PER_SECTOR


def lap_ms(row: dict, key: str) -> int:
    return row[key + "MinutesPart"] * 60000 + row[key + "MSPart"]


def timing_status(ms, valid, overall, personal):
    if ms is None:
        return None
    if valid and overall == ms:
        return "overall"
    if valid and personal == ms:
        return "personal"
    return "other"


def update_bests(bests, segments):
    for i, (ms, valid) in enumerate(segments):
        if ms is not None and valid and (bests[i] is None or ms < bests[i]):
            bests[i] = ms


def overall_bests(personal):
    return [min((ms for ms in column if ms is not None), default=None)
            for column in zip(*personal)] if personal else [None] * SEGMENTS


def boundaries(length: int, s2: float | None, s3: float | None) -> list[float]:
    if s2 is None or s3 is None or not 0 < s2 < s3 < length:
        return []
    sectors = [0., s2, s3, float(length)]
    return [sectors[i] + (sectors[i + 1] - sectors[i]) * j / MINIS_PER_SECTOR
            for i in range(3) for j in range(MINIS_PER_SECTOR)] + [float(length)]


@dataclass
class LapRecord:
    gates: list[float]
    start: float | None = None
    end: float | None = None
    total: int | None = None
    invalid: bool | None = None
    sectors: list[int | None] = field(default_factory=lambda: [None, None, None])
    flags: int | None = None
    previous: tuple[float, int, float] | None = None
    progress: float = -1.
    crossings: dict[int, float] = field(default_factory=dict)

    def update(self, row: dict, at: float, game_time: float) -> None:
        if self.start is None:
            self.start = at
        self.end = at
        self.invalid = bool(self.invalid or row["currentLapInvalid"])
        for i in range(min(row["sector"], 2)):
            value = lap_ms(row, f"sector{i + 1}Time")
            if value:
                self.sectors[i] = value
        d, ms = row["lapDistance"], row["currentLapTimeInMS"]
        if not self.gates or d is None or not 0 <= d <= self.gates[-1] + 55:
            self.previous = None
            return
        if self.progress < 0 and d <= 40 and ms <= 400:
            # A sample immediately after the line can use the game's lap-clock origin.
            self.crossings[0] = 0.
            if d > 0 and ms > 0:
                self.previous = 0., 0, game_time - ms / 1000
        if self.previous:
            old_d, old_ms, old_t = self.previous
            if 0 < d - old_d <= 55 and 0 < ms - old_ms <= 400 and 0 <= game_time - old_t <= .4:
                stop = bisect_right(self.gates, d)
                for i in range(bisect_right(self.gates, old_d), stop):
                    if self.gates[i] > self.progress:
                        self.crossings[i] = old_ms + (ms - old_ms) * (self.gates[i] - old_d) / (d - old_d)
        exact = bisect_right(self.gates, d) - 1
        if exact >= 0 and self.gates[exact] == d and d > self.progress:
            self.crossings.setdefault(exact, ms)
        self.progress = max(self.progress, d)
        self.previous = d, ms, game_time

    def sector_times(self):
        sectors = self.sectors.copy()
        source = ["game" if value is not None else None for value in sectors]
        s1, s2, s3 = sectors
        if self.total and s1 and s2 and s3 is None and self.total > s1 + s2:
            sectors[2], source[2] = self.total - s1 - s2, "difference"
        return sectors, source

    def mini_times(self):
        times = self.crossings.copy()
        s1, s2, _ = self.sectors
        for i, value in ((MINIS_PER_SECTOR, s1),
                         (2 * MINIS_PER_SECTOR, s1 + s2 if s1 and s2 else None),
                         (3 * MINIS_PER_SECTOR, self.total)):
            if value is not None:
                times[i] = value
        for i in range(len(self.gates) - 1):
            x, y = times.get(i), times.get(i + 1)
            yield round(y - x, 1) if x is not None and y is not None and y > x else None

    def finish(self, epoch: int, car: int, lap: int) -> dict:
        sectors, source = self.sector_times()
        minis = [{"number": i + 1, "sector": i // MINIS_PER_SECTOR + 1,
                  "fromM": round(a, 2), "toM": round(b, 2), "ms": ms}
                 for i, (a, b, ms) in enumerate(zip(self.gates, self.gates[1:], self.mini_times()))]
        return {"epoch": epoch, "car": car, "lap": lap, "start": self.start, "end": self.end,
                "ms": self.total, "valid": bool(self.flags & 1) if self.total and self.flags is not None else
                False if self.invalid else None,
                "sectors": [{"ms": value, "source": src, "valid": bool(self.flags & (2 << i))
                             if self.flags is not None else None}
                            for i, (value, src) in enumerate(zip(sectors, source))],
                "minis": minis}


def record_segments(record):
    for sector in record["sectors"]:
        yield sector["ms"], sector["valid"] if sector["valid"] is not None else record["valid"] is not False
    for mini in record["minis"]:
        yield mini["ms"], record["valid"] is not False and record["sectors"][mini["sector"] - 1]["valid"] is not False


class LiveTiming:
    """Track crossings from the live Lap Data stream independently of recording."""

    def __init__(self) -> None:
        self.gates: list[float] = []
        self.current: dict[int, tuple[int, LapRecord]] = {}
        self.previous: dict[int, int] = {}
        self.completed: dict[int, dict[int, LapRecord]] = {}
        self.history: dict[int, list[dict]] = {}
        self.personal: dict[int, list[float | None]] = {}

    def ingest(self, packet: Packet) -> None:
        if packet.header.kind == 1:
            if not self.gates:
                self.gates = boundaries(packet.field("trackLength"), packet.field("sector2LapDistanceStart"),
                                        packet.field("sector3LapDistanceStart"))
            return
        if packet.header.kind == 11:
            car = packet.field("carIdx")
            if car >= MAX_CARS:
                return
            history = [packet.row("lapHistoryData", i) for i in range(packet.field("numLaps"))]
            if history != self.history.get(car):
                self.history[car] = history
                self.refresh(car)
            return
        if packet.header.kind != 2:
            return
        for car in range(MAX_CARS):
            row = packet.row("lapData", car, LAP_KEYS)
            lap = row["currentLapNum"]
            if not lap or row["resultStatus"] < 2:
                continue
            prior, record = self.current.get(car, (0, None))
            if lap < prior:
                continue
            if lap != prior:
                if record is not None and lap == prior + 1:
                    record.total = row["lastLapTimeInMS"] or None
                    self.completed.setdefault(car, {})[prior] = record
                    self.previous[car] = prior
                    self.refresh(car)
                else:
                    self.previous.pop(car, None)
                record = LapRecord(self.gates)
                self.current[car] = lap, record
            if not record.gates and self.gates:
                record.gates = self.gates
            record.update(row, packet.header.time, packet.header.time)

    def refresh(self, car: int) -> None:
        bests = [None] * SEGMENTS
        laps = self.completed.get(car, {})
        history = self.history.get(car, [])
        for lap in laps.keys() | set(range(1, len(history) + 1)):
            record = laps.get(lap) or LapRecord([])
            if lap <= len(history):
                apply_history(record, history[lap - 1])
            update_bests(bests, record_segments(record.finish(0, car, lap)))
        self.personal[car] = bests

    def snapshot(self, cars: list[dict]) -> tuple[dict[int, list[float | None]], list[float | None]]:
        personal = self.personal.copy()
        current = {}
        for car in cars:
            i, lap = car["id"], car["lap"]
            entry = self.current.get(i)
            if not lap or not entry or entry[0] != lap["currentLapNum"]:
                continue
            number, record = entry
            row = record.finish(0, i, number)
            bests = personal.get(i, [None] * SEGMENTS).copy()
            update_bests(bests, record_segments(row))
            personal[i] = bests
            current[i] = row
        overall = overall_bests(list(personal.values()))
        for car in cars:
            i, lap = car["id"], car["lap"]
            if not lap:
                continue
            own = personal.get(i, [None] * SEGMENTS)
            row = current.get(i)
            previous_lap = lap["currentLapNum"] - 1
            previous = self.completed.get(i, {}).get(previous_lap) if self.previous.get(i) == previous_lap else None
            if previous and not lap.get("previousSector3"):
                lap["previousSector3"] = previous.sector_times()[0][2]
            prior_valid = False
            if previous:
                prior_valid = bool(previous.flags & 8) if previous.flags is not None else not previous.invalid
            elif lap.get("previousSector3"):
                history = self.history.get(i, [])
                prior_valid = 1 <= previous_lap <= len(history) and bool(history[previous_lap - 1]["lapValidBitFlags"] & 8)
            sector_ranks = [
                timing_status(lap.get(key), row is not None and row["valid"] is not False and
                              row["sectors"][j]["ms"] == lap.get(key), overall[j], own[j])
                for j, key in enumerate(("sector1", "sector2"))
            ]
            sector_ranks.append(timing_status(lap.get("previousSector3"), prior_valid, overall[2], own[2]))
            segments = list(record_segments(row)) if row else []
            mini_ranks = [timing_status(ms, valid, overall[j], own[j])
                          for j, (ms, valid) in enumerate(segments[3:], start=3)]
            car["timingRanks"] = {"sectors": sector_ranks, "minis": mini_ranks}
        return personal, overall


def apply_history(record, row):
    record.total = row["lapTimeInMS"] or record.total
    for i in range(3):
        record.sectors[i] = lap_ms(row, f"sector{i + 1}Time") or record.sectors[i]
    record.flags = row["lapValidBitFlags"]


def rank_records(records, references):
    bests = {}
    for record in records:
        key = record["epoch"], record["car"]
        update_bests(bests.setdefault(key, [None] * SEGMENTS), record_segments(record))
    overall = {
        epoch: overall_bests([best for (e, _), best in bests.items() if e == epoch])
        for epoch in {e for e, _ in bests}
    }
    if references:
        epoch, personal, session = references
        update_bests(overall.setdefault(epoch, [None] * SEGMENTS), ((ms, True) for ms in session))
        for car, values in personal.items():
            update_bests(bests.setdefault((epoch, car), [None] * SEGMENTS), ((ms, True) for ms in values))
    for record in records:
        epoch, car = record["epoch"], record["car"]
        for part, (ms, valid), best, own in zip(record["sectors"] + record["minis"], record_segments(record),
                                               overall[epoch], bests[epoch, car]):
            part["rank"] = timing_status(ms, valid, best, own)


def read_timing(db: Connection, run: str, car: int | None, *, ranked=False, references=None) -> dict:
    """Use the raw stream so existing captures and laps without CarTelemetry are included."""
    records = []
    epochs = [e for (e,) in db.execute("SELECT DISTINCT epoch FROM raw WHERE run=? ORDER BY epoch", (run,))]
    for epoch in epochs:
        cars = range(MAX_CARS) if car is None or (ranked and (references is None or references[0] != epoch)) else (car,)
        gates = []
        for (raw,) in db.execute("SELECT payload FROM raw WHERE run=? AND epoch=? AND kind=1 AND car=-1 "
                                 "ORDER BY t DESC, seq DESC LIMIT 16", (run, epoch)):
            session = parse(raw)
            gates = boundaries(session.field("trackLength"), session.field("sector2LapDistanceStart"),
                               session.field("sector3LapDistanceStart"))
            if gates:
                break
        laps: dict[tuple[int, int], LapRecord] = {}
        previous_lap: dict[int, int] = {}
        last_frame = -1
        for at, raw in db.execute("SELECT t,payload FROM raw WHERE run=? AND epoch=? AND kind=2 AND car=-1 "
                                  "ORDER BY t,seq", (run, epoch)):
            packet = parse(raw)
            if packet.header.overall <= last_frame:
                continue
            last_frame = packet.header.overall
            for i in cars:
                row = packet.row("lapData", i, LAP_KEYS)
                n = row["currentLapNum"]
                if not n or row["resultStatus"] < 2:
                    continue
                previous = previous_lap.get(i)
                if previous is not None and n < previous:
                    continue
                if n > 1 and row["lastLapTimeInMS"]:
                    # The first recorded packet may already be in the following lap.
                    key = (i, n - 1)
                    if key not in laps:
                        laps[key] = LapRecord(gates)
                    laps[key].total = row["lastLapTimeInMS"]
                key = (i, n)
                if key not in laps:
                    laps[key] = LapRecord(gates)
                laps[key].update(row, at, packet.header.time)
                previous_lap[i] = n
        for i in cars:
            # History packets are cumulative. Prefer the latest accepted game frame.
            history = db.execute("SELECT payload FROM raw WHERE run=? AND epoch=? AND kind=11 AND car=? "
                                 "ORDER BY frame DESC, seq DESC LIMIT 1", (run, epoch, i)).fetchone()
            if not history:
                continue
            packet = parse(history[0])
            for j in range(packet.field("numLaps")):
                row = packet.row("lapHistoryData", j)
                sectors = [lap_ms(row, f"sector{k}Time") or None for k in (1, 2, 3)]
                if not row["lapTimeInMS"] and not any(sectors) and (i, j + 1) not in laps:
                    continue
                key = (i, j + 1)
                if key not in laps:
                    laps[key] = LapRecord(gates)
                record = laps[key]
                apply_history(record, row)
        records.extend(record.finish(epoch, i, lap) for (i, lap), record in sorted(laps.items()))
    if ranked:
        rank_records(records, references)
        records = [record for record in records if car is None or record["car"] == car]
    return {"run": run, "miniSectorsPerSector": MINIS_PER_SECTOR, "laps": records}

