"""Main GUI window for Remote Routes using customtkinter."""

import sqlite3
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

import database
import connections as conn_launcher


# ── appearance ────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

_DEFAULT_PORTS = {"SSH": 22, "RDP": 3389}


# ── connection dialog (add / edit) ────────────────────────────────────────────
class ConnectionDialog(ctk.CTkToplevel):
    """Modal dialog for creating or editing a connection entry."""

    def __init__(self, parent, record=None):
        super().__init__(parent)
        self.title("Edit Connection" if record else "Add Connection")
        self.resizable(False, False)
        self.grab_set()

        self._result = None
        self._record = record

        pad = {"padx": 10, "pady": 6}

        # ── form fields ────────────────────────────────────────────────────
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

        ctk.CTkLabel(self, text="Username:").grid(row=4, column=0, sticky="e", **pad)
        self._username = ctk.CTkEntry(self, width=260)
        self._username.grid(row=4, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Password:").grid(row=5, column=0, sticky="e", **pad)
        self._password = ctk.CTkEntry(self, width=260, show="•")
        self._password.grid(row=5, column=1, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(self, text="Notes:").grid(row=6, column=0, sticky="ne", **pad)
        self._notes = ctk.CTkTextbox(self, width=260, height=60)
        self._notes.grid(row=6, column=1, columnspan=2, sticky="w", **pad)

        # ── buttons ────────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=7, column=0, columnspan=3, pady=(4, 10))

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

        # ── pre-populate when editing ──────────────────────────────────────
        if record:
            self._name.insert(0, record["name"])
            self._type_var.set(record["type"])
            self._host.insert(0, record["host"])
            self._port.insert(0, str(record["port"]))
            self._username.insert(0, record["username"])
            self._password.insert(0, record["password"])
            self._notes.insert("1.0", record["notes"])
        else:
            self._port.insert(0, "22")

        self._name.focus()
        self.wait_window()

    # ── helpers ───────────────────────────────────────────────────────────
    def _on_type_change(self, value: str) -> None:
        """Auto-fill the default port when the type changes."""
        current_port = self._port.get().strip()
        # Only overwrite if still a default port value or empty
        if current_port in ("", "22", "3389"):
            self._port.delete(0, "end")
            self._port.insert(0, str(_DEFAULT_PORTS[value]))

    def _save(self) -> None:
        name = self._name.get().strip()
        host = self._host.get().strip()
        port_str = self._port.get().strip()
        username = self._username.get().strip()
        conn_type = self._type_var.get()
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
                "Validation", "Port must be an integer between 1 and 65535.", parent=self
            )
            return

        self._result = {
            "name": name,
            "type": conn_type,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "notes": notes,
        }
        self.destroy()

    @property
    def result(self):
        return self._result


# ── detail panel ──────────────────────────────────────────────────────────────
class DetailPanel(ctk.CTkFrame):
    """Right-side panel that shows a read-only summary of a selected connection."""

    _FIELDS = [
        ("Name", "name"),
        ("Type", "type"),
        ("Host", "host"),
        ("Port", "port"),
        ("Username", "username"),
        ("Notes", "notes"),
    ]

    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self._labels: dict[str, ctk.CTkLabel] = {}

        for row, (label, key) in enumerate(self._FIELDS):
            ctk.CTkLabel(self, text=f"{label}:", anchor="e", width=80).grid(
                row=row, column=0, sticky="ne", padx=(10, 4), pady=4
            )
            val_label = ctk.CTkLabel(
                self, text="—", anchor="w", justify="left", wraplength=220
            )
            val_label.grid(row=row, column=1, sticky="nw", padx=(4, 10), pady=4)
            self._labels[key] = val_label

        self.grid_columnconfigure(1, weight=1)

    def show(self, record) -> None:
        if record is None:
            for lbl in self._labels.values():
                lbl.configure(text="—")
            return
        for _, key in self._FIELDS:
            val = str(record[key]) if record[key] else "—"
            self._labels[key].configure(text=val)


# ── main window ───────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Remote Routes")
        self.geometry("800x520")
        self.minsize(640, 400)

        database.init_db()

        self._selected_id: int | None = None
        self._rows: list[sqlite3.Row] = []

        self._build_ui()
        self._load_connections()

    # ── UI construction ───────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # ── search bar ────────────────────────────────────────────────────
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 4))
        top.grid_columnconfigure(0, weight=1)

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_list())
        ctk.CTkEntry(
            top,
            textvariable=self._search_var,
            placeholder_text="Search connections…",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(top, text="＋ Add", width=90, command=self._add).grid(
            row=0, column=1
        )

        # ── connection list ───────────────────────────────────────────────
        list_frame = ctk.CTkFrame(self)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 4), pady=4)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(
            list_frame,
            selectmode=tk.SINGLE,
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("", 12),
        )
        self._apply_listbox_theme()
        self._listbox.grid(row=0, column=0, sticky="nsew")
        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._listbox.bind("<Double-Button-1>", lambda _e: self._connect())

        sb = ctk.CTkScrollbar(list_frame, command=self._listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._listbox.configure(yscrollcommand=sb.set)

        # ── detail / info panel ───────────────────────────────────────────
        self._detail = DetailPanel(self, width=300)
        self._detail.grid(row=1, column=1, sticky="nsew", padx=(4, 10), pady=4)

        # ── action buttons ────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))

        self._btn_connect = ctk.CTkButton(
            btn_frame, text="⚡ Connect", width=110, command=self._connect
        )
        self._btn_connect.pack(side="left", padx=(0, 6))

        self._btn_edit = ctk.CTkButton(
            btn_frame, text="✏ Edit", width=90, command=self._edit,
            fg_color="gray40", hover_color="gray30",
        )
        self._btn_edit.pack(side="left", padx=6)

        self._btn_delete = ctk.CTkButton(
            btn_frame, text="🗑 Delete", width=90, command=self._delete,
            fg_color="#8B0000", hover_color="#6B0000",
        )
        self._btn_delete.pack(side="left", padx=6)

        self._update_button_states()

    # ── theme helper ──────────────────────────────────────────────────────
    def _apply_listbox_theme(self) -> None:
        mode = ctk.get_appearance_mode()
        if mode == "Dark":
            self._listbox.configure(
                bg="#2B2B2B", fg="white",
                selectbackground="#1F6AA5", selectforeground="white",
            )
        else:
            self._listbox.configure(
                bg="white", fg="black",
                selectbackground="#1F6AA5", selectforeground="white",
            )

    # ── data helpers ──────────────────────────────────────────────────────
    def _load_connections(self) -> None:
        self._all_rows = database.get_all_connections()
        self._filter_list()

    def _filter_list(self) -> None:
        query = self._search_var.get().lower()
        self._rows = [
            r for r in self._all_rows
            if query in r["name"].lower()
            or query in r["host"].lower()
            or query in r["type"].lower()
        ]
        self._listbox.delete(0, "end")
        for row in self._rows:
            self._listbox.insert("end", f"  [{row['type']}]  {row['name']}  ({row['host']})")

        # Restore selection if the same id is still visible
        self._selected_id = None
        self._detail.show(None)
        self._update_button_states()

    def _selected_record(self):
        sel = self._listbox.curselection()
        if not sel:
            return None
        idx = sel[0]
        if idx >= len(self._rows):
            return None
        return self._rows[idx]

    # ── UI state ──────────────────────────────────────────────────────────
    def _update_button_states(self) -> None:
        state = "normal" if self._listbox.curselection() else "disabled"
        self._btn_connect.configure(state=state)
        self._btn_edit.configure(state=state)
        self._btn_delete.configure(state=state)

    def _on_select(self, _event=None) -> None:
        rec = self._selected_record()
        self._detail.show(rec)
        self._update_button_states()

    # ── actions ───────────────────────────────────────────────────────────
    def _add(self) -> None:
        dlg = ConnectionDialog(self)
        data = dlg.result
        if data:
            database.add_connection(**data)
            self._load_connections()

    def _edit(self) -> None:
        rec = self._selected_record()
        if rec is None:
            return
        dlg = ConnectionDialog(self, record=rec)
        data = dlg.result
        if data:
            database.update_connection(rec["id"], **data)
            self._load_connections()

    def _delete(self) -> None:
        rec = self._selected_record()
        if rec is None:
            return
        if messagebox.askyesno(
            "Confirm Delete",
            f"Delete connection '{rec['name']}'?",
            parent=self,
        ):
            database.delete_connection(rec["id"])
            self._load_connections()

    def _connect(self) -> None:
        rec = self._selected_record()
        if rec is None:
            return
        try:
            conn_launcher.launch(rec["type"], rec["host"], rec["port"], rec["username"])
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc), parent=self)
