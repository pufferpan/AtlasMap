"""Extended Windows paths for filesystem I/O, independent of process manifests."""
import ntpath
import os
from pathlib import Path


def io_path(path):
    value=os.fspath(path)
    if os.name!='nt':return Path(value)
    if value.startswith('\\\\?\\'):return Path(value)
    absolute=ntpath.normpath(os.path.abspath(value))
    if absolute.startswith('\\\\'):
        return Path('\\\\?\\UNC\\'+absolute[2:])
    return Path('\\\\?\\'+absolute)


def display_path(path):
    value=os.fspath(path)
    if value.startswith('\\\\?\\UNC\\'):return '\\\\'+value[8:]
    return value[4:] if value.startswith('\\\\?\\') else value
