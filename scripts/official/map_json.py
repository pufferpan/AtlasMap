"""Stream large manifests to disk; never build a second giant JSON string."""
import json
import os
from pathlib import Path
import uuid


def write_json(path,data):
    from map_paths import io_path
    path=io_path(path)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,separators=(',',':'))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
