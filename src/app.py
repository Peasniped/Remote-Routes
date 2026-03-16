"""Main GUI window for Remote Routes — PySide6."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QSize, QTimer, Signal, QObject, QPoint, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QAction, QBitmap, QColor, QFont, QFontMetrics, QIcon, QImage, QPalette, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import database
import connections as conn_launcher

log = logging.getLogger("app")

# ── Icon helpers ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ICONS_DIR = os.path.join(_PROJECT_ROOT, "static", "icons")
# Source colors in the SVG files that will be recolored at runtime.
# Adding a color here means it gets replaced for ALL icon loads — suitable for
# switching themes later by changing _ICON_FG and calling _load_icon again.
_ICON_DARK_COLORS = ("#000000", "#464455")

def _load_icon(name: str, color: str = "#e0e0e0", size: int = 16) -> QIcon:
    """Load an SVG from static/icons/, recolor it, and return a QIcon.

    Color is applied via string replacement on the SVG source — no second icon
    set needed for light/dark themes; just call with a different *color*.
    """
    path = os.path.join(_ICONS_DIR, f"{name}.svg")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            svg = fh.read()
        for dark in _ICON_DARK_COLORS:
            svg = svg.replace(dark, color)
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        p = QPainter(px)
        renderer.render(p)
        p.end()
        return QIcon(px)
    except Exception:
        return QIcon()


_DEFAULT_PORTS = {"SSH": 22, "RDP": 3389}
_PING_MS = 30_000
_PROC_MS = 3_000
_SNAP_MS = 30_000   # screenshot refresh interval
CARD_W = 200
CARD_H = 120
CARD_GAP = 14

# ── Thread-safe ping signal ───────────────────────────────────────────────────
class _PingBus(QObject):
    result = Signal(int, bool)  # conn_id, is_online

_ping_bus = _PingBus()


# ═══════════════════════════════════════════════════════════════════════════════
#  Painted ping dot (QPainter circle)
# ═══════════════════════════════════════════════════════════════════════════════
_DOT_DIAMETER = 10

class PingDot(QWidget):
    """A small filled circle drawn via QPainter — scales properly."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(_DOT_DIAMETER, _DOT_DIAMETER)
        self._color = QColor("#666")

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, _DOT_DIAMETER, _DOT_DIAMETER)
        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Trapezoid active badge
# ═══════════════════════════════════════════════════════════════════════════════
class ActiveBadge(QWidget):
    """Green trapezoid badge — wider at top, narrower at bottom.

    Given *length* (== widget width):
      P1 = (0, 0)                 top-left
      P2 = (L, 0)                 top-right
      P3 = (7L/8, L/8)           bottom-right
      P4 = (L/8, L/8)            bottom-left
    Height is always L / 8.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._text = ""
        self.hide()

    def setText(self, text: str) -> None:
        self._text = text
        if text:
            fm = self.fontMetrics()
            length = max(90, fm.horizontalAdvance(text) + 40)
            h = max(16, length // 8)
            self.setFixedSize(length, h)
            self.update()
            self.show()
        else:
            self.hide()

    def paintEvent(self, event) -> None:
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        L = float(self.width())
        h = float(self.height())
        inset = L / 8.0

        path = QPainterPath()
        path.moveTo(0, 0)              # P1 — top-left
        path.lineTo(L, 0)              # P2 — top-right
        path.lineTo(L - inset, h)      # P3 — bottom-right
        path.lineTo(inset, h)          # P4 — bottom-left
        path.closeSubpath()

        painter.fillPath(path, QColor("#22c55e"))

        f = painter.font()
        f.setBold(True)
        f.setPointSize(8)
        painter.setFont(f)
        painter.setPen(QColor("white"))
        painter.drawText(self.rect(), Qt.AlignCenter, self._text)
        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Protocol badge (small rounded square in bottom left)
# ═══════════════════════════════════════════════════════════════════════════════
class ProtocolBadge(QWidget):
    """Small rounded square badge displaying protocol (ex. SSH/RDP/WEB) in bottom left corner of host card."""

    BADGE_MARGIN = 10
    BADGE_PADDING = 6
    CORNER_RADIUS = 7

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._protocol = ""
        self.hide()

    def set_protocol(self, protocol: str) -> None:
        """Set the protocol text (e.g., 'SSH', 'RDP', 'WEB')."""
        self._protocol = protocol.upper()
        # Calculate size based on text
        fm = self.fontMetrics()
        f = self.font()
        f.setBold(True)
        f.setPointSize(7)
        fm = QFontMetrics(f)
        text_width = fm.horizontalAdvance(self._protocol)
        width = text_width + self.BADGE_PADDING * 2
        height = fm.height() + self.BADGE_PADDING
        self.setFixedSize(width, height)
        self.show()
        self.update()

    def paintEvent(self, event) -> None:
        if not self._protocol:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Determine color based on protocol
        color_map = {
            "SSH": QColor("#3b82f6"),   # Blue
            "RDP": QColor("#f97316"),   # Orange
            "WEB": QColor("#8b5cf6"),   # Purple
        }
        badge_color = color_map.get(self._protocol, QColor("#6b7280"))
        
        # Draw rounded square (filled, no border)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setBrush(badge_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        
        # Draw text
        f = painter.font()
        f.setBold(True)
        f.setPointSize(7)
        painter.setFont(f)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignCenter, self._protocol)
        painter.end()


# ── Dark palette ──────────────────────────────────────────────────────────────
def _dark_palette() -> QPalette:
    p = QPalette()
    dark   = QColor("#1e1e1e")
    mid    = QColor("#2d2d2d")
    light  = QColor("#3a3a3a")
    text   = QColor("#e0e0e0")
    dim    = QColor("#888888")
    accent = QColor("#1F6AA5")

    p.setColor(QPalette.Window,          dark)
    p.setColor(QPalette.WindowText,      text)
    p.setColor(QPalette.Base,            mid)
    p.setColor(QPalette.AlternateBase,   light)
    p.setColor(QPalette.ToolTipBase,     mid)
    p.setColor(QPalette.ToolTipText,     text)
    p.setColor(QPalette.Text,            text)
    p.setColor(QPalette.Button,          light)
    p.setColor(QPalette.ButtonText,      text)
    p.setColor(QPalette.BrightText,      QColor("white"))
    p.setColor(QPalette.Link,            accent)
    p.setColor(QPalette.Highlight,       accent)
    p.setColor(QPalette.HighlightedText, QColor("white"))
    p.setColor(QPalette.Disabled, QPalette.Text,       dim)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, dim)
    return p


# ── Application QSS (shapes, radii, colours) ─────────────────────────────────
APP_QSS = """
QMainWindow, QDialog { background-color: #1e1e1e; }

QWidget { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }

/* ─ scroll bars ─ */
QScrollBar:vertical {
    background: #1e1e1e; width: 7px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #444; border-radius: 3px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #1e1e1e; height: 7px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #444; border-radius: 3px; min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ─ scroll area ─ */
QScrollArea { border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ─ toolbar buttons ─ */
QPushButton#btn_add {
    background-color: #16a34a;
    border: none; border-radius: 8px;
}
QPushButton#btn_add:hover { background-color: #15803d; }

QPushButton#btn_settings {
    background-color: #475569;
    border: none; border-radius: 8px;
}
QPushButton#btn_settings:hover { background-color: #64748b; }

/* ─ context menu ─ */
QMenu {
    background-color: #252525;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 4px;
    color: #e0e0e0;
}
QMenu::item {
    padding: 6px 12px 6px 14px;
    border-radius: 4px;
}
QMenu::icon {
    padding-left: 10px;
}
QMenu::item:selected { background-color: #1F6AA5; }
QMenu::separator {
    height: 1px;
    background: #3a3a3a;
    margin: 4px 8px;
}

/* ─ dialog / page buttons ─ */
QPushButton#btn_back {
    background-color: #3a3a3a; color: white;
    border: none; border-radius: 6px; padding: 5px 14px;
}
QPushButton#btn_back:hover { background-color: #4a4a4a; }

QPushButton#btn_primary {
    background-color: #1F6AA5; color: white;
    border: none; border-radius: 6px; padding: 6px 20px;
}
QPushButton#btn_primary:hover { background-color: #1a5a8d; }

