import math

import pytest

from faultgraph.oracle import threshold
from faultgraph.reliability import binomial, common_cause_exact, exact, exact_joint, monte_carlo


@pytest.mark.parametrize("n", range(1, 9))
@pytest.mark.parametrize("p", [0, 0.8, 0.9, 0.99, 1])
def test_exact_nist_binomial(n, p):
    for k in range(n + 1):
        assert exact(n, lambda s, k=k: threshold(s, k), [p] * n) == pytest.approx(
            binomial(n, k, p), abs=1e-13
        )


def test_nonidentical_independent_and_known_correlated_joint():
    ps = [0.2, 0.5, 0.8]
    value = exact(3, lambda s: threshold(s, 2), ps)
    expected = (
        ps[0] * ps[1] * (1 - ps[2])
        + ps[0] * (1 - ps[1]) * ps[2]
        + (1 - ps[0]) * ps[1] * ps[2]
        + math.prod(ps)
    )
    assert value == pytest.approx(expected)
    law = [("000", 0.5), ("111", 0.5)]
    assert exact_joint(3, lambda s: threshold(s, 1), law) == 0.5
    assert exact(3, lambda s: threshold(s, 1), [0.5] * 3) == 0.875
    assert common_cause_exact(3, lambda s: threshold(s, 2), [0.9] * 3, 0.1) == pytest.approx(
        0.9 * binomial(3, 2, 0.9)
    )


@pytest.mark.parametrize("ps", [[float("nan")], [float("inf")], [-0.1], [1.1], [], [True]])
def test_invalid_probabilities(ps):
    with pytest.raises(ValueError):
        exact(1, lambda s: True, ps)


def test_bad_joint_and_sampling():
    with pytest.raises(ValueError):
        exact_joint(1, lambda s: True, [("0", 0.2)])
    with pytest.raises(ValueError):
        exact_joint(1, lambda s: True, [("0", 0.5), ("0", 0.5)])
    with pytest.raises(ValueError):
        monte_carlo(1, lambda s: True, [0.5], samples=0)
    a = monte_carlo(3, lambda s: threshold(s, 2), [0.8] * 3, 5000, 17)
    assert a == monte_carlo(3, lambda s: threshold(s, 2), [0.8] * 3, 5000, 17)
    assert a.lower <= binomial(3, 2, 0.8) <= a.upper
    assert monte_carlo(1, lambda s: bool(s[0]), [0], 100, 1).lower == 0
    assert monte_carlo(1, lambda s: bool(s[0]), [1], 100, 1).upper == 1
