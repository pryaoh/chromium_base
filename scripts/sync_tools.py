#!/usr/bin/env python3
"""Download hash-pinned portable Windows build tools; never installs globally."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from sync_source import ROOT, extract_archive, regular_files, safe_path, sha256


def payload_hashes(destination):
    destination = Path(destination).resolve()
    paths = regular_files(destination, (".package.json",))
    with ThreadPoolExecutor(max_workers=16) as pool:
        return dict(zip((p.relative_to(destination).as_posix() for p in paths), pool.map(sha256, paths)))


def verify_installation(destination, package):
    stamp = Path(destination) / ".package.json"
    if not stamp.is_file():
        raise ValueError(f"Existing unmanaged tool directory: {destination}")
    metadata = json.loads(stamp.read_text())
    if metadata.get("schema") != 1 or metadata.get("package") != package:
        raise ValueError(f"Existing unmanaged/different tool package: {destination}; preserve it and install to a fresh directory")
    if not metadata.get("files") or payload_hashes(destination) != metadata["files"]:
        raise ValueError(f"Tool payload modified or missing: {destination}; preserve it and reinstall")
    return {"archive_sha256": package["sha256"], "inventory_sha256": sha256(stamp)}


def unpack(archive, destination):
    if archive.suffix != ".zip":
        extract_archive(archive, destination)
        return
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            safe_path(entry.filename.rstrip("/"))
        for entry in bundle.infolist():
            path = destination / entry.filename
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target)


def install(name, package, cache, tools):
    safe_path(name)
    safe_path(package["archive"])
    destination = tools / name
    if destination.exists():
        verify_installation(destination, package)
        print(f"Already installed and verified: {name}")
        return
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / package["archive"]
    if not archive.exists():
        print(f"Download: {name}", flush=True)
        partial = archive.with_suffix(archive.suffix + ".partial")
        urllib.request.urlretrieve(package["url"], partial)
        if sha256(partial) != package["sha256"]:
            raise ValueError(f"Download checksum mismatch: {partial}")
        partial.replace(archive)
    if sha256(archive) != package["sha256"]:
        raise ValueError(f"Cache checksum mismatch: {archive}")
    tools.mkdir(parents=True, exist_ok=True)
    content = tools / (name + ".staging-" + uuid.uuid4().hex)
    content.mkdir()
    try:
        unpack(archive, content)
        metadata = {"schema": 1, "package": package, "files": payload_hashes(content)}
        (content / ".package.json").write_text(json.dumps(metadata, indent=2) + "\n")
        content.rename(destination)
    finally:
        if content.exists() and content.resolve().is_relative_to(tools.resolve()):
            shutil.rmtree(content)
    print(f"Installed: {destination}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="*", default=["gn", "ninja", "rust-toolchain"])
    args = parser.parse_args(argv)
    try:
        lock = json.loads((ROOT / "tools.lock.json").read_text())
        for name in args.packages:
            install(name, lock["packages"][name], ROOT / ".cache/standalone", ROOT / ".tools")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
