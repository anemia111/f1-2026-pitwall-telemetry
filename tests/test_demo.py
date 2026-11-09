import pytest

from pitwall.demo import demo_packets
from pitwall.protocol_2026 import parse
from pitwall.state import LiveState


@pytest.mark.parametrize("frame", [0, 671, 2835, 4725, 5040, 6000, 12720, 13000])
def test_demo_boundaries(frame):
    packets = [parse(p) for p in demo_packets(frame, frame * 8 / 60, 123, 60)]
    lap = next(p for p in packets if p.header.kind == 2)
    assert lap.row("lapData", 23)["sector"] in (0, 1, 2)
    assert all(p.header.uid == 123 for p in packets)


def test_motion_received_after_lap_and_telemetry():
    packets = {parse(p).header.kind: parse(p) for p in demo_packets(0, 15, 123, 60)}
    state = LiveState()
    state.reset(packets[2], 100)
    assert not state.ingest(packets[2], 100)[1]
    assert not state.ingest(packets[6], 100)[1]
    _, rows = state.ingest(packets[0], 100)
    assert rows and "worldPositionX" in rows[0][2]
