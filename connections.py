"""Connection launchers for SSH and RDP."""

import shutil
import subprocess
import sys


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


def launch_ssh(host: str, port: int, username: str) -> subprocess.Popen:
    """Open an SSH session and return the process handle."""
    ssh_cmd = ["ssh", "-p", str(port), f"{username}@{host}"]

    if sys.platform == "win32":
        # Open SSH in its own console window so we can track the process
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


def launch(conn_type: str, host: str, port: int, username: str) -> subprocess.Popen:
    """Dispatch to the appropriate launcher and return the process handle."""
    if conn_type == "SSH":
        return launch_ssh(host, port, username)
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
