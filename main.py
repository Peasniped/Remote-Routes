"""Entry point for Remote Routes."""

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from app import App, APP_QSS, _dark_palette


if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    qt_app.setStyle("Fusion")
    qt_app.setPalette(_dark_palette())
    qt_app.setStyleSheet(APP_QSS)
    qt_app.setFont(QFont("Segoe UI", 10))
    window = App()
    window.show()
    sys.exit(qt_app.exec())
