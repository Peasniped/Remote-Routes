"""Main GUI window for Remote Routes — PySide6."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QTimer, Signal, QObject, QPoint, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QFont, QImage, QPalette, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
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

# ── Constants ─────────────────────────────────────────────────────────────────
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
    background-color: #16a34a; color: white;
    border: none; border-radius: 8px;
    font-size: 22px; font-weight: bold;
}
QPushButton#btn_add:hover { background-color: #15803d; }

QPushButton#btn_settings {
    background-color: #3a3a3a; color: #ccc;
    border: none; border-radius: 8px; font-size: 17px;
}
QPushButton#btn_settings:hover { background-color: #4a4a4a; }

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
_BORDER_WIDTH = 2.0


class CardInner(QFrame):
    """QFrame replacement that paints a rounded-rect background image + overlay."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._bg_pixmap: QPixmap | None = None
        self._active = False
        # Let QSS handle nothing — we do all painting ourselves.
        self.setStyleSheet("background: transparent; border: none;")

    def set_background(self, pixmap: QPixmap | None) -> None:
        self._bg_pixmap = pixmap
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
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
            # Centre-crop
            x = (scaled.width() - w) // 2
            y = (scaled.height() - h) // 2
            painter.drawPixmap(0, 0, scaled, x, y, w, h)
            # Dark overlay for legibility
            painter.fillRect(rect, _OVERLAY_COLOR)

        # 3) Active border
        if self._active:
            painter.setClipping(False)
            border_pen = QPen(_BORDER_ACTIVE, _BORDER_WIDTH)
            painter.setPen(border_pen)
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

        self._record = record
        self._on_left = on_left_click
        self._on_right = on_right_click
        self._active_count = 0

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

        card_layout.addWidget(info)
        card_layout.addStretch(1)

        # ── trapezoid badge (child of self, floats centred at top of _inner) ─
        self._badge = ActiveBadge(self)
        self._badge.raise_()

    # ── helpers ───────────────────────────────────────────────────────────
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

    # ── public API ────────────────────────────────────────────────────────
    def set_online(self, online: bool | None) -> None:
        self._ping_dot.set_color(
            "#666" if online is None else "#22c55e" if online else "#ef4444"
        )

    def set_active_count(self, count: int) -> None:
        self._active_count = count
        if count > 0:
            self._inner.set_active(True)
            self._badge.setText("Active" if count == 1 else f"{count} active")
            self._place_badge()
        else:
            self._inner.set_active(False)
            self._badge.setText("")   # hides automatically

    def set_background(self, pixmap: QPixmap | None) -> None:
        """Set a screenshot as the card background (with dark overlay)."""
        self._inner.set_background(pixmap)

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
        self._layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

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
    def __init__(self, on_back, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_back = on_back

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

        # ── General tab (placeholder for future settings) ─────────────
        general_page = QWidget()
        gen_layout = QVBoxLayout(general_page)
        gen_layout.setContentsMargins(12, 12, 12, 12)
        gen_placeholder = QLabel("No general settings yet.")
        gen_placeholder.setAlignment(Qt.AlignCenter)
        gen_placeholder.setStyleSheet("color: #666; background: transparent;")
        gen_layout.addWidget(gen_placeholder)
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
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
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

            btn_edit = QPushButton("✏")
            btn_edit.setObjectName("btn_neutral")
            btn_edit.setFixedSize(30, 26)
            btn_edit.clicked.connect(
                lambda _checked, uid=u["id"]: self._edit_user(uid)
            )
            row_layout.addWidget(btn_edit)

            btn_del = QPushButton("🗑")
            btn_del.setObjectName("btn_danger")
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


# ═══════════════════════════════════════════════════════════════════════════════
#  Main window
# ═══════════════════════════════════════════════════════════════════════════════
class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Routes")
        self.resize(820, 540)
        self.setMinimumSize(640, 420)

        database.init_db()

        self._procs: dict[int, list[subprocess.Popen]] = {}
        self._ping_cache: dict[int, Optional[bool]] = {}
        self._cards: dict[int, HostCard] = {}
        self._snap_hwnds: dict[int, list[int]] = {}   # cid → cached HWNDs
        self._snap_tags: dict[int, list[str]] = {}     # cid → title hints (accumulated)
        self._launch_counter: int = 0                   # unique tag suffix

        # Connect ping bus (emitted from background threads)
        _ping_bus.result.connect(self._set_ping)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._build_overview()
        self._settings_page = SettingsPage(on_back=self._show_overview)
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

    # ── Overview page ─────────────────────────────────────────────────────
    def _build_overview(self) -> None:
        self._overview_page = QWidget()
        outer = QVBoxLayout(self._overview_page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background: transparent;")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(12, 12, 12, 4)
        tb.setSpacing(6)

        btn_add = QPushButton("+")
        btn_add.setObjectName("btn_add")
        btn_add.setFixedSize(36, 36)
        btn_add.setToolTip("Add host")
        btn_add.clicked.connect(self._add_host)
        tb.addWidget(btn_add)

        btn_settings = QPushButton("⚙")
        btn_settings.setObjectName("btn_settings")
        btn_settings.setFixedSize(36, 36)
        btn_settings.setToolTip("Settings")
        btn_settings.clicked.connect(self._show_settings)
        tb.addWidget(btn_settings)

        tb.addStretch()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search…")
        self._search_edit.setFixedWidth(210)
        self._search_edit.setStyleSheet(
            "background-color: #2a2a2a; border: 1px solid #444;"
            " border-radius: 8px; padding: 5px 10px; color: #e0e0e0;"
        )
        self._search_edit.textChanged.connect(self._refresh_cards)
        tb.addWidget(self._search_edit)

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
        self._refresh_cards()

    def _show_settings(self) -> None:
        self._stack.setCurrentWidget(self._settings_page)
        self._settings_page.refresh()

    # ── Cards ─────────────────────────────────────────────────────────────
    def _refresh_cards(self) -> None:
        query = self._search_edit.text().lower()
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
            alive = [p for p in self._procs.get(rec["id"], []) if p.poll() is None]
            card.set_active_count(len(alive))
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
        for cid in list(self._procs):
            before = len(self._procs[cid])
            self._procs[cid] = [p for p in self._procs[cid] if p.poll() is None]
            after = len(self._procs[cid])
            if after == 0:
                del self._procs[cid]
                self._snap_hwnds.pop(cid, None)
                self._snap_tags.pop(cid, None)
            if before != after:
                card = self._cards.get(cid)
                if card:
                    card.set_active_count(after)

    # ── Window screenshots ────────────────────────────────────────────────
    def _snap_all(self) -> None:
        """Capture screenshots for every connection that has live processes."""
        for cid in list(self._procs):
            self._snap_one(cid)

    def _snap_one(self, cid: int) -> None:
        """Capture the most recent alive process window for *cid*."""
        procs = self._procs.get(cid, [])
        alive = [p for p in procs if p.poll() is None]
        if not alive:
            return

        cached_hwnds = self._snap_hwnds.get(cid, [])
        cached_hwnd = cached_hwnds[-1] if cached_hwnds else 0
        hints = self._snap_tags.get(cid, [])
        # Use the most recently launched process
        pid = alive[-1].pid

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
            return
        if attempt >= _MAX_ATTEMPTS:
            log.debug("cid=%d: timed out after %ds, snapping anyway", cid, _MAX_ATTEMPTS)
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
                if attempt % 5 == 0:
                    log.debug("cid=%d: tag %r still present (attempt %d)", cid, tag, attempt)
                QTimer.singleShot(1000, lambda: self._wait_for_auth(
                    cid, tag, attempt + 1, _phase="disappear"))
            else:
                log.debug("cid=%d: tag %r gone (attempt %d) — auth complete", cid, tag, attempt)
                QTimer.singleShot(500, lambda c=cid: self._snap_one(c))

    # ── Card clicks ───────────────────────────────────────────────────────
    def _on_card_left(self, record) -> None:
        cid = record["id"]
        alive = [p for p in self._procs.get(cid, []) if p.poll() is None]
        if alive:
            for proc in alive:
                conn_launcher.bring_process_to_front(proc.pid)
        else:
            self._connect(record)

    def _on_card_right(self, record, pos: QPoint) -> None:
        cid = record["id"]
        alive = [p for p in self._procs.get(cid, []) if p.poll() is None]
        menu = QMenu(self)
        if alive:
            n = len(alive)
            wlabel = "window" if n == 1 else "windows"
            menu.addAction(f"Locate {wlabel}",
                           lambda: self._locate_windows(record))
            menu.addAction("Move to this monitor",
                           lambda: self._move_windows(record))
            menu.addSeparator()
            menu.addAction("Start additional connection",
                           lambda: self._connect(record))
            clabel = "Close connection" if n == 1 else "Close all connections"
            menu.addAction(clabel,
                           lambda: self._close_all(record))
        else:
            menu.addAction("Connect", lambda: self._connect(record))
        menu.addSeparator()
        menu.addAction("Edit", lambda: self._edit_host(record))
        menu.addAction("Delete", lambda: self._delete_host(record))
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
        self._procs.pop(cid, None)
        self._snap_hwnds.pop(cid, None)
        self._snap_tags.pop(cid, None)
        card = self._cards.get(cid)
        if card:
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
            alive = len([p for p in self._procs[cid] if p.poll() is None])
            card = self._cards.get(cid)
            if card:
                card.set_active_count(alive)
            # Schedule first screenshot.
            if tag:
                # SSH: poll until the title changes away from our tag
                # (meaning auth completed and shell prompt took over).
                self._wait_for_auth(cid, tag)
            else:
                # RDP: just wait a few seconds for the window to appear.
                QTimer.singleShot(3000, lambda c=cid: self._snap_one(c))
        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))

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
