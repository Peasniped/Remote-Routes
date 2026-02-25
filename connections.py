"""Connection launchers for SSH and RDP."""

import shutil
import subprocess
import sys
from typing import Optional


def _find_terminal() -> list[str]:
    """Return a command prefix that opens a new terminal window."""
    if sys.platform == "win32":
        return []  # Windows uses CREATE_NEW_CONSOLE instead

    if sys.platform == "darwin":
        return []  # macOS handled via `open -a Terminal`

    # Linux – try common terminal emulators
    for term in (
        "x-terminal-emulator",
        "gnome-terminal",
        "xfce4-terminal",
        "konsole",
        "xterm",
    ):
        if shutil.which(term):
            if term in ("gnome-terminal", "xfce4-terminal"):
                return [term, "--"]
            return [term, "-e"]

    raise RuntimeError(
        "No suitable terminal emulator found. "
        "Please install xterm or another terminal emulator."
    )


def launch_ssh(
    host: str, port: int, username: str, title_tag: str | None = None
) -> subprocess.Popen:
    """Open an SSH session and return the process handle."""
    ssh_cmd = ["ssh", "-p", str(port), f"{username}@{host}"]

    if sys.platform == "win32":
        if title_tag:
            # Wrap in cmd so we can set a known window title for
            # reliable screenshot discovery (works with Windows Terminal).
            shell_line = f'title {title_tag} & ssh -p {port} {username}@{host}'
            return subprocess.Popen(
                f'cmd /c "{shell_line}"',
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        return subprocess.Popen(
            ssh_cmd, creationflags=subprocess.CREATE_NEW_CONSOLE
        )

    if sys.platform == "darwin":
        script = f'tell application "Terminal" to do script "{" ".join(ssh_cmd)}"'
        return subprocess.Popen(["osascript", "-e", script])

    prefix = _find_terminal()
    return subprocess.Popen(prefix + ssh_cmd)


def launch_rdp(host: str, port: int, username: str) -> subprocess.Popen:
    """Open an RDP session and return the process handle."""
    if sys.platform == "win32":
        mstsc_args = ["mstsc", f"/v:{host}:{port}"]
        if username:
            mstsc_args += [f"/u:{username}"]
        return subprocess.Popen(mstsc_args)

    if sys.platform == "darwin":
        rdp_url = f"rdp://full%20address=s:{host}:{port}"
        if username:
            rdp_url += f"&username=s:{username}"
        return subprocess.Popen(["open", rdp_url])

    # Linux: prefer xfreerdp, fall back to rdesktop
    if shutil.which("xfreerdp"):
        cmd = [
            "xfreerdp",
            f"/v:{host}:{port}",
            f"/u:{username}",
            "/dynamic-resolution",
            "/cert-ignore",
        ]
        return subprocess.Popen(cmd)

    if shutil.which("rdesktop"):
        return subprocess.Popen(["rdesktop", "-u", username, f"{host}:{port}"])

    raise RuntimeError(
        "No RDP client found. Please install xfreerdp (freerdp2-x11) or rdesktop."
    )


def launch(
    conn_type: str, host: str, port: int, username: str,
    title_tag: str | None = None,
) -> subprocess.Popen:
    """Dispatch to the appropriate launcher and return the process handle."""
    if conn_type == "SSH":
        return launch_ssh(host, port, username, title_tag=title_tag)
    elif conn_type == "RDP":
        return launch_rdp(host, port, username)
    else:
        raise ValueError(f"Unknown connection type: {conn_type}")


# ── Window management (Windows only) ─────────────────────────────────────────

def bring_process_to_front(pid: int) -> bool:
    """Attempt to bring the main visible window of *pid* to the foreground.

    Returns True if a matching window was found and activated.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        found: list[int] = []

        def _cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                win_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value == pid:
                    found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)

        if found:
            hwnd = found[0]
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def _get_process_tree_pids(pid: int) -> list[int]:
    """Return *pid* plus all descendant PIDs using CreateToolhelp32Snapshot."""
    if sys.platform != "win32":
        return [pid]
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        kernel32 = ctypes.windll.kernel32

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == -1:
            return [pid]

        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

        # Build parent → children map
        children: dict[int, list[int]] = {}
        if kernel32.Process32First(snap, ctypes.byref(pe)):
            while True:
                children.setdefault(pe.th32ParentProcessID, []).append(
                    pe.th32ProcessID
                )
                if not kernel32.Process32Next(snap, ctypes.byref(pe)):
                    break
        kernel32.CloseHandle(snap)

        # BFS to collect all descendants
        result = [pid]
        queue = [pid]
        while queue:
            p = queue.pop(0)
            for child in children.get(p, []):
                if child not in result:
                    result.append(child)
                    queue.append(child)
        return result
    except Exception:
        return [pid]


def find_window_by_title(title_hint: str) -> int:
    """Return the HWND of the first visible window whose title contains
    *title_hint*, or 0 if none found."""
    if sys.platform != "win32" or not title_hint:
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        result = 0

        def _cb(h, _lp):
            nonlocal result
            if user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                if title_hint in buf.value:
                    result = int(h)
                    return False  # stop enumeration
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return result
    except Exception:
        return 0


def capture_window(
    *, pid: int = 0, hwnd: int = 0, title_hints: list[str] | None = None
) -> Optional[tuple]:
    """Capture a window as raw BGRA pixels.

    Lookup order:
      1. *hwnd*         – use directly if the handle is still valid
      2. *title_hints*  – find a visible window whose title contains any hint
      3. *pid*          – enumerate windows owned by the process tree

    Returns ``(found_hwnd, width, height, bytes)`` or ``None``.
    The caller should cache *found_hwnd* for fast subsequent captures.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # ── Declare function signatures for 64-bit safety ─────────────
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long),
            ]

        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowDC.argtypes = [wintypes.HWND]
        user32.GetWindowDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        user32.PrintWindow.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int

        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.GetDIBits.argtypes = [
            wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
        ]
        gdi32.GetDIBits.restype = ctypes.c_int

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def _best_window(candidates):
            """Pick the largest non-minimised window from a list of HWNDs."""
            best, best_area = None, -1
            for h in candidates:
                if user32.IsIconic(h):
                    continue
                r = RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                area = (r.right - r.left) * (r.bottom - r.top)
                if area > best_area:
                    best_area, best = area, h
            return best if best and best_area > 0 else None

        target = None

        # ── Strategy 1: Reuse a cached HWND ───────────────────────────
        if hwnd:
            if (user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd)
                    and not user32.IsIconic(hwnd)):
                r = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                if (r.right - r.left) > 0 and (r.bottom - r.top) > 0:
                    target = hwnd
                    print(f"[snap] reusing cached hwnd={hwnd}")

        # ── Strategy 2: Find window by title substring ────────────────
        hints = [h for h in (title_hints or []) if h]
        if not target and hints:
            hits: list[int] = []

            def _title_cb(h, _lp):
                if user32.IsWindowVisible(h):
                    buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(h, buf, 512)
                    title = buf.value
                    if any(hint in title for hint in hints):
                        hits.append(h)
                return True

            user32.EnumWindows(WNDENUMPROC(_title_cb), 0)
            target = _best_window(hits)
            if target:
                print(f"[snap] found by title hints {hints!r}: hwnd={target}")

        # ── Strategy 3: Find window by PID / process tree ─────────────
        if not target and pid:
            target_pids = set(_get_process_tree_pids(pid))
            hits2: list[int] = []

            def _pid_cb(h, _lp):
                if user32.IsWindowVisible(h):
                    wp = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(wp))
                    if wp.value in target_pids:
                        cls = ctypes.create_unicode_buffer(256)
                        user32.GetClassNameW(h, cls, 256)
                        if cls.value != "PseudoConsoleWindow":
                            hits2.append(h)
                return True

            user32.EnumWindows(WNDENUMPROC(_pid_cb), 0)
            target = _best_window(hits2)
            if target:
                print(f"[snap] found by PID tree: hwnd={target}")

        if target is None:
            print(f"[snap] no window found (pid={pid}, hints={hints!r})")
            return None

        # ── Capture the window ────────────────────────────────────────
        rect = RECT()
        user32.GetWindowRect(target, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            print(f"[snap] window {target} has zero size ({w}x{h})")
            return None

        hwnd_dc = user32.GetWindowDC(target)
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        old_bmp = gdi32.SelectObject(mem_dc, bmp)

        PW_RENDERFULLCONTENT = 2
        user32.PrintWindow(target, mem_dc, PW_RENDERFULLCONTENT)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        buf_size = w * h * 4
        buf = ctypes.create_string_buffer(buf_size)
        gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)

        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(target, hwnd_dc)

        print(f"[snap] captured hwnd={target} {w}x{h}")
        return (int(target), w, h, bytes(buf))

    except Exception as exc:
        print(f"[snap] exception: {exc}")
        return None
