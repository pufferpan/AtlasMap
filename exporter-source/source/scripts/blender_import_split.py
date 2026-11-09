"""Compatibility entry point for verified source-aware split imports.

Historical importer source is retained in out/software_upgrade/20261031/source_backup.
Native glTF node transforms must not be recentered as if already baked.
"""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name("blender_import_verified.py")), run_name="__main__")
