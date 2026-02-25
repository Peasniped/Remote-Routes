"""Connection launchers for SSH and RDP."""

import shutil
import subprocess
import sys


def _find_terminal() -> list[str]:
    """Return a command prefix that opens a new terminal window."""
    if sys.platform == "win32":
        # Windows Terminal → conhost fallback
        if shutil.which("wt"):
            return ["wt", "--"]
        return ["cmd", "/c", "start", "cmd", "/k"]

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


def launch_ssh(host: str, port: int, username: str) -> None:
    """Open an SSH session in the default terminal emulator."""
    ssh_cmd = ["ssh", "-p", str(port), f"{username}@{host}"]

    if sys.platform == "darwin":
        # macOS: ask Terminal.app to run the command
        script = f'tell application "Terminal" to do script "{" ".join(ssh_cmd)}"'
        subprocess.Popen(["osascript", "-e", script])
        return

    prefix = _find_terminal()
    subprocess.Popen(prefix + ssh_cmd)


def launch_rdp(host: str, port: int, username: str) -> None:
    """Open an RDP session using the platform's default RDP client."""
    if sys.platform == "win32":
        # mstsc ships with every modern Windows installation
        mstsc_args = ["mstsc", f"/v:{host}:{port}"]
        if username:
            mstsc_args += [f"/u:{username}"]
        subprocess.Popen(mstsc_args)
        return

    if sys.platform == "darwin":
        # Microsoft Remote Desktop for macOS (App Store)
        rdp_url = f"rdp://full%20address=s:{host}:{port}"
        if username:
            rdp_url += f"&username=s:{username}"
        subprocess.Popen(["open", rdp_url])
        return

    # Linux: prefer xfreerdp, fall back to rdesktop
    if shutil.which("xfreerdp"):
        cmd = [
            "xfreerdp",
            f"/v:{host}:{port}",
            f"/u:{username}",
            "/dynamic-resolution",
            "/cert-ignore",
        ]
        subprocess.Popen(cmd)
        return

    if shutil.which("rdesktop"):
        subprocess.Popen(["rdesktop", "-u", username, f"{host}:{port}"])
        return

    raise RuntimeError(
        "No RDP client found. Please install xfreerdp (freerdp2-x11) or rdesktop."
    )


def launch(conn_type: str, host: str, port: int, username: str) -> None:
    """Dispatch to the appropriate launcher based on connection type."""
    if conn_type == "SSH":
        launch_ssh(host, port, username)
    elif conn_type == "RDP":
        launch_rdp(host, port, username)
    else:
        raise ValueError(f"Unknown connection type: {conn_type}")
