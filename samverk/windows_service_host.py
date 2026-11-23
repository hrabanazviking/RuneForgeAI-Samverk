"""S-410 -- the Windows service host: what the SCM launches.

`sc.exe` registers the service with a binPath; the Service
Control Manager will only run a program that answers the SCM
protocol (StartServiceCtrlDispatcher / SetServiceStatus). This
module is that program, in stdlib only: `ctypes` against
advapi32/kernel32, no pywin32, no new dependency (S-407's
register is untouched), no Docker, no WSL.

What it does, in order: registers its ServiceMain with the
dispatcher; reports START_PENDING; spawns the real server as
a child process (S-345's server entry, via
`windows_service.server_command` -- the database and repo
tree remain the meeting point, never a socket of ours);
reports RUNNING; waits on the child and on the stop event;
on SERVICE_CONTROL_STOP or SHUTDOWN it terminates the child,
waits for it, and reports STOPPED. If the child dies on its
own, ServiceMain returns and the SCM's declared failure
actions (restart after 60 s, S-410 spec) take it from there.

Importing this module is safe on every OS: no windll handle
is touched at import, and every Windows call lives inside
`_run_service`. `main()` off Windows refuses plainly with
the stable reason `windows_only` and exit code 2.

HONEST REMAINDER: this host has never run on a Windows
machine. Its structure, argument parsing, child command, and
off-Windows refusal are proven by the S-410 battery on Linux;
the SCM conversation itself is NOT PROVEN until a counted
run on a real Windows host (S-416's gate owns that claim).
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from . import platform_seam
from .windows_service import build_service_spec, server_command

__all__ = ["build_child_command", "parse_args", "main"]

# SCM constants (winbase.h / winsvc.h values, named once).
SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_RUNNING = 0x00000004
SERVICE_STOPPED = 0x00000001
SERVICE_START_PENDING = 0x00000002
SERVICE_STOP_PENDING = 0x00000003
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_SHUTDOWN = 0x00000005
ERROR_SERVICE_SPECIFIC_ERROR = 1066


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="samverk-windows-service-host",
        description="Samverk's native Windows service host (S-410).")
    parser.add_argument("--config", required=True,
                        help="path to samverk.ini")
    parser.add_argument("--data-root", required=True,
                        help="the instance data root")
    return parser.parse_args(argv)


def build_child_command(python_exe, config_path, data_root) -> list:
    """The server command this host supervises: the spec's
    server_command, composed through build_service_spec so the
    host and the registered binPath can never drift apart."""
    spec = build_service_spec(python_exe, data_root, config_path)
    return server_command(spec)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        family = platform_seam.os_name()
    except RuntimeError:
        family = "unknown"
    if family != "windows":
        print(f"windows_only: this host runs only on Windows "
              f"(this platform reports {family!r}); the service "
              f"definition itself lives in samverk.windows_service",
              file=sys.stderr)
        return 2
    return _run_service(args)


def _run_service(args) -> int:
    """The SCM conversation. Windows only; called by main()
    after the platform check. All ctypes structures are built
    here so importing this module never touches windll."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [("dwServiceType", wintypes.DWORD),
                    ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD),
                    ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD),
                    ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    class SERVICE_TABLE_ENTRY(ctypes.Structure):
        _fields_ = [("lpServiceName", wintypes.LPWSTR),
                    ("lpServiceProc", ctypes.c_void_p)]

    SERVICE_MAIN = ctypes.WINFUNCTYPE(None, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.LPWSTR))
    HANDLER = ctypes.WINFUNCTYPE(None, wintypes.DWORD)

    status = SERVICE_STATUS()
    status.dwServiceType = SERVICE_WIN32_OWN_PROCESS
    handle = ctypes.c_void_p()
    stop_event = kernel32.CreateEventW(None, True, False, None)

    def set_status(state, accept=0, win32_exit=0):
        status.dwCurrentState = state
        status.dwControlsAccepted = accept
        status.dwWin32ExitCode = win32_exit
        advapi32.SetServiceStatus(handle, ctypes.byref(status))

    @HANDLER
    def handler(control):
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            kernel32.SetEvent(stop_event)

    @SERVICE_MAIN
    def service_main(argc, argv):
        nonlocal handle
        handle = advapi32.RegisterServiceCtrlHandlerW(
            "Samverk", handler)
        if not handle:
            return
        set_status(SERVICE_START_PENDING)
        child = subprocess.Popen(build_child_command(
            sys.executable, args.config, args.data_root))
        set_status(SERVICE_RUNNING,
                   SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN)
        # Wait: child exit ends the service (SCM recovery acts);
        # a stop signal terminates the child first, cleanly.
        while True:
            if kernel32.WaitForSingleObject(stop_event, 500) == 0:
                set_status(SERVICE_STOP_PENDING)
                child.terminate()
                child.wait()
                break
            if child.poll() is not None:
                break
        set_status(SERVICE_STOPPED,
                   win32_exit=child.returncode or 0)

    table = (SERVICE_TABLE_ENTRY * 2)()
    table[0].lpServiceName = "Samverk"
    table[0].lpServiceProc = ctypes.cast(service_main, ctypes.c_void_p)
    if not advapi32.StartServiceCtrlDispatcherW(table):
        return ctypes.get_last_error() or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
