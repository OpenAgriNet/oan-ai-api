import argparse
import json
from pathlib import Path
from typing import List

from app.telemetry.events import SessionEvent
from app.telemetry.validator import validate_event_sequence


def load_events(path: Path) -> List[SessionEvent]:
    events: List[SessionEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if "training_event=" in line:
            line = line.split("training_event=", 1)[1].strip()
        events.append(SessionEvent.model_validate(json.loads(line)))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate OAN training telemetry events")
    parser.add_argument("--input", required=True, help="Path to JSONL or extracted log lines")
    args = parser.parse_args()

    events = load_events(Path(args.input))
    errors = validate_event_sequence(events)
    if errors:
        print("Validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print(f"Validation passed: {len(events)} events checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
