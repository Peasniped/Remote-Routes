import os
import subprocess

def get_shortcut_path():
    """Get the path to the shortcut file on the desktop."""
    programs = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs")
    return os.path.join(programs, "Remote Routes.lnk")

def create_shortcut(shortcut_path:str):
    """Create a shortcut to the application at the specified path using PowerShell."""
    project_root = os.path.abspath(os.path.dirname(__file__))
    pythonw = os.path.join(project_root, ".venv", "Scripts", "pythonw.exe")
    script = os.path.join(project_root, "main.py")
    icon_path = os.path.join(project_root, "static", "logo.ico")
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell;'
        f'$s = $ws.CreateShortcut("{shortcut_path}");'
        f'$s.TargetPath = "{pythonw}";'
        f'$s.Arguments = \'"{script}"\';'
        f'$s.WorkingDirectory = "{project_root}";'
        f'$s.IconLocation = "{icon_path}";'
        f'$s.Save()'
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)


if __name__ == "__main__":
    shortcut_path = get_shortcut_path()
    create_shortcut(shortcut_path)
    print(f"Shortcut created at: {shortcut_path}")

