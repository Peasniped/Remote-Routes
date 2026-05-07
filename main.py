"""Entry point for Remote Routes."""

import ctypes
import logging
import os
import sys

# Add src/ to the path so app, database and connections are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon
from PySide6.QtCore import QTimer

from app import App, APP_QSS, _dark_palette

LOGLEVEL = logging.INFO
LOGLEVEL = logging.DEBUG # DEBUG for development, INFO for production

logging.basicConfig(
    level=LOGLEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s:  %(message)s",
    datefmt="%H:%M:%S",
)


if __name__ == "__main__":
    # Give the app its own identity so Windows shows our icon in the taskbar
    # instead of grouping it with other python.exe processes.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Peasniped.RemoteRoutes")
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setPalette(_dark_palette())
    qt_app.setStyleSheet(APP_QSS)
    qt_app.setFont(QFont("Segoe UI", 10))
    _icon_path = os.path.join(os.path.dirname(__file__), "static", "logo.ico")
    qt_app.setWindowIcon(QIcon(_icon_path))
    window = App()
    # Defer show() to the next event-loop tick so all widget construction
    # and layout is complete before the OS renders the window frame.
    QTimer.singleShot(0, window.show)
    sys.exit(qt_app.exec())
