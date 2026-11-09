"""Re-decode a portable capture with the current parser without opening a network socket."""
import argparse
from collections import Counter
from pathlib import Path
from struct import Struct

from pitwall.protocol_2026 import PACKETS, PacketError, parse

RECORD = Struct("<dIH")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    counts = Counter()
    with args.capture.open("rb") as file:
        if file.read(8) != b"APEXUDP1":
            raise SystemExit("invalid capture magic")
        while header := file.read(RECORD.size):
            if len(header) != RECORD.size:
                raise SystemExit("truncated capture metadata")
            _, _, size = RECORD.unpack(header)
            payload = file.read(size)
            if len(payload) != size:
                raise SystemExit("truncated datagram")
            try:
                packet = parse(payload)
                packet.decode()
            except PacketError as exc:
                raise SystemExit(f"invalid captured packet: {exc}") from exc
            counts[PACKETS[packet.header.kind][0]] += 1
    for kind, count in counts.most_common():
        print(f"{kind:22} {count:8d}")


if __name__ == "__main__":
    main()
