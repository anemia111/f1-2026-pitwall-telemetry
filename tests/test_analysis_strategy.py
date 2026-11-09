from pytest import approx

from pitwall.analysis import compare
from pitwall.engineer import Engineer, answer
from pitwall.strategy import Assumptions, forecast


def test_interpolation_and_missing_segment():
    def point(d, ms, gear=4):
        return {"d": d, "ms": ms, "speed": 200, "throttle": 1., "brake": 0., "steer": 0.,
                "gear": gear, "engineRPM": 11000}
    current = [point(0, 0), point(10, 220, 5), point(20, 440, 6), point(120, 3500)]
    baseline = [point(0, 0), point(10, 200), point(20, 400), point(120, 3100)]
    result = compare(current, baseline)
    assert result["points"][1]["delta"] == approx(.01)
    assert result["points"][1]["a"]["gear"] == 4
    assert result["points"][8]["delta"] is None


def scenario(safety=0, online=True):
    car = {"id": 0, "lap": {"currentLapNum": 6, "carPosition": 4, "resultStatus": 2, "frontGap": 1350,
                            "currentLapTimeInMS": 20000},
           "status": {"visualTyreCompound": 17, "actualTyreCompound": 18, "tyresAgeLaps": 5},
           "damage": {"tyresWear": [20, 21, 20, 20]}}
    s = {"online": online, "ended": False, "red": False, "cars": [car], "player": 0, "clock": 4,
         "session": {"sessionType": 15, "totalLaps": 18, "safetyCarStatus": safety, "weather": 0,
                     "pitStopWindowIdealLap": 8}}
    observed = {0: {i: {"lap": i, "age": i-1, "tyre": 17, "ms": 89000+i*300, "valid": True,
                         "wear": [i*4]*4} for i in range(1, 6)}}
    sets = [{"available": 1, "fitted": 0, "wear": 0, "visualTyreCompound": 17, "actualTyreCompound": 18}]
    return s, observed, sets


def test_model_requires_evidence_and_reacts_to_safety_car():
    s, observed, sets = scenario()
    model = forecast(s, observed, sets, Assumptions())
    assert [p["pitLap"] for p in model["plans"]] == [8, 6, 10]
    assert model["model"]["wearRate"] == approx(4)
    assert model["model"]["degradation"] == approx(.3)
    assert model == forecast(s, observed, sets, Assumptions())
    neutral, *_ = scenario(safety=1)
    sc = forecast(neutral, observed, sets, Assumptions())
    assert sc["plans"][1]["pitLoss"] == 12
    assert sc["plans"][1]["remainingTime"] < model["plans"][1]["remainingTime"]
    assert forecast(s, {}, sets, Assumptions())["recommended"] is None
    assert forecast(s, observed, [], Assumptions())["recommended"] is None


def test_radio_priority_and_stale_data():
    s, observed, sets = scenario()
    e = Engineer()
    flag = {"code": "SCAR", "details": {"eventType": 0, "safetyCarType": 1}}
    assert e.update(s, observed, sets, Assumptions(), flag, now=5)[0]["priority"] == "CRITICAL"
    assert all(x["topic"] != "flag-セーフティカー" for x in e.update(s, observed, sets, Assumptions(), flag, now=6))
    s["online"] = False
    assert not e.update(s, observed, sets, Assumptions(), flag, now=25)
    assert "停止中" in answer("gap", s, e.strategy)
