# Distribution Options for Remote Routes

## Option 1: PyInstaller (Recommended starting point)

Bundles Python + all dependencies + your code into a single `.exe` or a folder.

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=static/icons/app.ico src/app.py
```

- `--onefile` → single `.exe` (slower startup, ~30-80 MB)
- `--windowed` → no console window
- Output goes to `dist/RemoteRoutes.exe`

**Pros:** No Python required on target machine, truly standalone
**Cons:** Antivirus false positives, slow cold start with `--onefile`

---

## Option 2: PyInstaller + Inno Setup (Best for a "simple installer")

**PyInstaller** builds the exe, **Inno Setup** (free) wraps it into a proper Windows installer `.exe` that:

- Extracts files to `%ProgramFiles%\RemoteRoutes\`
- Creates `instance/` for the DB
- Creates Start Menu / Desktop shortcuts
- Adds an Uninstaller entry in Windows

This is the most common approach for distributing Windows desktop Python apps.

---

## Option 3: Nuitka (Better performance, harder to set up)

Compiles Python to C then to a native `.exe`. Faster startup, smaller binary, fewer AV false positives than PyInstaller.

---

## Recommended Workflow

### Project structure

```
Remote-Routes/
├── src/
├── static/
├── instance/          ← created by installer, not bundled
├── RemoteRoutes.spec  ← PyInstaller spec file
├── installer.iss      ← Inno Setup script
└── build.bat          ← one-click build script
```

### Build script

```bat
@echo off
echo Building RemoteRoutes...
pyinstaller RemoteRoutes.spec
echo Running Inno Setup...
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
echo Done! Installer is in dist/
```

---

## Recommendation

1. **Start with PyInstaller** — get a working `.exe` first
2. **Add Inno Setup** — wrap it into a proper installer with shortcuts and uninstaller
3. **Sign the `.exe`** (optional but removes SmartScreen warnings) — requires a code signing certificate (~$70-200/yr) or use a self-signed cert for internal/technical users
