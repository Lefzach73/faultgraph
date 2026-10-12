"""Research CLI; outputs always go to explicitly supplied new directories."""

import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    w = sub.add_parser("worker")
    w.add_argument("--manifest", required=True)
    w.add_argument("--case", type=int, required=True)
    w.add_argument("--arm", required=True)
    s = sub.add_parser("study")
    s.add_argument("--manifest", required=True)
    s.add_argument("--output", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("--study", required=True)
    a = sub.add_parser("source-audit")
    a.add_argument("--output", required=True)
    args = p.parse_args()
    if args.command == "source-audit":
        from .source_audit import run

        result = run(args.output)
    elif args.command == "analyze":
        from .study import analyze

        result = analyze(args.study)
    else:
        from .study import run, worker

        if args.command == "study":
            result = run(args.manifest, args.output)
        else:
            path = Path(args.manifest)
            manifest = json.loads(path.read_text())
            cases = json.loads((path.parent / "cases.json").read_text())
            spec = cases[args.case]
            try:
                result = worker(spec, manifest, args.arm)
            except TimeoutError as error:
                result = {
                    "case": spec["id"],
                    "family": spec["family"],
                    "n": spec["n"],
                    "seed": spec["seed"],
                    "arm": args.arm,
                    "status": "TIMEOUT",
                    "error": str(error),
                }
    print(json.dumps(result, indent=2))
    if args.command == "study":
        return int(result["failures"] > 0)
    if args.command == "source-audit":
        if result["hait9_mismatches"] or not result["hait9_metric_matches"]:
            return 1
        if result["aait27"]["status"] != "UNSAT_FINITE_EQUIVALENCE":
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
