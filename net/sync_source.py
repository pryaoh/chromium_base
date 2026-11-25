"""Prepare a pinned Chromium snapshot containing the base and net targets."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "base/scripts"))
from sync_source import synchronize, validate_lock


def combined_lock():
    lock = json.loads((ROOT / "source.lock.json").read_text())
    extra = json.loads((ROOT / "net/source-extra.json").read_text())
    chromium = lock["repositories"][0]
    if extra["revision"] != chromium["revision"]:
        raise ValueError("Update the net source selections for the pinned base revision")
    chromium["paths"] = sorted(set(chromium["paths"] + extra["paths"]))
    lock["repositories"].extend(extra["repositories"])
    lock["target"] = "//net:net"
    validate_lock(lock)
    return lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "vendor/chromium-net")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/standalone")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        overlay = Path(directory)
        for source in (ROOT / "standalone", ROOT / "net/standalone"):
            shutil.copytree(source, overlay, dirs_exist_ok=True)
        synchronize(combined_lock(), args.destination, args.cache, overlay)


if __name__ == "__main__":
    main()
