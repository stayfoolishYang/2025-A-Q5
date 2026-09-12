"""Finish the existing batch by writing its oracle-scored report after runner exit."""
import ctypes,sys,traceback
from pathlib import Path
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_bool,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
handle=kernel.OpenProcess(0x00100000,False,int(sys.argv[1]))
if handle:
 while kernel.WaitForSingleObject(handle,60000)==258:pass
 kernel.CloseHandle(handle)
from analyze_tie_rollout200 import main
main()
