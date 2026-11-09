"""Parallel file work only. Worker threads never call the Unreal API."""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
try:
    from scripts.official.map_paths import io_path
except ImportError:
    from map_paths import io_path


def prepare(root, images, meshes, workers=8, progress=None):
    root = io_path(root)
    workers = max(1, min(16, int(workers), os.cpu_count() or 1))
    cache_path = root / "ue_input_fingerprints.json"
    try:
        previous = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    jobs = [("Textures", row, "file") for row in images] + [("Meshes", row, "fbx") for row in meshes]

    def inspect(job):
        kind, row, field = job
        path = io_path(root / row[field])
        stat = path.stat()
        key = kind + "/" + row["id"]
        old = previous.get(key, {})
        signature = [stat.st_size, stat.st_mtime_ns]
        if old.get("signature") == signature:
            digest = old["sha256"]
        else:
            sha = hashlib.sha256()
            with path.open("rb") as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(block)
            digest = sha.hexdigest()
        if kind == "Textures" and digest != row["sha256"]:
            raise ValueError("Texture changed or is incomplete: " + str(path))
        if stat.st_size < 16:
            raise ValueError("Empty input: " + str(path))
        return key, {"signature": signature, "sha256": digest}

    started = time.monotonic()
    result = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dfmap-input") as pool:
        futures = [pool.submit(inspect, job) for job in jobs]
        for future in as_completed(futures):
            key, record = future.result()
            result[key] = record
            if progress and (len(result) % 64 == 0 or len(result) == len(jobs)):
                progress(len(result), len(jobs))
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    temporary.replace(cache_path)
    return result, {"workers": workers, "files": len(result), "seconds": time.monotonic() - started}
