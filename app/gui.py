"""Small native configuration window for the standalone OSC service."""

import json
import os
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config_store import APP_VERSION, default_config_path, save_config
from service import StandaloneService


class App:
    def __init__(self, root, resource_root, config):
        self.root = root
        self.resource_root = resource_root
        self.config = dict(config)
        self.events = queue.Queue()
        self.service = StandaloneService(resource_root, self.events)
        self.root.title("maimai DX · VRChat OSC " + APP_VERSION)
        self.root.geometry("760x620")
        self.root.minsize(700, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._load_vars()
        self._poll_events()
        if self.config.get("auto_start", True):
            self.root.after(300, self.start)

    def _build(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="maimai DX · VRChat OSC " + APP_VERSION,
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="独立模式：直接读取 MaiDGBridge，不依赖 DGHub 设置。",
        ).pack(anchor="w", pady=(2, 12))

        settings = ttk.LabelFrame(outer, text="连接设置", padding=10)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        self.package_var = tk.StringVar()
        self.endpoint_var = tk.StringVar()
        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.player_var = tk.StringVar()
        self.update_var = tk.StringVar()
        self.keepalive_var = tk.StringVar()

        self._setting_row(settings, 0, "游戏 Package 目录", self.package_var, browse=True)
        self._setting_row(settings, 1, "桥接端点", self.endpoint_var)
        self._setting_row(settings, 2, "VRChat IPv4", self.host_var)
        self._setting_row(settings, 3, "OSC 端口", self.port_var)
        self._setting_row(settings, 4, "显示玩家", self.player_var)
        self._setting_row(settings, 5, "刷新间隔（秒）", self.update_var)
        self._setting_row(settings, 6, "保活间隔（秒）", self.keepalive_var)

        options = ttk.LabelFrame(outer, text="行为", padding=10)
        options.pack(fill="x", pady=(10, 0))
        self.auto_detect_var = tk.BooleanVar()
        self.auto_install_var = tk.BooleanVar()
        self.artist_var = tk.BooleanVar()
        self.judgements_var = tk.BooleanVar()
        self.result_var = tk.BooleanVar()
        self.notification_var = tk.BooleanVar()
        self.auto_start_var = tk.BooleanVar()
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=1)
        checks = [
            ("运行中自动识别游戏", self.auto_detect_var),
            ("自动安装/更新桥接", self.auto_install_var),
            ("显示 Artist", self.artist_var),
            ("显示连击与 MISS", self.judgements_var),
            ("显示结算卡片", self.result_var),
            ("播放 Chatbox 通知音", self.notification_var),
            ("软件启动时自动连接", self.auto_start_var),
        ]
        for index, (label, variable) in enumerate(checks):
            ttk.Checkbutton(options, text=label, variable=variable).grid(
                row=index // 2, column=index % 2, sticky="w", padx=4, pady=2
            )

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(12, 8))
        ttk.Button(actions, text="保存并启动", command=self.start).pack(side="left")
        ttk.Button(actions, text="仅保存", command=self.save).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="停止", command=self.stop).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="测试发送", command=self.test_send).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="打开配置目录", command=self.open_config_dir).pack(side="right")

        status = ttk.LabelFrame(outer, text="运行状态", padding=10)
        status.pack(fill="both", expand=True)
        self.bridge_status = tk.StringVar(value="桥接：未启动")
        self.stream_status = tk.StringVar(value="数据流：未启动")
        self.osc_status = tk.StringVar(value="OSC：未启动")
        self.card_status = tk.StringVar(value="当前卡片：无")
        for index, variable in enumerate((self.bridge_status, self.stream_status, self.osc_status, self.card_status)):
            ttk.Label(status, textvariable=variable).grid(row=index, column=0, sticky="w", pady=2)
        self.card = tk.Text(status, height=6, width=60, state="disabled", wrap="word")
        self.card.grid(row=0, column=1, rowspan=4, sticky="nsew", padx=(18, 0))
        status.columnconfigure(1, weight=1)
        status.rowconfigure(3, weight=1)
        ttk.Label(outer, text="配置文件：" + default_config_path()).pack(anchor="w", pady=(8, 0))

    def _setting_row(self, parent, row, label, variable, browse=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        if browse:
            ttk.Button(parent, text="浏览…", command=self.browse_package).grid(
                row=row, column=2, padx=(8, 0), pady=3
            )

    def _load_vars(self):
        self.package_var.set(self.config.get("game_package", ""))
        self.endpoint_var.set(self.config.get("endpoint", ""))
        self.host_var.set(self.config.get("osc_host", "127.0.0.1"))
        self.port_var.set(str(self.config.get("osc_port", 9000)))
        self.player_var.set(str(self.config.get("osc_player", 1)))
        self.update_var.set(str(self.config.get("osc_update_interval", 1.0)))
        self.keepalive_var.set(str(self.config.get("osc_keepalive_interval", 5.0)))
        self.auto_detect_var.set(self.config.get("auto_detect_game", True))
        self.auto_install_var.set(self.config.get("auto_install_bridge", True))
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
            "auto_detect_game": self.auto_detect_var.get(),
            "auto_install_bridge": self.auto_install_var.get(),
            "osc_show_artist": self.artist_var.get(),
            "osc_show_judgements": self.judgements_var.get(),
            "osc_show_result": self.result_var.get(),
            "osc_notification": self.notification_var.get(),
            "auto_start": self.auto_start_var.get(),
        }

    def browse_package(self):
        selected = filedialog.askdirectory(title="选择游戏 Package 目录")
        if selected:
            self.package_var.set(selected)

    def save(self):
        try:
            self.config = save_config(self._read_vars())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("配置无效", str(exc), parent=self.root)
            return False
        return True

    def start(self):
        if not self.save():
            return
        self.service.start(self.config)
        self.osc_status.set("OSC：正在连接")

    def stop(self):
        self.service.stop()
        self.osc_status.set("OSC：已停止")

    def test_send(self):
        if not self.service.running:
            self.start()
        self.service.test_send()

    def open_config_dir(self):
        directory = os.path.dirname(default_config_path())
        os.makedirs(directory, exist_ok=True)
        os.startfile(directory)

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("kind")
                if kind == "bridge":
                    self.bridge_status.set("桥接：" + str(event.get("detail", event.get("state", ""))))
                    detected = str(event.get("package", ""))
                    if event.get("detected") and detected and detected != self.package_var.get():
                        self.package_var.set(detected)
                        try:
                            self.config = save_config(self._read_vars())
                        except (OSError, ValueError):
                            pass
                elif kind == "stream":
                    self.stream_status.set("数据流：" + str(event.get("detail", event.get("state", ""))))
                elif kind == "card":
                    self.osc_status.set("OSC：" + str(event.get("detail", event.get("state", ""))))
                    self.card_status.set("当前卡片：" + str(event.get("card_kind", "")))
                    self.card.configure(state="normal")
                    self.card.delete("1.0", "end")
                    self.card.insert("1.0", event.get("text", ""))
                    self.card.configure(state="disabled")
                elif kind == "service":
                    self.osc_status.set("OSC：" + str(event.get("detail", event.get("state", ""))))
        except queue.Empty:
            pass
        self.root.after(200, self._poll_events)

    def close(self):
        self.service.stop()
        self.root.destroy()
