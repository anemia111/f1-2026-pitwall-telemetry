"""Review saved forecasts alongside observed pit laps and classification."""
import argparse
import json
from pathlib import Path
from statistics import mean

from pitwall.storage import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("run")
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit("database not found")
    store = Store(args.database)
    try:
        if not store.exists(args.run):
            raise SystemExit("session not found")
        evaluated = [row for row in store.outcomes(args.run) if row.get("outcome")]
        errors = [d["outcome"]["finishDifferenceS"] for d in evaluated if d["outcome"]["finishDifferenceS"] is not None]
        print(json.dumps({"predictions": len(evaluated), "comparableFinishPredictions": len(errors),
                          "meanAbsoluteErrorS": mean(map(abs, errors)) if errors else None,
                          "entries": evaluated}, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
