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
from PySide6.QtGui import QAction, QBitmap, QColor, QCursor, QFont, QFontMetrics, QIcon, QImage, QPalette, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
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


_DEFAULT_PORTS = {"SSH": 22, "RDP": 3389, "WEB": 443}
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
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
def _split_addr(addr: str) -> tuple[str, str]:
    """Split a stored address into (host, path).

    WEB hosts may carry a path in the address field, e.g.
    "traefik.example.com/dashboard/". Opening the URL needs the path back,
    while ping and DNS need the bare host — passing the whole string to
    ping makes it fail to resolve and shows the host as offline.

    A scheme or trailing ":port" that got pasted into the field is stripped
    too; both are stored in their own columns.
    """
    s = (addr or "").strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    host, path = s, ""
    cut = [s.index(c) for c in "/?#" if c in s]
    if cut:
        i = min(cut)
        host, path = s[:i], s[i:]
    # Strip a trailing :port, leaving IPv6 literals like [::1] alone
    if not host.startswith("[") and host.count(":") == 1:
        h, _, port = host.partition(":")
        if port.isdigit():
            host = h
    return host, path


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

QPushButton#btn_never {
    background-color: #3a2020; color: #cc8888;
    border: none; border-radius: 5px; padding: 3px 8px;
}
QPushButton#btn_never:hover { background-color: #4a2828; color: #e0a0a0; }

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
    _dns_resolved = Signal(str)       # emitted from DNS worker thread
    _ip_ping_result = Signal(bool)    # emitted from IP ping thread
    _host_ping_result = Signal(bool)  # emitted from host ping thread

    def __init__(self, parent: QWidget | None = None, record=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Host" if record else "Add Host")
        self.setFixedWidth(420)
        self.setModal(True)
        self._result = None
        self._users = database.get_all_users()
        self._can_add_hostname = True
        self._can_add_ip = True
        self._first_added = ""       # "hostname" | "ip" | ""
        self._dns_pending_host = ""
        self._dns_anim_frame = 0
        self._dns_row_shown = False
        self._lookup_direct = False
        self._ip_last_pinged = ""
        self._host_last_pinged = ""
        self._ip_ping_anim_frame = 0
        self._host_ping_anim_frame = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        def _row(label: str, widget: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFixedWidth(80)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            row.addWidget(widget)
            return row

        # (Type row added to layout below host section)
        type_row = QHBoxLayout()
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(4)
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
        self._btn_web = QPushButton("WEB")
        self._btn_web.setObjectName("type_btn")
        self._btn_web.setCheckable(True)
        self._btn_web.setFixedWidth(80)
        # Exclusive toggle
        self._btn_ssh.clicked.connect(lambda: self._set_type("SSH"))
        self._btn_rdp.clicked.connect(lambda: self._set_type("RDP"))
        self._btn_web.clicked.connect(lambda: self._set_type("WEB"))
        type_row.addWidget(lbl_type)
        type_row.addWidget(self._btn_ssh)
        type_row.addWidget(self._btn_rdp)
        type_row.addWidget(self._btn_web)
        type_row.addStretch()

        # ── Dynamic host section ──────────────────────────────────────────
        self._host = QLineEdit()
        self._host_ip = QLineEdit()

        # "Add" buttons row
        self._add_btns_widget = QWidget()
        self._add_btns_widget.setAttribute(Qt.WA_TranslucentBackground)
        ab_layout = QHBoxLayout(self._add_btns_widget)
        ab_layout.setContentsMargins(84, 0, 0, 0)
        ab_layout.setSpacing(6)
        self._add_hostname_btn = QPushButton("Add Hostname")
        self._add_hostname_btn.setObjectName("btn_add_green")
        self._add_hostname_btn.setFixedHeight(26)
        self._add_hostname_btn.clicked.connect(lambda: self._add_host_field("hostname"))
        ab_layout.addWidget(self._add_hostname_btn)
        self._add_ip_btn = QPushButton("Add IP Address")
        self._add_ip_btn.setObjectName("btn_add_green")
        self._add_ip_btn.setFixedHeight(26)
        self._add_ip_btn.clicked.connect(lambda: self._add_host_field("ip"))
        ab_layout.addWidget(self._add_ip_btn)
        ab_layout.addStretch()
        layout.addWidget(self._add_btns_widget)

        # Standalone trailing add-button widgets (placed in _hsl when one field already present)
        self._add_hn_trailing_widget = QWidget()
        self._add_hn_trailing_widget.setAttribute(Qt.WA_TranslucentBackground)
        ahn_t_l = QHBoxLayout(self._add_hn_trailing_widget)
        ahn_t_l.setContentsMargins(84, 0, 0, 0)
        ahn_t_l.setSpacing(0)
        self._btn_add_hn_trailing = QPushButton("Add Hostname")
        self._btn_add_hn_trailing.setObjectName("btn_add_green")
        self._btn_add_hn_trailing.setFixedHeight(26)
        self._btn_add_hn_trailing.clicked.connect(lambda: self._add_host_field("hostname"))
        ahn_t_l.addWidget(self._btn_add_hn_trailing)
        ahn_t_l.addStretch()

        self._add_ip_trailing_widget = QWidget()
        self._add_ip_trailing_widget.setAttribute(Qt.WA_TranslucentBackground)
        aip_t_l = QHBoxLayout(self._add_ip_trailing_widget)
        aip_t_l.setContentsMargins(84, 0, 0, 0)
        aip_t_l.setSpacing(6)
        btn_add_ip_t = QPushButton("Add IP Address")
        btn_add_ip_t.setObjectName("btn_add_green")
        btn_add_ip_t.setFixedHeight(26)
        btn_add_ip_t.clicked.connect(lambda: self._add_host_field("ip"))
        aip_t_l.addWidget(btn_add_ip_t)
        self._btn_lookup_ip_trailing = QPushButton("Look up IP")
        self._btn_lookup_ip_trailing.setObjectName("btn_add_green")
        self._btn_lookup_ip_trailing.setFixedHeight(26)
        self._btn_lookup_ip_trailing.setToolTip("Resolve address to IP via DNS")
        self._btn_lookup_ip_trailing.clicked.connect(self._lookup_ip_direct)
        self._btn_lookup_ip_trailing.hide()
        aip_t_l.addWidget(self._btn_lookup_ip_trailing)
        aip_t_l.addStretch()

        # Sub-container — holds host rows in preferred order
        self._host_section = QWidget()
        self._host_section.setAttribute(Qt.WA_TranslucentBackground)
        self._hsl = QVBoxLayout(self._host_section)
        self._hsl.setContentsMargins(0, 0, 0, 0)
        self._hsl.setSpacing(layout.spacing())
        layout.addWidget(self._host_section)
        layout.addLayout(type_row)  # Type below identifiers

        # Hostname input row
        self._hostname_row_widget = QWidget()
        self._hostname_row_widget.setAttribute(Qt.WA_TranslucentBackground)
        hn_layout = QHBoxLayout(self._hostname_row_widget)
        hn_layout.setContentsMargins(0, 0, 0, 0)
        hn_layout.setSpacing(4)
        self._lbl_hn = QLabel("Hostname:")
        self._lbl_hn.setFixedWidth(80)
        self._lbl_hn.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hn_layout.addWidget(self._lbl_hn)
        hn_layout.addWidget(self._host)
        btn_rm_hn = QPushButton("×")
        btn_rm_hn.setObjectName("btn_danger")
        btn_rm_hn.setFixedSize(26, 26)
        btn_rm_hn.setToolTip("Remove hostname")
        btn_rm_hn.clicked.connect(lambda: self._remove_host_field("hostname"))
        hn_layout.addWidget(btn_rm_hn)
        self._hostname_row_widget.hide()

        # WEB-type hostname access options (per-address scheme + port)
        self._web_hn_opts_widget = QWidget()
        self._web_hn_opts_widget.setAttribute(Qt.WA_TranslucentBackground)
        who_layout = QHBoxLayout(self._web_hn_opts_widget)
        who_layout.setContentsMargins(84, 0, 30, 0)
        who_layout.setSpacing(6)
        who_lbl = QLabel("via:")
        who_lbl.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        who_layout.addWidget(who_lbl)
        self._web_hn_scheme_combo = QComboBox()
        self._web_hn_scheme_combo.addItems(["https", "http"])
        self._web_hn_scheme_combo.setFixedWidth(80)
        self._web_hn_scheme_combo.currentTextChanged.connect(self._on_hn_scheme_changed)
        who_layout.addWidget(self._web_hn_scheme_combo)
        who_port_lbl = QLabel("port:")
        who_port_lbl.setStyleSheet("color: #888; background: transparent;")
        who_layout.addWidget(who_port_lbl)
        self._web_hn_port = QLineEdit()
        self._web_hn_port.setFixedWidth(60)
        self._web_hn_port.setAlignment(Qt.AlignCenter)
        self._web_hn_port.setPlaceholderText("443")
        who_layout.addWidget(self._web_hn_port)
        who_layout.addStretch()
        self._web_hn_opts_widget.hide()

        # DNS suggestion row
        self._dns_row_widget = QWidget()
        self._dns_row_widget.setAttribute(Qt.WA_TranslucentBackground)
        dns_rl = QHBoxLayout(self._dns_row_widget)
        dns_rl.setContentsMargins(84, 0, 30, 0)
        dns_rl.setSpacing(6)
        self._dns_lbl = QLabel()
        self._dns_lbl.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        dns_rl.addWidget(self._dns_lbl)
        dns_rl.addStretch()
        self._dns_btn_accept = QPushButton("Save")
        self._dns_btn_accept.setObjectName("btn_add_green")
        self._dns_btn_accept.setFixedHeight(26)
        self._dns_btn_accept.setToolTip("Add this IP")
        self._dns_btn_accept.clicked.connect(self._dns_accept)
        dns_rl.addWidget(self._dns_btn_accept)
        self._dns_btn_dismiss = QPushButton("×")
        self._dns_btn_dismiss.setObjectName("btn_danger")
        self._dns_btn_dismiss.setFixedSize(26, 26)
        self._dns_btn_dismiss.setToolTip("Dismiss")
        self._dns_btn_dismiss.clicked.connect(self._dns_dismiss)
        dns_rl.addWidget(self._dns_btn_dismiss)
        self._dns_btn_never = QPushButton("Never")
        self._dns_btn_never.setObjectName("btn_never")
        self._dns_btn_never.setFixedHeight(26)
        self._dns_btn_never.setToolTip("Disable DNS lookup feature")
        self._dns_btn_never.clicked.connect(self._dns_never)
        dns_rl.addWidget(self._dns_btn_never)
        self._dns_row_widget.hide()

        # IP input row
        self._ip_row_widget = QWidget()
        self._ip_row_widget.setAttribute(Qt.WA_TranslucentBackground)
        ip_layout = QHBoxLayout(self._ip_row_widget)
        ip_layout.setContentsMargins(0, 0, 0, 0)
        ip_layout.setSpacing(4)
        lbl_ip = QLabel("IP Address:")
        lbl_ip.setFixedWidth(80)
        lbl_ip.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ip_layout.addWidget(lbl_ip)
        ip_layout.addWidget(self._host_ip)
        btn_rm_ip = QPushButton("×")
        btn_rm_ip.setObjectName("btn_danger")
        btn_rm_ip.setFixedSize(26, 26)
        btn_rm_ip.setToolTip("Remove IP address")
        btn_rm_ip.clicked.connect(lambda: self._remove_host_field("ip"))
        ip_layout.addWidget(btn_rm_ip)
        self._ip_row_widget.hide()

        # WEB-type IP access options (per-IP scheme + port)
        self._web_ip_opts_widget = QWidget()
        self._web_ip_opts_widget.setAttribute(Qt.WA_TranslucentBackground)
        wio_layout = QHBoxLayout(self._web_ip_opts_widget)
        wio_layout.setContentsMargins(84, 0, 30, 0)
        wio_layout.setSpacing(6)
        wio_lbl = QLabel("IP via:")
        wio_lbl.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        wio_layout.addWidget(wio_lbl)
        self._host_ip_scheme_combo = QComboBox()
        self._host_ip_scheme_combo.addItems(["https", "http"])
        self._host_ip_scheme_combo.setFixedWidth(80)
        self._host_ip_scheme_combo.currentTextChanged.connect(self._on_ip_scheme_changed)
        wio_layout.addWidget(self._host_ip_scheme_combo)
        wio_port_lbl = QLabel("port:")
        wio_port_lbl.setStyleSheet("color: #888; background: transparent;")
        wio_layout.addWidget(wio_port_lbl)
        self._host_ip_port = QLineEdit()
        self._host_ip_port.setFixedWidth(60)
        self._host_ip_port.setAlignment(Qt.AlignCenter)
        self._host_ip_port.setPlaceholderText("443")
        wio_layout.addWidget(self._host_ip_port)
        wio_layout.addStretch()
        self._web_ip_opts_widget.hide()

        # Prefer row
        prefer_widget = QWidget()
        prefer_widget.setAttribute(Qt.WA_TranslucentBackground)
        prefer_layout = QHBoxLayout(prefer_widget)
        prefer_layout.setContentsMargins(0, 0, 0, 0)
        prefer_layout.setSpacing(6)
        lbl_prefer = QLabel("Primary:")
        lbl_prefer.setFixedWidth(80)
        lbl_prefer.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._btn_prefer_hostname = QPushButton("Hostname")
        self._btn_prefer_hostname.setObjectName("type_btn")
        self._btn_prefer_hostname.setCheckable(True)
        self._btn_prefer_hostname.setChecked(True)
        self._btn_prefer_hostname.setFixedWidth(104)
        self._btn_prefer_hostname.clicked.connect(lambda: self._set_prefer("hostname"))
        self._btn_prefer_ip = QPushButton("IP")
        self._btn_prefer_ip.setObjectName("type_btn")
        self._btn_prefer_ip.setCheckable(True)
        self._btn_prefer_ip.setFixedWidth(60)
        self._btn_prefer_ip.clicked.connect(lambda: self._set_prefer("ip"))
        prefer_layout.addWidget(lbl_prefer)
        prefer_layout.addWidget(self._btn_prefer_hostname)
        prefer_layout.addWidget(self._btn_prefer_ip)
        prefer_layout.addStretch()
        self._prefer_widget = prefer_widget
        self._prefer_widget.hide()

        # Port row
        self._port = QLineEdit()
        self._port.setFixedWidth(70)
        self._port.setText("22")
        self._port_row_widget = QWidget()
        self._port_row_widget.setAttribute(Qt.WA_TranslucentBackground)
        port_row = QHBoxLayout(self._port_row_widget)
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.setSpacing(4)
        lbl_p = QLabel("Port:")
        lbl_p.setFixedWidth(80)
        lbl_p.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        port_row.addWidget(lbl_p)
        port_row.addWidget(self._port)
        port_row.addStretch()
        layout.addWidget(self._port_row_widget)

        # Scheme row — only shown for WEB type
        self._scheme_combo = QComboBox()
        self._scheme_combo.addItems(["https", "http"])
        self._scheme_combo.setFixedWidth(80)
        self._scheme_combo.currentTextChanged.connect(self._on_scheme_changed)
        scheme_row = QHBoxLayout()
        scheme_row.setContentsMargins(0, 0, 0, 0)
        scheme_row.setSpacing(4)
        lbl_scheme = QLabel("Scheme:")
        lbl_scheme.setFixedWidth(80)
        lbl_scheme.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        scheme_row.addWidget(lbl_scheme)
        scheme_row.addWidget(self._scheme_combo)
        scheme_row.addStretch()
        self._scheme_row_widget = QWidget()
        self._scheme_row_widget.setAttribute(Qt.WA_TranslucentBackground)
        self._scheme_row_widget.setLayout(scheme_row)
        self._scheme_row_widget.hide()
        layout.addWidget(self._scheme_row_widget)

        # Credentials section — hidden for WEB type
        self._credentials_widget = QWidget()
        self._credentials_widget.setAttribute(Qt.WA_TranslucentBackground)
        cred_layout = QVBoxLayout(self._credentials_widget)
        cred_layout.setContentsMargins(0, 0, 0, 0)
        cred_layout.setSpacing(layout.spacing())

        # User dropdown
        user_labels = ["-- Manual --"] + [
            f"{u['display_name']} ({u['username']})" for u in self._users
        ]
        self._user_combo = QComboBox()
        self._user_combo.addItems(user_labels)
        self._user_combo.currentTextChanged.connect(self._on_user_change)
        cred_layout.addLayout(_row("User:", self._user_combo))

        # Username
        self._username = QLineEdit()
        cred_layout.addLayout(_row("Username:", self._username))

        # Password — hidden until added
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)

        self._add_pw_widget = QWidget()
        self._add_pw_widget.setAttribute(Qt.WA_TranslucentBackground)
        apw_layout = QHBoxLayout(self._add_pw_widget)
        apw_layout.setContentsMargins(84, 0, 0, 0)
        apw_layout.setSpacing(6)
        self._add_pw_btn = QPushButton("Add Password")
        self._add_pw_btn.setObjectName("btn_add_green")
        self._add_pw_btn.setFixedHeight(26)
        self._add_pw_btn.clicked.connect(self._add_password_field)
        apw_layout.addWidget(self._add_pw_btn)
        apw_layout.addStretch()
        cred_layout.addWidget(self._add_pw_widget)

        self._password_row_widget = QWidget()
        self._password_row_widget.setAttribute(Qt.WA_TranslucentBackground)
        pw_rl = QHBoxLayout(self._password_row_widget)
        pw_rl.setContentsMargins(0, 0, 0, 0)
        pw_rl.setSpacing(4)
        lbl_pw = QLabel("Password:")
        lbl_pw.setFixedWidth(80)
        lbl_pw.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pw_rl.addWidget(lbl_pw)
        pw_rl.addWidget(self._password)
        btn_rm_pw = QPushButton("\u00d7")
        btn_rm_pw.setObjectName("btn_danger")
        btn_rm_pw.setFixedSize(26, 26)
        btn_rm_pw.setToolTip("Remove password")
        btn_rm_pw.clicked.connect(self._remove_password_field)
        pw_rl.addWidget(btn_rm_pw)
        self._password_row_widget.hide()
        cred_layout.addWidget(self._password_row_widget)

        layout.addWidget(self._credentials_widget)

        # Alias — optional; if empty the primary identifier is used as the card title
        self._alias = QLineEdit()
        self._alias.setPlaceholderText("Optional — uses primary identifier if blank")
        layout.addLayout(_row("Alias:", self._alias))

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


        # Spinner overlaid inside self._host, right-aligned
        self._dns_spinner = QLabel(self._host)
        self._dns_spinner.setFixedSize(16, 16)
        self._dns_spinner.setAlignment(Qt.AlignCenter)
        self._dns_spinner.setStyleSheet("color: #aaa; font-size: 12px; background: transparent;")
        self._dns_spinner.hide()
        self._host.setTextMargins(0, 0, 18, 0)
        self._host.resizeEvent = self._on_host_resize

        # Hostname ping label (shares position with DNS spinner — never both visible)
        self._host_ping_lbl = QLabel(self._host)
        self._host_ping_lbl.setFixedSize(16, 16)
        self._host_ping_lbl.setAlignment(Qt.AlignCenter)
        self._host_ping_lbl.setStyleSheet("font-size: 12px; background: transparent;")
        self._host_ping_lbl.hide()

        # IP ping label (braille while pinging, ● when done)
        self._ip_ping_lbl = QLabel(self._host_ip)
        self._ip_ping_lbl.setFixedSize(16, 16)
        self._ip_ping_lbl.setAlignment(Qt.AlignCenter)
        self._ip_ping_lbl.setStyleSheet("color: #aaa; font-size: 12px; background: transparent;")
        self._ip_ping_lbl.hide()

        # "Look up IP" button — overlaid right-aligned inside _host_ip, WEB type only
        self._btn_lookup_ip = QPushButton("🔍", self._host_ip)
        self._btn_lookup_ip.setFixedSize(22, 22)
        self._btn_lookup_ip.setToolTip("Resolve address to IP via DNS")
        self._btn_lookup_ip.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid transparent;"
            " border-radius: 4px; color: #4ade80; font-size: 13px; padding: 0; }"
            "QPushButton:hover { border-color: #4ade80; background: rgba(74,222,128,0.12); }"
        )
        self._btn_lookup_ip.clicked.connect(self._lookup_ip_direct)
        self._btn_lookup_ip.hide()
        self._host_ip.setTextMargins(0, 0, 18, 0)
        self._host_ip.resizeEvent = self._on_host_ip_resize

        # DNS debounce timer
        self._dns_debounce = QTimer(self)
        self._dns_debounce.setSingleShot(True)
        self._dns_debounce.setInterval(250)
        self._dns_debounce.timeout.connect(self._start_dns_lookup)

        # DNS animation timer
        self._dns_anim_timer = QTimer(self)
        self._dns_anim_timer.setInterval(120)
        self._dns_anim_timer.timeout.connect(self._tick_dns_spinner)

        # IP ping debounce + animation timers
        self._ip_ping_debounce = QTimer(self)
        self._ip_ping_debounce.setSingleShot(True)
        self._ip_ping_debounce.setInterval(600)
        self._ip_ping_debounce.timeout.connect(self._start_ip_ping)
        self._ip_ping_anim_timer = QTimer(self)
        self._ip_ping_anim_timer.setInterval(120)
        self._ip_ping_anim_timer.timeout.connect(self._tick_ip_ping_spinner)

        # Hostname ping debounce + animation timers
        self._host_ping_debounce = QTimer(self)
        self._host_ping_debounce.setSingleShot(True)
        self._host_ping_debounce.setInterval(600)
        self._host_ping_debounce.timeout.connect(self._start_host_ping)
        self._host_ping_anim_timer = QTimer(self)
        self._host_ping_anim_timer.setInterval(120)
        self._host_ping_anim_timer.timeout.connect(self._tick_host_ping_spinner)

        # Pre-populate — must run after every widget above exists (_set_type
        # touches _btn_lookup_ip) but before the signals are wired below, so
        # that setText() here does not kick off DNS lookups and pings.
        if record:
            self._alias.setText(record["name"])
            self._set_type(record["type"])
            if record["host"]:
                self._host.setText(record["host"])
                self._add_host_field("hostname")
            if record["host_ip"]:
                self._host_ip.setText(record["host_ip"])
                self._add_host_field("ip")
            self._set_prefer(record["host_prefer"])
            self._port.setText(str(record["port"]))
            scheme = record["scheme"]
            if scheme:
                idx = self._scheme_combo.findText(scheme)
                if idx >= 0:
                    self._scheme_combo.setCurrentIndex(idx)
            # Per-field scheme/port for WEB hosts
            if record["type"] == "WEB":
                # Hostname (address) opts
                if record["host"]:
                    hn_scheme = record["scheme"] or "https"
                    idx = self._web_hn_scheme_combo.findText(hn_scheme)
                    if idx >= 0:
                        self._web_hn_scheme_combo.setCurrentIndex(idx)
                    hn_port = record["port"]
                    default_hn_port = 443 if hn_scheme == "https" else 80
                    if hn_port != default_hn_port:
                        self._web_hn_port.setText(str(hn_port))
                # IP opts
                if record["host_ip"]:
                    ip_scheme = record["host_ip_scheme"]
                    if ip_scheme:
                        idx = self._host_ip_scheme_combo.findText(ip_scheme)
                        if idx >= 0:
                            self._host_ip_scheme_combo.setCurrentIndex(idx)
                    ip_port = record["host_ip_port"]
                    if ip_port:
                        self._host_ip_port.setText(str(ip_port))
            if record["type"] != "WEB":
                self._username.setText(record["username"])
                if record["password"] and not record["user_id"]:
                    self._password.setText(record["password"])
                    self._add_password_field()
                if record["user_id"]:
                    for u in self._users:
                        if u["id"] == record["user_id"]:
                            label = f"{u['display_name']} ({u['username']})"
                            idx = self._user_combo.findText(label)
                            if idx >= 0:
                                self._user_combo.setCurrentIndex(idx)
                            break
            self._notes.setPlainText(record["notes"])
            # Fields are only now at their final values; _set_type() above decided
            # the magnifier's visibility against a still-empty IP field.
            self._sync_ip_lookup_button()

        self._host.setFocus()

        # Wire signals
        self._dns_resolved.connect(self._on_dns_result)
        self._ip_ping_result.connect(self._on_ip_ping_result)
        self._host_ping_result.connect(self._on_host_ping_result)
        self._host.textChanged.connect(self._on_host_text_changed)
        self._host_ip.textChanged.connect(self._on_ip_text_changed)

        # Trigger pings immediately when opening to edit an existing host
        if record:
            if record["host"]:
                self._host_ping_debounce.start()
            if record["host_ip"] and self._validate_ip(record["host_ip"]):
                self._ip_ping_debounce.start()

    def _sync_ip_lookup_button(self) -> None:
        """Show the in-field magnifier only for WEB hosts whose IP is still empty.

        Must be called after any change to the type or to the IP field's text.
        Pre-populate sets the IP with signals not yet wired, so nothing else
        re-evaluates it there — leaving the magnifier drawn on top of the IP
        ping dot.
        """
        show = self._btn_web.isChecked() and not self._host_ip.text().strip()
        self._btn_lookup_ip.setVisible(show)
        self._host_ip.setTextMargins(0, 0, 26 if show else 18, 0)

    def _set_type(self, conn_type: str) -> None:
        self._btn_ssh.setChecked(conn_type == "SSH")
        self._btn_rdp.setChecked(conn_type == "RDP")
        self._btn_web.setChecked(conn_type == "WEB")
        is_web = conn_type == "WEB"
        self._credentials_widget.setVisible(not is_web)
        self._port_row_widget.setVisible(not is_web)
        # Show lookup button in IP field when WEB type and field is currently empty
        self._sync_ip_lookup_button()
        # Show trailing lookup button only for WEB when address is filled and IP not added
        self._btn_lookup_ip_trailing.setVisible(
            is_web and bool(self._host.text().strip()) and self._can_add_ip
        )
        # Rename hostname label and buttons for WEB type
        hn_label = "Address:" if is_web else "Hostname:"
        self._lbl_hn.setText(hn_label)
        add_hn_text = "Add Address" if is_web else "Add Hostname"
        self._add_hostname_btn.setText(add_hn_text)
        self._btn_add_hn_trailing.setText(add_hn_text)
        if not is_web:
            cur = self._port.text().strip()
            if cur in ("", "80", "443"):
                self._port.setText(str(_DEFAULT_PORTS[conn_type]))
        # Rebuild layout so web opts widgets show/hide correctly
        self._rebuild_host_order()
        self.adjustSize()

    def _on_scheme_changed(self, scheme: str) -> None:
        """Auto-adjust port when scheme switches, unless user has customised it."""
        cur = self._port.text().strip()
        if cur in ("80", "443", ""):
            self._port.setText("443" if scheme == "https" else "80")

    def _on_hn_scheme_changed(self, scheme: str) -> None:
        """Auto-adjust hostname port when scheme switches."""
        cur = self._web_hn_port.text().strip()
        if cur in ("80", "443", ""):
            self._web_hn_port.setText("443" if scheme == "https" else "80")

    def _on_ip_scheme_changed(self, scheme: str) -> None:
        """Auto-adjust IP port when IP scheme switches."""
        cur = self._host_ip_port.text().strip()
        if cur in ("80", "443", ""):
            self._host_ip_port.setText("443" if scheme == "https" else "80")

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
                self._add_password_field()
                break

    def _set_prefer(self, prefer: str) -> None:
        self._btn_prefer_hostname.setChecked(prefer == "hostname")
        self._btn_prefer_ip.setChecked(prefer == "ip")
        # Reorder rows if both fields are present
        if not self._can_add_hostname and not self._can_add_ip:
            self._rebuild_host_order()
            self.adjustSize()

    def _rebuild_host_order(self) -> None:
        """Re-insert host rows into the sub-container in preferred order."""
        for w in [self._hostname_row_widget, self._dns_row_widget,
                  self._web_hn_opts_widget,
                  self._ip_row_widget, self._web_ip_opts_widget,
                  self._prefer_widget,
                  self._add_hn_trailing_widget, self._add_ip_trailing_widget]:
            self._hsl.removeWidget(w)
            w.hide()

        prefer_ip = self._btn_prefer_ip.isChecked()
        hn_added = not self._can_add_hostname
        ip_added = not self._can_add_ip
        is_web = self._btn_web.isChecked()

        # Combined add-buttons widget shown only when neither field is added yet
        self._add_btns_widget.setVisible(not hn_added and not ip_added)
        # Hide the sub-container itself when empty to avoid phantom spacing
        self._host_section.setVisible(hn_added or ip_added)
        # "Look up IP" in trailing widget: WEB + address filled + IP not yet added
        self._btn_lookup_ip_trailing.setVisible(
            is_web and bool(self._host.text().strip()) and not ip_added and hn_added
        )

        def _add_hostname_block() -> None:
            self._hsl.addWidget(self._hostname_row_widget)
            self._hostname_row_widget.show()
            self._hsl.addWidget(self._dns_row_widget)
            if self._dns_row_shown:
                self._dns_row_widget.show()
            # For WEB hosts, show the per-address scheme/port options below
            if is_web:
                self._hsl.addWidget(self._web_hn_opts_widget)
                self._web_hn_opts_widget.show()

        def _add_ip_block() -> None:
            self._hsl.addWidget(self._ip_row_widget)
            self._ip_row_widget.show()
            # For WEB hosts, show the per-IP scheme/port options below
            if is_web:
                self._hsl.addWidget(self._web_ip_opts_widget)
                self._web_ip_opts_widget.show()

        if prefer_ip:
            if ip_added:
                _add_ip_block()
            if hn_added:
                _add_hostname_block()
        else:
            if hn_added:
                _add_hostname_block()
            if ip_added:
                _add_ip_block()

        if hn_added and ip_added:
            self._hsl.addWidget(self._prefer_widget)
            self._prefer_widget.show()
        elif hn_added:
            # Hostname present, IP not — offer "Add IP" below
            self._hsl.addWidget(self._add_ip_trailing_widget)
            self._add_ip_trailing_widget.show()
        elif ip_added:
            # IP present, hostname not — offer "Add Hostname" below
            self._hsl.addWidget(self._add_hn_trailing_widget)
            self._add_hn_trailing_widget.show()

    def _add_host_field(self, field: str) -> None:
        if field == "hostname":
            self._can_add_hostname = False
            if not self._first_added:
                self._first_added = "hostname"
                self._btn_prefer_hostname.setChecked(True)
                self._btn_prefer_ip.setChecked(False)
        else:
            self._can_add_ip = False
            if not self._first_added:
                self._first_added = "ip"
                self._btn_prefer_ip.setChecked(True)
                self._btn_prefer_hostname.setChecked(False)
        self._rebuild_host_order()
        self.adjustSize()

    def _remove_host_field(self, field: str) -> None:
        if field == "hostname":
            self._host.clear()
            self._host_last_pinged = ""
            self._host_ping_debounce.stop()
            self._host_ping_anim_timer.stop()
            self._host_ping_lbl.hide()
            self._can_add_hostname = True
            # If hostname was primary and IP still exists, switch primary to IP
            if not self._btn_prefer_ip.isChecked() and not self._can_add_ip:
                self._btn_prefer_ip.setChecked(True)
                self._btn_prefer_hostname.setChecked(False)
        else:
            self._host_ip.clear()
            self._ip_last_pinged = ""
            self._ip_ping_debounce.stop()
            self._ip_ping_anim_timer.stop()
            self._ip_ping_lbl.hide()
            self._can_add_ip = True
            # If IP was primary and hostname still exists, switch primary to hostname
            if self._btn_prefer_ip.isChecked() and not self._can_add_hostname:
                self._btn_prefer_hostname.setChecked(True)
                self._btn_prefer_ip.setChecked(False)
        # Update first_added to reflect remaining field
        if not self._can_add_hostname and self._can_add_ip:
            self._first_added = "hostname"
        elif self._can_add_hostname and not self._can_add_ip:
            self._first_added = "ip"
        else:
            self._first_added = ""
        self._dns_row_shown = False
        self._rebuild_host_order()
        self.adjustSize()

    def _add_password_field(self) -> None:
        self._password_row_widget.show()
        self._add_pw_widget.hide()
        self.adjustSize()

    def _remove_password_field(self) -> None:
        self._password_row_widget.hide()
        self._password.clear()
        self._password.setEnabled(True)
        self._add_pw_widget.show()
        self.adjustSize()

    def _on_host_resize(self, event) -> None:
        h = self._host.height()
        sw = self._dns_spinner.width()
        x = self._host.width() - sw - 8
        y = (h - self._dns_spinner.height()) // 2
        self._dns_spinner.move(x, y)
        self._host_ping_lbl.move(x, y)
        QLineEdit.resizeEvent(self._host, event)

    def _on_host_ip_resize(self, event) -> None:
        h = self._host_ip.height()
        lw = self._ip_ping_lbl.width()
        x = self._host_ip.width() - lw - 8
        y = (h - self._ip_ping_lbl.height()) // 2
        self._ip_ping_lbl.move(x, y)
        bw = self._btn_lookup_ip.width()
        self._btn_lookup_ip.move(self._host_ip.width() - bw - 4,
                                 (h - self._btn_lookup_ip.height()) // 2)
        QLineEdit.resizeEvent(self._host_ip, event)

    def _on_host_text_changed(self, text: str) -> None:
        self._dns_anim_timer.stop()
        self._dns_spinner.hide()
        self._dns_debounce.stop()
        self._host_ping_debounce.stop()
        self._host_ping_anim_timer.stop()
        self._host_ping_lbl.hide()
        self._host_last_pinged = ""
        if self._dns_row_shown:
            self._dns_row_shown = False
            focused = self.focusWidget()
            self._rebuild_host_order()
            self.adjustSize()
            if focused:
                focused.setFocus()
        hostname = text.strip()
        if hostname:
            # DNS lookup doesn't make sense for WEB hosts (IP might be a different machine)
            if database.get_setting("nslookup_on_hostname") != "0" and not self._btn_web.isChecked():
                self._dns_debounce.start()
            self._host_ping_debounce.start()
        # Show "Look up IP" in the trailing widget when WEB + address filled + no IP yet
        is_web = self._btn_web.isChecked()
        show_lookup_trailing = is_web and bool(hostname) and self._can_add_ip
        self._btn_lookup_ip_trailing.setVisible(show_lookup_trailing)

    def _tick_dns_spinner(self) -> None:
        self._dns_anim_frame = (self._dns_anim_frame + 1) % len(_SPINNER_FRAMES)
        self._dns_spinner.setText(_SPINNER_FRAMES[self._dns_anim_frame])

    def _lookup_ip_direct(self) -> None:
        """Trigger DNS lookup and fill the IP field directly (no suggestion row)."""
        self._lookup_direct = True
        self._start_dns_lookup()

    def _start_dns_lookup(self) -> None:
        hostname = self._host.text().strip()
        if not hostname:
            return
        # For SSH/RDP, respect the nslookup setting; for WEB it's always manual
        if not self._btn_web.isChecked() and database.get_setting("nslookup_on_hostname") == "0":
            return
        self._dns_pending_host = hostname
        lookup_host, _ = _split_addr(hostname)
        if not lookup_host:
            return
        h = self._host.height()
        sw = self._dns_spinner.width()
        self._dns_spinner.move(self._host.width() - sw - 8, (h - self._dns_spinner.height()) // 2)
        self._dns_spinner.setText(_SPINNER_FRAMES[0])
        self._dns_spinner.show()
        self._dns_spinner.raise_()
        self._dns_anim_timer.start()

        def _work() -> None:
            import socket as _socket
            try:
                results = _socket.getaddrinfo(lookup_host, None, _socket.AF_INET)
                ip = results[0][4][0] if results else ""
            except Exception:
                ip = ""
            self._dns_resolved.emit(ip)

        threading.Thread(target=_work, daemon=True).start()

    def _on_dns_result(self, ip: str) -> None:
        self._dns_anim_timer.stop()
        self._dns_spinner.hide()
        if self._host.text().strip() != self._dns_pending_host:
            self._lookup_direct = False
            return
        if not ip:
            self._lookup_direct = False
            return
        self._dns_resolved_ip = ip
        # Direct mode: fill field immediately, no suggestion row
        if getattr(self, "_lookup_direct", False):
            self._lookup_direct = False
            if self._can_add_ip:
                self._host_ip.setText(ip)
                self._add_host_field("ip")
            else:
                self._host_ip.setText(ip)
            return
        if self._can_add_ip:
            self._dns_lbl.setText(f"Resolved to  {ip}")
        else:
            current = self._host_ip.text().strip()
            if current == ip:
                return  # already matches, no suggestion
            self._dns_lbl.setText(f"Change IP to  {ip}" if current else f"Resolved to  {ip}")
        self._dns_row_shown = True
        focused = self.focusWidget()
        self._rebuild_host_order()
        self.adjustSize()
        if focused:
            focused.setFocus()

    def _dns_accept(self) -> None:
        ip = getattr(self, "_dns_resolved_ip", "")
        self._dns_row_shown = False
        focused = self.focusWidget()
        self._rebuild_host_order()
        self.adjustSize()
        if focused:
            focused.setFocus()
        if ip:
            if self._can_add_ip:
                self._host_ip.setText(ip)
                self._add_host_field("ip")
            else:
                self._host_ip.setText(ip)

    def _dns_dismiss(self) -> None:
        self._dns_row_shown = False
        focused = self.focusWidget()
        self._rebuild_host_order()
        self.adjustSize()
        if focused:
            focused.setFocus()

    def _dns_never(self) -> None:
        self._dns_row_shown = False
        self._rebuild_host_order()
        self.adjustSize()
        database.set_setting("nslookup_on_hostname", "0")

    def _on_ip_text_changed(self, text: str) -> None:
        self._ip_ping_debounce.stop()
        self._ip_ping_anim_timer.stop()
        self._ip_ping_lbl.hide()
        self._ip_last_pinged = ""
        ip = text.strip()
        # Show lookup button only for WEB when field is empty
        self._sync_ip_lookup_button()
        if ip and self._validate_ip(ip):
            self._ip_ping_debounce.start()

    def _tick_ip_ping_spinner(self) -> None:
        self._ip_ping_anim_frame = (self._ip_ping_anim_frame + 1) % len(_SPINNER_FRAMES)
        self._ip_ping_lbl.setText(_SPINNER_FRAMES[self._ip_ping_anim_frame])

    def _start_ip_ping(self) -> None:
        ip = self._host_ip.text().strip().split("/")[0]  # strip path if present
        if not ip or not self._validate_ip(ip):
            return
        self._ip_last_pinged = ip
        self._ip_ping_anim_frame = 0
        h = self._host_ip.height()
        lw = self._ip_ping_lbl.width()
        self._ip_ping_lbl.move(self._host_ip.width() - lw - 8, (h - self._ip_ping_lbl.height()) // 2)
        self._ip_ping_lbl.setText(_SPINNER_FRAMES[0])
        self._ip_ping_lbl.setStyleSheet("color: #aaa; font-size: 12px; background: transparent;")
        self._ip_ping_lbl.show()
        self._ip_ping_lbl.raise_()
        self._ip_ping_anim_timer.start()

        def _work() -> None:
            try:
                if sys.platform == "win32":
                    cmd = ["ping", "-n", "1", "-w", "1500", ip]
                    kw: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
                else:
                    cmd = ["ping", "-c", "1", "-W", "2", ip]
                    kw = {}
                r = subprocess.run(cmd, capture_output=True, **kw)
                online = r.returncode == 0
            except Exception:
                online = False
            self._ip_ping_result.emit(online)

        threading.Thread(target=_work, daemon=True).start()

    def _on_ip_ping_result(self, online: bool) -> None:
        self._ip_ping_anim_timer.stop()
        color = "#22c55e" if online else "#ef4444"
        self._ip_ping_lbl.setText("●")
        self._ip_ping_lbl.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent;")
        self._ip_ping_lbl.show()

    def _tick_host_ping_spinner(self) -> None:
        self._host_ping_anim_frame = (self._host_ping_anim_frame + 1) % len(_SPINNER_FRAMES)
        self._host_ping_lbl.setText(_SPINNER_FRAMES[self._host_ping_anim_frame])

    def _start_host_ping(self) -> None:
        hostname = self._host.text().strip()
        if not hostname:
            return
        self._host_last_pinged = hostname
        ping_host, _ = _split_addr(hostname)
        if not ping_host:
            return
        self._host_ping_anim_frame = 0
        h = self._host.height()
        sw = self._host_ping_lbl.width()
        self._host_ping_lbl.move(self._host.width() - sw - 8, (h - self._host_ping_lbl.height()) // 2)
        self._host_ping_lbl.setText(_SPINNER_FRAMES[0])
        self._host_ping_lbl.setStyleSheet("color: #aaa; font-size: 12px; background: transparent;")
        self._host_ping_lbl.show()
        self._host_ping_lbl.raise_()
        self._host_ping_anim_timer.start()

        def _work() -> None:
            try:
                if sys.platform == "win32":
                    cmd = ["ping", "-n", "1", "-w", "1500", ping_host]
                    kw: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
                else:
                    cmd = ["ping", "-c", "1", "-W", "2", ping_host]
                    kw = {}
                r = subprocess.run(cmd, capture_output=True, **kw)
                online = r.returncode == 0
            except Exception:
                online = False
            self._host_ping_result.emit(online)

        threading.Thread(target=_work, daemon=True).start()

    def _on_host_ping_result(self, online: bool) -> None:
        self._host_ping_anim_timer.stop()
        color = "#22c55e" if online else "#ef4444"
        self._host_ping_lbl.setText("●")
        self._host_ping_lbl.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent;")
        self._host_ping_lbl.show()

    @staticmethod
    @staticmethod
    def _validate_ip(ip: str) -> bool:
        # Strip optional path (e.g. "10.0.0.1/dashboard/" → "10.0.0.1")
        ip = ip.split("/")[0]
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

    def _selected_user_id(self) -> Optional[int]:
        val = self._user_combo.currentText()
        if val == "-- Manual --":
            return None
        for u in self._users:
            if f"{u['display_name']} ({u['username']})" == val:
                return u["id"]
        return None

    def _save(self) -> None:
        name = self._alias.text().strip()
        host = self._host.text().strip()
        host_ip = self._host_ip.text().strip()
        host_prefer = "ip" if self._btn_prefer_ip.isChecked() else "hostname"
        conn_type = "WEB" if self._btn_web.isChecked() else ("SSH" if self._btn_ssh.isChecked() else "RDP")
        is_web = conn_type == "WEB"

        # Derive scheme / port depending on type
        if is_web:
            hn_added = not self._can_add_hostname
            ip_only = not hn_added and not self._can_add_ip
            if hn_added:
                scheme = self._web_hn_scheme_combo.currentText()
                port_str = self._web_hn_port.text().strip() or ("443" if scheme == "https" else "80")
            elif ip_only:
                scheme = self._host_ip_scheme_combo.currentText()
                port_str = self._host_ip_port.text().strip() or ("443" if scheme == "https" else "80")
            else:
                scheme, port_str = "https", "443"
            host_ip_scheme = self._host_ip_scheme_combo.currentText() if host_ip else ""
            host_ip_port_str = self._host_ip_port.text().strip() if host_ip else ""
        else:
            scheme = ""
            port_str = self._port.text().strip()
            host_ip_scheme = ""
            host_ip_port_str = ""

        user_id = None
        username = ""
        password = ""
        if not is_web:
            user_id = self._selected_user_id()
            # Re-enable disabled fields momentarily so text() can be read
            un_dis = not self._username.isEnabled()
            if un_dis:
                self._username.setEnabled(True)
            username = self._username.text().strip()
            if un_dis:
                self._username.setEnabled(False)
            password = self._password.text() if self._password_row_widget.isVisible() else ""

        notes = self._notes.toPlainText().strip()

        if not host and not host_ip:
            QMessageBox.warning(self, "Validation", "Hostname or IP is required.")
            return
        if host_ip and not self._validate_ip(host_ip):
            QMessageBox.warning(
                self, "Validation",
                "IP address is not valid.\nExpected format: 0–255 per octet (e.g. 192.168.1.1)."
            )
            return
        if not is_web and not username:
            QMessageBox.warning(self, "Validation", "Username is required.")
            return
        try:
            port = int(port_str)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Validation", "Port must be 1–65535.")
            return
        try:
            host_ip_port = int(host_ip_port_str) if host_ip_port_str else 0
            if host_ip_port and not 1 <= host_ip_port <= 65535:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Validation", "IP port must be 1–65535.")
            return

        self._result = {
            "name": name, "type": conn_type, "host": host, "host_ip": host_ip,
            "host_prefer": host_prefer, "port": port, "scheme": scheme,
            "host_ip_scheme": host_ip_scheme, "host_ip_port": host_ip_port,
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
        self._is_web = record["type"] == "WEB"
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._animate_dots)
        self._dot_count = 0
        # Pre-load hover icons once per card (QApp already running at this point)
        self._icon_connect = _load_icon("paperplane-svgrepo", color="white", size=26)
        self._icon_open = _load_icon("globe-europe-solid-svgrepo-com", color="white", size=26)
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

        alias = record["name"]          # may be empty
        default_port = _DEFAULT_PORTS.get(record["type"])
        is_nonstandard = record["port"] != default_port
        # Read port-display settings
        _port_show   = database.get_setting("card_port_show")    # primary|secondary|both|none
        _port_filter = (
            database.get_setting("card_port_filter_web")
            if record["type"] == "WEB"
            else database.get_setting("card_port_filter")
        )
        def _with_port(addr: str, on: bool) -> str:
            """Return addr with ':port' inserted after the host (before any path)."""
            if not on:
                return addr
            if _port_filter == "nonstandard" and not is_nonstandard:
                return addr
            if "/" in addr:
                host_part, path_part = addr.split("/", 1)
                return f"{host_part}:{record['port']}/{path_part}"
            return f"{addr}:{record['port']}"
        primary_sfx   = _with_port  # used as a callable below
        secondary_sfx = _with_port
        show_primary_port   = _port_show in ("primary", "both")
        show_secondary_port = _port_show in ("secondary", "both")
        # Respect host_prefer when picking primary vs secondary
        prefer_ip = record["host_prefer"] == "ip"
        if prefer_ip:
            primary_addr = record["host_ip"] or record["host"]
            secondary_addr = record["host"] if (record["host"] and record["host_ip"]) else ""
        else:
            primary_addr = record["host"] or record["host_ip"]
            secondary_addr = record["host_ip"] if (record["host"] and record["host_ip"]) else ""

        # Title: alias if set, otherwise primary identifier (with port)
        if alias:
            title = alias
            primary_line = _with_port(primary_addr, show_primary_port)
            show_secondary = database.get_setting("show_secondary_on_card") != "0"
            secondary_line = _with_port(secondary_addr, show_secondary_port) if (show_secondary and secondary_addr) else ""
        else:
            title = _with_port(primary_addr, show_primary_port)
            primary_line = ""   # title already is the primary
            secondary_line = _with_port(secondary_addr, show_secondary_port) if secondary_addr else ""  # always show when no alias

        self._name_lbl = QLabel(title)
        self._name_lbl.setAlignment(Qt.AlignCenter)
        self._name_lbl.setStyleSheet(
            "background: transparent; font-size: 16px; font-weight: bold;"
        )
        info_layout.addWidget(self._name_lbl)

        # Primary address sub-line (only when alias is set)
        self._addr_lbl = QLabel(primary_line)
        self._addr_lbl.setAlignment(Qt.AlignCenter)
        self._addr_lbl.setStyleSheet(
            "background: transparent; font-size: 10px; color: #888;"
        )
        self._addr_lbl.setVisible(bool(primary_line))
        info_layout.addWidget(self._addr_lbl)

        # Secondary address line
        self._secondary_lbl = QLabel(secondary_line)
        self._secondary_lbl.setAlignment(Qt.AlignCenter)
        self._secondary_lbl.setStyleSheet(
            "background: transparent; font-size: 10px; color: #888;"
        )
        self._secondary_lbl.setVisible(bool(secondary_line))
        info_layout.addWidget(self._secondary_lbl)

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
            # QCursor.pos() rather than event.globalPosition(): when a context
            # menu is already open, the click that dismisses it is *replayed*
            # to the card underneath, and the replayed event still carries the
            # coordinates of the original click. The live cursor position is
            # always where the user actually clicked.
            self._on_right(self._record, QCursor.pos())
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        if not self._connecting:
            if self._active_count > 0:
                self._hover_text = "Bring to front"
                icon = self._icon_bring
            elif self._is_web:
                self._hover_text = "Open"
                icon = self._icon_open
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

    def update_secondary_visibility(self) -> None:
        """Show/hide secondary identifier line based on settings (alias-only cards)."""
        alias = self._record["name"]
        if not alias:
            # No alias: secondary always shown if it exists — nothing to toggle
            return
        show = database.get_setting("show_secondary_on_card") != "0"
        if show and self._secondary_lbl.text():
            self._secondary_lbl.show()
        else:
            self._secondary_lbl.hide()

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

        self._nslookup_toggle = self._make_toggle_row(
            gen_layout, "DNS Lookup",
            "Resolve hostname and offer to add the IP when creating/editing a host",
            "nslookup_on_hostname",
        )
        self._nslookup_toggle.toggled.connect(self._on_nslookup_changed)

        self._secondary_toggle = self._make_toggle_row(
            gen_layout, "Show Secondary Identifier",
            "Show both hostname and IP as grey text on cards that have an alias and both",
            "show_secondary_on_card",
        )
        self._secondary_toggle.toggled.connect(self._on_secondary_changed)

        # ── Port display row ──────────────────────────────────────────────
        port_row_frame = QFrame()
        port_row_frame.setObjectName("user_row")
        port_row_frame.setAttribute(Qt.WA_StyledBackground, True)
        port_rl = QHBoxLayout(port_row_frame)
        port_rl.setContentsMargins(12, 8, 12, 8)
        port_rl.setSpacing(8)
        port_col = QVBoxLayout()
        port_col.setSpacing(2)
        port_title_lbl = QLabel("Show Port On Card")
        port_title_lbl.setStyleSheet("font-weight: bold; background: transparent;")
        port_col.addWidget(port_title_lbl)
        port_desc_lbl = QLabel("Which identifier line(s) include the port number")
        port_desc_lbl.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        port_col.addWidget(port_desc_lbl)
        port_rl.addLayout(port_col)
        port_rl.addStretch()

        _show_opts   = ["Primary only", "Secondary only", "Both", "Neither"]
        _show_vals   = ["primary", "secondary", "both", "none"]
        _filter_opts = ["Non-standard", "All"]
        _filter_vals = ["nonstandard", "all"]

        cur_show        = database.get_setting("card_port_show")
        cur_filter      = database.get_setting("card_port_filter")
        cur_filter_web  = database.get_setting("card_port_filter_web")
        show_idx        = _show_vals.index(cur_show)         if cur_show        in _show_vals   else 0
        filter_idx      = _filter_vals.index(cur_filter)    if cur_filter      in _filter_vals else 0
        filter_web_idx  = _filter_vals.index(cur_filter_web) if cur_filter_web in _filter_vals else 1  # default "all"

        self._port_show_combo = QComboBox()
        self._port_show_combo.addItems(_show_opts)
        self._port_show_combo.setCurrentIndex(show_idx)
        self._port_show_combo.setFixedWidth(130)
        port_rl.addWidget(self._port_show_combo)

        self._port_for_lbl = QLabel("  SSH/RDP:")
        self._port_for_lbl.setStyleSheet("background: transparent; color: #aaa;")
        port_rl.addWidget(self._port_for_lbl)

        self._port_filter_combo = QComboBox()
        self._port_filter_combo.addItems(_filter_opts)
        self._port_filter_combo.setCurrentIndex(filter_idx)
        self._port_filter_combo.setFixedWidth(115)
        port_rl.addWidget(self._port_filter_combo)

        self._port_for_web_lbl = QLabel("  WEB:")
        self._port_for_web_lbl.setStyleSheet("background: transparent; color: #aaa;")
        port_rl.addWidget(self._port_for_web_lbl)

        self._port_filter_web_combo = QComboBox()
        self._port_filter_web_combo.addItems(_filter_opts)
        self._port_filter_web_combo.setCurrentIndex(filter_web_idx)
        self._port_filter_web_combo.setFixedWidth(115)
        port_rl.addWidget(self._port_filter_web_combo)

        # Hide filter combos when "Neither" is selected
        _port_filter_visible = cur_show != "none"
        self._port_for_lbl.setVisible(_port_filter_visible)
        self._port_filter_combo.setVisible(_port_filter_visible)
        self._port_for_web_lbl.setVisible(_port_filter_visible)
        self._port_filter_web_combo.setVisible(_port_filter_visible)

        self._port_show_vals   = _show_vals
        self._port_filter_vals = _filter_vals

        def _on_port_show_changed(idx: int) -> None:
            val = _show_vals[idx]
            database.set_setting("card_port_show", val)
            visible = val != "none"
            self._port_for_lbl.setVisible(visible)
            self._port_filter_combo.setVisible(visible)
            self._port_for_web_lbl.setVisible(visible)
            self._port_filter_web_combo.setVisible(visible)
            self._on_settings_changed()

        def _on_port_filter_changed(idx: int) -> None:
            database.set_setting("card_port_filter", _filter_vals[idx])
            self._on_settings_changed()

        def _on_port_filter_web_changed(idx: int) -> None:
            database.set_setting("card_port_filter_web", _filter_vals[idx])
            self._on_settings_changed()

        self._port_show_combo.currentIndexChanged.connect(_on_port_show_changed)
        self._port_filter_combo.currentIndexChanged.connect(_on_port_filter_changed)
        self._port_filter_web_combo.currentIndexChanged.connect(_on_port_filter_web_changed)
        gen_layout.addWidget(port_row_frame)

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

        # ── Web browser path ──────────────────────────────────────────────
        browser_group = QFrame()
        browser_group.setObjectName("user_row")
        browser_group.setAttribute(Qt.WA_StyledBackground, True)
        browser_vl = QVBoxLayout(browser_group)
        browser_vl.setContentsMargins(0, 0, 0, 0)
        browser_vl.setSpacing(0)

        browser_top = QWidget()
        browser_top.setAttribute(Qt.WA_TranslucentBackground)
        browser_top_l = QHBoxLayout(browser_top)
        browser_top_l.setContentsMargins(12, 8, 12, 8)
        browser_top_l.setSpacing(8)
        browser_col = QVBoxLayout()
        browser_col.setSpacing(2)
        browser_title_lbl = QLabel("Web Browser")
        browser_title_lbl.setStyleSheet("font-weight: bold; background: transparent;")
        browser_col.addWidget(browser_title_lbl)
        browser_desc_lbl = QLabel("Custom browser executable for web hosts (empty = system default)")
        browser_desc_lbl.setStyleSheet("color: #888; font-size: 11px; background: transparent;")
        browser_col.addWidget(browser_desc_lbl)
        browser_top_l.addLayout(browser_col)
        browser_vl.addWidget(browser_top)

        browser_sep = QFrame()
        browser_sep.setFrameShape(QFrame.HLine)
        browser_sep.setStyleSheet("background: #3a3a3a; max-height: 1px; border: none;")
        browser_vl.addWidget(browser_sep)

        browser_path_row = QWidget()
        browser_path_row.setStyleSheet("background: transparent;")
        bpr_l = QHBoxLayout(browser_path_row)
        bpr_l.setContentsMargins(12, 8, 12, 8)
        bpr_l.setSpacing(8)
        self._browser_path_edit = QLineEdit()
        self._browser_path_edit.setPlaceholderText(
            r"e.g. C:\Program Files\Google\Chrome\Application\chrome.exe"
        )
        self._browser_path_edit.setText(database.get_setting("web_browser_path"))
        self._browser_path_edit.editingFinished.connect(self._on_browser_path_changed)
        bpr_l.addWidget(self._browser_path_edit)
        btn_browse_browser = QPushButton("Browse…")
        btn_browse_browser.setFixedWidth(70)
        btn_browse_browser.clicked.connect(self._browse_browser_path)
        bpr_l.addWidget(btn_browse_browser)
        browser_vl.addWidget(browser_path_row)

        gen_layout.addWidget(browser_group)

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

    def _on_nslookup_changed(self, checked: bool) -> None:
        database.set_setting("nslookup_on_hostname", "1" if checked else "0")
        self._nslookup_toggle.setText("ON" if checked else "OFF")

    def _on_secondary_changed(self, checked: bool) -> None:
        database.set_setting("show_secondary_on_card", "1" if checked else "0")
        self._secondary_toggle.setText("ON" if checked else "OFF")
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

    def _on_browser_path_changed(self) -> None:
        database.set_setting("web_browser_path", self._browser_path_edit.text().strip())

    def _browse_browser_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Browser Executable", "",
            "Executables (*.exe);;All Files (*)"
        )
        if path:
            self._browser_path_edit.setText(path)
            database.set_setting("web_browser_path", path)


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
        self._ctx_menu: QMenu | None = None             # currently open context menu

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
        self._stack.setCurrentWidget(self._overview_page)  # just switch page; _apply_general_settings() below loads cards

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
            or query in (r["host_ip"] or "").lower()
            or query in r["type"].lower()
        ]

        for card in self._cards.values():
            card.hide()
            card.deleteLater()
        self._cards.clear()

        new_cards: list[HostCard] = []
        for rec in filtered:
            card = HostCard(rec, self._on_card_left, self._on_card_right,
                            parent=self._card_grid)
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
            rec = card.record
            host, _ = _split_addr(rec["host"] or rec["host_ip"])
            if host:
                self._ping_host(cid, host)

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
        if record["type"] == "WEB":
            self._open_web_url(record)
            return
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
        # Dismiss a menu left open on another card, so we never stack a second
        # menu inside the first one's blocking exec() loop. Deleting it here
        # rather than on close keeps at most one stale menu alive, and avoids
        # tearing a menu down while one of its own actions is still running.
        if self._ctx_menu is not None:
            self._ctx_menu.close()
            self._ctx_menu.deleteLater()
            self._ctx_menu = None

        menu = QMenu(self)
        if record["type"] == "WEB":
            host = record["host"]
            host_ip = record["host_ip"]
            if host and host_ip:
                prefer_ip = record["host_prefer"] == "ip"
                # Default action first (matches what left-click does)
                if prefer_ip:
                    act = QAction(_load_icon("globe-europe-solid-svgrepo-com"), "Open with IP", menu)
                    act.triggered.connect(lambda: self._open_web_url(record, use="ip"))
                    menu.addAction(act)
                    act = QAction(_load_icon("globe-europe-solid-svgrepo-com"), "Open with Hostname", menu)
                    act.triggered.connect(lambda: self._open_web_url(record, use="hostname"))
                    menu.addAction(act)
                else:
                    act = QAction(_load_icon("globe-europe-solid-svgrepo-com"), "Open with Hostname", menu)
                    act.triggered.connect(lambda: self._open_web_url(record, use="hostname"))
                    menu.addAction(act)
                    act = QAction(_load_icon("globe-europe-solid-svgrepo-com"), "Open with IP", menu)
                    act.triggered.connect(lambda: self._open_web_url(record, use="ip"))
                    menu.addAction(act)
            else:
                act = QAction(_load_icon("globe-europe-solid-svgrepo-com"), "Open", menu)
                act.triggered.connect(lambda: self._open_web_url(record))
                menu.addAction(act)
            menu.addSeparator()
        else:
            cid = record["id"]
            n = self._active_window_count(cid)
            if n > 0:
                wlabel = "window" if n == 1 else "windows"
                act = QAction(_load_icon("locate-svgrepo"), f"Locate {wlabel}", menu)
                act.triggered.connect(lambda: self._locate_windows(record))
                menu.addAction(act)

                act = QAction(_load_icon("move-here-svgrepo"), "Move to this monitor", menu)
                act.triggered.connect(lambda: self._move_windows(record))
                menu.addAction(act)

                menu.addSeparator()

                act = QAction(_load_icon("plus-square-on-square-svgrepo-com"), "Start additional connection", menu)
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

        # popup() instead of exec(): non-blocking, so right-clicking another
        # card does not nest a second event loop inside this one.
        self._ctx_menu = menu
        menu.popup(pos)

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
        host_ip = record["host_ip"]
        host_prefer = record["host_prefer"]
        if host and host_ip:
            effective_host = conn_launcher.resolve_host(host, host_ip, host_prefer, record["port"])
        else:
            effective_host = host or host_ip
        # Accumulate title hints so older windows can still be found.
        existing = self._snap_tags.get(cid, [])
        for h in (tag, host, effective_host):
            if h and h not in existing:
                existing.append(h)
        if existing:
            self._snap_tags[cid] = existing
        try:
            proc = conn_launcher.launch(
                record["type"], effective_host, record["port"], username,
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
        name = record["name"] or record["host"] or record["host_ip"] or "Host"
        reply = QMessageBox.question(
            self, "Confirm", f"Delete '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            database.delete_connection(record["id"])
            self._refresh_cards()

    def _open_web_url(self, record, use: str = "") -> None:
        """Build the URL and open it in the configured browser."""
        scheme = record["scheme"] or "https"
        port = record["port"]
        host = record["host"]
        host_ip = record["host_ip"]
        if use == "hostname":
            addr = host
            effective_scheme = scheme
            effective_port = port
        elif use == "ip":
            addr = host_ip
            effective_scheme = record["host_ip_scheme"] or scheme
            ip_port = record["host_ip_port"]
            effective_port = ip_port if ip_port else port
        else:
            prefer = record["host_prefer"]
            if prefer == "ip" and host_ip:
                addr = host_ip
                effective_scheme = record["host_ip_scheme"] or scheme
                ip_port = record["host_ip_port"]
                effective_port = ip_port if ip_port else port
            else:
                addr = host or host_ip
                effective_scheme = scheme
                effective_port = port
        if not addr:
            return
        # Split off any path component stored in the address (e.g. "10.0.0.1/dashboard/")
        addr_host, addr_path = _split_addr(addr)
        default_port = 443 if effective_scheme == "https" else 80
        if effective_port != default_port:
            url = f"{effective_scheme}://{addr_host}:{effective_port}{addr_path}"
        else:
            url = f"{effective_scheme}://{addr_host}{addr_path}"
        browser_path = database.get_setting("web_browser_path")
        conn_launcher.launch_web(url, browser_path)
