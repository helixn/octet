"""Hardware specs without third-party dependencies.

Windows: GlobalMemoryStatusEx via ctypes; Linux: /proc/meminfo.
Threads: os.cpu_count().
"""
import ctypes
import os
import platform


def ram_gb() -> int:
    system = platform.system()
    try:
        if system == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(stat))
            return int(stat.ullTotalPhys // (1024 ** 3))
        # Linux / macOS: read /proc/meminfo (Linux); fall back to sysconf
        if system == "Linux" and os.path.exists("/proc/meminfo"):
            for line in open("/proc/meminfo", encoding="ascii"):
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return int(kb // (1024 * 1024))
        import resource  # noqa: F401  (macOS fallback below)
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page // (1024 ** 3))
    except Exception:
        return 0


def cpu_threads() -> int:
    return os.cpu_count() or 1
