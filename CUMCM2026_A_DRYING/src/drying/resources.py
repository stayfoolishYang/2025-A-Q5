"""Cooperative CPU-process memory budget (OS hard limits remain external)."""
import os
import sys


def process_memory_mb():
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
                (name,ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize',
                'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
        item=Counters(); item.cb=ctypes.sizeof(item)
        kernel=ctypes.WinDLL('kernel32'); kernel.GetCurrentProcess.restype=wintypes.HANDLE
        psapi=ctypes.WinDLL('psapi'); psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(item),item.cb):
            raise OSError('process memory measurement failed')
        return item.WorkingSetSize/2**20
    import resource
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak/(2**20 if sys.platform=='darwin' else 1024)


class MemoryBudgetReached(RuntimeError):
    pass
