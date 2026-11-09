"""Reconstruct lap records from the immutable UDP archive."""
from bisect import bisect_right
from dataclasses import dataclass, field
from sqlite3 import Connection

from .protocol_2026 import MAX_CARS, parse
from .state import lap_ms

MINIS_PER_SECTOR = 10
LAP_KEYS = ("currentLapNum", "resultStatus", "lapDistance",
            "currentLapTimeInMS", "lastLapTimeInMS", "currentLapInvalid", "sector",
            "sector1TimeMSPart", "sector1TimeMinutesPart", "sector2TimeMSPart", "sector2TimeMinutesPart")


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

    def finish(self, epoch: int, car: int, lap: int) -> dict:
        sectors = self.sectors.copy()
        source = ["game" if value is not None else None for value in sectors]
        s1, s2, s3 = sectors
        if self.total and s1 and s2 and s3 is None and self.total > s1 + s2:
            sectors[2], source[2] = self.total - s1 - s2, "difference"
        times = self.crossings.copy()
        for i, value in ((MINIS_PER_SECTOR, s1),
                         (2 * MINIS_PER_SECTOR, s1 + s2 if s1 and s2 else None),
                         (3 * MINIS_PER_SECTOR, self.total)):
            if value is not None:
                times[i] = value
        minis = []
        for i, (a, b) in enumerate(zip(self.gates, self.gates[1:])):
            x, y = times.get(i), times.get(i + 1)
            minis.append({"number": i + 1, "sector": i // MINIS_PER_SECTOR + 1,
                          "fromM": round(a, 2), "toM": round(b, 2),
                          "ms": round(y - x, 1) if x is not None and y is not None and y > x else None})
        return {"epoch": epoch, "car": car, "lap": lap, "start": self.start, "end": self.end,
                "ms": self.total, "valid": bool(self.flags & 1) if self.total and self.flags is not None else
                False if self.invalid else None,
                "sectors": [{"ms": value, "source": src, "valid": bool(self.flags & (2 << i))
                             if self.flags is not None else None}
                            for i, (value, src) in enumerate(zip(sectors, source))],
                "minis": minis}


def read_timing(db: Connection, run: str, car: int | None) -> dict:
    """Use the raw stream so existing captures and laps without CarTelemetry are included."""
    cars = range(MAX_CARS) if car is None else (car,)
    records = []
    epochs = [e for (e,) in db.execute("SELECT DISTINCT epoch FROM raw WHERE run=? ORDER BY epoch", (run,))]
    for epoch in epochs:
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
                record.total = row["lapTimeInMS"] or record.total
                record.sectors = [official or recorded for official, recorded in zip(sectors, record.sectors)]
                record.flags = row["lapValidBitFlags"]
        records.extend(record.finish(epoch, i, lap) for (i, lap), record in sorted(laps.items()))
    return {"run": run, "miniSectorsPerSector": MINIS_PER_SECTOR, "laps": records}

