"""Switch an idle, built Windows base snapshot to the combined net source."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "base/scripts"))
import chromium_base as driver
from net.sync_source import combined_lock
from sync_source import INVENTORY, sha256, verify_snapshot


def base_lock():
    return json.loads((ROOT / "source.lock.json").read_text(encoding="utf-8"))


def plain_path(path):
    path = Path(path).absolute()
    if ".." in path.parts or path == path.parent:
        raise ValueError(f"Unsafe snapshot path: {path}")
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0)
                                 & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError(f"Refusing filesystem link: {item}")
    return path


@contextmanager
def exclusive_lock(path):
    # The OS releases the byte-range lock if a process is interrupted. Keep
    # the lock file so a second process never locks a different inode.
    with path.open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Another snapshot switch or recovery is running") from error
        yield


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def manifest_updates(source, old_identity, new_identity):
    outputs = source / "out"
    changes = {}

    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(outputs, onerror=walk_error):
        directory = Path(directory)
        if ".ninja_lock" in dirs or ".ninja_lock" in files:
            raise ValueError(f"Stop the active build before switching: {directory}")
        if driver.MANIFEST not in files:
            # Custom output directories can be nested. Do not traverse junctions.
            for name in dirs.copy():
                entry = directory / name
                if entry.is_symlink() or (getattr(entry.lstat(), "st_file_attributes", 0)
                                          & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                    dirs.remove(name)
            continue
        dirs.clear()
        original = plain_path(directory / driver.MANIFEST).read_bytes().decode("utf-8")
        managed = json.loads(original)
        if managed.get("state") in ("configuring", "building"):
            raise ValueError(f"Stop the active build before switching: {directory}")
        plan = managed.get("plan", {})
        if (managed.get("schema") != 1 or Path(plan.get("source", "")) != source
                or Path(plan.get("output", "")) != directory):
            continue
        identity = managed.get("identity", {})
        if any(identity.get(key) != value for key, value in old_identity.items()):
            continue
        updated = dict(managed, identity={**identity, **new_identity}, state="needs_configure")
        changes[directory.relative_to(outputs).as_posix()] = {
            "manifest": original, "promoted_manifest": updated,
        }
    return changes


def validate_inputs(source, combined, backup, plan):
    if backup.exists():
        raise ValueError(f"Backup already exists: {backup}")
    if (combined / "out").exists() or (combined / "out").is_symlink():
        raise ValueError(f"Combined snapshot already has an out directory: {combined}")
    output = plain_path(plan["output"])
    for tree in (source, combined):
        plain_path(tree / INVENTORY)
    for name in ("base.dll", "base.dll.lib", ".ninja_deps", ".ninja_log",
                 "build.ninja", "toolchain.ninja", "args.gn"):
        if not plain_path(output / name).is_file():
            raise ValueError(f"Missing base build output: {output / name}")

    old = json.loads((source / INVENTORY).read_bytes())
    new = json.loads((combined / INVENTORY).read_bytes())
    if old["lock"] != base_lock() or new["lock"] != combined_lock():
        raise ValueError("Both snapshots must match the current base and net locks")
    if old["revision"] != new["revision"] or old["revision"] != old["lock"]["repositories"][0]["revision"]:
        raise ValueError("Snapshot revisions differ from the pin")
    # The existing doctor verifies every original input and the tool identities.
    report = driver.inspect_environment(plan)
    manifest = driver.read_manifest(plan, report)
    if manifest["state"] != "built":
        raise ValueError("The selected shared base output must have completed its build")
    driver.verify_generated_toolchain(plan)
    new_identity = verify_snapshot(combined)
    if (old["files"].get("BUILD.gn") != sha256(ROOT / "standalone/BUILD.gn") or
            new["files"].get("BUILD.gn") != sha256(ROOT / "net/standalone/BUILD.gn")):
        raise ValueError("Unexpected root BUILD.gn overlay")
    for name, digest in old["files"].items():
        if name != "BUILD.gn" and new["files"].get(name) != digest:
            raise ValueError(f"Combined snapshot changes a base input: {name}")
    old_identity = {key: report["identity"][key] for key in new_identity}
    changes = manifest_updates(source, old_identity, new_identity)
    if output.relative_to(source / "out").as_posix() not in changes:
        raise ValueError(f"Selected output no longer matches the verified base snapshot: {output}")
    for name, digest in old["files"].items():
        if new["files"].get(name) == digest:
            previous = (source / name).stat()
            os.utime(combined / name, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    return changes


def rollback(source, combined, backup, journal, plan):
    transaction = json.loads(journal.read_bytes())
    if (transaction["source"], transaction["combined"], transaction["output"]) != (
            str(source), str(combined), str(plan["output"])):
        raise ValueError("Recovery requires the original source, combined and output paths")
    old_tree = backup if backup.exists() else source
    new_tree = combined if combined.exists() else source
    if old_tree == new_tree or any(
        sha256(plain_path(tree / INVENTORY)) != transaction[key]
        for tree, key in ((old_tree, "base_hash"), (new_tree, "combined_hash"))
    ):
        raise ValueError(f"Unexpected snapshot identity during recovery; preserved {journal}")
    if backup.exists() and source.exists() and combined.exists():
        raise ValueError("Recovery destination occupied; all three source trees preserved")

    old_out, new_out = plain_path(old_tree / "out"), plain_path(new_tree / "out")
    if old_out.exists() == new_out.exists():
        raise ValueError("Recovery requires exactly one original out directory")
    current_out = new_out if new_out.exists() else old_out
    changes = transaction.get("manifests")
    if changes is None:
        # Journals from the single-output promotion stored this record at the root.
        selected = Path(plan["output"]).relative_to(source / "out").as_posix()
        changes = {selected: transaction}
    restore = {}
    for name, change in changes.items():
        manifest = plain_path(current_out / name / driver.MANIFEST)
        if not manifest.is_relative_to(current_out) or manifest.parent == current_out:
            raise ValueError(f"Invalid output in recovery journal: {name}")
        original = change["manifest"].encode("utf-8")
        current = manifest.read_bytes()
        if current != original:
            if json.loads(current) != change["promoted_manifest"]:
                raise ValueError(f"Output changed after promotion; preserved {manifest} for inspection")
            restore[manifest] = original
    for manifest, original in restore.items():
        atomic_write(manifest, original)
    if new_out.exists():
        new_out.rename(old_out)
    if not combined.exists():
        source.rename(combined)
    if backup.exists():
        backup.rename(source)
    journal.unlink()


def switch(source, combined, toolchain, llvm_root, recover=False):
    source, combined = plain_path(source), plain_path(combined)
    backup = plain_path(source.with_name(source.name + ".base-backup"))
    journal = plain_path(source.with_name(source.name + ".net-switch.json"))
    lock = plain_path(source.with_name(source.name + ".net-switch.lock"))
    if source.parent != combined.parent or combined in (source, backup, journal, lock):
        raise ValueError("Use distinct sibling source directories on the same volume")
    output = source / "out" / ("sh" if toolchain == "chromium" else "eh")
    plan = driver.make_plan(source, toolchain, llvm_root, linkage="shared", output_dir=output)
    with exclusive_lock(lock):
        if recover:
            rollback(source, combined, backup, journal, plan)
            return
        if journal.exists():
            raise ValueError(f"Interrupted switch found at {journal}; use --recover first")
        changes = validate_inputs(source, combined, backup, plan)
        record = dict(source=str(source), combined=str(combined), output=str(output),
                      base_hash=sha256(source / INVENTORY), combined_hash=sha256(combined / INVENTORY),
                      manifests=changes)
        atomic_write(journal, json.dumps(record, indent=2).encode("utf-8"))
        try:
            source.rename(backup)
            combined.rename(source)
            (backup / "out").rename(source / "out")
            for name, change in changes.items():
                atomic_write(source / "out" / name / driver.MANIFEST,
                             json.dumps(change["promoted_manifest"], indent=2).encode("utf-8"))
            journal.unlink()
        except (OSError, ValueError):
            rollback(source, combined, backup, journal, plan)
            raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Stop all builds using either source tree before running. The original source "
        "is retained as <source>.base-backup. Re-run net/build.py configure and build "
        "with --source pointing to the promoted base path."))
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/chromium")
    parser.add_argument("--combined", type=Path, default=ROOT / "vendor/chromium-net")
    parser.add_argument("--toolchain", choices=("chromium", "external"), default="chromium")
    parser.add_argument("--llvm-root", type=Path)
    parser.add_argument("--recover", action="store_true", help="roll back an interrupted switch")
    args = parser.parse_args()
    try:
        backup = switch(args.source, args.combined, args.toolchain, args.llvm_root, args.recover)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"Base source retained at {backup}. Run configure before build." if backup
          else "Restored both snapshots and the original output.")


if __name__ == "__main__":
    main()
