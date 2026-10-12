"""Verify the curated edition without pretending to validate the private archive."""
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "PUBLIC_EXPORT_MANIFEST.json").read_text())
if not manifest["files"] or len(manifest["source_identity"]) != 40:
    raise SystemExit("invalid public file/source inventory")
if (root / ".git").exists():
    tracked = set(subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode().split("\0")) - {""}
    expected_files = set(manifest["files"]) | {"PUBLIC_EXPORT_MANIFEST.json"}
    if tracked != expected_files:
        raise SystemExit("tracked public file inventory differs from export manifest")
actual_sources = {str(p.relative_to(root)) for p in (root / "src").rglob("*.py")}
if actual_sources != set(manifest["source_identity"]):
    raise SystemExit("scientific source inventory changed")
for name, expected in manifest["files"].items():
    path = root / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("public export hash mismatch: " + name)
for name, expected in manifest["source_identity"].items():
    if manifest["files"].get(name) != expected:
        raise SystemExit("source identity mismatch: " + name)
print(json.dumps({"status": "PASS", "source_files": 40,
                  "public_files": len(manifest["files"]),
                  "private_origin_commit": manifest["private_origin_commit"],
                  "scope": "curated public tree; not private archive integrity"}, indent=2))
