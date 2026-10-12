"""Offline optional symbolic CLI, with explicit certificate status/exit codes."""

import argparse
import json
from pathlib import Path

from ..model import GLModel, ModelError, load_json, model_from_dict
from .circuit import Circuit
from .cudd import Diagram


def load(path):
    data = load_json(path)
    if type(data) is not dict:
        raise ModelError("symbolic artifact must be a JSON object")
    if data.get("schema") == "faultgraph-aig-1":
        return Circuit.from_dict(data)
    if data.get("schema") == "faultgraph-decision-1":
        if (
            set(data) != {"schema", "n", "root", "nodes"}
            or type(data["nodes"]) is not list
            or any(type(v) is not list for v in data["nodes"])
        ):
            raise ModelError("invalid decision diagram schema")
        return Diagram(data["n"], tuple(tuple(v) for v in data["nodes"]), data["root"])
    return model_from_dict(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("model")
    compile_parser.add_argument(
        "--backend",
        choices=("cudd-fixed", "cudd-sift", "block-fixed", "block-sift", "abc-mono", "abc-block"),
        default="block-sift",
    )
    compile_parser.add_argument("--output", required=True)
    compile_parser.add_argument("--abc")
    compile_parser.add_argument("--timeout-ms", type=int, default=30000)
    compare = sub.add_parser("equivalent")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.add_argument("--timeout-ms", type=int, default=30000)
    compare.add_argument("--smt-output")
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("artifact")
    evaluate.add_argument("--state", required=True)
    probability = sub.add_parser("reliability")
    probability.add_argument("artifact")
    probability.add_argument("--probabilities", required=True)
    probability.add_argument("--common-cause", type=float, default=0.0)
    study = sub.add_parser("study")
    study.add_argument("--manifest", required=True)
    study.add_argument("--output", required=True)
    study.add_argument("--abc", required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--manifest", required=True)
    worker.add_argument("--output", required=True)
    worker.add_argument("--abc", required=True)
    worker.add_argument("--case", type=int, required=True)
    worker.add_argument("--arm", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--study", required=True)
    args = parser.parse_args()
    code = 0
    if args.command == "worker":
        from .study import dump, worker

        path = Path(args.manifest)
        manifest = json.loads(path.read_text())
        cases = json.loads((path.parent / "cases.json").read_text())
        if not 0 <= args.case < len(cases):
            raise ModelError("case index outside manifest")
        spec = cases[args.case]
        try:
            result = worker(spec, manifest, args.arm, args.output, args.abc)
        except (TimeoutError, MemoryError, ModelError) as error:
            result = {
                "case": spec["id"],
                "family": spec["family"],
                "policy": spec["policy"],
                "seed": spec["seed"],
                "n": spec["n"],
                "arm": args.arm,
                "status": "TIMEOUT"
                if isinstance(error, TimeoutError)
                else "RESOURCE_OR_MODEL_ERROR",
                "error": str(error),
            }
            Path(args.output).mkdir(parents=True, exist_ok=True)
            dump(Path(args.output) / "result.json", result)
        code = int(result["status"] != "COMPLETE")
        result = {k: result[k] for k in ("case", "arm", "status")}
    elif args.command == "study":
        from .study import run

        result = run(args.manifest, args.output, args.abc)
        code = int(result["failures"] > 0)
    elif args.command == "analyze":
        from .study import analyze

        result = analyze(args.study)
        code = 0 if result["complete"] else 3
    elif args.command == "evaluate":
        from ..evaluator import operational

        artifact = load(args.artifact)
        result = {
            "operational": operational(artifact, args.state)
            if isinstance(artifact, GLModel)
            else artifact.evaluate(args.state)
        }
    elif args.command == "reliability":
        artifact = load(args.artifact)
        if not isinstance(artifact, Diagram) or not 0 <= args.common_cause <= 1:
            raise ModelError("requires a decision diagram and common-cause probability in[0,1]")
        ps = load_json(args.probabilities)
        independent = artifact.reliability(ps)
        result = {
            "independent": independent,
            "common_cause_q": args.common_cause,
            "correlated": (1 - args.common_cause) * independent
            + args.common_cause * artifact.evaluate((0,) * artifact.n),
            "law": "all processors failed with q; original independent processor law otherwise; no independence of derived edges assumed",
        }
    else:
        from .equivalence import check

        if args.command == "compile":
            from . import abc
            from .compile import connectivity_circuit
            from .cudd import Compiled
            from .study import deadline

            original = load(args.model)
            if not isinstance(original, GLModel):
                raise ModelError("compile expects an original GL model")
            output = Path(args.output)
            paths = [
                output,
                Path(str(output) + ".certificate.json"),
                Path(str(output) + ".smt2"),
                Path(str(output) + ".candidate.json"),
            ]
            if any(p.exists() for p in paths):
                raise ModelError("new output path required")
            with deadline(30):
                circuit = connectivity_circuit(
                    original, factor=args.backend.startswith("block") or args.backend == "abc-block"
                )
                if args.backend.startswith("abc"):
                    if not args.abc:
                        raise ModelError("ABC backend requires --abc path")
                    artifact, _ = abc.synthesize(circuit, args.abc, str(output) + ".abc")
                else:
                    artifact = Compiled(circuit, reorder=args.backend.endswith("sift")).diagram
            candidate = artifact.circuit() if isinstance(artifact, Diagram) else artifact
            result = check(original, candidate, timeout_ms=args.timeout_ms, smt_path=paths[2])
            target = output if result["status"] == "UNSAT_FINITE_EQUIVALENCE" else paths[3]
            target.write_text(json.dumps(artifact.to_dict(), indent=2) + "\n")
            paths[1].write_text(json.dumps(result, indent=2) + "\n")
        else:
            a, b = load(args.left), load(args.right)
            if args.smt_output and Path(args.smt_output).exists():
                raise ModelError("new SMT output path required")
            result = check(
                a.circuit() if isinstance(a, Diagram) else a,
                b.circuit() if isinstance(b, Diagram) else b,
                timeout_ms=args.timeout_ms,
                smt_path=args.smt_output,
            )
        code = (
            0
            if result["status"] == "UNSAT_FINITE_EQUIVALENCE"
            else 1
            if result["status"] == "COUNTEREXAMPLE"
            else 3
        )
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TimeoutError as error:
        print(json.dumps({"status": "TIMEOUT", "error": str(error)}))
        raise SystemExit(3) from error
    except (ValueError, OSError, ImportError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}))
        raise SystemExit(2) from error
