"""Static probability laws only; independent and common-cause kept distinct."""

import random
from dataclasses import asdict, dataclass
from math import comb, fsum, isfinite, prod, sqrt

from .model import states, validate_state


def probabilities(ps, n):
    if len(ps) != n or any(
        type(p) not in (float, int) or not isfinite(p) or not 0 <= p <= 1 for p in ps
    ):
        raise ValueError("one finite working probability in [0,1] per processor required")
    return tuple(float(p) for p in ps)


def exact(n, indicator, ps):
    ps = probabilities(ps, n)
    value = fsum(
        prod(p if x else 1 - p for p, x in zip(ps, s, strict=False))
        for s in states(n)
        if indicator(s)
    )
    return min(1.0, max(0.0, value))


def binomial(n, required, p):
    probabilities([p] * n, n)
    if type(required) is not int or not 0 <= required <= n:
        raise ValueError("invalid survivor threshold")
    return fsum(comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(required, n + 1))


def exact_joint(n, indicator, distribution):
    seen, terms, mass = set(), [], []
    for state, weight in distribution:
        s = validate_state(state, n)
        probabilities([weight], 1)
        if s in seen:
            raise ValueError("duplicate joint state")
        seen.add(s)
        mass.append(weight)
        terms.append(weight * bool(indicator(s)))
    if abs(fsum(mass) - 1) > 1e-12:
        raise ValueError("joint distribution must sum to one")
    return fsum(terms)


def common_cause_exact(n, indicator, ps, q):
    probabilities([q], 1)
    return q * bool(indicator((0,) * n)) + (1 - q) * exact(n, indicator, ps)


@dataclass(frozen=True)
class Estimate:
    estimate: float
    lower: float
    upper: float
    successes: int
    samples: int
    seed: int
    law: str
    method: str = "Wilson score 95% marginal interval, z=1.959963984540054"

    def to_dict(self):
        return asdict(self)


def monte_carlo(n, indicator, ps, samples=10000, seed=0, common_cause=0.0):
    ps = probabilities(ps, n)
    probabilities([common_cause], 1)
    if type(samples) is not int or samples < 1 or type(seed) is not int:
        raise ValueError("positive integer samples and integer seed required")
    rng = random.Random(seed)
    successes = 0
    for _ in range(samples):
        s = (
            (0,) * n
            if common_cause and rng.random() < common_cause
            else tuple(int(rng.random() < p) for p in ps)
        )
        successes += bool(indicator(s))
    p, z = successes / samples, 1.959963984540054
    denom = 1 + z * z / samples
    center = (p + z * z / (2 * samples)) / denom
    half = z * sqrt(p * (1 - p) / samples + z * z / (4 * samples * samples)) / denom
    return Estimate(
        p,
        0.0 if successes == 0 else max(0.0, center - half),
        1.0 if successes == samples else min(1.0, center + half),
        successes,
        samples,
        seed,
        f"common-cause mixture q={common_cause}" if common_cause else "independent Bernoulli",
    )
