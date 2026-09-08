"""Blender entry point for the reusable native verifier."""
import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propforge.native_verify import verify

parser = argparse.ArgumentParser()
parser.add_argument("--build", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
try:
    report = verify(Path(args.build), out)
    print(f"Native Pruefung bestanden: {len(report['props'])} Props, {len(report['dictionaries'])} YTDs")
except Exception as exc:
    (out / "native_result.json").write_text(json.dumps({"status": "failed", "error": str(exc), "traceback": traceback.format_exc()}, indent=2), encoding="utf-8")
    traceback.print_exc()
    sys.exit(1)
