"""Offline CLI with structured outputs and nonzero failed-check exit codes."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, transform
from .equivalence import check_functions, check_models
from .evaluator import active_edges, conditioned_operational, operational
from .expr import ExpressionError
from .metrics import model_metrics
from .model import ConditionedModel, ModelError, load_conditioned, load_json, load_model, save_model
from .reliability import common_cause_exact, exact, monte_carlo


def main(argv=None):
    parser = argparse.ArgumentParser(description="FaultGraph Lab — finite static GL research")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate")
    p.add_argument("model")
    p = sub.add_parser("evaluate")
    p.add_argument("model")
    p.add_argument("--state", required=True)
    p = sub.add_parser("prove-equivalence")
    p.add_argument("left")
    p.add_argument("right")
    p = sub.add_parser("reliability")
    p.add_argument("model")
    p.add_argument("--probabilities", required=True)
    p.add_argument("--samples", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--common-cause", type=float, default=0.0)
    p = sub.add_parser("transform")
    p.add_argument("model")
    p.add_argument("--operation", choices=["T0", "T1", "T2", "T3"], required=True)
    p.add_argument("--u")
    p.add_argument("--v")
    p.add_argument("--edge")
    p.add_argument("--new-edge", default="new-edge")
    p.add_argument("--vertex", default="new-vertex")
    p.add_argument("--moved", nargs="*", default=[])
    p.add_argument("--output", required=True)
    p = sub.add_parser("reproduce-paper")
    p.add_argument("--root", default=".")
    p.add_argument("--spec")
    p.add_argument("--output", default="artifacts/reproduction/paper8")
    p = sub.add_parser("reproduce-donors")
    p.add_argument("--output", default="artifacts/reproduction/donors")
    p.add_argument("--include-recipients", action="store_true")
    p = sub.add_parser("optimize")
    p.add_argument("model")
    p.add_argument("--budget", type=int, default=32)
    p.add_argument("--output", required=True)
    p = sub.add_parser("compose")
    p.add_argument("conditioned")
    p.add_argument("--method", choices=["aligned", "auto", "wedge"], default="auto")
    p.add_argument("--output", required=True)
    p = sub.add_parser("bench")
    p.add_argument("--manifest", default="experiments/study_v1.json")
    p.add_argument("--output", default="artifacts/studies/study-v1")
    p = sub.add_parser("report")
    p.add_argument("--study", default="artifacts/studies/study-v1")
    p = sub.add_parser("export-dot")
    p.add_argument("model")
    p.add_argument("--state")
    p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command in (
            "validate",
            "evaluate",
            "reliability",
            "transform",
            "export-dot",
            "optimize",
        ):
            m = load_model(args.model)
        if args.command == "validate":
            result = {"status": "VALID", "model_hash": m.digest, "metrics": model_metrics(m)}
        elif args.command == "evaluate":
            result = {
                "state": args.state,
                "operational": operational(m, args.state),
                "vertices": list(m.vertices),
                "active_edges": [e.id for e in active_edges(m, args.state)],
            }
        elif args.command == "prove-equivalence":
            result = check_models(load_model(args.left), load_model(args.right)).to_dict()
            code = (
                0
                if result["status"] == "EXHAUSTIVE_PASS"
                else 1
                if result["status"] == "COUNTEREXAMPLE"
                else 3
            )
        elif args.command == "reliability":
            ps = load_json(args.probabilities)

            def indicator(s):
                return operational(m, s)

            value = (
                common_cause_exact(m.num_processors, indicator, ps, args.common_cause)
                if args.common_cause
                else exact(m.num_processors, indicator, ps)
            )
            result = {
                "exact": value,
                "monte_carlo": monte_carlo(
                    m.num_processors, indicator, ps, args.samples, args.seed, args.common_cause
                ).to_dict(),
                "probability_semantics": "P(processor works)",
                "model": "static",
            }
        elif args.command == "transform":
            if args.operation == "T0":
                t = transform.zero_edge(m, args.u, args.v, args.new_edge)
            elif args.operation == "T1":
                t = transform.split_vertex(m, args.u, args.vertex, args.moved, args.new_edge)
            elif args.operation == "T2":
                t = transform.add_leaf(m, args.u, args.vertex, args.new_edge)
            else:
                t = transform.subdivide(m, args.edge, args.vertex, args.new_edge)
            check = check_models(m, t.model).to_dict()
            if check["status"] != "EXHAUSTIVE_PASS":
                result, code = check, 3
            else:
                save_model(t.model, args.output)
                result = {**t.record, "check_status": check["status"], "certificate": check}
                Path(args.output + ".lineage.json").write_text(json.dumps(result, indent=2) + "\n")
        elif args.command == "reproduce-paper":
            from .paper import reproduce

            result = reproduce(args.root, args.output, args.spec)
            code = int(result["mismatch_count"] > 0 or bool(result["metric_discrepancies"]))
        elif args.command == "reproduce-donors":
            from .subsystems import reproduce_donors, reproduce_recipients

            result = reproduce_donors(args.output)
            code = int(result["mismatches"] > 0)
            if args.include_recipients:
                result["recipients"] = reproduce_recipients(args.output)
                code = max(code, int(result["recipients"]["mismatches"] > 0))
        elif args.command == "optimize":
            from .optimize import optimize

            r = optimize(m, args.budget)
            candidate = r.pop("model")
            result = r
            if r["status"] == "EXHAUSTIVE_PASS":
                save_model(candidate, args.output)
                Path(args.output + ".lineage.json").write_text(json.dumps(r, indent=2) + "\n")
            else:
                code = 3
        elif args.command == "compose":
            cm = load_conditioned(args.conditioned)
            records = []
            if args.method == "auto":
                aligned = transform.align_models(cm.models)
                for original, t in zip(cm.models, aligned, strict=True):
                    certificate = check_models(original, t.model).to_dict()
                    if certificate["status"] != "EXHAUSTIVE_PASS":
                        raise ModelError("auxiliary alignment failed finite equivalence")
                    records.append({**t.record, "certificate": certificate})
                combined = transform.combine_aligned(
                    ConditionedModel(cm.selectors, tuple(t.model for t in aligned))
                ).model
            elif args.method == "aligned":
                combined = transform.combine_aligned(cm).model
            else:
                combined = transform.combine_wedge(cm)
            certificate = check_functions(
                combined.num_processors,
                lambda s: operational(combined, s),
                lambda s: conditioned_operational(cm, s),
            ).to_dict()
            result = {
                "certificate": certificate,
                "model_hash": combined.digest,
                "alignment": records,
            }
            code = 0 if certificate["status"] == "EXHAUSTIVE_PASS" else 1
            if code == 0:
                save_model(combined, args.output)
                Path(args.output + ".lineage.json").write_text(json.dumps(result, indent=2) + "\n")
        elif args.command == "bench":
            from .experiments import run_study

            result = run_study(args.manifest, args.output)
            code = int(result["failure_count"] > 0)
        elif args.command == "report":
            from .experiments import report

            result = report(args.study)
        else:
            from .visualize import to_dot

            Path(args.output).write_text(to_dot(m, args.state))
            result = {"output": args.output}
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        RecursionError,
        ModelError,
        ExpressionError,
    ) as e:
        print(json.dumps({"status": "ERROR", "message": str(e)}), file=sys.stderr)
        return 2
