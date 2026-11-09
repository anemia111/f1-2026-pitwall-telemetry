import pytest

from pitwall.demo import demo_packets
from pitwall.protocol_2026 import parse


@pytest.mark.parametrize("frame", [0, 671, 2835, 4725, 5040, 6000, 12720, 13000])
def test_demo_boundaries(frame):
    packets = [parse(p) for p in demo_packets(frame, frame * 8 / 60, 123, 60)]
    lap = next(p for p in packets if p.header.kind == 2)
    assert lap.row("lapData", 23)["sector"] in (0, 1, 2)
    assert all(p.header.uid == 123 for p in packets)
