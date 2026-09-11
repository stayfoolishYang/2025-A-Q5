"""Direct core invocation for local batch research; omits HTTP/session bookkeeping."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import Engine
from scenario_io import generate_document, load_scenario


def make_engine(seed_hex, problem=4):
    scene = generate_document(seed_hex=seed_hex, problem=problem)
    return Engine(load_scenario(scene))


if __name__ == "__main__":
    engine = make_engine(bytes(range(32)).hex())
    actions = [("/enter", {}),
               ("/measure", {"position": {"x": 300, "y": 400}, "channel": 1}),
               ("/clear", {"position": {"x": 300, "y": 400}, "channel": 1}),
               ("/exit", {})]
    for path, body in actions:
        print(json.dumps({"path": path, **engine.apply(path, body)}, ensure_ascii=False))
