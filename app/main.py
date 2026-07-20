"""Standalone Windows application for maimai DX VRChat OSC."""

import ctypes
import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox

from config_store import DEFAULT_CONFIG, app_data_dir, load_config
from gui import App


def resource_root():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def main():
    mutex = None
    if os.name == "nt":
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MaimaiVrchatOsc-2")
        if ctypes.windll.kernel32.GetLastError() == 183:
            notice = tk.Tk()
            notice.withdraw()
            messagebox.showinfo("maimai DX · VRChat OSC", "独立 OSC 已经在运行。")
            notice.destroy()
            return
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
    try:
        root = tk.Tk()
        App(root, resource_root(), config)
        root.mainloop()
    except Exception as exc:
        logging.exception("Application failed")
        notice = tk.Tk()
        notice.withdraw()
        messagebox.showerror("maimai DX · VRChat OSC", str(exc))
        notice.destroy()


if __name__ == "__main__":
    main()
