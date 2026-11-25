"""Configure and build Chromium net and base in the same Windows x64 GN output."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "base/scripts"))
import chromium_base
from net.sync_source import combined_lock
from sync_source import INVENTORY


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "doctor", "configure", "build"))
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/chromium-net")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--toolchain", choices=("chromium", "external"), default="chromium")
    parser.add_argument("--llvm-root", type=Path)
    parser.add_argument("--jobs", type=int, help="Limit concurrent Ninja jobs")
    args = parser.parse_args(argv)
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be positive")
    output = args.output_dir or args.source / "out" / ("sh" if args.toolchain == "chromium" else "eh")
    try:
        plan = chromium_base.make_plan(args.source, args.toolchain, args.llvm_root,
                                       linkage="shared", output_dir=output)
        if args.command == "plan":
            print(json.dumps(dict(target="//net:net", **plan), indent=2))
            return 0
        inventory = json.loads((args.source / INVENTORY).read_text(encoding="utf-8"))
        lock = combined_lock()
        if inventory["revision"] != lock["repositories"][0]["revision"] or inventory["lock"] != lock:
            raise ValueError("Prepare the pinned combined snapshot with net/sync_source.py")
        report = chromium_base.inspect_environment(plan)
        if args.command == "doctor":
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 1
        if args.command == "configure":
            chromium_base.configure(plan, report)
        else:
            chromium_base.build(plan, report, target="net", jobs=args.jobs)
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
