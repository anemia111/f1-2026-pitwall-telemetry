"""Synthetic 24-car UDP generator. Send only to the demo listener by default."""
import argparse
import asyncio
from math import cos, pi, sin
import socket
from time import monotonic, time_ns

from .protocol_2026 import HEADER, MAX_CARS, PACKETS, layout


class Builder:
    def __init__(self, kind: int, frame: int, game_time: float, uid: int):
        _, self.name, size = PACKETS[kind]
        self.data = bytearray(size)
        HEADER.pack_into(self.data, 0, 2026, 25, 1, 25, 1, kind, uid, game_time, frame, frame, 0, 255)

    def write(self, values: dict, structure: str | None = None, offset: int = 0) -> None:
        fields = layout(structure or self.name)[1]
        for key, value in values.items():
            f = fields[key]
            if f.codec is None:
                raise ValueError(key)
            if f.kind == "char":
                f.codec.pack_into(self.data, offset + f.offset, value.encode("utf8"))
            else:
                f.codec.pack_into(self.data, offset + f.offset, *(value if f.dims else [value]))

    def row(self, field: str, i: int, **values) -> None:
        f = layout(self.name)[1][field]
        self.write(values, f.kind, f.offset + i * f.unit)


TRACK = 5080
TOTAL = 18


def demo_packets(frame: int, game_time: float, uid: int, rate: int) -> list[bytes]:
    def new(kind: int) -> Builder:
        return Builder(kind, frame, game_time, uid)
    motion, laps, telemetry, status, aero = (new(k) for k in (0, 2, 6, 7, 16))
    detail = frame % max(1, rate // 10) == 0
    damage = new(10) if detail else None
    finished = game_time >= (89.5 + 20 * .045 + .16 * (TOTAL - 1)) * TOTAL + 23 * 1.15
    lap_result = 3 if finished else 2
    final = new(8) if finished and frame % rate == 0 else None
    if final:
        final.write({"numCars": MAX_CARS})
    for i in range(MAX_CARS):
        # Player runs P4. The synthetic fleet shares one simulated route.
        position = 4 if i == 0 else i if i <= 3 else i + 1
        gaps = (position - 1) * 1.15
        adjusted = max(0, game_time - gaps)
        average = 89.5 + (position - 4) * .045
        # Solve elapsed = base * laps + .16 * laps * (laps - 1).
        k = max(0, int((-(average - .16) + ((average - .16)**2 + .64 * adjusted)**.5) / .32))
        lap_time = average + .32 * k
        lap_elapsed = max(0., adjusted - k * (average + .16 * (k - 1)))
        distance = min(TRACK - .1, TRACK * lap_elapsed / lap_time)
        a = 2 * pi * distance / TRACK
        phase = (distance + (k % 3) * 7) % 890
        corner = max(0, 1 - abs(phase - 680) / 175)
        brake = max(0, 1 - abs(phase - 611) / 70) * .85
        speed = round(317 - 170 * corner - 16 * max(0., sin(a * 4)))
        throttle = max(.08, 1 - 1.08 * corner - .4 * brake)
        x = 510 * cos(a) + 126 * cos(3 * a) - 45 * sin(5 * a)
        z = 390 * sin(a) + 95 * sin(2 * a) + 48 * cos(4 * a)
        motion.row("carMotionData", i, worldPositionX=x, worldPositionY=5 * sin(a), worldPositionZ=z)
        laps.row("lapData", i, lastLapTimeInMS=round((lap_time - .32) * 1000) if k else 0,
                 currentLapTimeInMS=round(lap_elapsed * 1000), sector1TimeMSPart=round(lap_time * 325) if distance >= 1651 else 0,
                 sector2TimeMSPart=round(lap_time * 325) if distance >= 3302 else 0,
                 deltaToCarInFrontMSPart=1150 if position > 1 and game_time > 28 else 0,
                 deltaToRaceLeaderMSPart=round(gaps * 1000) if game_time > 28 else 0, lapDistance=distance,
                 totalDistance=k * TRACK + distance, carPosition=position, currentLapNum=min(TOTAL, k + 1),
                 sector=min(2, int(distance // 1651)), gridPosition=position, driverStatus=4, resultStatus=lap_result)
        telemetry.row("carTelemetryData", i, speed=speed, throttle=throttle, brake=brake,
                      steer=.55 * corner * sin(a * 2), gear=max(2, min(8, speed // 42)), engineRPM=8800 + speed * 8,
                      brakesTemperature=[round(500 + 430 * brake)] * 4,
                      tyresSurfaceTemperature=[91 + round(corner * 12) + j for j in range(4)],
                      tyresInnerTemperature=[91 + j for j in range(4)], engineTemperature=112,
                      tyresPressure=[23.2, 23.3, 24.0, 24.1])
        status.row("carStatusData", i, fuelInTank=max(1, 57 - 2.7 * k - 2.7 * distance / TRACK), fuelCapacity=110,
                   fuelRemainingLaps=max(1, 20 - k), actualTyreCompound=18, visualTyreCompound=17, tyresAgeLaps=k,
                   enginePowerICE=speed * 1120, enginePowerMGUK=180000 * throttle, ersStoreEnergy=3100000 - distance * 270,
                   ersDeployMode=1, ersHarvestedThisLapMGUK=distance * 190, ersDeployedThisLap=distance * 235)
        aero.row("carTelemetry2Data", i, activeAeroMode=int(corner < .05), activeAeroAvailable=int(corner < .12),
                 activeAeroActivationDistance=round(900 - phase) if corner >= .12 else 0,
                 overtakeAvailable=int(i % 4 == 0), overtakeActive=int(i % 4 == 0 and throttle > .98 and phase < 180),
                 **{"2026Regulations": 1})
        if damage:
            damage.row("carDamageData", i, tyresWear=[min(98, 4.7 * (k + distance / TRACK) + j * .4) for j in range(4)])
        if final:
            final.row("classificationData", i, position=position, numLaps=TOTAL, gridPosition=position, resultStatus=3,
                      bestLapTimeInMS=round(average * 1000), totalRaceTime=TOTAL * (average + .16 * (TOTAL - 1)))
    builders = [motion, laps, telemetry, status, aero]
    if damage:
        builders.append(damage)
    if final:
        builders.append(final)
    sc = int(7 * 89.5 <= game_time < 7.5 * 89.5)
    if frame % max(1, rate // 2) == 0:
        session = new(1)
        session.write({"weather": 0, "trackTemperature": 35, "airTemperature": 26, "totalLaps": TOTAL,
                       "trackLength": TRACK, "sessionType": 15, "trackId": -1, "formula": 13, "pitSpeedLimit": 80,
                       "safetyCarStatus": sc, "pitStopWindowIdealLap": 10, "pitStopWindowLatestLap": 13,
                       "pitStopRejoinPosition": 18, "sector2LapDistanceStart": 1651., "sector3LapDistanceStart": 3302.,
                       "numActiveAeroZonesFull": 2})
        session.row("activeAeroZonesFull", 0, zoneStart=.05, zoneEnd=.22)
        session.row("activeAeroZonesFull", 1, zoneStart=.71, zoneEnd=.84)
        builders.append(session)
    if frame % rate == 0:
        sets = new(12)
        sets.row("tyreSetData", 0, actualTyreCompound=18, visualTyreCompound=17, wear=0, available=1)
        sets.row("tyreSetData", 1, actualTyreCompound=19, visualTyreCompound=18, wear=0, available=1)
        builders.append(sets)
    if frame % (rate * 5) == 0:
        p = new(4)
        p.write({"numActiveCars": MAX_CARS})
        for i in range(MAX_CARS):
            p.row("participants", i, aiControlled=int(i != 0), driverId=65535, teamId=476 + (i // 2) % 11,
                  raceNumber=i + 1, name="DEMO / 裕樹" if i == 0 else f"Demo Driver {i + 1:02}", yourTelemetry=1)
        builders.append(p)
    crossed_sc = game_time >= 7 * 89.5 > game_time - 8 / rate
    left_sc = game_time >= 7.5 * 89.5 > game_time - 8 / rate
    if frame == 0 or crossed_sc or left_sc:
        event = new(3)
        code = b"SSTA" if frame == 0 else b"SCAR"
        event.write({"eventStringCode": list(code)})
        if code == b"SCAR":
            event.write({"safetyCarType": 1, "eventType": 0 if crossed_sc else 2}, "EventSafetyCar", 33)
        builders.append(event)
    return [bytes(builder.data) for builder in builders]


async def transmit(port: int, *, rate: int = 30, host: str = "127.0.0.1") -> None:
    uid = time_ns()
    frame = 0
    deadline = monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        while True:
            game_time = frame * 8 / rate
            for data in demo_packets(frame, game_time, uid, rate):
                sock.sendto(data, (host, port))
            frame += 1
            deadline += 1 / rate
            delay = deadline - monotonic()
            if delay < -1:
                deadline = monotonic()
            await asyncio.sleep(max(0, delay))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--port", type=int, default=20778)
    cli.add_argument("--hz", type=int, choices=[10, 20, 30, 60], default=60)
    cli.add_argument("--host", default="127.0.0.1")
    options = cli.parse_args()
    try:
        asyncio.run(transmit(options.port, host=options.host, rate=options.hz))
    except KeyboardInterrupt:
        pass
