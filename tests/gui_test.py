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
    gui_module.save_config = fake_save
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
        app.close()
    finally:
        gui_module.save_config = original_save
        try:
            root.destroy()
        except tk.TclError:
            pass
    print("gui ok: locale font, no save button, immediate toggles, debounced field save")


if __name__ == "__main__":
    main()
