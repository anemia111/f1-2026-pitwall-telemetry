from pytest import approx

from pitwall.demo import Builder
from pitwall.storage import Store
from pitwall.timing import boundaries, read_timing


def test_raw_archive_lap_sectors_and_gaps(tmp_path):
    store = Store(tmp_path / "timing.sqlite3")
    try:
        def packet(kind, frame, at):
            return Builder(kind, frame, at, 9)

        def save(b, kind, frame, at, epoch=0, car=-1):
            assert store.put(("raw", ("run", at, epoch, kind, car, frame, bytes(b.data))))

        assert store.put(("run", ("run", "9", "LIVE", 0)))
        s = packet(1, 1, 0)
        s.write({"trackLength": 300, "sector2LapDistanceStart": 100., "sector3LapDistanceStart": 200.})
        save(s, 1, 1, 0)
        for frame, at, distance, ms, n, last in [(2, 0.1, 2, 20, 1, 0), (3, .3, 20, 200, 1, 0),
                                                  (4, 1.8, 180, 1800, 1, 0), (5, 3.2, 0, 0, 2, 3000)]:
            p = packet(2, frame, at)
            p.row("lapData", 0, currentLapNum=n, resultStatus=2, currentLapTimeInMS=ms,
                  lastLapTimeInMS=last, lapDistance=distance, sector=0)
            save(p, 2, frame, at)
        history = packet(11, 6, 3.3)
        history.write({"numLaps": 2, "carIdx": 0})
        history.row("lapHistoryData", 0, lapTimeInMS=3000, sector1TimeMSPart=1000,
                    sector2TimeMSPart=1000, sector3TimeMSPart=1000, lapValidBitFlags=15)
        history.row("lapHistoryData", 1, lapTimeInMS=3060, sector1TimeMSPart=1020,
                    sector2TimeMSPart=1020, sector3TimeMSPart=1020, lapValidBitFlags=14)
        save(history, 11, 6, 3.3, car=0)
        p = packet(2, 7, 3.4)
        p.row("lapData", 0, currentLapNum=1, resultStatus=2, lapDistance=10, currentLapTimeInMS=100)
        save(p, 2, 7, 3.4, epoch=1)
        store.queue.join()
        with store.open() as db:
            report = read_timing(db, "run", None)
        one, two, rewound = report["laps"]
        assert one["ms"] == 3000 and one["valid"]
        assert [s["ms"] for s in one["sectors"]] == [1000, 1000, 1000]
        assert len(one["minis"]) == 30
        assert one["minis"][0]["ms"] == approx(100)
        assert one["minis"][2]["ms"] is None
        assert two["ms"] == 3060 and two["valid"] is False
        assert rewound["epoch"] == 1 and rewound["ms"] is None and not rewound["minis"]
        assert boundaries(300, 0, 200) == []
    finally:
        store.close()

