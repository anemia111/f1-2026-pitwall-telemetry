"""Build a static Pages demo from synthetic 2026 UDP, without reading any archives."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from shutil import copyfile

from pitwall.demo import TRACK, demo_packets
from pitwall.protocol_2026 import parse
from pitwall.state import LiveState
from pitwall.storage import DDL, INSERT
from pitwall.strategy import Assumptions, forecast
from pitwall.timing import read_timing

ROOT = Path(__file__).resolve().parent.parent
FPS = 4
SECONDS = 92


def generate(db: sqlite3.Connection) -> dict:
    state = LiveState(source="DEMO")
    frames = []
    traces: list[list[list[float | int]]] = [[] for _ in range(24)]
    rate = 10
    for frame in range(SECONDS * rate):
        t = frame / rate
        for raw in demo_packets(frame, t * 8, 1, rate):
            p = parse(raw)
            if state.uid is None:
                state.reset(p, t)
            state.ingest(p, t)
            if p.header.kind == 1:
                db.execute(INSERT["raw"], ("demo", t, 0, p.header.kind, -1, p.header.overall, raw))
        motion, laps = state.get(0, t), state.get(2, t)
        if not motion or not laps:
            raise RuntimeError(f"demo frame {frame} is missing Motion or Lap Data")
        for i, trace in enumerate(traces):
            position = motion.row("carMotionData", i, ("worldPositionX", "worldPositionZ"))
            lap = laps.row("lapData", i, ("currentLapNum",))["currentLapNum"]
            trace.append([round(position["worldPositionX"], 1), round(position["worldPositionZ"], 1), lap])
        if frame % rate not in (0, 2, 5, 7):
            continue
        snap = state.snapshot(t)
        session = snap["session"] or {}
        tyre_sets = state.get(12, t, 0)
        model = forecast(snap, state.observed_laps, tyre_sets.field("tyreSetData") if tyre_sets else None, Assumptions())
        cars = []
        for c in snap["cars"]:
            lap, telem, aero = (c[k] or {} for k in ("lap", "telemetry", "aero"))
            number = c["id"] + 1
            cars.append({
                "id": number, "name": f"DEMO DRIVER {number:02}", "position": lap.get("carPosition"),
                "lap": lap.get("currentLapNum"), "gap": lap.get("frontGap"), "leader": lap.get("leaderGap"),
                "behind": lap.get("rearGap"), "sector1": lap.get("sector1"), "sector2": lap.get("sector2"),
                "pit": lap.get("pitStatus"), "penalties": lap.get("penalties"), "status": lap.get("resultStatus"),
                "best": c["best"], "last": lap.get("lastLapTimeInMS"), "tyre": c["tyre"],
                "age": (c["status"] or {}).get("tyresAgeLaps"), "speed": telem.get("speed"),
                "rpm": telem.get("engineRPM"), "gear": telem.get("gear"),
                "brake": round(telem.get("brake", 0) * 100), "throttle": round(telem.get("throttle", 0) * 100),
                "aero": aero.get("activeAeroMode"), "overtake": aero.get("overtakeActive"),
                "overtakeAvailable": aero.get("overtakeAvailable"),
                "distance": lap.get("lapDistance"), "elapsed": lap.get("currentLapTimeInMS"),
                "stops": lap.get("numPitStops"), "teamId": (c["participant"] or {}).get("teamId"),
                "used": max((c["damage"] or {}).get("tyresWear") or [], default=None),
                "energy": (c["status"] or {}).get("ersStoreEnergy"),
            })
        frames.append({"t": t, "sample": frame, "lap": cars[0]["lap"], "total": session.get("totalLaps"),
                       "temperature": session.get("trackTemperature"),
                       "safety": session.get("safetyCarStatus"), "cars": cars,
                       "strategy": {"pick": model["recommended"], "reason": model["reason"],
                                    "plans": [{"id": p["id"], "lap": p["pitLap"], "time": p["remainingTime"],
                                               "interval": p["interval"], "loss": p.get("pitLoss")} for p in model["plans"]],
                                    "wear": model["model"]["wear"], "remaining": model["model"]["remaining"]}})
    # Replay frames preserve the strategy model's sampling cadence. Record finer
    # synthetic LapData separately so distance crossings can be interpolated.
    timing_rate = 24
    for frame in range(SECONDS * timing_rate):
        t = frame / timing_rate
        raw = next(raw for raw in demo_packets(frame, t * 8, 1, timing_rate) if parse(raw).header.kind == 2)
        db.execute(INSERT["raw"], ("demo", t, 0, 2, -1, frame, raw))
    return {"version": 4, "fps": FPS, "trackLength": TRACK, "traces": traces, "frames": frames,
            "sectorBounds": [0, session["sector2LapDistanceStart"], session["sector3LapDistanceStart"], TRACK],
            "timing": read_timing(db, "demo", None)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    target = args.output
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "pages.css", "demo.js"):
        copyfile(ROOT / "web" / "pages" / filename, target / filename)
    copyfile(ROOT / "web" / "src" / "style.css", target / "pitwall.css")
    copyfile(ROOT / "LICENSE", target / "LICENSE")
    (target / "README.md").write_text("# APEX 2026 Pit Wall Demo\n\nStatic GitHub Pages demo. All race data is synthetic.\n", encoding="utf8")
    (target / ".nojekyll").touch()
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(DDL)
        race = generate(db)
    timing = race.pop("timing")
    for name, data in (("race.json", race), ("timing.json", timing)):
        (target / name).write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf8")


if __name__ == "__main__":
    main()
