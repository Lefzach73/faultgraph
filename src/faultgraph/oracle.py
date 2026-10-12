"""Independent domain definitions: these never read GL edges or call BFS."""

from .model import validate_state


def threshold(state, required):
    if type(required) is not int or not 0 <= required <= len(state):
        raise ValueError("invalid survivor threshold")
    return sum(state) >= required


def consecutive(state, k, circular=False):
    """G-system: at least one run of k working processors."""
    n = len(state)
    if type(k) is not int or not 1 <= k <= n:
        raise ValueError("invalid run length")
    return any(
        all(state[(i + j) % n] == 1 for j in range(k)) for i in range(n if circular else n - k + 1)
    )


def exceptional(state, max_failures, accepted):
    return len(state) - sum(state) <= max_failures or "".join(map(str, state)) in accepted


def domain_truth(spec, state):
    s = validate_state(state, spec["n"])
    kind = spec["kind"]
    if kind == "threshold":
        return threshold(s, spec["required"])
    if kind in ("line", "ring"):
        return consecutive(s, spec["k"], kind == "ring")
    if kind == "exceptional":
        return exceptional(s, spec["max_failures"], spec["accepted"])
    if kind == "conditional":
        return threshold(s, spec["high"] if s[0] else spec["low"])
    if kind == "paired":
        return all(s[i] or s[i + 1] for i in range(0, len(s), 2))
    if kind == "corner":
        return spec["operational"]
    if kind == "channels":
        # Independent cut-set definition of the communication-channel system.
        # Read the generated domain specification, never GL edges/predicates/BFS.
        v = spec["vertices"]
        for mask in range(2 ** (v - 1) - 1):
            inside = {0} | {j + 1 for j in range(v - 1) if mask & (1 << j)}
            if not any(
                s[i] and ((a in inside) != (b in inside))
                for i, (a, b) in enumerate(spec["channels"])
            ):
                return False
        return True
    raise ValueError(f"unknown independent domain: {kind}")
