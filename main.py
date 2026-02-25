"""Entry point for Remote Routes."""

import logging
import os
import sys

# Add src/ to the path so app, database and connections are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from app import App, APP_QSS, _dark_palette

LOGLEVEL = logging.INFO
LOGLEVEL = logging.DEBUG

logging.basicConfig(
    level=LOGLEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s:  %(message)s",
    datefmt="%H:%M:%S",
)


if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setPalette(_dark_palette())
    qt_app.setStyleSheet(APP_QSS)
    qt_app.setFont(QFont("Segoe UI", 10))
    window = App()
    window.show()
    sys.exit(qt_app.exec())
