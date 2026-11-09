"""UDP transport, sampling and bounded publication."""
import asyncio
import json
import logging
import socket
from collections import deque
from dataclasses import dataclass
from time import monotonic, perf_counter, time
from uuid import uuid4

from .analysis import compare
from .engineer import Engineer
from .protocol_2026 import PacketError, parse
from .state import LiveState
from .storage import Store
from .strategy import Assumptions

LOG = logging.getLogger(__name__)


@dataclass
class Settings:
    mode: str = "LIVE"
    udp_host: str = "0.0.0.0"
    udp_port: int = 20777
    ps5_ip: str = ""
    key: str = ""
    ollama: str = ""


class Receiver(asyncio.DatagramProtocol):
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings
        self.state = LiveState(source=settings.mode)
        self.engineer = Engineer()
        self.config = Assumptions()
        self.client: str | None = None
        self.retired: deque[int] = deque(maxlen=16)
        self.recording = True
        self.last_error: str | None = None
        self.last_process_ms = 0.
        self.peaks: deque[float] = deque(maxlen=120)
        self.latest_event: deque[dict] = deque(maxlen=80)
        self.snapshot: dict = self.state.snapshot()
        self.serialized = "{}"
        self.coaching: str | None = None
        self.coached_lap: int | None = None
        self.archive_started = 0.

    def begin(self, now: float) -> None:
        if self.state.uid is None or not self.recording:
            return
        run = uuid4().hex
        if self.store.put(("run", (run, str(self.state.uid), self.state.source, time()))):
            self.state.run = run
            self.archive_started = now

    def record(self, enabled: bool) -> None:
        self.recording = enabled
        if not enabled:
            self.state.run = None
        elif self.state.run is None:
            self.begin(monotonic())

    def error_received(self, exc: Exception) -> None:
        self.last_error = str(exc)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        sock = transport.get_extra_info("socket")
        self.settings.udp_port = sock.getsockname()[1]
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        start = perf_counter()
        now = monotonic()
        s = self.state
        if (self.settings.ps5_ip and addr[0] != self.settings.ps5_ip) or (
            self.client and addr[0] != self.client and now - s.last < 5
        ):
            s.counts["ignored"] += 1
            return
        try:
            packet = parse(data)
        except PacketError as exc:
            s.counts["invalid"] += 1
            self.last_error = str(exc)
            return
        h = packet.header
        if h.uid != s.uid:
            if h.uid in self.retired:
                s.counts["ignored"] += 1
                return
            if s.uid is not None:
                self.retired.append(s.uid)
            s.reset(packet, now)
            s.player = h.player
            self.engineer = Engineer()
            self.coaching = None
            self.coached_lap = None
            self.latest_event.clear()
            self.begin(now)
        self.client = addr[0]
        s.counts["valid"] += 1
        event, samples = s.ingest(packet, now)
        if event:
            if event["code"] == "FLBK":
                self.engineer = Engineer()
                self.coaching = None
                self.coached_lap = None
                self.latest_event.clear()
            self.latest_event.append(event)
        if s.run:
            t = round(now - self.archive_started, 6)
            car = packet.field("carIdx") if h.kind in (11, 12) else -1
            rows = [("raw", (s.run, t, s.epoch, h.kind, car, h.overall, data))]
            rows.extend(("sample", (s.run, s.epoch, i, lap, t, json.dumps({**body, "t": t}, separators=(",", ":"))))
                        for i, lap, body in samples)
            if event:
                rows.append(("event", (s.run, s.epoch, t, json.dumps({**event, "time": t}, ensure_ascii=False))))
            self.store.put(*rows)
        self.last_process_ms = (perf_counter() - start) * 1000
        self.peaks.append(self.last_process_ms)

    def tyre_sets(self, now: float) -> list[dict] | None:
        packet = self.state.get(12, now, self.state.player)
        return packet.field("tyreSetData") if packet else None

    def log(self, item: dict, now: float) -> bool:
        if not self.state.run:
            return False
        t = max(0., now - self.archive_started)
        return self.store.put(("decision", (self.state.run, self.state.epoch, t,
                                            json.dumps({**item, "time": t}, ensure_ascii=False))))

    def publish(self, tick: int) -> None:
        now = monotonic()
        snap = self.state.snapshot(now)
        if self.latest_event or tick % 5 == 0 or (not snap["online"] and self.snapshot.get("online")):
            events = list(self.latest_event) or [None]
            self.latest_event.clear()
            for event in events:
                for item in self.engineer.update(snap, self.state.observed_laps, self.tyre_sets(now), self.config, event, now):
                    self.log(item, now)
        snap.update({"strategy": self.engineer.strategy, "radio": list(self.engineer.radio)[:20],
                     "revision": self.engineer.revision, "coaching": self.coaching,
                     "connection": {"port": self.settings.udp_port, "sender": self.client, "error": self.last_error,
                                    "recording": self.recording, "archiveDrops": self.store.dropped,
                                    "archiveError": self.store.error, "archiveQueue": self.store.queue.qsize(),
                                    "processMs": round(self.last_process_ms, 3),
                                    "peakMs": round(max(self.peaks, default=0), 3)}})
        self.snapshot = snap
        self.serialized = json.dumps(snap, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    async def loop(self) -> None:
        tick = 0
        task = None
        while True:
            self.publish(tick)
            s = self.state
            valid = [p for p in s.observed_laps.get(s.player, {}).values() if p["valid"]]
            if s.run and len(valid) > 1 and valid[-1]["lap"] != self.coached_lap and (task is None or task.done()):
                self.coached_lap = valid[-1]["lap"]
                best = min(valid[:-1], key=lambda p: p["ms"])
                task = asyncio.create_task(self.review(s.run, s.epoch, s.player, valid[-1]["lap"], best["lap"]))
            tick += 1
            await asyncio.sleep(.1)

    async def review(self, run: str, epoch: int, car: int, current: int, reference: int) -> None:
        def report() -> dict:
            args = run, epoch, car
            return compare(self.store.samples(*args, lap=current), self.store.samples(*args, lap=reference))
        try:
            data = await asyncio.to_thread(report)
        except Exception:
            LOG.exception("Lap review failed")
            return
        s = self.state
        if (run, epoch, car) != (s.run, s.epoch, s.player):
            return
        zone = max(data["zones"], key=lambda z: z["loss"], default=None)
        if not zone or zone["loss"] <= .1:
            self.coaching = None
            return
        self.coaching = (f"前周の{zone['from']:.0f}〜{zone['to']:.0f}メートルで、"
                         f"基準より{zone['loss']:.2f}秒ロス。 "
                         + (zone["hypothesis"] or "制動と出口速度を比較してください。"))
        now = monotonic()
        snap = s.snapshot(now)
        if not snap["red"] and not (snap["session"] or {}).get("gamePaused"):
            item = self.engineer.emit(snap, "LOW", "coaching", self.coaching,
                                      {"referenceLap": reference, "measuredLap": current, "zone": zone}, now, 50)
            if item:
                self.log(item, now)