QPushButton#btn_secondary {
    background-color: #3a3a3a; color: white;
    border: none; border-radius: 6px; padding: 6px 20px;
}
QPushButton#btn_secondary:hover { background-color: #4a4a4a; }

QPushButton#btn_add_green {
    background-color: #16a34a; color: white;
    border: none; border-radius: 6px; padding: 5px 14px;
}
QPushButton#btn_add_green:hover { background-color: #15803d; }

QPushButton#btn_danger {
    background-color: #8B0000; color: white;
    border: none; border-radius: 5px; padding: 3px 8px;
}
QPushButton#btn_danger:hover { background-color: #6B0000; }

QPushButton#btn_neutral {
    background-color: #3a3a3a; color: white;
    border: none; border-radius: 5px; padding: 3px 8px;
}
QPushButton#btn_neutral:hover { background-color: #4a4a4a; }

/* ─ type toggle (SSH / RDP) ─ */
QPushButton#type_btn {
    background-color: #3a3a3a; color: #aaa;
    border: none; border-radius: 6px; padding: 5px 20px;
}
QPushButton#type_btn:checked {
    background-color: #1F6AA5; color: white;
}

/* ─ on/off setting toggles ─ */
QPushButton#toggle_btn {
    background-color: #3a3a3a; color: #aaa;
    border: none; border-radius: 6px; padding: 4px 14px;
    min-width: 54px;
}
QPushButton#toggle_btn:hover { background-color: #4a4a4a; color: #ccc; }
QPushButton#toggle_btn:checked {
    background-color: #16a34a; color: white;
}
QPushButton#toggle_btn:checked:hover { background-color: #15803d; }

