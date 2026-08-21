"""Windows Job Object so children die with the launcher, even on hard parent kill.

All children are bound to a Job Object whose only limit is KILL_ON_JOB_CLOSE:
when the launcher process exits for any reason — including SIGKILL — the kernel
closes the job handle and terminates every process in it. No orphaned servers.
"""

import ctypes
import os
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformationClass = 9  # SetInformationJobObject info class


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (n, ctypes.c_uint64)
        for n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


def assign_children_to_job(process_ids: list[int]) -> bool:
    """Bind child processes (by PID) to a kill-on-close job object.

    Returns False on non-Windows. Raises OSError with the kernel error code if
    a Windows call fails — silent degradation here cost us an orphan hunt once.
    """
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        _JobObjectExtendedLimitInformationClass,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    opened: list[int] = []
    try:
        for pid in process_ids:
            handle = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
            if not handle:
                raise OSError(ctypes.get_last_error(), f"OpenProcess({pid}) failed")
            opened.append(handle)
            # AssignProcessToJobObject needs the HANDLE, never the PID.
            if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(handle)):
                raise OSError(ctypes.get_last_error(), f"AssignProcessToJobObject({pid}) failed")
    except OSError:
        for handle in opened:
            kernel32.CloseHandle(handle)
        kernel32.CloseHandle(job)
        raise
    # Deliberately leak both the job and the child handles: their lifetime IS
    # the kill switch — the kernel closes them when our process dies.
    return True
