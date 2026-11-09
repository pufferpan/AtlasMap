"""Atomic receipts and immutable file sharing for isolated native workers."""
import json
import os
from pathlib import Path
import shutil
import uuid
try:
    from .map_paths import io_path, display_path as metadata_path
except ImportError:
    from map_paths import io_path, display_path as metadata_path


def atomic_bytes(path,data):
    path=io_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.partial')
    try:
        temporary.write_bytes(data)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path,data):
    atomic_bytes(path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))


def share_file(source,target,cancelled=None):
    """Hardlink completed, immutable files on one volume; atomic copy otherwise."""
    source,target=io_path(source),io_path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.partial')
    try:
        try:os.link(source,temporary)
        except OSError:
            with source.open('rb') as reader,temporary.open('wb') as writer:
                while True:
                    if cancelled and cancelled():raise InterruptedError('已终止文件保存')
                    block=reader.read(4*1024*1024)
                    if not block:break
                    writer.write(block)
            shutil.copystat(source,temporary)
        os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)


def cached_blob(cache,target,blob,digest):
    cache=io_path(cache);cache.mkdir(parents=True,exist_ok=True)
    shared=cache/digest
    if not shared.is_file():
        temporary=shared.with_name(digest+'.'+uuid.uuid4().hex+'.partial')
        try:
            temporary.write_bytes(blob)
            try:os.link(temporary,shared)
            except FileExistsError:pass
            except OSError:
                if not shared.exists():os.replace(temporary,shared)
        finally:temporary.unlink(missing_ok=True)
    share_file(shared,target)
