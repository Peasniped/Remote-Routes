# Remote-Routes
A very lightweight and simple Python-based program to store remote connection hosts and settings.

## Features
- Store SSH and RDP connection profiles (name, host, port, username, password, notes)
- Launch SSH sessions in the default terminal emulator
- Launch RDP sessions via the system's default RDP client
- Search/filter connections by name, host, or type
- Add, edit, and delete connections through a clean GUI

## Requirements
- Python 3.10+
- customtkinter (`pip install customtkinter`)

## Installation
```bash
pip install -r requirements.txt
```

## Usage
```bash
python main.py
```

## Connection types

### SSH
Opens an SSH session in the default terminal emulator.
- **Linux**: uses `x-terminal-emulator`, `gnome-terminal`, `xfce4-terminal`, `konsole`, or `xterm`
- **macOS**: opens in Terminal.app via AppleScript
- **Windows**: uses Windows Terminal (`wt`) or cmd

### RDP
Opens a Remote Desktop session.
- **Linux**: uses `xfreerdp` (package: `freerdp2-x11`) or `rdesktop`
- **macOS**: uses the `rdp://` URI scheme (Microsoft Remote Desktop from the App Store)
- **Windows**: uses the built-in `mstsc.exe`

## Data storage
Connection details are saved in an SQLite database at `~/.remote_routes.db`.

