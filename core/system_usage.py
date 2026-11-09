"""Non-blocking Windows CPU and physical-memory counters, without extra packages."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


def cpu_percent(previous, current):
    """GetSystemTimes kernel time includes idle time; compare cumulative ticks."""
    if previous is None:
        return None
    idle = current[0] - previous[0]
    total = (current[1] - previous[1]) + (current[2] - previous[2])
    if idle < 0 or total <= 0:
        return None
    return max(0.0, min(100.0, (total - idle) * 100.0 / total))


class _MemoryStatus(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD),
                ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                ('avail_extended_virtual', ctypes.c_ulonglong)]


class SystemUsage:
    def __init__(self):
        self._previous = None
        self._kernel = None
        if os.name == 'nt':
            self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self._kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
            self._kernel.GetSystemTimes.restype = wintypes.BOOL
            self._kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatus)]
            self._kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL

    def reset(self):
        self._previous = None

    def sample(self):
        result = {'cpu_percent': None, 'memory_percent': None,
                  'memory_used': None, 'memory_total': None,
                  'memory_available':None,'commit_available':None}
        if self._kernel is None:
            return result
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if self._kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            current = tuple((value.dwHighDateTime << 32) | value.dwLowDateTime
                            for value in (idle, kernel, user))
            result['cpu_percent'] = cpu_percent(self._previous, current)
            self._previous = current
        memory = _MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if self._kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result.update(memory_percent=float(memory.load), memory_total=int(memory.total_phys),
                          memory_used=int(memory.total_phys - memory.avail_phys),
                          memory_available=int(memory.avail_phys),commit_available=int(memory.avail_page))
        return result


def ue_process_capacity(requested,snapshot=None):
    snapshot=SystemUsage().sample() if snapshot is None else snapshot
    physical=snapshot.get('memory_available');commit=snapshot.get('commit_available')
    if physical is None or commit is None:return min(requested,2)
    gb=1024**3
    # Leave headroom for the desktop and native import/texture allocations.
    total=snapshot.get('memory_total')
    total_slots=max(1,int(total/(6*gb))) if total else requested
    return max(1,min(requested,total_slots,int(max(0,physical-gb)/(2*gb)),int(max(0,commit-2*gb)/(4.5*gb))))


def ue_import_memory(manifest,mesh_bytes):
    # Native texture import retains source pixels, conversion buffers and editor
    # data. Encoded PNG size alone greatly understates this allocation.
    pixels=sum(int(row['size'][0])*int(row['size'][1]) for row in manifest['images'])
    return max(4*1024**3,pixels*16+int(mesh_bytes)*2+1024**3)


def ue_import_capacity(requested,costs,snapshot=None):
    snapshot=SystemUsage().sample() if snapshot is None else snapshot
    limit=ue_process_capacity(requested,snapshot)
    physical=snapshot.get('memory_available');commit=snapshot.get('commit_available')
    if not costs or physical is None or commit is None:return min(limit,1)
    budget=min(max(0,physical-1024**3),max(0,commit-2*1024**3))
    # Budget the largest shards first; workers may start in any completion order.
    used=0;capacity=0
    for cost in sorted(costs,reverse=True)[:limit]:
        if used+cost>budget:break
        used+=cost;capacity+=1
    return max(1,capacity)
