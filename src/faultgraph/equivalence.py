"""Exact finite checks. These certificates are not universal theorems."""

from dataclasses import asdict, dataclass

from .evaluator import operational
from .model import ModelError, states


@dataclass(frozen=True)
class CheckResult:
    status: str
    num_processors: int
    checked_states: int
    witness: str | None = None
    left: bool | None = None
    right: bool | None = None
    scope: str = "exhaustive finite Boolean domain; no general theorem"

    def to_dict(self):
        return asdict(self)


def check_functions(n, left, right, limit=12):
    try:
        domain = states(n, limit)
    except ModelError:
        return CheckResult("NOT_CHECKED", n, 0)
    checked = 0
    for s in domain:
        a, b = bool(left(s)), bool(right(s))
        checked += 1
        if a != b:
            return CheckResult("COUNTEREXAMPLE", n, checked, "".join(map(str, s)), a, b)
    return CheckResult("EXHAUSTIVE_PASS", n, checked)


def check_models(left, right, limit=12):
    if left.num_processors != right.num_processors:
        raise ModelError("cannot compare different processor domains")
    return check_functions(
        left.num_processors, lambda s: operational(left, s), lambda s: operational(right, s), limit
    )
