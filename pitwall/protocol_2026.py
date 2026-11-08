"""Packed, little-endian EA Season Pack 2026 v1.2 wire layouts."""
from dataclasses import dataclass
from functools import cache
from math import isfinite, prod
from pathlib import Path
from struct import Struct
from typing import Any
import json

MAX_CARS = 24
VERSION = 1
HEADER = Struct("<HBBBBBQfIIBB")
SCHEMA = json.loads(Path(__file__).with_name("schema_2026.json").read_text(encoding="utf8"))
LABELS = json.loads(Path(__file__).with_name("labels_2026.json").read_text(encoding="utf8"))
PACKETS = tuple(tuple(row) for row in SCHEMA["packets"])
PRIMITIVES = dict(zip(
    ("uint8", "int8", "uint16", "int16", "uint32", "int32", "uint64", "float", "double", "uint"),
    "BbHhIiQfdI", strict=True,
))


class PacketError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Header:
    format: int
    game_year: int
    game_major: int
    game_minor: int
    version: int
    kind: int
    uid: int
    time: float
    frame: int
    overall: int
    player: int
    secondary: int


@dataclass(frozen=True, slots=True)
class Field:
    kind: str
    name: str
    dims: tuple[int, ...]
    offset: int
    unit: int
    codec: Struct | None


@cache
def layout(name: str) -> tuple[int, dict[str, Field]]:
    fields = {}
    offset = 0
    for kind, key, *counts in SCHEMA["structs"][name]:
        dims = tuple(counts)
        number = prod(dims)
        codec = None
        if kind in PRIMITIVES:
            codec = Struct("<" + str(number) + PRIMITIVES[kind])
            unit = codec.size // number
        elif kind == "char":
            codec = Struct(f"<{number}s")
            unit = 1
        elif kind == "EventDataDetails":
            unit = 12
        else:
            unit = layout(kind)[0]
        fields[key] = Field(kind, key, dims, offset, unit, codec)
        offset += unit * number
    return offset, fields


def reshape(values: tuple | list, dims: tuple[int, ...]) -> list:
    if len(dims) == 1:
        return list(values)
    width = prod(dims[1:])
    return [reshape(values[i:i + width], dims[1:]) for i in range(0, len(values), width)]


def decode_field(data: bytes, field: Field, base: int) -> Any:
    offset = base + field.offset
    if field.codec:
        values = field.codec.unpack_from(data, offset)
        if field.kind == "char":
            return values[0].split(b"\0", 1)[0].decode("utf8", errors="replace")
        if field.kind in ("float", "double"):
            values = tuple(x if isfinite(x) else None for x in values)
        return reshape(values, field.dims) if field.dims else values[0]
    if field.kind == "EventDataDetails":
        code = data[offset - 4:offset].decode("ascii", errors="replace")
        subtype = SCHEMA["event_types"].get(code)
        return decode_struct(data, subtype, offset) if subtype else {}
    if field.dims:
        values = [decode_struct(data, field.kind, offset + i * field.unit) for i in range(prod(field.dims))]
        return reshape(values, field.dims)
    return decode_struct(data, field.kind, offset)


def decode_struct(data: bytes, name: str, offset: int = 0, keys: tuple[str, ...] | None = None) -> dict:
    fields = layout(name)[1]
    return {key: decode_field(data, fields[key], offset) for key in (fields if keys is None else keys)}


@dataclass(frozen=True, slots=True)
class Packet:
    header: Header
    raw: bytes

    @property
    def structure(self) -> str:
        return PACKETS[self.header.kind][1]

    def decode(self) -> dict:
        body = decode_struct(self.raw, self.structure)
        body["header"]["sessionUID"] = str(self.header.uid)
        return body

    def field(self, name: str) -> Any:
        return decode_field(self.raw, layout(self.structure)[1][name], 0)

    def row(self, name: str, index: int, keys: tuple[str, ...] | None = None) -> dict:
        field = layout(self.structure)[1][name]
        if not 0 <= index < field.dims[0]:
            raise IndexError(index)
        return decode_struct(self.raw, field.kind, field.offset + index * field.unit, keys)


def parse(data: bytes) -> Packet:
    if len(data) < HEADER.size:
        raise PacketError("truncated header")
    h = Header(*HEADER.unpack_from(data))
    if h.format != 2026:
        raise PacketError(f"unsupported UDP format {h.format}")
    if h.kind >= len(PACKETS):
        raise PacketError(f"unknown packet ID {h.kind}")
    if h.version != VERSION:
        raise PacketError(f"unsupported packet version {h.version} for ID {h.kind}")
    if len(data) != PACKETS[h.kind][2]:
        raise PacketError(f"wrong length for ID {h.kind}: {len(data)}")
    if not isfinite(h.time) or h.time < 0 or any(i >= MAX_CARS and i != 255 for i in (h.player, h.secondary)):
        raise PacketError("invalid header time or car index")
    packet = Packet(h, data)
    for key, limit in COUNT_LIMITS.get(h.kind, ()):
        if packet.field(key) > limit:
            raise PacketError(f"out of bounds: {key}")
    return packet


COUNT_LIMITS = {
    1: (("numMarshalZones", 21), ("numWeatherForecastSamples", 64), ("numSessionsInWeekend", 12),
        ("numActiveAeroZonesFull", 8), ("numActiveAeroZonesPartial", 8), ("numDRSZones", 4)),
    4: (("numActiveCars", MAX_CARS),),
    8: (("numCars", MAX_CARS),),
    9: (("numPlayers", MAX_CARS),),
    11: (("carIdx", MAX_CARS - 1), ("numLaps", 100), ("numTyreStints", 8)),
    12: (("carIdx", MAX_CARS - 1),),
    15: (("numLaps", 50),),
}
for name, structure, size in PACKETS:
    if layout(structure)[0] != size:
        raise RuntimeError(f"{name} layout does not match published size")
