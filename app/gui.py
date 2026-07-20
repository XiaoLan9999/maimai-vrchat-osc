"""Lightweight native configuration window for the standalone OSC service."""

import json
import os
import queue
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config_store import APP_VERSION, default_config_path, save_config
from i18n import LANGUAGE_CHOICES, language_code, language_label, tr
from service import StandaloneService


BG = "#F4F1EA"
CARD = "#FFFEFA"
INK = "#292722"
MUTED = "#777168"
BORDER = "#E4DED3"
FIELD = "#F7F4EE"
ACCENT = "#C96349"
ACCENT_DARK = "#A94D39"
SAGE = "#59776A"
SAGE_PALE = "#E7EFE9"
SAND = "#EFE8DC"
FONT = "Microsoft YaHei UI"


class App:
    def __init__(self, root, resource_root, config):
        self.root = root
        self.resource_root = resource_root
        self.config = dict(config)
        self.events = queue.Queue()
        self.service = StandaloneService(resource_root, self.events)
        self._last_events = {}
        self._make_vars()
        self._load_vars()
        self.root.geometry("700x900")
        self.root.minsize(640, 650)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._poll_events()
        if self.config.get("auto_start", True):
            self.root.after(350, self.start)

    def _make_vars(self):
        self.package_var = tk.StringVar()
        self.endpoint_var = tk.StringVar()
        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.player_var = tk.StringVar()
        self.update_var = tk.StringVar()
        self.keepalive_var = tk.StringVar()
        self.retry_var = tk.StringVar()
        self.language_var = tk.StringVar()
        self.auto_detect_var = tk.BooleanVar()
        self.auto_install_var = tk.BooleanVar()
        self.version_var = tk.BooleanVar()
        self.artist_var = tk.BooleanVar()
        self.judgements_var = tk.BooleanVar()
        self.result_var = tk.BooleanVar()
        self.notification_var = tk.BooleanVar()
        self.auto_start_var = tk.BooleanVar()
        self.overall_var = tk.StringVar()
        self.status_vars = {
            "bridge": tk.StringVar(),
            "stream": tk.StringVar(),
            "osc": tk.StringVar(),
            "card": tk.StringVar(),
        }

    def _language(self):
        return language_code(self.language_var.get())

    def _t(self, key, **values):
        return tr(self._language(), key, **values)

    def _build(self):
        for child in self.root.winfo_children():
            child.destroy()
        language = self._language()
        self.root.title("{0} {1}".format(tr(language, "app.title"), APP_VERSION))
        self._configure_styles()

        viewport = tk.Frame(self.root, bg=BG)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, bg=BG, bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        outer = tk.Frame(canvas, bg=BG, padx=26, pady=18)
        window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window, width=event.width),
        )
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas = canvas
        outer.grid_columnconfigure(0, weight=1)

        header = tk.Frame(outer, bg=BG)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.grid_columnconfigure(0, weight=1)
        tk.Label(
            header,
            text=tr(language, "app.eyebrow"),
            bg=BG,
            fg=ACCENT,
            font=(FONT, 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text=tr(language, "app.heading"),
            bg=BG,
            fg=INK,
            font=(FONT, 19, "bold"),
            wraplength=530,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 2))
        tk.Label(
            header,
            text=tr(language, "app.subtitle"),
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
            wraplength=530,
            justify="left",
        ).grid(row=2, column=0, sticky="w")
        self.overall_var.set(tr(language, "status.not_started"))
        tk.Label(
            header,
            textvariable=self.overall_var,
            bg=SAGE_PALE,
            fg=SAGE,
            font=(FONT, 9, "bold"),
            padx=14,
            pady=8,
        ).grid(row=0, column=1, rowspan=3, sticky="e")

        connection = self._card(outer)
        connection.grid(row=1, column=0, sticky="ew")
        connection.grid_columnconfigure(0, weight=1)
        connection.grid_columnconfigure(1, weight=1)
        self._section_title(connection, tr(language, "section.connection"), 0)
        self._field(
            connection, 1, 0, tr(language, "field.game_package"), self.package_var,
            columnspan=2, browse=True,
        )
        self._field(
            connection, 2, 0, tr(language, "field.endpoint"), self.endpoint_var,
            columnspan=2,
        )
        self._field(connection, 3, 0, tr(language, "field.osc_host"), self.host_var)
        self._field(connection, 3, 1, tr(language, "field.osc_port"), self.port_var)
        self._field(connection, 4, 0, tr(language, "field.osc_player"), self.player_var)
        self._field(connection, 4, 1, tr(language, "field.retry_limit"), self.retry_var)
        self._field(
            connection, 5, 0, tr(language, "field.update_interval"), self.update_var
        )
        self._field(
            connection, 5, 1, tr(language, "field.keepalive_interval"), self.keepalive_var
        )
        self._language_field(connection, 6, tr(language, "field.language"))

        preferences = self._card(outer)
        preferences.grid(row=2, column=0, sticky="ew", pady=(20, 0))
        for column in range(4):
            preferences.grid_columnconfigure(column, weight=1)
        self._section_title(preferences, tr(language, "section.preferences"), 0, 4)
        checks = (
            ("option.auto_detect", self.auto_detect_var),
            ("option.auto_install", self.auto_install_var),
            ("option.show_version", self.version_var),
            ("option.show_artist", self.artist_var),
            ("option.show_judgements", self.judgements_var),
            ("option.show_result", self.result_var),
            ("option.notification", self.notification_var),
            ("option.auto_start", self.auto_start_var),
        )
        for index, (key, variable) in enumerate(checks):
            column = index % 4
            tk.Checkbutton(
                preferences,
                text=tr(language, key),
                variable=variable,
                bg=CARD,
                fg=INK,
                activebackground=CARD,
                activeforeground=INK,
                selectcolor=CARD,
                highlightthickness=0,
                bd=0,
                anchor="w",
                justify="left",
                wraplength=120,
                font=(FONT, 8),
            ).grid(
                row=1 + index // 4,
                column=column,
                sticky="w",
                padx=(20 if column == 0 else 6, 6),
                pady=(7, 13 if index >= 4 else 7),
            )

        live = self._card(outer)
        live.grid(row=3, column=0, sticky="ew", pady=(20, 0))
        live.grid_columnconfigure(0, weight=2)
        live.grid_columnconfigure(1, weight=3)
        self._section_title(live, tr(language, "section.live"), 0)
        status_keys = (
            ("bridge", "status.bridge"),
            ("stream", "status.stream"),
            ("osc", "status.osc"),
            ("card", "status.card"),
        )
        for row, (name, label_key) in enumerate(status_keys, start=1):
            self._status_row(live, row, tr(language, label_key), self.status_vars[name])

        preview = tk.Frame(live, bg=SAGE_PALE, padx=14, pady=12)
        preview.grid(
            row=1, column=1, rowspan=4, sticky="nsew", padx=(8, 20), pady=(0, 12)
        )
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(0, weight=1)
        self.card = tk.Text(
            preview,
            height=5,
            width=24,
            state="disabled",
            wrap="word",
            relief="flat",
            borderwidth=0,
            bg=SAGE_PALE,
            fg=INK,
            insertbackground=INK,
            font=(FONT, 10),
            padx=2,
            pady=2,
        )
        self.card.grid(row=0, column=0, sticky="nsew")

        actions = tk.Frame(live, bg=CARD)
        actions.grid(row=5, column=0, columnspan=2, sticky="ew", padx=20, pady=(4, 20))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        self._button(
            actions, tr(language, "action.save_start"), self.start, primary=True
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._button(actions, tr(language, "action.save"), self.save).grid(
            row=1, column=0, sticky="ew", padx=(0, 4)
        )
        self._button(actions, tr(language, "action.stop"), self.stop).grid(
            row=1, column=1, sticky="ew", padx=(4, 0)
        )
        self._button(actions, tr(language, "action.test"), self.test_send).grid(
            row=2, column=0, sticky="ew", padx=(0, 4), pady=(8, 0)
        )
        self._button(
            actions, tr(language, "action.open_config"), self.open_config_dir
        ).grid(row=2, column=1, sticky="ew", padx=(4, 0), pady=(8, 0))

        footer = tk.Frame(outer, bg=BG)
        footer.grid(row=4, column=0, sticky="ew", pady=(15, 0))
        footer.grid_columnconfigure(0, weight=1)
        tk.Label(
            footer,
            text=tr(
                language,
                "footer.config",
                path=os.path.join("%LOCALAPPDATA%", "MaimaiVrchatOsc", "config.json"),
            ),
            bg=BG,
            fg=MUTED,
            font=(FONT, 8),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            footer,
            text=tr(language, "footer.author") + " ",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
        ).grid(row=0, column=1, sticky="e")
        author = tk.Label(
            footer,
            text="XiaoLan9999",
            bg=BG,
            fg=ACCENT,
            cursor="hand2",
            font=(FONT, 9, "bold", "underline"),
        )
        author.grid(row=0, column=2, sticky="e")
        author.bind("<Button-1>", lambda _event: webbrowser.open_new("https://XiaoLan9999.net"))
        self._render_statuses()

    def _on_mousewheel(self, event):
        if hasattr(self, "canvas"):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _configure_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Studio.TCheckbutton",
            background=CARD,
            foreground=INK,
            font=(FONT, 9),
            padding=2,
        )
        style.map("Studio.TCheckbutton", background=[("active", CARD)])
        style.configure(
            "Studio.TCombobox",
            fieldbackground=FIELD,
            background=FIELD,
            foreground=INK,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowsize=14,
            padding=6,
        )

    @staticmethod
    def _card(parent):
        return tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            bd=0,
        )

    @staticmethod
    def _section_title(parent, text, row, columnspan=2):
        tk.Label(
            parent,
            text=text,
            bg=CARD,
            fg=INK,
            font=(FONT, 12, "bold"),
        ).grid(
            row=row,
            column=0,
            columnspan=columnspan,
            sticky="w",
            padx=20,
            pady=(18, 10),
        )

    def _field(self, parent, row, column, label, variable, columnspan=1, browse=False):
        box = tk.Frame(parent, bg=CARD)
        box.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=(20 if column == 0 else 8, 20 if column + columnspan >= 2 else 8),
            pady=2,
        )
        box.grid_columnconfigure(0, weight=1)
        tk.Label(box, text=label, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        entry = tk.Entry(
            box,
            textvariable=variable,
            relief="flat",
            bd=0,
            bg=FIELD,
            fg=INK,
            insertbackground=INK,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=(FONT, 9),
        )
        entry.grid(row=1, column=0, sticky="ew", ipady=3)
        if browse:
            self._button(box, self._t("action.browse"), self.browse_package).grid(
                row=1, column=1, padx=(8, 0), sticky="ns"
            )

    def _language_field(self, parent, row, label):
        box = tk.Frame(parent, bg=CARD)
        box.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(3, 14))
        box.grid_columnconfigure(0, weight=1)
        tk.Label(box, text=label, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        combo = ttk.Combobox(
            box,
            textvariable=self.language_var,
            values=[label for _, label in LANGUAGE_CHOICES],
            state="readonly",
            style="Studio.TCombobox",
        )
        combo.grid(row=1, column=0, sticky="ew")
        combo.bind("<<ComboboxSelected>>", self._on_language_changed)

    @staticmethod
    def _status_row(parent, row, label, variable):
        line = tk.Frame(parent, bg=CARD)
        line.grid(row=row, column=0, sticky="ew", padx=20, pady=3)
        line.grid_columnconfigure(2, weight=1)
        tk.Label(line, text="●", bg=CARD, fg=SAGE, font=(FONT, 7)).grid(
            row=0, column=0, sticky="w", padx=(0, 7)
        )
        tk.Label(line, text=label, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
            row=0, column=1, sticky="w", padx=(0, 8)
        )
        tk.Label(line, textvariable=variable, bg=CARD, fg=INK, font=(FONT, 9, "bold")).grid(
            row=0, column=2, sticky="w"
        )

    @staticmethod
    def _button(parent, text, command, primary=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            bg=ACCENT if primary else SAND,
            activebackground=ACCENT_DARK if primary else BORDER,
            fg="white" if primary else INK,
            activeforeground="white" if primary else INK,
            cursor="hand2",
            font=(FONT, 9, "bold" if primary else "normal"),
            padx=12,
            pady=8,
        )

    def _load_vars(self):
        self.package_var.set(self.config.get("game_package", ""))
        self.endpoint_var.set(self.config.get("endpoint", ""))
        self.host_var.set(self.config.get("osc_host", "127.0.0.1"))
        self.port_var.set(str(self.config.get("osc_port", 9000)))
        self.player_var.set(str(self.config.get("osc_player", 1)))
        self.update_var.set(str(self.config.get("osc_update_interval", 1.0)))
        self.keepalive_var.set(str(self.config.get("osc_keepalive_interval", 5.0)))
        self.retry_var.set(str(self.config.get("activity_retry_limit", 5)))
        self.language_var.set(language_label(self.config.get("language", "zh-CN")))
        self.auto_detect_var.set(self.config.get("auto_detect_game", True))
        self.auto_install_var.set(self.config.get("auto_install_bridge", True))
        self.version_var.set(self.config.get("osc_show_version", True))
        self.artist_var.set(self.config.get("osc_show_artist", True))
        self.judgements_var.set(self.config.get("osc_show_judgements", True))
        self.result_var.set(self.config.get("osc_show_result", True))
        self.notification_var.set(self.config.get("osc_notification", False))
        self.auto_start_var.set(self.config.get("auto_start", True))

    def _read_vars(self):
        return {
            "game_package": self.package_var.get(),
            "endpoint": self.endpoint_var.get(),
            "osc_host": self.host_var.get(),
            "osc_port": self.port_var.get(),
            "osc_player": self.player_var.get(),
            "osc_update_interval": self.update_var.get(),
            "osc_keepalive_interval": self.keepalive_var.get(),
            "activity_retry_limit": self.retry_var.get(),
            "language": self._language(),
            "auto_detect_game": self.auto_detect_var.get(),
            "auto_install_bridge": self.auto_install_var.get(),
            "osc_show_version": self.version_var.get(),
            "osc_show_artist": self.artist_var.get(),
            "osc_show_judgements": self.judgements_var.get(),
            "osc_show_result": self.result_var.get(),
            "osc_notification": self.notification_var.get(),
            "auto_start": self.auto_start_var.get(),
        }

    def _on_language_changed(self, _event=None):
        was_running = self.service.running
        self._build()
        self.root.after(50, self.start if was_running else self.save)

    def browse_package(self):
        selected = filedialog.askdirectory(title=self._t("dialog.choose_package"))
        if selected:
            self.package_var.set(selected)

    def save(self):
        try:
            self.config = save_config(self._read_vars())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror(
                self._t("dialog.invalid_config"), str(exc), parent=self.root
            )
            return False
        return True

    def start(self):
        if not self.save():
            return
        self.service.start(self.config)
        self.overall_var.set(self._t("status.starting"))
        self.status_vars["osc"].set(self._t("status.starting"))

    def stop(self):
        self.service.stop()
        self.overall_var.set(self._t("status.stopped"))
        self.status_vars["osc"].set(self._t("status.stopped"))

    def test_send(self):
        if not self.service.running:
            self.start()
        self.service.test_send()

    @staticmethod
    def open_config_dir():
        directory = os.path.dirname(default_config_path())
        os.makedirs(directory, exist_ok=True)
        os.startfile(directory)

    def _event_detail(self, event, fallback="status.not_started"):
        key = event.get("message_key")
        if key:
            values = event.get("message_values") or {}
            return self._t(key, **values)
        state_keys = {
            "starting": "status.starting",
            "connected": "status.connected",
            "pending": "status.pending",
            "disconnected": "status.disconnected",
            "stopped": "status.stopped",
            "sending": "status.sending",
            "ready": "status.ready",
            "warn": "status.warning",
            "fail": "status.failed",
            "ok": "status.ready",
        }
        return self._t(state_keys.get(event.get("state"), fallback))

    def _render_statuses(self):
        for name in ("bridge", "stream", "osc"):
            event = self._last_events.get(name, {})
            self.status_vars[name].set(self._event_detail(event))
        card_event = self._last_events.get("card", {})
        card_keys = {
            "STARTING": "osc.starting",
            "MENU": "osc.menu",
            "LOGIN": "card.login",
            "MODE_SELECT": "card.mode_select",
            "MAP_SELECT": "card.map_select",
            "TICKET_SELECT": "card.ticket_select",
            "CHARACTER_SELECT": "card.character_select",
            "GAME_INFO": "osc.game_info",
            "PRESENTS": "osc.presents",
            "LOADING": "osc.loading",
            "SELECTING": "card.selecting",
            "PLAYING": "card.playing",
            "RESULT": "card.result",
        }
        card_key = card_keys.get(str(card_event.get("card_kind") or "").upper())
        self.status_vars["card"].set(
            self._t(card_key) if card_key else self._t("status.none")
        )
        if card_event and hasattr(self, "card"):
            self.card.configure(state="normal")
            self.card.delete("1.0", "end")
            self.card.insert("1.0", card_event.get("text", ""))
            self.card.configure(state="disabled")

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("kind")
                if kind == "bridge":
                    self._last_events["bridge"] = event
                    detected = str(event.get("package", ""))
                    if event.get("detected") and detected and detected != self.package_var.get():
                        self.package_var.set(detected)
                        try:
                            self.config = save_config(self._read_vars())
                        except (OSError, ValueError):
                            pass
                elif kind == "stream":
                    self._last_events["stream"] = event
                    if event.get("state") == "connected":
                        self.overall_var.set(self._t("status.connected"))
                    elif event.get("state") == "disconnected":
                        self.overall_var.set(self._t("status.disconnected"))
                elif kind == "card":
                    self._last_events["card"] = event
                    self._last_events["osc"] = event
                elif kind == "service":
                    self._last_events["osc"] = event
                    if event.get("state") == "stopped":
                        self.overall_var.set(self._t("status.stopped"))
                self._render_statuses()
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def close(self):
        self.service.stop()
        self.root.destroy()
