"""Single-process local FastAPI entry point."""
import argparse
import asyncio
import hmac
import io
import json
import logging
import os
import socket
from contextlib import asynccontextmanager, suppress
from ipaddress import IPv4Address, ip_address
from pathlib import Path
from time import monotonic
from typing import Annotated, Literal

import httpx
import qrcode
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .analysis import compare
from .engineer import TOPICS, answer, identify
from .service import Receiver, Settings
from .storage import Store, csv_stream, parquet_export
from .strategy import Assumptions, forecast

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEB = ROOT / "web" / "dist"
LOG = logging.getLogger(__name__)
Run = Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")]
Car = Annotated[int, Query(ge=0, lt=24)]
Epoch = Annotated[int, Query(ge=0)]
Lap = Annotated[int, Query(ge=1, le=255)]
Until = Annotated[float, Query(ge=0, le=1e12)]


class Key(BaseModel):
    key: str = Field(max_length=256)


class Question(BaseModel):
    text: str = Field(min_length=1, max_length=240)


class Configuration(BaseModel):
    pit_loss: float = Field(ge=0, le=180)
    sc_loss: float = Field(ge=0, le=180)
    vsc_loss: float = Field(ge=0, le=180)
    wear_limit: float = Field(ge=1, le=100)


class Selection(BaseModel):
    plan: Literal["A", "B", "C"]


def addresses() -> list[str]:
    result = set()
    with suppress(OSError):
        for item in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = ip_address(item[4][0])
            if ip.is_private and not ip.is_loopback and not ip.is_link_local:
                result.add(str(ip))
    return sorted(result)


