"""Small deterministic regression set. Not a production quality benchmark."""
import json
import os
import platform
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from assistant.pipeline import ROOT, build, read_jsonl
from assistant.engine import Engine


def run():
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"DEMO_ENABLE_LLM": "0"}):
        path = Path(folder) / "eval.sqlite"
        build(target=path)
        engine = Engine(path)
        results = []
        for case in read_jsonl(ROOT / "data/eval.jsonl"):
            actual = engine.ask(case)
            ok = actual["route"] == case["route"] and actual["mode"] == case["mode"]
            ids = [s["id"] for s in actual["sources"]]
            if case["source"]:
                ok = ok and case["source"] in ids
            results.append({"id": case["id"], "pass": ok, "route": actual["route"], "mode": actual["mode"], "sources": ids})
    report = {"dataset": "handwritten synthetic regression cases; not held-out campus data", "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
              "random_seed": "not applicable: no randomized baseline", "model_calls": 0, "vectors": False,
              "passed": sum(r["pass"] for r in results), "total": len(results), "cases": results}
    return report


if __name__ == "__main__":
    report = run()
    out = ROOT / "build" / "evaluation.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
