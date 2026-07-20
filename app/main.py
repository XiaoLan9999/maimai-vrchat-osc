"""Standalone Windows application for maimai DX VRChat OSC."""

import ctypes
import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox

from config_store import DEFAULT_CONFIG, app_data_dir, load_config
from gui import App
from i18n import tr


def resource_root():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def main():
    os.makedirs(app_data_dir(), exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(app_data_dir(), "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = load_config()
    except Exception:
        logging.exception("Failed to load config; defaults are in use")
        config = dict(DEFAULT_CONFIG)
    language = config.get("language", "zh-CN")
    mutex = None
    if os.name == "nt":
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MaimaiVrchatOsc-2")
        if ctypes.windll.kernel32.GetLastError() == 183:
            notice = tk.Tk()
            notice.withdraw()
            messagebox.showinfo(tr(language, "app.title"), tr(language, "app.already_running"))
            notice.destroy()
            return
    try:
        root = tk.Tk()
        App(root, resource_root(), config)
        root.mainloop()
    except Exception as exc:
        logging.exception("Application failed")
        notice = tk.Tk()
        notice.withdraw()
        messagebox.showerror(tr(language, "app.title"), str(exc))
        notice.destroy()


if __name__ == "__main__":
    main()
