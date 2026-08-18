import pathlib
import sys
import time
import tkinter as tk


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import gui as gui_module  # noqa: E402
from config_store import DEFAULT_CONFIG, normalize_config  # noqa: E402
from gui import App, FONT_CANDIDATES  # noqa: E402


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main():
    saved = []

    def fake_save(value):
        normalized = normalize_config(value)
        saved.append(normalized)
        return normalized

    original_save = gui_module.save_config
    original_update_check = gui_module.check_for_updates
    original_bridge_check = gui_module.inspect_bridge_installation
    gui_module.save_config = fake_save
    gui_module.check_for_updates = lambda _version: {
        "state": "current",
        "current_version": "2.1.12",
        "latest_version": "2.1.12",
        "bridge_version": "1.4.16",
        "release_url": "https://github.com/XiaoLan9999/maimai-vrchat-osc/releases/tag/v2.1.12",
    }
    gui_module.inspect_bridge_installation = lambda *_args, **_kwargs: {
        "state": "pending",
        "package": "",
        "detected": False,
        "needs_update": False,
        "installed_version": "",
        "available_version": "1.4.16",
        "game_running": False,
    }
    root = tk.Tk()
    try:
        config = dict(DEFAULT_CONFIG)
        config["auto_start"] = False
        app = App(root, str(ROOT / "app"), normalize_config(config))
        root.update()

        expected_font = next(
            (
                family
                for family in FONT_CANDIDATES["zh-CN"]
                if family in set(gui_module.tkfont.families(root))
            ),
            "TkDefaultFont",
        )
        assert app.font == expected_font

        widgets = list(descendants(root))
        buttons = [item.cget("text") for item in widgets if item.winfo_class() == "Button"]
        assert "仅保存" not in buttons
        assert "启动 OSC" in buttons
        assert "检测桥接 DLL" in buttons
        assert "检查程序更新" in buttons

        version_toggle = next(
            item
            for item in widgets
            if item.winfo_class() == "Checkbutton" and item.cget("text") == "显示版本号"
        )
        app.host_var.set("10.0.0.8")
        version_toggle.invoke()
        assert saved and saved[-1]["osc_show_version"] is False

        count = len(saved)
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline and len(saved) == count:
            root.update()
            time.sleep(0.02)
        assert len(saved) > count
        assert saved[-1]["osc_host"] == "10.0.0.8"
        assert app.save_state_var.get() == "已自动保存"
        assert app.status_vars["update"].get() == "当前 2.1.12 已是最新版"
        app.close()
    finally:
        gui_module.save_config = original_save
        gui_module.check_for_updates = original_update_check
        gui_module.inspect_bridge_installation = original_bridge_check
        try:
            root.destroy()
        except tk.TclError:
            pass
    print("gui ok: update and bridge checks, immediate toggles, debounced field save")


if __name__ == "__main__":
    main()
