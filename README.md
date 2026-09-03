# Remote Routes

A lightweight desktop application for managing and launching remote SSH and RDP connections, built with Python and PySide6.

> **Note:** Generative AI has been used in this project.

## Features

- **Connection management** — store SSH and RDP profiles (name, host, port, credentials, notes)
- **One-click launch** — open SSH terminals or RDP sessions directly from the GUI
- **Live status indicators** — per-host ping dots show online/offline state
- **User management** — save reusable credential sets and link them to connections
- **Session tracking** — detects active terminal/RDP windows launched from the program.
- **Search & filter** — find connections by name or host (toggleable search bar)
- **Live screenshots** — captures previews of active sessions as card backgrounds (configurable interval)

## Requirements

- **Python 3.10+**
- **Windows** (primary target — Linux/macOS launch support exists but is less tested)
- Dependencies:
  - `PySide6 >= 6.10.2`

## Installation

```bash
git clone https://github.com/Peasniped/Remote-Routes.git
cd Remote-Routes
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

## Project Structure

```
Remote-Routes/
├── main.py              # Entry point
├── src/
│   ├── app.py           # GUI (PySide6): main window, cards, settings, dialogs
│   ├── connections.py   # SSH/RDP launch logic (cross-platform)
│   └── database.py      # SQLite database (CRUD, settings, screenshots)
├── static/icons/        # SVG icons
├── instance/            # Runtime data (SQLite DB, created automatically)
├── requirements.txt
├── ATTRIBUTIONS.md      # Third-party assets and their licenses
└── LICENSE              # GPL
```

## Connection Types

### SSH
Opens an SSH session in the default terminal emulator.
- **Windows**: Windows Terminal (`wt`) or `cmd`
- **Linux**: `x-terminal-emulator`, `gnome-terminal`, `xfce4-terminal`, `konsole`, or `xterm`
- **macOS**: Terminal.app via AppleScript

### RDP
Opens a Remote Desktop session.
- **Windows**: built-in `mstsc.exe`
- **Linux**: `xfreerdp` (`freerdp2-x11`) or `rdesktop`
- **macOS**: `rdp://` URI scheme (Microsoft Remote Desktop)

## Data Storage

All data is stored in a local SQLite database at `instance/.remote_routes.db`. The database is created automatically on first run.

## Roadmap

- **Host failover** — support both hostname and IP per host, with automatic failover
- **Web hosts** — shortcuts to web-based admin pages (HTTP/HTTPS + port)
- **Enhanced status dot** — hover tooltips, warning state for slow ping or partial reachability
- **Error handling** — surface connection errors (refused, auth failure) in the UI
- **UI/UX polish** — improved search bar, empty-state guidance, right-click copy, user search when linking credentials
- **Branding** — app logo in titlebar, taskbar icon, version info
- **Custom backgrounds** — per-host background images with screenshot fallback rules
- **Theming** — light theme toggle, fully configurable color schemes
- **Host grouping** — create/collapse groups, drag-and-drop reordering
- **Security review** — audit password storage

## Attributions

Icons are from [SVG Repo](https://www.svgrepo.com/). See [ATTRIBUTIONS.md](ATTRIBUTIONS.md)
for the full list of third-party assets and their licenses.

## License

[GNU General Public License v3.0](LICENSE)

