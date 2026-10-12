"""Strict validated simple undirected GL models; persistent nonempty vertices."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import product
from pathlib import Path
from types import MappingProxyType

from .expr import Expr, parse_expr


class ModelError(ValueError):
    pass


def freeze_json(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze_json(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json(v) for v in value)
    return value


def plain_json(value):
    if isinstance(value, Mapping):
        return {k: plain_json(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [plain_json(v) for v in value]
    return value


def states(n: int, limit=12):
    if type(n) is not int or n < 1 or n > limit:
        raise ModelError(f"finite enumeration requires 1 <= n <= {limit}; not checked")
    return product((0, 1), repeat=n)


def validate_state(state, n):
    if isinstance(state, str):
        if len(state) != n or any(c not in "01" for c in state):
            raise ModelError(f"state must contain exactly {n} binary digits x1..xn")
        return tuple(int(c) for c in state)
    state = tuple(state)
    if len(state) != n or any(type(x) is not int or x not in (0, 1) for x in state):
        raise ModelError("state must be a binary integer vector of the processor domain")
    return state


@dataclass(frozen=True)
class Edge:
    id: str
    u: str
    v: str
    predicate: Expr

    def to_dict(self):
        return {"id": self.id, "u": self.u, "v": self.v, "predicate": self.predicate.to_dict()}


@dataclass(frozen=True)
class GLModel:
    num_processors: int
    vertices: tuple[str, ...]
    edges: tuple[Edge, ...]
    model_id: str = "anonymous"
    metadata: dict = field(default_factory=dict, compare=False)

    def __post_init__(self):
        if type(self.num_processors) is not int or not 1 <= self.num_processors <= 64:
            raise ModelError("num_processors must be an integer in 1..64")
        if type(self.vertices) is not tuple or not self.vertices or len(self.vertices) > 10000:
            raise ModelError("vertices must be a nonempty tuple, at most 10000")
        if not all(type(v) is str and v for v in self.vertices) or len(set(self.vertices)) != len(
            self.vertices
        ):
            raise ModelError("vertex IDs must be unique nonempty strings")
        if type(self.edges) is not tuple or len(self.edges) > 50000:
            raise ModelError("edges must be a tuple, at most 50000")
        ids, pairs = set(), set()
        for e in self.edges:
            if not isinstance(e, Edge) or type(e.id) is not str or not e.id or e.id in ids:
                raise ModelError("edge IDs must be unique nonempty strings")
            if (
                type(e.u) is not str
                or type(e.v) is not str
                or e.u not in self.vertices
                or e.v not in self.vertices
                or e.u == e.v
            ):
                raise ModelError("edge endpoints must exist; self loops unsupported")
            pair = frozenset((e.u, e.v))
            if pair in pairs:
                raise ModelError("parallel undirected edges unsupported")
            ids.add(e.id)
            pairs.add(pair)
            if not isinstance(e.predicate, Expr):
                raise ModelError("predicate must be a safe expression")
            parse_expr(e.predicate.to_dict(), self.num_processors)
        if type(self.model_id) is not str or not self.model_id:
            raise ModelError("model_id must be a nonempty string")
        if not isinstance(self.metadata, Mapping):
            raise ModelError("metadata must be an object")
        try:
            object.__setattr__(
                self,
                "metadata",
                freeze_json(json.loads(json.dumps(plain_json(self.metadata), allow_nan=False))),
            )
        except (ValueError, TypeError) as e:
            raise ModelError("metadata must be finite JSON data") from e

    def to_dict(self):
        return {
            "schema_version": "faultgraph-1",
            "model_id": self.model_id,
            "num_processors": self.num_processors,
            "vertices": list(self.vertices),
            "edges": [e.to_dict() for e in self.edges],
            "metadata": plain_json(self.metadata),
        }

    @property
    def digest(self):
        return sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @property
    def topology(self):
        return (
            frozenset(self.vertices),
            frozenset((e.id, frozenset((e.u, e.v))) for e in self.edges),
        )


def model_from_dict(d):
    if type(d) is not dict:
        raise ModelError("model must be an object")
    version = d.get("schema_version")
    allowed = {"schema_version", "model_id", "num_processors", "vertices", "edges", "metadata"}
    if version == "research-example-0.1":
        allowed |= {"state_semantics", "note"}
    elif version != "faultgraph-1":
        raise ModelError("unknown schema_version")
    if set(d) - allowed or not {"num_processors", "vertices", "edges"} <= set(d):
        raise ModelError("unknown or missing model fields")
    if type(d["vertices"]) is not list or type(d["edges"]) is not list:
        raise ModelError("vertices and edges must be arrays")
    n = d["num_processors"]
    if type(n) is not int or not 1 <= n <= 64:
        raise ModelError("invalid processor domain")
    edges = []
    for e in d["edges"]:
        if type(e) is not dict or set(e) != {"id", "u", "v", "predicate"}:
            raise ModelError("unknown or missing edge fields")
        edges.append(Edge(e["id"], e["u"], e["v"], parse_expr(e["predicate"], n)))
    metadata = d.get("metadata", {})
    if version == "research-example-0.1":
        metadata = {"imported_schema": version, "note": d.get("note", "")}
    return GLModel(n, tuple(d["vertices"]), tuple(edges), d.get("model_id", "anonymous"), metadata)


def load_json(path):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise ModelError(f"duplicate JSON field: {k}")
            d[k] = v
        return d

    p = Path(path)
    if p.stat().st_size > 10_000_000:
        raise ModelError("JSON input exceeds 10 MB")
    return json.loads(
        p.read_text(),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ModelError("nonfinite JSON")),
    )


def load_model(path):
    return model_from_dict(load_json(path))


def save_model(model, path):
    Path(path).write_text(json.dumps(model.to_dict(), indent=2, sort_keys=True) + "\n")


@dataclass(frozen=True)
class ConditionedModel:
    selectors: tuple[Expr, ...]
    models: tuple[GLModel, ...]

    def __post_init__(self):
        if type(self.selectors) is not tuple or type(self.models) is not tuple:
            raise ModelError("selectors and models must be tuples")
        if not self.models or len(self.selectors) != len(self.models):
            raise ModelError("one selector required per auxiliary model")
        n = self.models[0].num_processors
        if any(m.num_processors != n for m in self.models):
            raise ModelError("auxiliary processor domains must match")
        for c in self.selectors:
            parse_expr(c.to_dict(), n)
        for s in states(n):
            count = sum(c.evaluate(s) for c in self.selectors)
            if count != 1:
                raise ModelError(
                    f"selectors must partition all states: witness={''.join(map(str, s))}, matches={count}"
                )


def load_conditioned(path):
    d = load_json(path)
    if (
        type(d) is not dict
        or set(d) != {"schema_version", "selectors", "models"}
        or d["schema_version"] != "faultgraph-conditioned-1"
    ):
        raise ModelError("invalid conditioned-model schema")
    if type(d["models"]) is not list or not d["models"] or type(d["selectors"]) is not list:
        raise ModelError("conditioned models and selectors must be nonempty arrays")
    models = tuple(model_from_dict(m) for m in d["models"])
    n = models[0].num_processors
    selectors = tuple(parse_expr(c, n) for c in d["selectors"])
    return ConditionedModel(selectors, models)
