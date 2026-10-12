"""Immutable restricted Boolean AST; no executable model input.

Indices are one-based. Complexity v1 counts each n-ary AND/OR as n-1
binary operations, and each NOT occurrence once (tree, not shared DAG).
"""

import json
import re
from dataclasses import dataclass


class ExpressionError(ValueError):
    pass


class Expr:
    def evaluate(self, state: tuple[int, ...]) -> bool:
        raise NotImplementedError

    def to_dict(self) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class Const(Expr):
    value: bool

    def __post_init__(self):
        if type(self.value) is not bool:
            raise ExpressionError("constant must be bool")

    def evaluate(self, state):
        return self.value

    def to_dict(self):
        return {"type": "const", "value": self.value}


@dataclass(frozen=True)
class Var(Expr):
    index: int

    def __post_init__(self):
        if type(self.index) is not int or self.index < 1:
            raise ExpressionError("variable index must be a positive integer")

    def evaluate(self, state):
        return bool(state[self.index - 1])

    def to_dict(self):
        return {"type": "var", "index": self.index}


@dataclass(frozen=True)
class Not(Expr):
    arg: Expr

    def __post_init__(self):
        if not isinstance(self.arg, Expr):
            raise ExpressionError("NOT requires an expression")

    def evaluate(self, state):
        return not self.arg.evaluate(state)

    def to_dict(self):
        return {"type": "not", "arg": self.arg.to_dict()}


@dataclass(frozen=True)
class And(Expr):
    args: tuple[Expr, ...]

    def __post_init__(self):
        if (
            type(self.args) is not tuple
            or len(self.args) < 2
            or not all(isinstance(a, Expr) for a in self.args)
        ):
            raise ExpressionError("AND/OR require a tuple of at least two expressions")

    def evaluate(self, state):
        return all(a.evaluate(state) for a in self.args)

    def to_dict(self):
        return {"type": "and", "args": [a.to_dict() for a in self.args]}


@dataclass(frozen=True)
class Or(And):
    def evaluate(self, state):
        return any(a.evaluate(state) for a in self.args)

    def to_dict(self):
        return {"type": "or", "args": [a.to_dict() for a in self.args]}


TRUE, FALSE = Const(True), Const(False)


def conj(*args):
    return TRUE if not args else args[0] if len(args) == 1 else And(tuple(args))


def disj(*args):
    return FALSE if not args else args[0] if len(args) == 1 else Or(tuple(args))


def parse_expr(data, num_processors: int, *, max_nodes=10000, max_depth=64) -> Expr:
    count = 0

    def visit(d, depth):
        nonlocal count
        count += 1
        if count > max_nodes or depth > max_depth:
            raise ExpressionError("expression resource limit exceeded")
        if type(d) is not dict:
            raise ExpressionError("expression must be a JSON object")
        kind = d.get("type")
        if kind == "const" and set(d) == {"type", "value"}:
            return Const(d["value"])
        if kind == "var":
            if set(d) == {"type", "name"} and isinstance(d["name"], str):
                match = re.fullmatch(r"x([1-9][0-9]*)", d["name"])
                if not match:
                    raise ExpressionError("legacy variable must be x1, x2, ...")
                index = int(match[1])
            elif set(d) == {"type", "index"}:
                index = d["index"]
            else:
                raise ExpressionError("invalid variable fields")
            v = Var(index)
            if v.index > num_processors:
                raise ExpressionError("variable outside processor domain")
            return v
        if kind == "not" and set(d) == {"type", "arg"}:
            return Not(visit(d["arg"], depth + 1))
        if kind in ("and", "or") and set(d) == {"type", "args"}:
            if type(d["args"]) is not list or len(d["args"]) < 2:
                raise ExpressionError("AND/OR require at least two arguments")
            return (And if kind == "and" else Or)(tuple(visit(a, depth + 1) for a in d["args"]))
        raise ExpressionError("unknown expression type or fields")

    return visit(data, 0)


def complexity(expr: Expr) -> dict:
    nodes, ops, unique = [], {"and": 0, "or": 0, "not": 0}, set()
    stack = [expr]
    while stack:
        e = stack.pop()
        nodes.append(e)
        unique.add(e)
        if isinstance(e, Not):
            ops["not"] += 1
            stack.append(e.arg)
        elif isinstance(e, And):
            ops["or" if isinstance(e, Or) else "and"] += len(e.args) - 1
            stack.extend(e.args)
    return {**ops, "total": sum(ops.values()), "tree_nodes": len(nodes), "dag_nodes": len(unique)}


def simplify(expr: Expr) -> Expr:
    """local-v1: constants, flattening, idempotence, complement, absorption.

    No truth-table lookup, tuning, or oracle access. Rewrites are separately tested.
    """
    if isinstance(expr, (Const, Var)):
        return expr
    if isinstance(expr, Not):
        a = simplify(expr.arg)
        return (
            Const(not a.value) if isinstance(a, Const) else a.arg if isinstance(a, Not) else Not(a)
        )
    cls = type(expr)
    is_or = cls is Or
    flat = []
    for a in expr.args:
        a = simplify(a)
        flat.extend(a.args if type(a) is cls else [a])
    annihilator = TRUE if is_or else FALSE
    identity = FALSE if is_or else TRUE
    if annihilator in flat:
        return annihilator
    unique = set(flat) - {identity}
    if any((a.arg if isinstance(a, Not) else Not(a)) in unique for a in unique):
        return annihilator
    dual = And if is_or else Or
    unique = {a for a in unique if not (type(a) is dual and any(b in unique for b in a.args))}
    args = sorted(unique, key=lambda a: json.dumps(a.to_dict(), sort_keys=True))
    return identity if not args else args[0] if len(args) == 1 else cls(tuple(args))