/* ─ inputs ─ */
QLineEdit, QTextEdit {
    background-color: #2a2a2a; border: 1px solid #444;
    border-radius: 6px; padding: 5px 8px; color: #e0e0e0;
}
QLineEdit:focus, QTextEdit:focus { border-color: #1F6AA5; }
QLineEdit:disabled { color: #555; background-color: #222; }

QComboBox {
    background-color: #2a2a2a; border: 1px solid #444;
    border-radius: 6px; padding: 5px 8px; color: #e0e0e0;
}
QComboBox::drop-down { border: none; padding-right: 6px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background-color: #2a2a2a; border: 1px solid #555;
    selection-background-color: #1F6AA5; outline: none;
}

/* ─ settings user row ─ */
QFrame#user_row {
    background-color: #2d2d2d; border-radius: 8px;
    border: none;
}
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  Connection Dialog
# ═══════════════════════════════════════════════════════════════════════════════
class ConnectionDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, record=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Host" if record else "Add Host")
        self.setFixedWidth(420)
        self.setModal(True)
        self._result = None
        self._users = database.get_all_users()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        def _row(label: str, widget: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(80)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            row.addWidget(widget)
            return row

        # Name
        self._name = QLineEdit()
        layout.addLayout(_row("Name:", self._name))

        # Type
        type_row = QHBoxLayout()
        lbl_type = QLabel("Type:")
        lbl_type.setFixedWidth(80)
        lbl_type.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._btn_ssh = QPushButton("SSH")
        self._btn_ssh.setObjectName("type_btn")
        self._btn_ssh.setCheckable(True)
        self._btn_ssh.setChecked(True)
        self._btn_ssh.setFixedWidth(80)
        self._btn_rdp = QPushButton("RDP")
        self._btn_rdp.setObjectName("type_btn")
        self._btn_rdp.setCheckable(True)
        self._btn_rdp.setFixedWidth(80)
        # Exclusive toggle
        self._btn_ssh.clicked.connect(lambda: self._set_type("SSH"))
        self._btn_rdp.clicked.connect(lambda: self._set_type("RDP"))
        type_row.addWidget(lbl_type)
        type_row.addWidget(self._btn_ssh)
        type_row.addWidget(self._btn_rdp)
        type_row.addStretch()
        layout.addLayout(type_row)

        # Host & Port (same row)
        self._host = QLineEdit()
        self._port = QLineEdit()
        self._port.setFixedWidth(70)
        self._port.setText("22")
        hp_row = QHBoxLayout()
        lbl_h = QLabel("Host:")
        lbl_h.setFixedWidth(80)
        lbl_h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hp_row.addWidget(lbl_h)
        hp_row.addWidget(self._host)
        lbl_p = QLabel("Port:")
        lbl_p.setContentsMargins(8, 0, 0, 0)
        hp_row.addWidget(lbl_p)
        hp_row.addWidget(self._port)
        layout.addLayout(hp_row)

        # User dropdown
        user_labels = ["-- Manual --"] + [
            f"{u['display_name']} ({u['username']})" for u in self._users
        ]
        self._user_combo = QComboBox()
        self._user_combo.addItems(user_labels)
        self._user_combo.currentTextChanged.connect(self._on_user_change)
        layout.addLayout(_row("User:", self._user_combo))

        # Username
        self._username = QLineEdit()
        layout.addLayout(_row("Username:", self._username))

        # Password
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        layout.addLayout(_row("Password:", self._password))

        # Notes
        self._notes = QTextEdit()
        self._notes.setFixedHeight(56)
        layout.addLayout(_row("Notes:", self._notes))

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_save = QPushButton("Save")
        btn_save.setObjectName("btn_primary")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btn_secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        # Pre-populate
        if record:
            self._name.setText(record["name"])
            self._set_type(record["type"])
            self._host.setText(record["host"])
            self._port.setText(str(record["port"]))
            self._username.setText(record["username"])
            self._password.setText(record["password"])
            self._notes.setPlainText(record["notes"])
            if record["user_id"]:
                for u in self._users:
                    if u["id"] == record["user_id"]:
                        label = f"{u['display_name']} ({u['username']})"
                        idx = self._user_combo.findText(label)
                        if idx >= 0:
                            self._user_combo.setCurrentIndex(idx)
                        break

        self._name.setFocus()

    def _set_type(self, conn_type: str) -> None:
        self._btn_ssh.setChecked(conn_type == "SSH")
        self._btn_rdp.setChecked(conn_type == "RDP")
        cur = self._port.text().strip()
        if cur in ("", "22", "3389"):
            self._port.setText(str(_DEFAULT_PORTS[conn_type]))

    def _on_user_change(self, value: str) -> None:
        if value == "-- Manual --":
            self._username.setEnabled(True)
            self._password.setEnabled(True)
            return
        for u in self._users:
            if f"{u['display_name']} ({u['username']})" == value:
                self._username.setText(u["username"])
                self._username.setEnabled(False)
                self._password.setText(u["password"])
                self._password.setEnabled(False)
                break

    def _selected_user_id(self) -> Optional[int]:
        val = self._user_combo.currentText()
        if val == "-- Manual --":
            return None
        for u in self._users:
            if f"{u['display_name']} ({u['username']})" == val:
                return u["id"]
        return None

    def _save(self) -> None:
        name = self._name.text().strip()
        host = self._host.text().strip()
        port_str = self._port.text().strip()
        conn_type = "SSH" if self._btn_ssh.isChecked() else "RDP"
        user_id = self._selected_user_id()

        # Briefly re-enable to read values
        un_dis = not self._username.isEnabled()
        pw_dis = not self._password.isEnabled()
        self._username.setEnabled(True)
        self._password.setEnabled(True)
        username = self._username.text().strip()
        password = self._password.text()
        notes = self._notes.toPlainText().strip()
        if un_dis:
            self._username.setEnabled(False)
        if pw_dis:
            self._password.setEnabled(False)

        if not name:
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        if not host:
            QMessageBox.warning(self, "Validation", "Host is required.")
            return
        if not username:
            QMessageBox.warning(self, "Validation", "Username is required.")
            return
        try:
            port = int(port_str)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Validation", "Port must be 1–65535.")
            return

        self._result = {
            "name": name, "type": conn_type, "host": host, "port": port,
            "user_id": user_id, "username": username, "password": password,
            "notes": notes,
        }
        self.accept()

    @property
    def result(self):
        return self._result


# ═══════════════════════════════════════════════════════════════════════════════
#  User Dialog
# ═══════════════════════════════════════════════════════════════════════════════
class UserDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, user=None):
        super().__init__(parent)
        self.setWindowTitle("Edit User" if user else "Add User")
        self.setFixedWidth(340)
        self.setModal(True)
        self._result = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        def _row(label: str, widget: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            row.addWidget(widget)
            return row

        self._display_name = QLineEdit()
        layout.addLayout(_row("Display Name:", self._display_name))
        self._username = QLineEdit()
        layout.addLayout(_row("Username:", self._username))
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        layout.addLayout(_row("Password:", self._password))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_save = QPushButton("Save")
        btn_save.setObjectName("btn_primary")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("btn_secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        if user:
            self._display_name.setText(user["display_name"])
            self._username.setText(user["username"])
            self._password.setText(user["password"])

        self._display_name.setFocus()

    def _save(self) -> None:
        dn = self._display_name.text().strip()
        un = self._username.text().strip()
        pw = self._password.text()
        if not dn:
            QMessageBox.warning(self, "Validation", "Display name is required.")
            return
        if not un:
            QMessageBox.warning(self, "Validation", "Username is required.")
            return
        self._result = {"display_name": dn, "username": un, "password": pw}
        self.accept()

    @property
    def result(self):
        return self._result


# ═══════════════════════════════════════════════════════════════════════════════
#  Card inner frame with optional screenshot background
# ═══════════════════════════════════════════════════════════════════════════════
_CARD_BG = QColor("#2d2d2d")
_CARD_RADIUS = 22.0
_OVERLAY_COLOR = QColor(0, 0, 0, 160)   # semi-transparent dark fade
_BORDER_ACTIVE = QColor("#22c55e")
_BORDER_CONNECTING = QColor("#eab308")
_BORDER_WIDTH = 2.0
_HOVER_COLOR = QColor(37, 99, 235, 100)       # semi-transparent blue overlay on hover
_CONNECTING_OVERLAY = QColor(0, 0, 0, 180)   # semi-transparent dark


class CardInner(QFrame):
    """QFrame replacement that paints a rounded-rect background image + overlay."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bg_pixmap: QPixmap | None = None
        self._active = False
        self._connecting = False
        self._hover = False
        # Blur effect (disabled by default)
        self._blur_effect = QGraphicsBlurEffect(self)
        self._blur_effect.setBlurRadius(12)
        self._blur_effect.setEnabled(False)
        self.setGraphicsEffect(self._blur_effect)
        # Let QSS handle nothing — we do all painting ourselves.
        self.setStyleSheet("background: transparent; border: none;")

    def set_background(self, pixmap: QPixmap | None) -> None:
        self._bg_pixmap = pixmap
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def set_connecting(self, connecting: bool) -> None:
        self._connecting = connecting
        self._blur_effect.setEnabled(connecting)
        self.update()

    def set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._blur_effect.setEnabled(hover or self._connecting)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)

        # Clip everything to the rounded rect
        path = QPainterPath()
        path.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
        painter.setClipPath(path)

        # 1) Base colour
        painter.fillRect(rect, _CARD_BG)

        # 2) Background screenshot (if any)
        if self._bg_pixmap:
            scaled = self._bg_pixmap.scaled(
                w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = (scaled.width() - w) // 2
            y = (scaled.height() - h) // 2
            painter.drawPixmap(0, 0, scaled, x, y, w, h)
            painter.fillRect(rect, _OVERLAY_COLOR)

        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Overlay painted on top of all card children (hover / connecting)
# ═══════════════════════════════════════════════════════════════════════════════
class CardOverlay(QWidget):
    """Transparent widget that sits above all card children and paints overlays."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # clicks pass through
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self._hover = False
        self._hover_text = ""
        self._hover_icon: QIcon | None = None
        self._connecting = False
        self._connecting_text = ""
        self._active = False

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def set_hover(self, hover: bool, text: str = "", icon: "QIcon | None" = None) -> None:
        self._hover = hover
        self._hover_text = text
        self._hover_icon = icon
        self.update()

    def set_connecting(self, connecting: bool) -> None:
        self._connecting = connecting
        self.update()

    def set_connecting_text(self, text: str) -> None:
        self._connecting_text = text
        self.update()

    def paintEvent(self, event) -> None:
        show_hover = self._hover and not self._connecting
        show_connecting = self._connecting
        show_border = self._connecting or self._active
        if not show_hover and not show_connecting and not show_border:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
        painter.setClipPath(path)

        if show_hover:
            painter.fillRect(rect, _HOVER_COLOR)
            f = painter.font()
            f.setPointSize(13)
            f.setBold(True)
            painter.setFont(f)
            fm = painter.fontMetrics()
            text_h = fm.height()
            icon_size = 26
            gap = 6
            total_h = icon_size + gap + text_h
            group_top = (h - total_h) / 2
            # Icon centered above text
            if self._hover_icon:
                px = self._hover_icon.pixmap(icon_size, icon_size)
                painter.drawPixmap(int((w - icon_size) / 2), int(group_top), px)
            # Text below icon
            painter.setPen(QColor("white"))
            text_rect = QRectF(0, group_top + icon_size + gap, w, text_h + 4)
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, self._hover_text)

        if show_connecting:
            painter.fillRect(rect, _CONNECTING_OVERLAY)
            f = painter.font()
            f.setPointSize(12)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor("#eab308"))
            painter.drawText(rect, Qt.AlignCenter, self._connecting_text)

        # Border (painted above blur effect)
        painter.setClipping(False)
        if self._connecting:
            pen = QPen(_BORDER_CONNECTING, _BORDER_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            inset = _BORDER_WIDTH / 2
            painter.drawRoundedRect(
                QRectF(inset, inset, w - _BORDER_WIDTH, h - _BORDER_WIDTH),
                _CARD_RADIUS, _CARD_RADIUS,
            )
        elif self._active:
            pen = QPen(_BORDER_ACTIVE, _BORDER_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            inset = _BORDER_WIDTH / 2
            painter.drawRoundedRect(
                QRectF(inset, inset, w - _BORDER_WIDTH, h - _BORDER_WIDTH),
                _CARD_RADIUS, _CARD_RADIUS,
            )

        painter.end()


# ═══════════════════════════════════════════════════════════════════════════════
#  Host Card
# ═══════════════════════════════════════════════════════════════════════════════
class HostCard(QWidget):
    """Rounded card tile for a single remote host."""

    def __init__(self, record, on_left_click, on_right_click,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(CARD_W, CARD_H)
        self._apply_mask()

        self._record = record
        self._on_left = on_left_click
        self._on_right = on_right_click
        self._active_count = 0
        self._connecting = False
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._animate_dots)
        self._dot_count = 0
        # Pre-load hover icons once per card (QApp already running at this point)
        self._icon_connect = _load_icon("paperplane-svgrepo", color="white", size=26)
        self._icon_bring = _load_icon("bring-to-front-svgrepo", color="white", size=26)

        # ── inner card frame ──────────────────────────────────────────────
        self._inner = CardInner(self)
        self._inner.setGeometry(0, 0, CARD_W, CARD_H)

        # ── card internals ────────────────────────────────────────────────
        card_layout = QVBoxLayout(self._inner)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ping dot — painted circle, top-right corner
        self._ping_dot = PingDot(self._inner)
        FROM_RIGHT = 14
        FROM_TOP = 14
        self._ping_dot.move(CARD_W - FROM_TOP - FROM_RIGHT, FROM_TOP)  # 18px from right, 12px from top

        # hostname + IP group — centred vertically in the card
        card_layout.addStretch(1)

        info = QWidget()
        info.setAttribute(Qt.WA_TranslucentBackground)
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(8, 0, 8, 0)
        info_layout.setSpacing(2)

        self._name_lbl = QLabel(record["name"])
        self._name_lbl.setAlignment(Qt.AlignCenter)
        self._name_lbl.setStyleSheet(
            "background: transparent; font-size: 16px; font-weight: bold;"
        )
        info_layout.addWidget(self._name_lbl)

        default_port = _DEFAULT_PORTS.get(record["type"])
        port_suffix = "" if record["port"] == default_port else f":{record['port']}"
        self._addr_lbl = QLabel(f"{record['host']}{port_suffix}")
        self._addr_lbl.setAlignment(Qt.AlignCenter)
        self._addr_lbl.setStyleSheet(
            "background: transparent; font-size: 10px; color: #888;"
        )
        info_layout.addWidget(self._addr_lbl)

        self._info_widget = info   # store ref for hide/show
        card_layout.addWidget(info)
        card_layout.addStretch(1)

        # ── trapezoid badge (child of self, floats centred at top of _inner) ─
        self._badge = ActiveBadge(self)

        # ── protocol badge (child of self, positioned bottom-left) ────────
        self._protocol_badge = ProtocolBadge(self)
        protocol = record["type"]
        self._protocol_badge.set_protocol(protocol)
        # Position in bottom-left corner with 8px margin
        badge_h = self._protocol_badge.height()
        margin = self._protocol_badge.BADGE_MARGIN
        self._protocol_badge.move(margin, CARD_H - badge_h - margin)
        # Check setting to show/hide
        show_badge = database.get_setting("show_protocol_badge") != "0"
        self._protocol_badge.setVisible(show_badge)

        # ── overlay for hover / connecting (sits above everything) ────────
        self._overlay = CardOverlay(self)
        self._overlay.setGeometry(0, 0, CARD_W, CARD_H)
        self._overlay.raise_()

        # Badge must be above overlay so it isn't tinted
        self._badge.raise_()

        # ── hover / connecting state ──────────────────────────────────────
        self._hover_active = False
        self._hover_text = ""
        self._connecting_text = ""

    # ── helpers ───────────────────────────────────────────────────────────
    def _apply_mask(self) -> None:
        """Clip HostCard to a rounded rect so blurred CardInner can't bleed past corners."""
        bmp = QBitmap(self.size())
        bmp.fill(Qt.color0)
        p = QPainter(bmp)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.color1)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()),
                          _CARD_RADIUS, _CARD_RADIUS)
        p.end()
        self.setMask(bmp)

    def _place_badge(self) -> None:
        """Centre the badge horizontally, flush with the card's top edge."""
        bw = self._badge.width()
        x = (CARD_W - bw) // 2
        self._badge.move(x, 0)          # top of badge == top of card

    # ── mouse ─────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_left(self._record)
        elif event.button() == Qt.RightButton:
            self._on_right(self._record, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        if not self._connecting:
            if self._active_count > 0:
                self._hover_text = "Bring to front"
                icon = self._icon_bring
            else:
                self._hover_text = "Connect"
                icon = self._icon_connect
            self._hover_active = True
            self._inner.set_hover(True)
            self._overlay.set_hover(True, self._hover_text, icon)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_active = False
        self._inner.set_hover(False)
        self._overlay.set_hover(False)
        super().leaveEvent(event)

    # ── public API ────────────────────────────────────────────────────────
    def set_online(self, online: bool | None) -> None:
        self._ping_dot.set_color(
            "#666" if online is None else "#22c55e" if online else "#ef4444"
        )

    def set_active_count(self, count: int) -> None:
        self._active_count = count
        active = count > 0
        self._inner.set_active(active)
        self._overlay.set_active(active)
        if active:
            self._badge.setText("Active" if count == 1 else f"{count} active")
            self._place_badge()
        else:
            self._badge.setText("")   # hides automatically

    def set_background(self, pixmap: QPixmap | None) -> None:
        """Set a screenshot as the card background (with dark overlay)."""
        self._inner.set_background(pixmap)

    def set_connecting(self, connecting: bool) -> None:
        """Show/hide the 'Connecting...' animation with yellow border."""
        self._connecting = connecting
        if connecting:
            self._dot_count = 0
            self._inner.set_connecting(True)
            self._connecting_text = "Connecting"
            self._overlay.set_connecting(True)
            self._overlay.set_connecting_text("Connecting")
            self._dot_timer.start(500)
            self.setCursor(Qt.ForbiddenCursor)
        else:
            self._dot_timer.stop()
            self._inner.set_connecting(False)
            self._connecting_text = ""
            self._overlay.set_connecting(False)
            self._overlay.set_connecting_text("")
            self.setCursor(Qt.PointingHandCursor)

    def _animate_dots(self) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        self._connecting_text = f"Connecting{dots}"
        self._overlay.set_connecting_text(self._connecting_text)

    def update_protocol_badge_visibility(self) -> None:
        """Update protocol badge visibility based on settings."""
        show_badge = database.get_setting("show_protocol_badge") != "0"
        self._protocol_badge.setVisible(show_badge)

    @property
    def record(self):
        return self._record


# ═══════════════════════════════════════════════════════════════════════════════
#  Responsive card grid
# ═══════════════════════════════════════════════════════════════════════════════
class CardGrid(QWidget):
    """Widget that holds HostCards in a reflowing grid."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cards: list[HostCard] = []
        self._layout = QGridLayout(self)
        self._layout.setSpacing(CARD_GAP)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

    def set_cards(self, cards: list[HostCard]) -> None:
        for card in self._cards:
            self._layout.removeWidget(card)
        self._cards = cards
        self._reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        if not self._cards:
            return
        cols = max(1, (self.width() - 24) // (CARD_W + CARD_GAP))
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // cols, i % cols,
                                   Qt.AlignTop | Qt.AlignLeft)


# ═══════════════════════════════════════════════════════════════════════════════
#  Settings page
# ═══════════════════════════════════════════════════════════════════════════════
class SettingsPage(QWidget):
    def __init__(self, on_back, on_settings_changed=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_back = on_back
        self._on_settings_changed = on_settings_changed or (lambda: None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        btn_back = QPushButton("← Back")
        btn_back.setObjectName("btn_back")
        btn_back.setFixedWidth(80)
        btn_back.clicked.connect(on_back)
        header.addWidget(btn_back)
        title = QLabel("Settings")
        title.setStyleSheet(
            "font-size: 20px; font-weight: bold; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        # Tab widget
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # ── General tab ───────────────────────────────────────────────────
        general_page = QWidget()
        gen_layout = QVBoxLayout(general_page)
        gen_layout.setContentsMargins(12, 12, 12, 12)
        gen_layout.setSpacing(8)

        self._search_bar_toggle = self._make_toggle_row(
            gen_layout, "Search Bar",
            "Show the search bar in the toolbar",
            "show_search_bar",
        )
        self._search_bar_toggle.toggled.connect(self._on_search_bar_changed)

        self._protocol_badge_toggle = self._make_toggle_row(
            gen_layout, "Protocol Badge",
            "Show protocol (SSH/RDP/WEB) badge on host cards",
            "show_protocol_badge",
        )
        self._protocol_badge_toggle.toggled.connect(self._on_protocol_badge_changed)

        snap_on = database.get_setting("screenshot_enabled") != "0"

        # Screenshots group — single rounded card containing toggle + interval
        snap_group = QFrame()
        snap_group.setObjectName("user_row")
        snap_group.setAttribute(Qt.WA_StyledBackground, True)
        snap_vl = QVBoxLayout(snap_group)
        snap_vl.setContentsMargins(0, 0, 0, 0)
        snap_vl.setSpacing(0)

        # Top section: title/description + toggle button
        snap_top = QWidget()
        snap_top.setAttribute(Qt.WA_TranslucentBackground)
        snap_top_l = QHBoxLayout(snap_top)
        snap_top_l.setContentsMargins(12, 8, 12, 8)
        snap_top_l.setSpacing(8)
        snap_col = QVBoxLayout()
        snap_col.setSpacing(2)
        snap_title = QLabel("Screenshots")
        snap_title.setStyleSheet("font-weight: bold; background: transparent;")
        snap_col.addWidget(snap_title)
        snap_desc = QLabel("Capture window screenshots as card backgrounds")
        snap_desc.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        snap_col.addWidget(snap_desc)
        snap_top_l.addLayout(snap_col)
        snap_top_l.addStretch()
        self._snap_toggle = QPushButton("ON" if snap_on else "OFF")
        self._snap_toggle.setObjectName("toggle_btn")
        self._snap_toggle.setCheckable(True)
        self._snap_toggle.setChecked(snap_on)
        self._snap_toggle.setFixedWidth(60)
        snap_top_l.addWidget(self._snap_toggle)
        self._snap_toggle.toggled.connect(self._on_screenshot_changed)
        snap_vl.addWidget(snap_top)

        # Separator + interval row (hidden together when screenshots is OFF)
        self._snap_sep = QFrame()
        self._snap_sep.setFrameShape(QFrame.HLine)
        self._snap_sep.setStyleSheet("background: #3a3a3a; max-height: 1px; border: none;")
        self._snap_sep.setVisible(snap_on)
        snap_vl.addWidget(self._snap_sep)

        self._interval_row = QWidget()
        self._interval_row.setStyleSheet("background: transparent;")
        irl = QHBoxLayout(self._interval_row)
        irl.setContentsMargins(12, 8, 12, 8)
        irl.setSpacing(8)
        lbl_interval = QLabel("Capture interval")
        lbl_interval.setStyleSheet("background: transparent;")
        irl.addWidget(lbl_interval)
        irl.addStretch()
        self._interval_edit = QLineEdit()
        self._interval_edit.setFixedWidth(60)
        self._interval_edit.setAlignment(Qt.AlignCenter)
        val = database.get_setting("screenshot_interval")
        self._interval_edit.setText(val if val else "30")
        self._interval_edit.editingFinished.connect(self._on_interval_changed)
        irl.addWidget(self._interval_edit)
        lbl_secs = QLabel("seconds")
        lbl_secs.setStyleSheet("background: transparent;")
        irl.addWidget(lbl_secs)
        self._interval_row.setVisible(snap_on)
        snap_vl.addWidget(self._interval_row)

        gen_layout.addWidget(snap_group)

        gen_layout.addStretch()
        self._tabs.addTab(general_page, "General")

        # ── Users tab ─────────────────────────────────────────────────
        users_page = QWidget()
        users_layout = QVBoxLayout(users_page)
        users_layout.setContentsMargins(12, 12, 12, 12)
        users_layout.setSpacing(8)

        sec_row = QHBoxLayout()
        sec_row.addStretch()
        btn_add_user = QPushButton("+ Add User")
        btn_add_user.setObjectName("btn_add_green")
        btn_add_user.clicked.connect(self._add_user)
        sec_row.addWidget(btn_add_user)
        users_layout.addLayout(sec_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setAttribute(Qt.WA_TranslucentBackground)
        self._list_container = QWidget()
        self._list_container.setAttribute(Qt.WA_TranslucentBackground)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_container)
        users_layout.addWidget(self._scroll, 1)

        self._tabs.addTab(users_page, "Users")

        self.refresh()

    def refresh(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        users = database.get_all_users()
        if not users:
            placeholder = QLabel(
                "No users yet. Click '+ Add User' to create one."
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #666; background: transparent;")
            self._list_layout.insertWidget(0, placeholder)
            return

        for i, u in enumerate(users):
            row = QFrame()
            row.setObjectName("user_row")
            row.setAttribute(Qt.WA_StyledBackground, True)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 6, 12, 6)
            row_layout.setSpacing(8)

            name_lbl = QLabel(u["display_name"])
            name_lbl.setStyleSheet("font-weight: bold; background: transparent;")
            row_layout.addWidget(name_lbl)
            un_lbl = QLabel(f"({u['username']})")
            un_lbl.setStyleSheet("color: #888; background: transparent;")
            row_layout.addWidget(un_lbl)
            row_layout.addStretch()

            btn_edit = QPushButton()
            btn_edit.setObjectName("btn_neutral")
            btn_edit.setIcon(_load_icon("edit-svgrepo", color="#e0e0e0", size=14))
            btn_edit.setIconSize(QSize(14, 14))
            btn_edit.setFixedSize(30, 26)
            btn_edit.clicked.connect(
                lambda _checked, uid=u["id"]: self._edit_user(uid)
            )
            row_layout.addWidget(btn_edit)

            btn_del = QPushButton()
            btn_del.setObjectName("btn_danger")
            btn_del.setIcon(_load_icon("delete-svgrepo", color="#e0e0e0", size=14))
            btn_del.setIconSize(QSize(14, 14))
            btn_del.setFixedSize(30, 26)
            btn_del.clicked.connect(
                lambda _checked, uid=u["id"], nm=u["display_name"]:
                    self._del_user(uid, nm)
            )
            row_layout.addWidget(btn_del)

            self._list_layout.insertWidget(i, row)

    def _add_user(self) -> None:
        dlg = UserDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            database.add_user(**dlg.result)
            self.refresh()

    def _edit_user(self, uid: int) -> None:
        user = database.get_user_by_id(uid)
        if not user:
            return
        dlg = UserDialog(self, user=user)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            database.update_user(uid, **dlg.result)
            self.refresh()

    def _del_user(self, uid: int, name: str) -> None:
        reply = QMessageBox.question(
            self, "Confirm", f"Delete user '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            database.delete_user(uid)
            self.refresh()

    # ── General settings helpers ──────────────────────────────────────────
    def _make_toggle_row(self, layout, title: str, desc: str,
                         key: str, default: str = "1") -> QPushButton:
        """Create a labeled toggle row, add to *layout*, return the button."""
        row = QFrame()
        row.setObjectName("user_row")
        row.setAttribute(Qt.WA_StyledBackground, True)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 8, 12, 8)
        rl.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-weight: bold; background: transparent;")
        col.addWidget(title_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        col.addWidget(desc_lbl)
        rl.addLayout(col)
        rl.addStretch()
        current = database.get_setting(key)
        is_on = (current if current != "" else default) != "0"
        btn = QPushButton("ON" if is_on else "OFF")
        btn.setObjectName("toggle_btn")
        btn.setCheckable(True)
        btn.setChecked(is_on)
        btn.setFixedWidth(60)
        rl.addWidget(btn)
        layout.addWidget(row)
        return btn

    def _on_search_bar_changed(self, checked: bool) -> None:
        database.set_setting("show_search_bar", "1" if checked else "0")
        self._search_bar_toggle.setText("ON" if checked else "OFF")
        self._on_settings_changed()

    def _on_protocol_badge_changed(self, checked: bool) -> None:
        database.set_setting("show_protocol_badge", "1" if checked else "0")
        self._protocol_badge_toggle.setText("ON" if checked else "OFF")
        self._on_settings_changed()

    def _on_screenshot_changed(self, checked: bool) -> None:
        database.set_setting("screenshot_enabled", "1" if checked else "0")
        self._snap_toggle.setText("ON" if checked else "OFF")
        self._snap_sep.setVisible(checked)
        self._interval_row.setVisible(checked)
        self._on_settings_changed()

    def _on_interval_changed(self) -> None:
        text = self._interval_edit.text().strip()
        if text.isdigit() and int(text) >= 5:
            database.set_setting("screenshot_interval", text)
            self._on_settings_changed()


# ═══════════════════════════════════════════════════════════════════════════════
#  Main window
# ═══════════════════════════════════════════════════════════════════════════════
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Routes")
        self.setWindowIcon(QIcon(os.path.join(_PROJECT_ROOT, "static", "logo.ico")))
        self.resize(820, 540)
        self.setMinimumSize(CARD_W + 48, 420)

        database.init_db()

        self._procs: dict[int, list[subprocess.Popen]] = {}
        self._ping_cache: dict[int, Optional[bool]] = {}
        self._cards: dict[int, HostCard] = {}
        self._snap_hwnds: dict[int, list[int]] = {}   # cid → cached HWNDs
        self._snap_tags: dict[int, list[str]] = {}     # cid → title hints (accumulated)
        self._popen_hwnds: set[int] = set()             # HWNDs discovered for Popen-backed launches
        self._launch_counter: int = 0                   # unique tag suffix
        self._connecting_cids: set[int] = set()         # cids currently connecting

        # Connect ping bus (emitted from background threads)
        _ping_bus.result.connect(self._set_ping)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._build_overview()
        self._settings_page = SettingsPage(
            on_back=self._show_overview,
            on_settings_changed=self._apply_general_settings,
        )
        self._stack.addWidget(self._overview_page)
        self._stack.addWidget(self._settings_page)

        self._show_overview()

        self._proc_timer = QTimer(self)
        self._proc_timer.timeout.connect(self._check_processes)
        self._proc_timer.start(_PROC_MS)

        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._ping_all)
        self._ping_timer.start(_PING_MS)

        self._snap_timer = QTimer(self)
        self._snap_timer.timeout.connect(self._snap_all)
        self._snap_timer.start(_SNAP_MS)

        # Apply persisted General settings (search bar visibility, screenshot timer)
        self._apply_general_settings()

        # Reattach to windows left open from a previous session
        self._reattach_sessions()

    # ── Session reattach ────────────────────────────────────────────────────
    def _reattach_sessions(self) -> None:
        """Restore active-connection state for windows still alive from a
        previous run of the application."""
        sessions = database.get_sessions()
        if not sessions:
            return

        reattached: dict[int, list[int]] = {}  # cid → [hwnds]
        stale_ids: list[int] = []

        for s in sessions:
            cid, hwnd, tag = s["conn_id"], s["hwnd"], s["tag"]
            if hwnd and conn_launcher.is_window_valid(hwnd):
                reattached.setdefault(cid, []).append(hwnd)
                # Restore tracking data
                hwnd_list = self._snap_hwnds.setdefault(cid, [])
                if hwnd not in hwnd_list:
                    hwnd_list.append(hwnd)
                tag_list = self._snap_tags.setdefault(cid, [])
                if tag and tag not in tag_list:
                    tag_list.append(tag)
            else:
                stale_ids.append(s["id"])

        # Clean up rows for windows that no longer exist
        for sid in stale_ids:
            with database._get_conn() as conn:
                conn.execute("DELETE FROM active_sessions WHERE id = ?", (sid,))
                conn.commit()

        if not reattached:
            return

        log.info("Reattached %d window(s) across %d connection(s)",
                 sum(len(v) for v in reattached.values()), len(reattached))

        # Update cards to show the reattached windows as active
        for cid, hwnds in reattached.items():
            card = self._cards.get(cid)
            if card:
                card.set_active_count(len(hwnds))

        # Trigger a screenshot refresh for reattached connections
        QTimer.singleShot(1000, self._snap_all)

    # ── Close event ────────────────────────────────────────────────────────
    def closeEvent(self, event) -> None:
        """Prompt the user if connections are still open."""
        # Collect all connections that have live windows (either tracked
        # processes that are still running, or reattached HWNDs).
        active_cids: dict[int, int] = {}  # cid → window count
        for cid, procs in self._procs.items():
            alive = [p for p in procs if p.poll() is None]
            if alive:
                active_cids[cid] = len(alive)
        # Also count reattached-only windows (no Popen, just HWNDs)
        for cid, hwnds in self._snap_hwnds.items():
            if cid not in active_cids:
                valid = [h for h in hwnds if conn_launcher.is_window_valid(h)]
                if valid:
                    active_cids[cid] = len(valid)

        if not active_cids:
            database.clear_sessions()
            event.accept()
            return

        # Build a readable list of open connections
        lines: list[str] = []
        all_conns = {r["id"]: r for r in database.get_all_connections()}
        for cid, count in active_cids.items():
            rec = all_conns.get(cid)
            name = rec["name"] if rec else f"Connection {cid}"
            suffix = f"  ({count} windows)" if count > 1 else ""
            lines.append(f"  • {name}{suffix}")

        dlg = QMessageBox(self)
        dlg.setWindowTitle("Open Connections")
        dlg.setIcon(QMessageBox.Question)
        dlg.setText(
            "The following connections are still open:\n\n"
            + "\n".join(lines)
        )
        dlg.setInformativeText("What would you like to do?")
        btn_close = dlg.addButton("Close them", QMessageBox.DestructiveRole)
        btn_leave = dlg.addButton("Leave running", QMessageBox.AcceptRole)
        btn_cancel = dlg.addButton("Cancel", QMessageBox.RejectRole)
        dlg.setDefaultButton(btn_leave)
        dlg.exec()

        clicked = dlg.clickedButton()
        if clicked == btn_cancel:
            event.ignore()
            return

        if clicked == btn_close:
            # Kill every tracked process tree
            for cid, procs in list(self._procs.items()):
                for proc in procs:
                    try:
                        conn_launcher.kill_process_tree(proc.pid)
                    except Exception:
                        pass
            # Also kill reattached-only windows (no Popen)
            for cid, hwnds in list(self._snap_hwnds.items()):
                for hwnd in hwnds:
                    if conn_launcher.is_window_valid(hwnd):
                        # Find the PID of the window and kill its tree
                        try:
                            import ctypes
                            from ctypes import wintypes
                            user32 = ctypes.windll.user32
                            wp = wintypes.DWORD()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
                            if wp.value:
                                conn_launcher.kill_process_tree(wp.value)
                        except Exception:
                            pass
            database.clear_sessions()
        else:
            # "Leave running" — sessions are already persisted
            pass

        event.accept()

    # ── Overview page ─────────────────────────────────────────────────────
    def _build_overview(self) -> None:
        self._overview_page = QWidget()
        outer = QVBoxLayout(self._overview_page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setAttribute(Qt.WA_TranslucentBackground)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(12, 12, 12, 4)
        tb.setSpacing(6)

        # Right button group — built first so we know its exact width
        btn_add = QPushButton()
        btn_add.setObjectName("btn_add")
        btn_add.setFixedSize(30, 30)
        btn_add.setIcon(_load_icon("plus-svgrepo", size=20))
        btn_add.setIconSize(QSize(20, 20))
        btn_add.setToolTip("Add host")
        btn_add.clicked.connect(self._add_host)

        btn_settings = QPushButton()
        btn_settings.setObjectName("btn_settings")
        btn_settings.setFixedSize(30, 30)
        btn_settings.setIcon(_load_icon("settings-svgrepo", size=20))
        btn_settings.setIconSize(QSize(20, 20))
        btn_settings.setToolTip("Settings")
        btn_settings.clicked.connect(self._show_settings)

        right_group = QWidget()
        right_group.setAttribute(Qt.WA_TranslucentBackground)
        rg = QHBoxLayout(right_group)
        rg.setContentsMargins(0, 0, 0, 0)
        rg.setSpacing(6)
        rg.addWidget(btn_add)
        rg.addWidget(btn_settings)
        _right_w = 30 + 6 + 30  # must match left_spacer width

        # Left spacer mirrors the right button group width so the centre is symmetric
        left_spacer = QWidget()
        left_spacer.setFixedWidth(_right_w)
        left_spacer.setAttribute(Qt.WA_TranslucentBackground)

        # Centre section — search bar is centred within it via inner stretches
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setMaximumWidth(260)
        self._search_edit.setMinimumWidth(60)
        self._search_edit.setFixedHeight(30)
        self._search_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._search_edit.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444;"
            " border-radius: 8px; padding: 4px 10px; color: #e0e0e0;"
        )
        self._search_edit.textChanged.connect(self._refresh_cards)

        center = QWidget()
        center.setAttribute(Qt.WA_TranslucentBackground)
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addStretch(1)
        cl.addWidget(self._search_edit, 1)  # stretch=1 so it grows; capped by maxWidth
        cl.addStretch(1)

        tb.addWidget(left_spacer)
        tb.addWidget(center, 1)   # takes all remaining space
        tb.addWidget(right_group)

        outer.addWidget(toolbar)

        # Scrollable card grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._card_grid = CardGrid()
        self._scroll.setWidget(self._card_grid)
        outer.addWidget(self._scroll, 1)

    # ── Page switching ────────────────────────────────────────────────────
    def _show_overview(self) -> None:
        self._stack.setCurrentWidget(self._overview_page)
        if hasattr(self, "_snap_timer"):
            self._apply_general_settings()
        else:
            self._refresh_cards()

    def _show_settings(self) -> None:
        self._stack.setCurrentWidget(self._settings_page)
        self._settings_page.refresh()

    def _apply_general_settings(self) -> None:
        """Read General-tab settings from the DB and apply them immediately."""
        # Search bar visibility
        show_search = database.get_setting("show_search_bar") != "0"
        self._search_edit.setVisible(show_search)
        # Screenshot timer
        snap_enabled = database.get_setting("screenshot_enabled") != "0"
        if snap_enabled:
            interval_s = database.get_setting("screenshot_interval")
            ms = max(5, int(interval_s)) * 1000 if interval_s.isdigit() else _SNAP_MS
            self._snap_timer.setInterval(ms)
            if not self._snap_timer.isActive():
                self._snap_timer.start()
        else:
            self._snap_timer.stop()
        self._refresh_cards()

    # ── Cards ─────────────────────────────────────────────────────────────
    def _refresh_cards(self) -> None:
        query = self._search_edit.text().lower() if self._search_edit.isVisible() else ""
        rows = database.get_all_connections()
        filtered = [
            r for r in rows
            if query in r["name"].lower()
            or query in r["host"].lower()
            or query in r["type"].lower()
        ]

        for card in self._cards.values():
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        new_cards: list[HostCard] = []
        for rec in filtered:
            card = HostCard(rec, self._on_card_left, self._on_card_right)
            self._cards[rec["id"]] = card
            card.set_online(self._ping_cache.get(rec["id"]))
            card.set_active_count(self._active_window_count(rec["id"]))
            if rec["id"] in self._connecting_cids:
                card.set_connecting(True)
            # Restore persisted screenshot
            png = database.get_screenshot(rec["id"])
            if png:
                pix = QPixmap()
                pix.loadFromData(png, "PNG")
                if not pix.isNull():
                    card.set_background(pix)
            new_cards.append(card)

        self._card_grid.set_cards(new_cards)
        self._ping_all()

    # ── Ping ──────────────────────────────────────────────────────────────
    def _ping_all(self) -> None:
        for cid, card in self._cards.items():
            self._ping_host(cid, card.record["host"])

    def _ping_host(self, cid: int, host: str) -> None:
        def _work():
            try:
                if sys.platform == "win32":
                    cmd = ["ping", "-n", "1", "-w", "1500", host]
                    kw: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
                else:
                    cmd = ["ping", "-c", "1", "-W", "2", host]
                    kw = {}
                r = subprocess.run(cmd, capture_output=True, **kw)
                online = r.returncode == 0
            except Exception:
                online = False
            _ping_bus.result.emit(cid, online)  # thread-safe Qt signal

        threading.Thread(target=_work, daemon=True).start()

    def _set_ping(self, cid: int, online: bool) -> None:
        self._ping_cache[cid] = online
        card = self._cards.get(cid)
        if card:
            card.set_online(online)

    # ── Process tracking ──────────────────────────────────────────────────
    def _check_processes(self) -> None:
        # Check Popen-tracked processes
        for cid in list(self._procs):
            before = len(self._procs[cid])
            self._procs[cid] = [p for p in self._procs[cid] if p.poll() is None]
            after = len(self._procs[cid])
            if after == 0:
                del self._procs[cid]
                self._clear_connecting(cid)
            if before != after:
                card = self._cards.get(cid)
                if card:
                    card.set_active_count(self._active_window_count(cid))

        # Validate all tracked HWNDs (including reattached-only)
        for cid in list(self._snap_hwnds):
            remaining = [
                h for h in self._snap_hwnds[cid]
                if conn_launcher.is_window_valid(h)
            ]
            # Discard stale entries from the Popen-HWND tracker
            stale = set(self._snap_hwnds[cid]) - set(remaining)
            self._popen_hwnds -= stale
            if remaining:
                self._snap_hwnds[cid] = remaining
            else:
                self._snap_hwnds.pop(cid, None)
                self._snap_tags.pop(cid, None)
                database.clear_sessions(cid)
                # Update card if no Popen either
                if cid not in self._procs:
                    card = self._cards.get(cid)
                    if card:
                        card.set_active_count(0)

    # ── Window screenshots ────────────────────────────────────────────────
    def _snap_all(self) -> None:
        """Capture screenshots for every connection that has live windows."""
        cids = set(self._procs.keys()) | set(self._snap_hwnds.keys())
        for cid in cids:
            self._snap_one(cid)

    def _snap_one(self, cid: int) -> None:
        """Capture the most recent alive process window for *cid*."""
        procs = self._procs.get(cid, [])
        alive = [p for p in procs if p.poll() is None]

        cached_hwnds = self._snap_hwnds.get(cid, [])
        cached_hwnd = cached_hwnds[-1] if cached_hwnds else 0
        hints = self._snap_tags.get(cid, [])

        if not alive and not cached_hwnd and not hints:
            return

        # Use the most recently launched process PID, or 0 for reattached
        pid = alive[-1].pid if alive else 0

        log.debug("cid=%d: capture (pid=%d, hwnd=%d, hints=%r)", cid, pid, cached_hwnd, hints)
        result = conn_launcher.capture_window(
            pid=pid, hwnd=cached_hwnd, title_hints=hints
        )
        if result is None:
            log.debug("cid=%d: capture returned None", cid)
            return

        found_hwnd, w, h, buf = result
        if found_hwnd:
            hwnd_list = self._snap_hwnds.setdefault(cid, [])
            if found_hwnd not in hwnd_list:
                hwnd_list.append(found_hwnd)

        log.debug("cid=%d: got %dx%d image", cid, w, h)
        img = QImage(buf, w, h, w * 4, QImage.Format_ARGB32)
        if img.isNull():
            return
        pix = QPixmap.fromImage(img)
        if pix.isNull():
            return
        card = self._cards.get(cid)
        if card:
            card.set_background(pix)
        # Persist as PNG in the database
        ba = QByteArray()
        qbuf = QBuffer(ba)
        qbuf.open(QIODevice.WriteOnly)
        pix.save(qbuf, "PNG")
        qbuf.close()
        database.save_screenshot(cid, bytes(ba))

    def _wait_for_auth(self, cid: int, tag: str, attempt: int = 0,
                       _phase: str = "appear") -> None:
        """Two-phase poll for SSH authentication completion.

        Phase 1 ("appear"): Wait for a window with *tag* in the title to
            appear.  Cache its HWND for later screenshot capture.
        Phase 2 ("disappear"): Wait for *tag* to vanish from the title.
            This means the remote shell took over (auth complete).

        Gives up after ~60 s total.
        """
        _MAX_ATTEMPTS = 60
        alive = [p for p in self._procs.get(cid, []) if p.poll() is None]
        if not alive:
            log.debug("cid=%d: process dead, giving up", cid)
            self._clear_connecting(cid)
            return
        if attempt >= _MAX_ATTEMPTS:
            log.debug("cid=%d: timed out after %ds, snapping anyway", cid, _MAX_ATTEMPTS)
            self._clear_connecting(cid)
            self._snap_one(cid)
            return

        found_hwnd = conn_launcher.find_window_by_title(tag)

        if _phase == "appear":
            if found_hwnd:
                # Window appeared — cache its HWND so capture_window can
                # reuse it even after the title changes.
                hwnd_list = self._snap_hwnds.setdefault(cid, [])
                if found_hwnd not in hwnd_list:
                    hwnd_list.append(found_hwnd)
                self._popen_hwnds.add(found_hwnd)
                # Persist for reattach across restarts
                database.save_session(cid, found_hwnd, tag)
                log.debug("cid=%d: window appeared hwnd=%d (attempt %d)", cid, found_hwnd, attempt)
                QTimer.singleShot(1000, lambda: self._wait_for_auth(
                    cid, tag, attempt + 1, _phase="disappear"))
            else:
                if attempt % 5 == 0:
                    log.debug("cid=%d: waiting for window (attempt %d)", cid, attempt)
                QTimer.singleShot(500, lambda: self._wait_for_auth(
                    cid, tag, attempt + 1, _phase="appear"))
        else:  # disappear
            if found_hwnd:
                # Update cached HWND in case it changed.
                hwnd_list = self._snap_hwnds.setdefault(cid, [])
                if found_hwnd not in hwnd_list:
                    hwnd_list.append(found_hwnd)
                self._popen_hwnds.add(found_hwnd)
                if attempt % 5 == 0:
                    log.debug("cid=%d: tag %r still present (attempt %d)", cid, tag, attempt)
                QTimer.singleShot(1000, lambda: self._wait_for_auth(
                    cid, tag, attempt + 1, _phase="disappear"))
            else:
                log.debug("cid=%d: tag %r gone (attempt %d) — auth complete", cid, tag, attempt)
                self._clear_connecting(cid)
                QTimer.singleShot(500, lambda c=cid: self._snap_one(c))

    # ── Card clicks ───────────────────────────────────────────────────────
    def _has_active_windows(self, cid: int) -> bool:
        """Return True if *cid* has any tracked live processes or valid reattached HWNDs."""
        alive = [p for p in self._procs.get(cid, []) if p.poll() is None]
        if alive:
            return True
        return any(
            conn_launcher.is_window_valid(h)
            for h in self._snap_hwnds.get(cid, [])
        )

    def _active_window_count(self, cid: int) -> int:
        """Return the number of live windows for *cid* (Popen + reattached HWNDs)."""
        alive_popen_count = sum(
            1 for p in self._procs.get(cid, []) if p.poll() is None
        )
        # Count valid HWNDs that were NOT discovered for a Popen launch
        # (i.e. reattached-only windows from a previous session).
        reattached_count = sum(
            1 for h in self._snap_hwnds.get(cid, [])
            if conn_launcher.is_window_valid(h) and h not in self._popen_hwnds
        )
        return alive_popen_count + reattached_count

    def _on_card_left(self, record) -> None:
        cid = record["id"]
        if cid in self._connecting_cids:
            return  # already connecting — ignore click
        alive = [p for p in self._procs.get(cid, []) if p.poll() is None]
        if alive:
            for proc in alive:
                conn_launcher.bring_process_to_front(proc.pid)
        elif self._has_active_windows(cid):
            # Reattached-only — bring windows to front
            hwnds = self._collect_hwnds(cid)
            if hwnds:
                conn_launcher.restore_windows(hwnds)
        else:
            self._connect(record)

    def _on_card_right(self, record, pos: QPoint) -> None:
        cid = record["id"]
        n = self._active_window_count(cid)
        menu = QMenu(self)
        if n > 0:
            wlabel = "window" if n == 1 else "windows"
            act = QAction(_load_icon("locate-svgrepo"), f"Locate {wlabel}", menu)
            act.triggered.connect(lambda: self._locate_windows(record))
            menu.addAction(act)

            act = QAction(_load_icon("move-here-svgrepo"), "Move to this monitor", menu)
            act.triggered.connect(lambda: self._move_windows(record))
            menu.addAction(act)

            menu.addSeparator()

            act = QAction(_load_icon("new-window-svgrepo"), "Start additional connection", menu)
            act.triggered.connect(lambda: self._connect(record))
            menu.addAction(act)

            clabel = "Close connection" if n == 1 else "Close all connections"
            act = QAction(_load_icon("close-svgrepo"), clabel, menu)
            act.triggered.connect(lambda: self._close_all(record))
            menu.addAction(act)
        else:
            act = QAction(_load_icon("paperplane-svgrepo"), "Connect", menu)
            act.triggered.connect(lambda: self._connect(record))
            menu.addAction(act)

        menu.addSeparator()

        act = QAction(_load_icon("edit-svgrepo"), "Edit", menu)
        act.triggered.connect(lambda: self._edit_host(record))
        menu.addAction(act)

        act = QAction(_load_icon("delete-svgrepo"), "Delete", menu)
        act.triggered.connect(lambda: self._delete_host(record))
        menu.addAction(act)

        menu.exec(pos)

    # ── Actions ───────────────────────────────────────────────────────────
    def _collect_hwnds(self, cid: int) -> list[int]:
        hwnds: list[int] = []
        # Start with all cached HWNDs (accumulated over launches)
        for h in self._snap_hwnds.get(cid, []):
            if h not in hwnds:
                hwnds.append(h)
        # Also search by every title hint (tag + host, across launches)
        for hint in self._snap_tags.get(cid, []):
            for h in conn_launcher.find_windows_by_title(hint):
                if h not in hwnds:
                    hwnds.append(h)
        return hwnds

    def _locate_windows(self, record) -> None:
        hwnds = self._collect_hwnds(record["id"])
        if not hwnds:
            return
        cycles = 4

        def _do_locate():
            conn_launcher.restore_windows(hwnds)
            time.sleep(0.05)
            threads = []
            for hwnd in hwnds:
                t = threading.Thread(
                    target=conn_launcher.shake_window,
                    args=(hwnd, cycles),
                    daemon=True,
                )
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

        threading.Thread(target=_do_locate, daemon=True).start()

    def _move_windows(self, record) -> None:
        hwnds = self._collect_hwnds(record["id"])
        if not hwnds:
            return
        screen = self.screen()
        geom = screen.geometry() if screen else None
        if not geom:
            return
        target_rect = (geom.x(), geom.y(), geom.width(), geom.height())
        for i, hwnd in enumerate(hwnds):
            conn_launcher.move_window_to_monitor(hwnd, target_rect, offset=i * 40)

    def _close_all(self, record) -> None:
        cid = record["id"]
        for proc in self._procs.get(cid, []):
            try:
                conn_launcher.kill_process_tree(proc.pid)
            except Exception:
                pass
        # Also kill reattached-only windows (no Popen)
        for hwnd in self._snap_hwnds.get(cid, []):
            if conn_launcher.is_window_valid(hwnd):
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    wp = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
                    if wp.value:
                        conn_launcher.kill_process_tree(wp.value)
                except Exception:
                    pass
        self._procs.pop(cid, None)
        self._snap_hwnds.pop(cid, None)
        self._snap_tags.pop(cid, None)
        database.clear_sessions(cid)
        self._connecting_cids.discard(cid)
        card = self._cards.get(cid)
        if card:
            card.set_connecting(False)
            card.set_active_count(0)

    def _connect(self, record) -> None:
        cid = record["id"]
        username, _ = database.get_effective_credentials(cid)
        # Build title hints so we can find the terminal window later.
        # The tag is set at launch; the host survives after SSH auth
        # changes the title to "user@host: ~".
        self._launch_counter += 1
        tag = f"Remote-Routes-{cid}-{self._launch_counter}" if record["type"] == "SSH" else ""
        host = record["host"]
        # Accumulate title hints so older windows can still be found.
        existing = self._snap_tags.get(cid, [])
        for h in (tag, host):
            if h and h not in existing:
                existing.append(h)
        if existing:
            self._snap_tags[cid] = existing
        try:
            proc = conn_launcher.launch(
                record["type"], record["host"], record["port"], username,
                title_tag=tag or None,
            )
            self._procs.setdefault(cid, []).append(proc)
            # Show "Connecting..." animation (active count updates when it resolves)
            self._connecting_cids.add(cid)
            card = self._cards.get(cid)
            if card:
                card.set_connecting(True)
            # Schedule first screenshot.
            if tag:
                # SSH: poll until the title changes away from our tag
                # (meaning auth completed and shell prompt took over).
                self._wait_for_auth(cid, tag)
            else:
                # RDP: just wait a few seconds for the window to appear.
                QTimer.singleShot(3000, lambda c=cid: self._snap_one(c))
                QTimer.singleShot(3500, lambda c=cid: self._clear_connecting(c))
        except Exception as exc:
            self._connecting_cids.discard(cid)
            card = self._cards.get(cid)
            if card:
                card.set_connecting(False)
            QMessageBox.critical(self, "Connection Error", str(exc))

    def _clear_connecting(self, cid: int) -> None:
        """Remove *cid* from the connecting set and update its card."""
        self._connecting_cids.discard(cid)
        card = self._cards.get(cid)
        if card:
            card.set_connecting(False)
            card.set_active_count(self._active_window_count(cid))

    def _add_host(self) -> None:
        dlg = ConnectionDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            database.add_connection(**dlg.result)
            self._refresh_cards()

    def _edit_host(self, record) -> None:
        dlg = ConnectionDialog(self, record=record)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            database.update_connection(record["id"], **dlg.result)
            self._refresh_cards()

    def _delete_host(self, record) -> None:
        reply = QMessageBox.question(
            self, "Confirm", f"Delete '{record['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            database.delete_connection(record["id"])
            self._refresh_cards()
