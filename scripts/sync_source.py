#!/usr/bin/env python3
"""Export one pinned base/dependency snapshot, independent of LLVM selection."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ".chromium-source.json"


def safe_path(value):
    path = PurePosixPath(value)
    if (not value or value == "." or "\\" in value or ":" in value or
            path.is_absolute() or any(p in ("..", ".git") for p in path.parts) or
            any(ord(c) < 32 for c in value)):
        raise ValueError(f"Unsafe source path: {value!r}")
    return path


def validate_lock(lock):
    if lock.get("schema") != 1 or not lock.get("repositories"):
        raise ValueError("Source lock requires schema 1 and repositories")
    names, destinations = set(), set()
    for repo in lock["repositories"]:
        if not re.fullmatch(r"[a-z0-9_-]+", repo["name"]) or repo["name"] in names:
            raise ValueError("Invalid or repeated repository name")
        names.add(repo["name"])
        if not re.fullmatch(r"[a-f0-9]{40}", repo["revision"]):
            raise ValueError("Each revision must be a full Git commit SHA")
        if not repo["url"].startswith("https://"):
            raise ValueError("Repository URL must use HTTPS")
        destination = repo["destination"]
        if destination:
            safe_path(destination)
        if destination in destinations:
            raise ValueError("Repeated repository destination")
        destinations.add(destination)
        if not repo["paths"]:
            raise ValueError("Explicit source paths are required")
        for path in repo["paths"]:
            safe_path(path)
    if lock["repositories"][0]["destination"] != "":
        raise ValueError("First repository must supply the snapshot root")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(cache, *args, **kwargs):
    return subprocess.run(["git", "--no-replace-objects", "-C", str(cache), *args], check=True, **kwargs)


def selected_entries(cache, revision, paths):
    for path in paths:
        safe_path(path)
    top = git(cache, "ls-tree", "-z", revision, "--", *paths, capture_output=True).stdout
    found = {entry.split(b"\t", 1)[1].decode() for entry in top.split(b"\0") if entry}
    missing = set(paths) - found
    if missing:
        raise ValueError(f"Locked source path not found at {revision}: {', '.join(sorted(missing))}")
    return git(cache, "ls-tree", "-rz", revision, "--", *paths,
               capture_output=True).stdout.split(b"\0")


def prepare_cache(repo, cache_root):
    cache = Path(cache_root) / repo["name"]
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--filter=blob:none", "--depth=1", "--no-checkout",
                        repo["url"], str(cache)], check=True)
    remote = git(cache, "remote", "get-url", "origin", capture_output=True, text=True).stdout.strip()
    if remote != repo["url"]:
        raise ValueError(f"Cache has a different remote: {cache}")
    present = subprocess.run(["git", "--no-replace-objects", "-C", str(cache), "cat-file", "-e", repo["revision"] + "^{commit}"],
                             capture_output=True).returncode == 0
    if not present:
        git(cache, "fetch", "--depth=1", "--filter=blob:none", "origin", repo["revision"])
    entries = selected_entries(cache, repo["revision"], repo["paths"])
    wanted = {line.split(b"\t", 1)[0].split()[2].decode() for line in entries
              if line and line.split(b"\t", 1)[0].split()[1] == b"blob"}
    available = set(git(cache, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)",
                        capture_output=True, text=True).stdout.splitlines())
    missing = wanted - available
    if missing:
        print(f"  Fetch {len(missing)} selected blobs", flush=True)
        git(cache, "-c", "gc.auto=0", "-c", "fetch.negotiationAlgorithm=noop",
            "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no",
            "--filter=blob:none", "origin", "--stdin",
            input=("\n".join(sorted(missing)) + "\n").encode("ascii"))
    # Worktree files are neither consulted nor changed. The pinned objects alone
    # determine the export, even when an existing cache has a working tree.
    return cache


def extract_archive(archive, destination):
    destination = Path(destination).resolve()
    with tarfile.open(archive, "r:*") as tar:
        members = tar.getmembers()
        table = {m.name.rstrip("/"): m for m in members}
        # Validate the entire archive before touching the destination.
        for member in members:
            safe_path(member.name.rstrip("/"))
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError(f"Unsupported archive entry: {member.name}")
            if member.issym() or member.islnk():
                target = member.linkname if member.islnk() else posixpath.join(posixpath.dirname(member.name), member.linkname)
                safe_path(posixpath.normpath(target))
        def regular(member, visited):
            if member.isfile():
                return member
            if member.name in visited or not (member.issym() or member.islnk()):
                raise ValueError(f"Cannot materialize source link: {member.name}")
            target = member.linkname if member.islnk() else posixpath.join(posixpath.dirname(member.name), member.linkname)
            target = posixpath.normpath(target)
            if target not in table:
                raise ValueError(f"Source link target not selected: {member.name} -> {target}")
            return regular(table[target], visited | {member.name})
        for member in members:
            path = destination / member.name
            if not path.resolve().is_relative_to(destination):
                raise ValueError(f"Destination link escapes snapshot: {path}")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            if path.exists():
                raise ValueError(f"Refusing to overwrite source file: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            source = regular(member, set())
            with tar.extractfile(source) as stream, path.open("xb") as output:
                shutil.copyfileobj(stream, output)
            if os.name != "nt":
                path.chmod(member.mode & 0o777)


def export_tree(cache, revision, paths, destination):
    # git archive consults attributes outside the selected tree, causing unrelated
    # lazy downloads in partial clones. Read only explicitly selected Git blobs.
    entries = selected_entries(cache, revision, paths)
    with tempfile.TemporaryDirectory(prefix="base-export-") as temporary:
        archive = Path(temporary) / "source.tar"
        with subprocess.Popen(["git", "--no-replace-objects", "-C", str(cache), "cat-file", "--batch"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as batch:
            with tarfile.open(archive, "w") as tar:
                for entry in entries:
                    if not entry:
                        continue
                    metadata, name = entry.split(b"\t", 1)
                    mode, kind, oid = metadata.split()
                    if kind == b"commit":
                        continue  # Dependency repositories are exported separately.
                    path = name.decode("utf-8")
                    safe_path(path)
                    batch.stdin.write(oid + b"\n")
                    batch.stdin.flush()
                    header = batch.stdout.readline().split()
                    if len(header) != 3 or header[1] != b"blob":
                        raise ValueError(f"Cannot export blob: {path}")
                    data = batch.stdout.read(int(header[2]))
                    if len(data) != int(header[2]) or batch.stdout.read(1) != b"\n":
                        raise ValueError(f"Truncated blob: {path}")
                    member = tarfile.TarInfo(path)
                    if mode == b"120000":
                        member.type = tarfile.SYMTYPE
                        member.linkname = data.decode("utf-8")
                    else:
                        member.mode = int(mode, 8) & 0o777
                        member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
            batch.stdin.close()
            if batch.wait():
                raise ValueError("git cat-file failed")
        extract_archive(archive, destination)


def regular_files(destination, exclude_root=()):
    destination = Path(destination).resolve()
    paths = []
    def onerror(error):
        raise error
    for directory, dirs, files in os.walk(destination, onerror=onerror):
        if Path(directory) == destination:
            dirs[:] = [name for name in dirs if name not in exclude_root]
            files = [name for name in files if name not in exclude_root]
        for name in dirs + files:
            path = Path(directory) / name
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            if path.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError(f"Unexpected filesystem link: {path}")
        for name in files:
            path = Path(directory) / name
            paths.append(path)
    return sorted(paths)


def source_files(destination):
    return regular_files(destination, ("out", INVENTORY))


def write_inventory(destination, lock):
    destination = Path(destination)
    paths = source_files(destination)
    with ThreadPoolExecutor(max_workers=16) as pool:
        files = dict(zip((p.relative_to(destination).as_posix() for p in paths), pool.map(sha256, paths)))
    inventory = {"schema": 1, "revision": lock["repositories"][0]["revision"],
                 "lock": lock, "files": files}
    (destination / INVENTORY).write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def verify_snapshot(destination):
    destination = Path(destination).resolve()
    path = destination / INVENTORY
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema") != 1 or not inventory.get("files"):
        raise ValueError("Invalid source inventory")
    def verify_file(item):
        name, digest = item
        safe_path(name)
        source = destination / name
        if not source.resolve().is_relative_to(destination) or not source.is_file():
            raise ValueError(f"Source missing or outside snapshot: {name}")
        if sha256(source) != digest:
            raise ValueError(f"Source modified: {name}; regenerate the snapshot from its lock")
    actual = {p.relative_to(destination).as_posix() for p in source_files(destination)}
    added = actual - inventory["files"].keys()
    if added:
        raise ValueError(f"Unexpected source files: {', '.join(sorted(added)[:5])}")
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(verify_file, inventory["files"].items()))
    return {"revision": inventory["revision"], "source_inventory_sha256": sha256(path),
            "source_files": len(inventory["files"])}


def write_commit_timestamp(cache, revision, destination):
    """Replace the gclient timestamp hook without requiring a Git worktree."""
    timestamp = git(cache, "show", "-s", "--format=%ct", revision,
                    capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r"[0-9]+", timestamp):
        raise ValueError("Pinned commit has an invalid timestamp")
    target = Path(destination) / "build/util/LASTCHANGE.committime"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(timestamp + "\n", encoding="utf-8")


def synchronize(lock, destination, cache_root, overlay):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError(f"Destination already exists; verify it or choose a fresh path: {destination}")
    validate_lock(lock)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / (destination.name + ".staging-" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        prepared = []
        for repo in lock["repositories"]:
            print(f"Source: {repo['name']} @ {repo['revision']}", flush=True)
            cache = prepare_cache(repo, cache_root)
            prepared.append((repo, cache))
        for repo, cache in prepared:
            print(f"Export: {repo['name']}", flush=True)
            export_tree(cache, repo["revision"], repo["paths"], stage / repo["destination"])
        write_commit_timestamp(prepared[0][1], prepared[0][0]["revision"], stage)
        if overlay:
            for path in sorted(Path(overlay).rglob("*")):
                if path.is_file():
                    target = stage / path.relative_to(overlay)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Overlays intentionally replace upstream build entry points.
                    shutil.copyfile(path, target)
        inventory = write_inventory(stage, lock)
        size = sum((stage / p).stat().st_size for p in inventory["files"])
        stage.rename(destination)
        print(json.dumps({"destination": str(destination), "files": len(inventory["files"]),
                          "source_bytes": size, "revision": inventory["revision"]}, indent=2))
    finally:
        if stage.exists() and stage.resolve().is_relative_to(destination.parent):
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "source.lock.json")
    parser.add_argument("--destination", type=Path, default=ROOT / "vendor/chromium")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/standalone")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            print(json.dumps(verify_snapshot(args.destination), indent=2))
        else:
            synchronize(json.loads(args.lock.read_text(encoding="utf-8")), args.destination,
                        args.cache, ROOT / "standalone")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
