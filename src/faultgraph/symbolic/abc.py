"""Pinned external ABC adapter; no shell or model-controlled commands."""

import subprocess
from pathlib import Path
from time import perf_counter

from ..model import ModelError
from .circuit import Circuit

RESYN2 = "strash; balance; rewrite; refactor; balance; rewrite; rewrite -z; balance; refactor -z; rewrite -z; balance"


def parse_binary_aiger(data, expected_n):
    end = data.find(b"\n")
    header = data[:end].split()
    if end < 0 or len(header) != 6 or header[0] != b"aig":
        raise ModelError("unsupported binary AIGER header")
    m, n, latches, outputs, count = map(int, header[1:])
    if n != expected_n or latches or outputs != 1 or m != n + count or not 0 <= count <= 100000:
        raise ModelError("AIGER dimensions/domain changed")
    pos = end + 1
    end = data.find(b"\n", pos)
    if end < 0:
        raise ModelError("truncated AIGER output")
    output = int(data[pos:end])
    pos = end + 1

    def number():
        nonlocal pos
        result, shift = 0, 0
        while pos < len(data) and shift <= 28:
            char = data[pos]
            pos += 1
            result |= (char & 127) << shift
            if char < 128:
                return result
            shift += 7
        raise ModelError("truncated or oversized AIGER variable integer")

    gates = []
    for index in range(n + 1, m + 1):
        a = 2 * index - number()
        b = a - number()
        gates.append((a, b))
    # ABC is instructed to save I/O names. Refuse a silent input permutation.
    symbols = {}
    for line in data[pos:].decode("utf-8").splitlines():
        if line == "c":
            break
        if line.startswith("i"):
            key, name = line.split(" ", 1)
            symbols[int(key[1:])] = name
    if symbols != {i: f"x{i + 1}" for i in range(n)}:
        raise ModelError("AIGER input names/order missing or changed")
    return Circuit(n, tuple(gates), output)


def synthesize(circuit, binary, directory, timeout=30):
    binary = Path(binary).resolve()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "input.blif").write_text(circuit.blif())
    command = [
        str(binary),
        "-c",
        "read_blif input.blif; " + RESYN2 + "; print_stats; write_aiger -s output.aig",
    ]
    start = perf_counter()
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        (directory / "synthesis.log").write_bytes((error.stdout or b"") + (error.stderr or b""))
        raise TimeoutError("ABC synthesis deadline") from error
    (directory / "synthesis.log").write_bytes(result.stdout + result.stderr)
    path = directory / "output.aig"
    if result.returncode or not path.exists():
        raise ModelError("ABC failed to produce an AIGER output; see synthesis.log")
    compiled = parse_binary_aiger(path.read_bytes(), circuit.n)
    return compiled, {
        "command": command,
        "exit_code": result.returncode,
        "seconds": perf_counter() - start,
    }


def equivalence(binary, directory, timeout=30):
    command = [str(Path(binary).resolve()), "-c", "cec input.blif output.aig"]
    start = perf_counter()
    try:
        result = subprocess.run(
            command, cwd=directory, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
        status = (
            "EQUIVALENT"
            if result.returncode == 0 and "Networks are equivalent" in output
            else "INCONCLUSIVE"
        )
        if "Networks are NOT EQUIVALENT" in output:
            status = "COUNTEREXAMPLE"
        exit_code = result.returncode
    except subprocess.TimeoutExpired as error:
        output = str(error.stdout or "") + str(error.stderr or "")
        status, exit_code = "TIMEOUT", None
    Path(directory, "cec.log").write_text(output)
    return {
        "status": status,
        "command": command,
        "exit_code": exit_code,
        "seconds": perf_counter() - start,
    }
