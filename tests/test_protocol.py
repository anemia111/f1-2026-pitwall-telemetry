from struct import pack_into
import pytest

from pitwall.protocol_2026 import HEADER, PACKETS, PacketError, parse


def datagram(kind, **overrides):
    values = dict(format=2026, year=25, major=1, minor=25, version=1, kind=kind,
                  uid=2**63 + 11, time=15.5, frame=100, overall=105, player=23, secondary=255)
    values.update(overrides)
    packet = bytearray(PACKETS[kind][2])
    HEADER.pack_into(packet, 0, *values.values())
    return packet


@pytest.mark.parametrize("kind,size", enumerate(
    [1325, 926, 1399, 45, 1470, 1233, 1448, 1445, 1134, 1062, 1133, 1460, 231, 273, 104, 1231, 269]
))
def test_all_packet_lengths(kind, size):
    raw = bytes(datagram(kind))
    assert len(raw) == size
    packet = parse(raw)
    assert packet.decode()["header"]["sessionUID"] == str(2**63 + 11)
    for wrong in (raw[:-1], raw + b"\0"):
        with pytest.raises(PacketError, match="length"):
            parse(wrong)


def test_24th_car_and_signed_telemetry():
    raw = datagram(6)
    pack_into("<Hfffb bH", raw, 29 + 23 * 59, 323, .9, -.2, .25, 1, -1, 12000)
    row = parse(bytes(raw)).row("carTelemetryData", 23)
    assert (row["speed"], row["gear"], row["engineRPM"]) == (323, -1, 12000)
    assert row["steer"] == pytest.approx(-.2)


def test_2026_aero_offsets():
    raw = datagram(16)
    pack_into("<BBHBBHBB", raw, 259, 1, 1, 513, 1, 0, 2049, 1, 0)
    row = parse(bytes(raw)).row("carTelemetry2Data", 23)
    assert row["activeAeroActivationDistance"] == 513
    assert row["overtakeActivationDistance"] == 2049
    assert row["2026Regulations"] == 1


def test_event_union():
    raw = datagram(3)
    pack_into("<4sBf", raw, 29, b"FTLP", 23, 90.25)
    assert parse(bytes(raw)).field("eventDetails") == {"vehicleIdx": 23, "lapTime": 90.25}
    pack_into("<4sBB", raw, 29, b"SCAR", 2, 0)
    assert parse(bytes(raw)).field("eventDetails") == {"safetyCarType": 2, "eventType": 0}


@pytest.mark.parametrize("changes", [{"format": 2025}, {"version": 2}, {"player": 24},
                                    {"time": float("nan")}, {"kind": 255}])
def test_invalid_headers(changes):
    raw = datagram(6)
    fields = dict(zip(("format", "year", "major", "minor", "version", "kind", "uid",
                       "time", "frame", "overall", "player", "secondary"), HEADER.unpack_from(raw)))
    fields.update(changes)
    HEADER.pack_into(raw, 0, *fields.values())
    with pytest.raises(PacketError):
        parse(bytes(raw))
