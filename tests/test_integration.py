import io
import socket
from time import monotonic, sleep

import pyarrow.parquet as parquet
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pitwall.demo import demo_packets
from pitwall.server import create_app
from pitwall.service import Settings


def wait_for(fn, timeout=5):
    end = monotonic() + timeout
    while monotonic() < end:
        value = fn()
        if value:
            return value
        sleep(.05)
    raise AssertionError("condition did not become true")


def test_udp_ws_archives_and_stale_radio(tmp_path):
    settings = Settings(mode="DEMO", udp_host="127.0.0.1", udp_port=0)
    with TestClient(create_app(settings, tmp_path / "test.sqlite3")) as client, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        target = "127.0.0.1", settings.udp_port
        sock.sendto(b"bad", target)
        for frame in range(12):
            for packet in demo_packets(frame, 12.0 + frame / 3.0, 987654321, 30):
                sock.sendto(packet, target)
            sleep(.02)
        with client.websocket_connect("/ws") as ws:
            live = ws.receive_json()
            for _ in range(15):
                if len(live.get("cars", [])) == 24:
                    break
                live = ws.receive_json()
            assert live["source"] == "DEMO"
            assert live["online"]
            assert len(live["cars"]) == 24
            assert live["counts"]["invalid"] == 1
            assert live["cars"][23]["telemetry"]["speed"] > 0
        run = wait_for(lambda: (client.get("/api/runs").json() or [None])[0])
        rid = run["id"]
        assert client.get(f"/api/laps?run={rid}&car=0").json()[0]["samples"] >= 2
        replay = client.get(f"/api/replay?run={rid}&t={run['duration']}").json()
        assert replay["replay"] and len(replay["cars"]) == 24
        csv = client.get(f"/api/export?run={rid}&format=csv")
        assert csv.status_code == 200 and b"engineRPM" in csv.content
        binary = client.get(f"/api/export?run={rid}&format=udp")
        assert binary.content.startswith(b"APEXUDP1")
        data = client.get(f"/api/export?run={rid}&format=parquet")
        assert parquet.read_table(io.BytesIO(data.content)).num_rows >= 24
        client.post("/api/record?enabled=false").raise_for_status()
        assert wait_for(lambda: client.get("/api/state").json()["run"] is None)
        assert wait_for(lambda: not client.get("/api/state").json()["online"])
        assert "停止中" in client.post("/api/ask", json={"text": "前の車との差は？"}).json()["text"]


def test_access_key_for_http_and_ws(tmp_path):
    settings = Settings(udp_host="127.0.0.1", udp_port=0, key="unique-test-key")
    with TestClient(create_app(settings, tmp_path / "secure.sqlite3")) as client:
        assert client.get("/api/runs").status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
        assert client.post("/api/login", json={"key": settings.key}).status_code == 204
        assert client.get("/api/runs").status_code == 200
        assert client.post("/api/record?enabled=false", headers={"Origin": "https://example.invalid"}).status_code == 401
        with client.websocket_connect("/ws", headers={"Origin": "http://testserver"}) as ws:
            assert ws.receive_json() is not None
