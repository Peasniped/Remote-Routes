"""Main GUI window for Remote Routes using customtkinter."""

import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

import database
import connections as conn_launcher

# ── Appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

_DEFAULT_PORTS = {"SSH": 22, "RDP": 3389}

# ── Colours ───────────────────────────────────────────────────────────────────
_CLR_ONLINE = "#22c55e"
_CLR_OFFLINE = "#ef4444"
_CLR_ACTIVE = "#22c55e"
_CLR_ADD = "#16a34a"
_CLR_ADD_HOVER = "#15803d"
_CLR_UNKNOWN = "gray50"
_CLR_CARD_DARK = "#3a3a3a"
_CLR_CARD_LIGHT = "#d4d4d4"

# ── Timer intervals (ms) ─────────────────────────────────────────────────────
_PING_INTERVAL = 30_000
_PROC_INTERVAL = 3_000


# ═══════════════════════════════════════════════════════════════════════════════
#  Connection Dialog (add / edit a host)
# ═══════════════════════════════════════════════════════════════════════════════
class ConnectionDialog(ctk.CTkToplevel):
    """Modal dialog for creating or editing a host entry."""

    def __init__(self, parent, record=None):
        super().__init__(parent)
        self.title("Edit Host" if record else "Add Host")
        self.resizable(False, False)
        self.grab_set()

        self._result = None
        self._record = record
        self._users = database.get_all_users()

        pad = {"padx": 10, "pady": 6}

        # ── form fields ───────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Name:").grid(row=0, column=0, sticky="e", **pad)
        self._name = ctk.CTkEntry(self, width=260)
        self._name.grid(row=0, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Type:").grid(row=1, column=0, sticky="e", **pad)
        self._type_var = ctk.StringVar(value="SSH")
        self._type = ctk.CTkSegmentedButton(
            self,
            values=["SSH", "RDP"],
            variable=self._type_var,
            command=self._on_type_change,
        )
        self._type.grid(row=1, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Host:").grid(row=2, column=0, sticky="e", **pad)
        self._host = ctk.CTkEntry(self, width=260)
        self._host.grid(row=2, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Port:").grid(row=3, column=0, sticky="e", **pad)
        self._port = ctk.CTkEntry(self, width=80)
        self._port.grid(row=3, column=1, sticky="w", **pad)

        # ── user selection ────────────────────────────────────────────────
        ctk.CTkLabel(self, text="User:").grid(row=4, column=0, sticky="e", **pad)
        user_labels = ["-- Manual --"] + [
            f"{u['display_name']} ({u['username']})" for u in self._users
        ]
        self._user_var = ctk.StringVar(value="-- Manual --")
        self._user_menu = ctk.CTkOptionMenu(
            self,
            variable=self._user_var,
            values=user_labels,
            command=self._on_user_change,
            width=260,
        )
        self._user_menu.grid(row=4, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Username:").grid(row=5, column=0, sticky="e", **pad)
        self._username = ctk.CTkEntry(self, width=260)
        self._username.grid(row=5, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Password:").grid(row=6, column=0, sticky="e", **pad)
        self._password = ctk.CTkEntry(self, width=260, show="•")
        self._password.grid(row=6, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Notes:").grid(row=7, column=0, sticky="ne", **pad)
        self._notes = ctk.CTkTextbox(self, width=260, height=60)
        self._notes.grid(row=7, column=1, columnspan=2, sticky="w", **pad)

        # ── buttons ───────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=8, column=0, columnspan=3, pady=(4, 10))
        ctk.CTkButton(btn_frame, text="Save", command=self._save, width=100).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            command=self.destroy,
            width=100,
            fg_color="gray40",
            hover_color="gray30",
        ).pack(side="left", padx=8)

        # ── pre-populate when editing ─────────────────────────────────────
        if record:
            self._name.insert(0, record["name"])
            self._type_var.set(record["type"])
            self._host.insert(0, record["host"])
            self._port.insert(0, str(record["port"]))
            self._username.insert(0, record["username"])
            self._password.insert(0, record["password"])
            self._notes.insert("1.0", record["notes"])
            if record["user_id"]:
                for u in self._users:
                    if u["id"] == record["user_id"]:
                        label = f"{u['display_name']} ({u['username']})"
                        self._user_var.set(label)
                        self._on_user_change(label)
                        break
        else:
            self._port.insert(0, "22")

        self._name.focus()
        self.wait_window()

    # ── helpers ───────────────────────────────────────────────────────────
    def _on_type_change(self, value: str) -> None:
        cur = self._port.get().strip()
        if cur in ("", "22", "3389"):
            self._port.delete(0, "end")
            self._port.insert(0, str(_DEFAULT_PORTS[value]))

    def _on_user_change(self, value: str) -> None:
        if value == "-- Manual --":
            self._username.configure(state="normal")
            self._password.configure(state="normal")
            return
        for u in self._users:
            if f"{u['display_name']} ({u['username']})" == value:
                self._username.configure(state="normal")
                self._username.delete(0, "end")
                self._username.insert(0, u["username"])
                self._username.configure(state="disabled")
                self._password.configure(state="normal")
                self._password.delete(0, "end")
                self._password.insert(0, u["password"])
                self._password.configure(state="disabled")
                break

    def _selected_user_id(self):
        val = self._user_var.get()
        if val == "-- Manual --":
            return None
        for u in self._users:
            if f"{u['display_name']} ({u['username']})" == val:
                return u["id"]
        return None

    def _save(self) -> None:
        name = self._name.get().strip()
        host = self._host.get().strip()
        port_str = self._port.get().strip()
        conn_type = self._type_var.get()
        user_id = self._selected_user_id()

        # re-enable so we can read the values
        self._username.configure(state="normal")
        self._password.configure(state="normal")
        username = self._username.get().strip()
        password = self._password.get()
        notes = self._notes.get("1.0", "end").strip()

        if not name:
            messagebox.showerror("Validation", "Name is required.", parent=self)
            return
        if not host:
            messagebox.showerror("Validation", "Host is required.", parent=self)
            return
        if not username:
            messagebox.showerror("Validation", "Username is required.", parent=self)
            return
        try:
            port = int(port_str)
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Validation", "Port must be 1\u201365535.", parent=self
            )
            return

        self._result = {
            "name": name,
            "type": conn_type,
            "host": host,
            "port": port,
            "user_id": user_id,
            "username": username,
            "password": password,
            "notes": notes,
        }
        self.destroy()

    @property
    def result(self):
        return self._result


# ═══════════════════════════════════════════════════════════════════════════════
#  User Dialog (add / edit a saved user)
# ═══════════════════════════════════════════════════════════════════════════════
class UserDialog(ctk.CTkToplevel):
    """Modal dialog for creating or editing a user."""

    def __init__(self, parent, user=None):
        super().__init__(parent)
        self.title("Edit User" if user else "Add User")
        self.resizable(False, False)
        self.grab_set()
        self._result = None

        pad = {"padx": 10, "pady": 6}

        ctk.CTkLabel(self, text="Display Name:").grid(
            row=0, column=0, sticky="e", **pad
        )
        self._display_name = ctk.CTkEntry(self, width=220)
        self._display_name.grid(row=0, column=1, sticky="w", **pad)

        ctk.CTkLabel(self, text="Username:").grid(
            row=1, column=0, sticky="e", **pad
        )
        self._username = ctk.CTkEntry(self, width=220)
        self._username.grid(row=1, column=1, sticky="w", **pad)

        ctk.CTkLabel(self, text="Password:").grid(
            row=2, column=0, sticky="e", **pad
        )
        self._password = ctk.CTkEntry(self, width=220, show="\u2022")
        self._password.grid(row=2, column=1, sticky="w", **pad)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(4, 10))
        ctk.CTkButton(btn_frame, text="Save", command=self._save, width=100).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            command=self.destroy,
            width=100,
            fg_color="gray40",
            hover_color="gray30",
        ).pack(side="left", padx=8)

        if user:
            self._display_name.insert(0, user["display_name"])
            self._username.insert(0, user["username"])
            self._password.insert(0, user["password"])

        self._display_name.focus()
        self.wait_window()

    def _save(self) -> None:
        dn = self._display_name.get().strip()
        un = self._username.get().strip()
        pw = self._password.get()
        if not dn:
            messagebox.showerror(
                "Validation", "Display name is required.", parent=self
            )
            return
        if not un:
            messagebox.showerror(
                "Validation", "Username is required.", parent=self
            )
            return
        self._result = {"display_name": dn, "username": un, "password": pw}
        self.destroy()

    @property
    def result(self):
        return self._result


# ═══════════════════════════════════════════════════════════════════════════════
#  Host Card
# ═══════════════════════════════════════════════════════════════════════════════
class HostCard(ctk.CTkFrame):
    """Rounded tile representing a single remote host.

    Layout (top → bottom inside a transparent wrapper):
      • a small badge label ("Active" / "x active") – hidden when idle
      • an inner card with centred protocol, hostname, and address
      • a ping-status dot placed in the top-right corner of the card
    """

    WIDTH = 180
    HEIGHT = 120

    def __init__(self, parent, record, on_left_click, on_right_click, **kw):
        # Transparent outer wrapper – holds badge + card
        super().__init__(parent, fg_color="transparent")

        self._record = record
        self._on_left = on_left_click
        self._on_right = on_right_click
        self._active_count = 0

        # ── active badge (sits above the card) ────────────────────────────
        self._badge = ctk.CTkLabel(
            self,
            text="",
            height=16,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_CLR_ACTIVE,
        )
        self._badge.pack(pady=(0, 2))

        # ── inner card frame ──────────────────────────────────────────────
        card_color = _CLR_CARD_DARK if ctk.get_appearance_mode() == "Dark" else _CLR_CARD_LIGHT
        self._inner = ctk.CTkFrame(
            self,
            width=self.WIDTH,
            height=self.HEIGHT,
            corner_radius=16,
            border_width=0,
            fg_color=card_color,
        )
        self._inner.pack()
        self._inner.pack_propagate(False)

        # ── ping dot (top-right corner) ───────────────────────────────────
        self._ping_dot = ctk.CTkLabel(
            self._inner,
            text="\u25cf",
            font=ctk.CTkFont(size=12),
            text_color=_CLR_UNKNOWN,
        )
        self._ping_dot.place(relx=1.0, rely=0.0, anchor="ne", x=-8, y=8)

        # ── protocol label (vertically centred in card) ───────────────────
        self._type_lbl = ctk.CTkLabel(
            self._inner,
            text=record["type"],
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        self._type_lbl.place(relx=0.5, rely=0.42, anchor="center")

        # ── hostname + IP (tight group, pinned just below centre) ─────────
        info = ctk.CTkFrame(self._inner, fg_color="transparent")
        info.place(relx=0.5, rely=0.78, anchor="center")

        self._name_lbl = ctk.CTkLabel(
            info,
            text=record["name"],
            font=ctk.CTkFont(size=12),
        )
        self._name_lbl.pack()

        default_port = _DEFAULT_PORTS.get(record["type"])
        port_suffix = "" if record["port"] == default_port else f":{record['port']}"
        self._addr_lbl = ctk.CTkLabel(
            info,
            text=f"{record['host']}{port_suffix}",
            font=ctk.CTkFont(size=10),
            text_color="gray60",
        )
        self._addr_lbl.pack(pady=0)

        # ── bind clicks recursively ───────────────────────────────────────
        self._bind_recursive(self)

    # ── internals ─────────────────────────────────────────────────────────
    def _bind_recursive(self, widget):
        widget.bind("<Button-1>", self._left)
        widget.bind("<Button-3>", self._right)
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _left(self, _event=None):
        self._on_left(self._record)

    def _right(self, event=None):
        self._on_right(self._record, event)

    # ── public API ────────────────────────────────────────────────────────
    def set_online(self, online: bool | None) -> None:
        if online is None:
            colour = _CLR_UNKNOWN
        elif online:
            colour = _CLR_ONLINE
        else:
            colour = _CLR_OFFLINE
        self._ping_dot.configure(text_color=colour)

    def set_active_count(self, count: int) -> None:
        self._active_count = count
        if count > 0:
            self._inner.configure(border_width=3, border_color=_CLR_ACTIVE)
            text = "Active" if count == 1 else f"{count} active"
            self._badge.configure(text=text)
        else:
            self._inner.configure(border_width=0)
            self._badge.configure(text="")

    @property
    def record(self):
        return self._record

    @property
    def active_count(self):
        return self._active_count


# ═══════════════════════════════════════════════════════════════════════════════
#  Settings Page
# ═══════════════════════════════════════════════════════════════════════════════
class SettingsPage(ctk.CTkFrame):
    """Full-page overlay with user management."""

    def __init__(self, parent, on_back, **kw):
        super().__init__(parent, **kw)
        self._on_back = on_back

        # ── header ────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkButton(
            header,
            text="\u2190 Back",
            width=80,
            command=on_back,
            fg_color="gray40",
            hover_color="gray30",
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text="Settings",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left", padx=16)

        # ── users section ─────────────────────────────────────────────────
        section = ctk.CTkFrame(self, fg_color="transparent")
        section.pack(fill="both", expand=True, padx=16, pady=8)

        sec_header = ctk.CTkFrame(section, fg_color="transparent")
        sec_header.pack(fill="x")

        ctk.CTkLabel(
            sec_header,
            text="Users",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            sec_header,
            text="+ Add User",
            width=110,
            fg_color=_CLR_ADD,
            hover_color=_CLR_ADD_HOVER,
            command=self._add_user,
        ).pack(side="right")

        self._user_list = ctk.CTkScrollableFrame(section)
        self._user_list.pack(fill="both", expand=True, pady=(8, 0))

        self.refresh()

    # ── refresh list ──────────────────────────────────────────────────────
    def refresh(self) -> None:
        for w in self._user_list.winfo_children():
            w.destroy()

        users = database.get_all_users()
        if not users:
            ctk.CTkLabel(
                self._user_list,
                text="No users yet. Click '+ Add User' to create one.",
                text_color="gray50",
            ).pack(pady=20)
            return

        for u in users:
            row = ctk.CTkFrame(self._user_list, corner_radius=8)
            row.pack(fill="x", pady=4, padx=4)

            ctk.CTkLabel(
                row,
                text=u["display_name"],
                font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(side="left", padx=(12, 4), pady=8)

            ctk.CTkLabel(
                row,
                text=f"({u['username']})",
                text_color="gray60",
            ).pack(side="left", pady=8)

            # delete button (right-most)
            ctk.CTkButton(
                row,
                text="\U0001f5d1",
                width=32,
                fg_color="#8B0000",
                hover_color="#6B0000",
                command=lambda uid=u["id"], name=u["display_name"]: self._del_user(
                    uid, name
                ),
            ).pack(side="right", padx=(4, 12), pady=6)

            # edit button
            ctk.CTkButton(
                row,
                text="\u270f",
                width=32,
                fg_color="gray40",
                hover_color="gray30",
                command=lambda uid=u["id"]: self._edit_user(uid),
            ).pack(side="right", padx=4, pady=6)

    # ── actions ───────────────────────────────────────────────────────────
    def _add_user(self) -> None:
        dlg = UserDialog(self)
        if dlg.result:
            database.add_user(**dlg.result)
            self.refresh()

    def _edit_user(self, uid: int) -> None:
        user = database.get_user_by_id(uid)
        if not user:
            return
        dlg = UserDialog(self, user=user)
        if dlg.result:
            database.update_user(uid, **dlg.result)
            self.refresh()

    def _del_user(self, uid: int, name: str) -> None:
        if messagebox.askyesno("Confirm", f"Delete user '{name}'?", parent=self):
            database.delete_user(uid)
            self.refresh()


# ═══════════════════════════════════════════════════════════════════════════════
#  Main application window
# ═══════════════════════════════════════════════════════════════════════════════
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Remote Routes")
        self.geometry("800x520")
        self.minsize(640, 400)

        database.init_db()

        # active processes per connection  {conn_id: [Popen, ...]}
        self._procs: dict[int, list[subprocess.Popen]] = {}
        # cached ping results  {conn_id: bool | None}
        self._ping_cache: dict[int, bool | None] = {}
        # card widgets  {conn_id: HostCard}
        self._cards: dict[int, HostCard] = {}

        self._build_overview()
        self._build_settings()
        self._show_overview()
        self._start_timers()

    # ── page construction ─────────────────────────────────────────────────
    def _build_overview(self) -> None:
        self._overview = ctk.CTkFrame(self, fg_color="transparent")

        # toolbar
        toolbar = ctk.CTkFrame(self._overview, fg_color="transparent")
        toolbar.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkButton(
            toolbar,
            text="+",
            width=36,
            height=36,
            font=ctk.CTkFont(size=20, weight="bold"),
            fg_color=_CLR_ADD,
            hover_color=_CLR_ADD_HOVER,
            corner_radius=8,
            command=self._add_host,
        ).pack(side="left")

        ctk.CTkButton(
            toolbar,
            text="\u2699",
            width=36,
            height=36,
            font=ctk.CTkFont(size=18),
            fg_color="gray40",
            hover_color="gray30",
            corner_radius=8,
            command=self._show_settings,
        ).pack(side="left", padx=(6, 0))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._refresh_cards())
        ctk.CTkEntry(
            toolbar,
            textvariable=self._search_var,
            placeholder_text="Search\u2026",
            width=200,
        ).pack(side="right")

        # scrollable card grid
        self._grid = ctk.CTkScrollableFrame(self._overview)
        self._grid.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self._grid.bind("<Configure>", lambda _e: self._layout_cards())

    def _build_settings(self) -> None:
        self._settings = SettingsPage(self, on_back=self._show_overview)

    # ── page switching ────────────────────────────────────────────────────
    def _show_overview(self) -> None:
        self._settings.pack_forget()
        self._overview.pack(fill="both", expand=True)
        self._refresh_cards()

    def _show_settings(self) -> None:
        self._overview.pack_forget()
        self._settings.pack(fill="both", expand=True)
        self._settings.refresh()

    # ── card grid ─────────────────────────────────────────────────────────
    def _refresh_cards(self) -> None:
        """Reload host cards from the database."""
        for w in self._grid.winfo_children():
            w.destroy()
        self._cards.clear()

        query = self._search_var.get().lower()
        rows = database.get_all_connections()
        filtered = [
            r
            for r in rows
            if query in r["name"].lower()
            or query in r["host"].lower()
            or query in r["type"].lower()
        ]

        for rec in filtered:
            card = HostCard(
                self._grid,
                rec,
                on_left_click=self._on_card_left,
                on_right_click=self._on_card_right,
            )
            self._cards[rec["id"]] = card

            # restore cached ping state
            card.set_online(self._ping_cache.get(rec["id"]))

            # restore active-process count
            alive = [p for p in self._procs.get(rec["id"], []) if p.poll() is None]
            card.set_active_count(len(alive))

        self._layout_cards()
        self._ping_all()

    def _layout_cards(self) -> None:
        """Reflow cards into a responsive grid."""
        cards = list(self._cards.values())
        if not cards:
            return
        try:
            width = self._grid.winfo_width()
        except Exception:
            width = 600
        if width < 10:
            width = 600

        cell = HostCard.WIDTH + 24
        cols = max(1, width // cell)
        for i, card in enumerate(cards):
            card.grid(row=i // cols, column=i % cols, padx=10, pady=10)

    # ── ping ──────────────────────────────────────────────────────────────
    def _ping_all(self) -> None:
        for cid, card in self._cards.items():
            self._ping_host(cid, card.record["host"])

    def _ping_host(self, cid: int, host: str) -> None:
        def _work():
            try:
                if sys.platform == "win32":
                    cmd = ["ping", "-n", "1", "-w", "1500", host]
                    kw = {"creationflags": subprocess.CREATE_NO_WINDOW}
                else:
                    cmd = ["ping", "-c", "1", "-W", "2", host]
                    kw = {}
                r = subprocess.run(cmd, capture_output=True, **kw)
                online = r.returncode == 0
            except Exception:
                online = False
            self.after(0, lambda: self._set_ping(cid, online))

        threading.Thread(target=_work, daemon=True).start()

    def _set_ping(self, cid: int, online: bool) -> None:
        self._ping_cache[cid] = online
        card = self._cards.get(cid)
        if card:
            card.set_online(online)

    # ── process tracking ──────────────────────────────────────────────────
    def _check_processes(self) -> None:
        for cid in list(self._procs):
            before = len(self._procs[cid])
            self._procs[cid] = [
                p for p in self._procs[cid] if p.poll() is None
            ]
            after = len(self._procs[cid])
            if after == 0:
                del self._procs[cid]
            if before != after:
                card = self._cards.get(cid)
                if card:
                    card.set_active_count(after)
        self.after(_PROC_INTERVAL, self._check_processes)

    # ── timers ────────────────────────────────────────────────────────────
    def _start_timers(self) -> None:
        self.after(_PROC_INTERVAL, self._check_processes)
        self.after(_PING_INTERVAL, self._ping_timer)

    def _ping_timer(self) -> None:
        self._ping_all()
        self.after(_PING_INTERVAL, self._ping_timer)

    # ── card click handlers ───────────────────────────────────────────────
    def _on_card_left(self, record) -> None:
        """Left-click: bring all active connections to front, or start a new one."""
        cid = record["id"]
        alive = [p for p in self._procs.get(cid, []) if p.poll() is None]
        if alive:
            for proc in alive:
                conn_launcher.bring_process_to_front(proc.pid)
        else:
            self._connect(record)

    def _on_card_right(self, record, event) -> None:
        """Right-click: context menu."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Connect", command=lambda: self._connect(record))
        menu.add_separator()
        menu.add_command(label="Edit", command=lambda: self._edit_host(record))
        menu.add_command(label="Delete", command=lambda: self._delete_host(record))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── actions ───────────────────────────────────────────────────────────
    def _connect(self, record) -> None:
        cid = record["id"]
        username, _password = database.get_effective_credentials(cid)
        try:
            proc = conn_launcher.launch(
                record["type"], record["host"], record["port"], username
            )
            self._procs.setdefault(cid, []).append(proc)
            alive = len([p for p in self._procs[cid] if p.poll() is None])
            card = self._cards.get(cid)
            if card:
                card.set_active_count(alive)
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc), parent=self)

    def _add_host(self) -> None:
        dlg = ConnectionDialog(self)
        if dlg.result:
            database.add_connection(**dlg.result)
            self._refresh_cards()

    def _edit_host(self, record) -> None:
        dlg = ConnectionDialog(self, record=record)
        if dlg.result:
            database.update_connection(record["id"], **dlg.result)
            self._refresh_cards()

    def _delete_host(self, record) -> None:
        if messagebox.askyesno(
            "Confirm", f"Delete '{record['name']}'?", parent=self
        ):
            database.delete_connection(record["id"])
            self._refresh_cards()