def create_app(settings: Settings, path: Path, web: Path = DEFAULT_WEB, *, demo_rate: int = 0) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(path)
        receiver = Receiver(store, settings)
        app.state.receiver = receiver
        loop = asyncio.get_running_loop()
        tasks = []
        transport = None
        try:
            transport, _ = await loop.create_datagram_endpoint(lambda: receiver,
                           local_addr=(settings.udp_host, settings.udp_port), family=socket.AF_INET)
            tasks.append(asyncio.create_task(receiver.loop()))
            if demo_rate:
                from .demo import transmit
                tasks.append(asyncio.create_task(transmit(settings.udp_port, rate=demo_rate)))
            for task in tasks:
                task.add_done_callback(log_task)
            yield
        finally:
            if transport:
                transport.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(store.close)

    app = FastAPI(title="APEX PIT WALL", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    llm_lock = asyncio.Lock()

    def local(request: Request | WebSocket) -> bool:
        # TestClient supplies a non-IP client; production connections always use a socket IP.
        if not request.client:
            return False
        try:
            return ip_address(request.client.host).is_loopback
        except ValueError:
            return request.client.host == "testclient"

    def same_origin(request: Request | WebSocket) -> bool:
        origin = request.headers.get("origin")
        return not origin or origin == f"{'https' if request.url.scheme in ('https', 'wss') else 'http'}://{request.headers.get('host')}"

    def allowed(request: Request | WebSocket) -> bool:
        if not same_origin(request):
            return False
        if settings.key:
            return hmac.compare_digest(request.cookies.get("apex_access", "").encode(), settings.key.encode())
        host = request.url.hostname
        return local(request) and host in ("127.0.0.1", "localhost", "::1", "testserver")

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.url.path != "/api/login" and not allowed(request):
            return Response(status_code=401, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        if not request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.post("/api/login")
    async def login(request: Request, body: Key):
        if not same_origin(request) or not settings.key or not hmac.compare_digest(body.key.encode(), settings.key.encode()):
            await asyncio.sleep(.35)
            raise HTTPException(401, "アクセスキーが一致しません。")
        response = Response(status_code=204)
        response.set_cookie("apex_access", body.key, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    def engine() -> Receiver:
        return app.state.receiver

    def archive(run: str) -> Store:
        store = engine().store
        if not store.exists(run):
            raise HTTPException(404, "セッションが見つかりません。")
        return store

    @app.get("/api/state")
    async def live():
        return Response(engine().serialized, media_type="application/json")

    @app.get("/api/network")
    async def network(request: Request):
        r = engine()
        return {"addresses": addresses(), "httpPort": request.url.port or 80, "udpPort": settings.udp_port,
                "lan": bool(settings.key), "source": r.settings.mode, "ollama": bool(settings.ollama)}

    @app.get("/api/trace")
    async def trace(car: Car, uid: Annotated[str, Query(pattern=r"^[0-9]{1,20}$")], epoch: Epoch):
        state = engine().state
        if uid != str(state.uid) or epoch != state.epoch:
            return []
        return list(state.traces.get(car, ()))

    @app.get("/api/qr")
    def qr(host: str, port: Annotated[int, Query(ge=1, le=65535)] = 8000):
        if not settings.key or host not in addresses():
            raise HTTPException(404)
        output = io.BytesIO()
        qrcode.make(f"http://{host}:{port}/").save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png")

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        if not allowed(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                await asyncio.wait_for(ws.send_text(engine().serialized), timeout=2)
                try:
                    message = await asyncio.wait_for(ws.receive(), timeout=.1)
                    if message["type"] == "websocket.disconnect":
                        break
                except TimeoutError:
                    pass
        except (WebSocketDisconnect, TimeoutError, OSError):
            return

    @app.post("/api/record")
    async def record(enabled: bool):
        engine().record(enabled)
        return {"recording": enabled}

    @app.post("/api/config")
    async def configure(body: Configuration):
        engine().config = Assumptions(**body.model_dump())
        return body

    @app.post("/api/plan")
    async def select(body: Selection):
        r = engine()
        s = r.state.snapshot()
        current = forecast(s, r.state.observed_laps, r.tyre_sets(monotonic()), r.config)
        plan = next((p for p in current["plans"] if p["id"] == body.plan and p["pitLap"]), None)
        if not plan or not s["run"]:
            raise HTTPException(409, "ライブ戦略または記録がありません。")
        decision = {"topic": "selection", "lap": current["input"]["lap"], "selectedPlan": body.plan,
                    "time": s["clock"], "reason": "ユーザーが手動で選択", "evidence": plan,
                    "confidence": "条件付き推定", "outcome": None}
        if not r.log(decision, monotonic()):
            raise HTTPException(503, "記録の書き込みに失敗しました。")
        return decision

    @app.get("/api/runs")
    def runs():
        return engine().store.runs()

    @app.get("/api/laps")
    def laps(run: Run, car: Car):
        return archive(run).laps(run, car)

    @app.get("/api/samples")
    def samples(run: Run, epoch: Epoch, car: Car, lap: Lap | None = None, until: Until = 1e12,
                limit: Annotated[int, Query(ge=2, le=5000)] = 900):
        return archive(run).samples(run, epoch, car, lap=lap, until=until, limit=limit)

    @app.get("/api/compare")
    def compare_laps(run: Run, a: Car, b: Car, lap_a: Lap, lap_b: Lap, epoch_a: Epoch = 0,
                     epoch_b: Epoch = 0, until: Until = 1e12):
        store = archive(run)
        return compare(store.samples(run, epoch_a, a, lap=lap_a, until=until),
                       store.samples(run, epoch_b, b, lap=lap_b, until=until))

    @app.get("/api/replay")
    def replay(run: Run, t: Until):
        return archive(run).replay(run, t)

    @app.get("/api/events")
    def events(run: Run):
        return archive(run).logs(run, "events")

    @app.get("/api/decisions")
    def decisions(run: Run):
        return archive(run).outcomes(run)

    @app.get("/api/packet")
    async def packet(kind: Annotated[int, Query(ge=0, le=16)], car: Car = 0):
        r = engine()
        raw = r.state.get(kind, monotonic(), car if kind in (11, 12) else -1)
        return raw.decode() if raw else None

    @app.get("/api/export")
    def export(run: Run, format: Literal["csv", "parquet", "udp"]):
        store = archive(run)
        headers = {"Content-Disposition": f'attachment; filename="apex-{run}.{format}"'}
        if format == "parquet":
            path = parquet_export(store, run)
            return FileResponse(path, media_type="application/vnd.apache.parquet", headers=headers,
                                background=BackgroundTask(path.unlink, missing_ok=True))
        if format == "csv":
            return StreamingResponse(csv_stream(store, run), media_type="text/csv", headers=headers)
        # Portable capture: magic, then arrival seconds, epoch, payload size, raw datagram.
        from struct import Struct
        header = Struct("<dIH")
        def records():
            yield b"APEXUDP1"
            for t, epoch, _, _, data in store.raw_rows(run):
                yield header.pack(t, epoch, len(data)) + data
        return StreamingResponse(records(), media_type="application/octet-stream", headers=headers)

    @app.post("/api/ask")
    async def ask(body: Question):
        r = engine()
        topic = identify(body.text)
        metrics = None
        initial = r.state.uid, r.state.epoch
        if not topic and settings.ollama and not llm_lock.locked() and r.snapshot.get("online"):
            start = monotonic()
            async with llm_lock:
                try:
                    async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
                        response = await client.post("http://127.0.0.1:11434/api/chat", json={
                            "model": settings.ollama, "stream": False, "keep_alive": "2m",
                            "format": {"type": "object", "properties": {"topic": {"enum": [*TOPICS, "unknown"]}},
                                       "required": ["topic"]},
                            "messages": [{"role": "system", "content": "Classify the driver's request by topic. Return only the schema."},
                                         {"role": "user", "content": body.text}],
                        })
                        response.raise_for_status()
                        payload = response.json()
                        candidate = json.loads(payload["message"]["content"]).get("topic")
                        if candidate in TOPICS:
                            topic = candidate
                        metrics = {"wallMs": round((monotonic() - start) * 1000), "loadNs": payload.get("load_duration"),
                                   "evaluationNs": payload.get("eval_duration"), "tokens": payload.get("eval_count")}
                except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                    metrics = {"wallMs": round((monotonic() - start) * 1000), "fallback": True}
        snap = r.state.snapshot()
        if initial != (r.state.uid, r.state.epoch):
            return {"text": "セッションが切り替わりました。もう一度質問してください。", "llm": metrics}
        strategy = forecast(snap, r.state.observed_laps, r.tyre_sets(monotonic()), r.config)
        return {"text": answer(topic, snap, strategy, body.text, r.coaching), "llm": metrics}

    if (web / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    @app.get("/")
    async def index():
        file = web / "index.html"
        return FileResponse(file) if file.is_file() else HTMLResponse(
            "<h1>APEX PIT WALL</h1><p>Run npm ci and npm run build before opening the dashboard.</p>", status_code=503)

    return app


def log_task(task: asyncio.Task) -> None:
    if not task.cancelled() and (error := task.exception()):
        LOG.error("Background task stopped", exc_info=error)


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="APEX PIT WALL")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--demo-listen-only", action="store_true", help="Use an external synthetic UDP sender")
    parser.add_argument("--lan", action="store_true")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--udp-port", type=int)
    parser.add_argument("--demo-rate", type=int, choices=[10, 20, 30, 60], default=30)
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "pitwall.sqlite3")
    parser.add_argument("--web", type=Path, default=DEFAULT_WEB)
    args = parser.parse_args()
    if args.demo_listen_only and not args.demo:
        parser.error("--demo-listen-only requires --demo")
    key = os.getenv("APEX_ACCESS_KEY", "") if args.lan else ""
    if args.lan and (len(key) < 12 or len(key) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        parser.error("LAN mode requires APEX_ACCESS_KEY (12–256 printable ASCII characters without spaces)")
    ps5 = os.getenv("APEX_PS5_IP", "") if not args.demo else "127.0.0.1"
    if ps5:
        try:
            IPv4Address(ps5)
        except ValueError:
            parser.error("APEX_PS5_IP must be an IPv4 address")
    settings = Settings("DEMO" if args.demo else "LIVE", "127.0.0.1" if args.demo else "0.0.0.0",
                        args.udp_port or (20778 if args.demo else 20777), ps5, key, os.getenv("APEX_OLLAMA_MODEL", ""))
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(settings, args.data, args.web,
                           demo_rate=args.demo_rate if args.demo and not args.demo_listen_only else 0),
                host="0.0.0.0" if args.lan else "127.0.0.1", port=args.http_port,
                proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
