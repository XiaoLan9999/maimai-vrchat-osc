import hashlib
import json
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from bridge_installer import ensure_bridge_installed  # noqa: E402
from config_store import DEFAULT_CONFIG, load_config, normalize_config, save_config  # noqa: E402
from service import CardState  # noqa: E402


def test_config():
    with tempfile.TemporaryDirectory() as temporary:
        path = pathlib.Path(temporary) / "config.json"
        value = dict(DEFAULT_CONFIG)
        value.update({
            "osc_host": "10.0.0.168",
            "osc_port": "9000",
            "osc_player": "2",
            "osc_keepalive_interval": "5",
        })
        saved = save_config(value, str(path))
        loaded = load_config(str(path))
        assert loaded == saved
        assert loaded["osc_port"] == 9000
        assert loaded["osc_player"] == 2
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf")

    for invalid in (
        {"endpoint": "http://10.0.0.1:8891/events"},
        {"osc_host": "8.8.8.8"},
        {"osc_port": 0},
        {"osc_keepalive_interval": 1},
    ):
        value = dict(DEFAULT_CONFIG)
        value.update(invalid)
        try:
            normalize_config(value)
        except ValueError:
            pass
        else:
            raise AssertionError("accepted invalid config: " + repr(invalid))


def test_card_state():
    config = normalize_config(DEFAULT_CONFIG)
    cards = CardState(config)
    menu = cards.handle({"event": "presence", "status": "MENU", "version": "Ver.CN1.55-8"}, 1.0)
    assert "Ver.CN1.55-8" in menu["text"]
    selecting = cards.handle({
        "event": "presence",
        "status": "SELECTING",
        "remaining": 42,
        "title": "Test Song",
        "difficulty": "MASTER",
    }, 2.0)
    assert "42s 正在选歌" in selecting["text"]
    assert cards.handle({"event": "counts", "status": "PLAYING", "player": 2}, 3.0) is None
    playing = cards.handle({
        "event": "counts",
        "status": "PLAYING",
        "player": 1,
        "title": "Test Song",
        "achievement": 97.5,
        "miss": 1,
    }, 3.0)
    assert "ACH 97.5000%" in playing["text"]
    result = cards.handle({
        "event": "settle",
        "status": "RESULT",
        "player": 1,
        "title": "Test Song",
        "achievement": 95.1234,
    }, 4.0)
    assert "RESULT 95.1234%" in result["text"]
    assert cards.handle({"event": "presence", "status": "MENU", "version": "x"}, 5.0) is None
    assert cards.handle({"event": "presence", "status": "RESULT_SCREEN"}, 6.0) is None
    after_result = cards.handle({"event": "presence", "status": "MENU", "version": "x"}, 7.0)
    assert "版本号 x" in after_result["text"]


def test_bridge_coexistence():
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        resource = root / "resource"
        payload = resource / "payload"
        package = root / "Package"
        (package / "Mods").mkdir(parents=True)
        payload.mkdir(parents=True)
        (package / "Sinmai.exe").write_bytes(b"exe")
        (package / "MelonLoader").mkdir()

        installed = b"DGHub bridge build"
        bundled = b"standalone bridge build"
        installed_hash = hashlib.sha256(installed).hexdigest()
        bundled_hash = hashlib.sha256(bundled).hexdigest()
        (package / "Mods" / "MaiDGBridge.dll").write_bytes(installed)
        (package / "MaiDGBridge.ini").write_text("Enabled=true\n", encoding="utf-8")
        (package / "MaiDGBridge.dghub.json").write_text(json.dumps({
            "plugin": "maimai_link",
            "bridge_version": "1.4.1",
            "dll_sha256": installed_hash,
        }), encoding="utf-8")
        (payload / "MaiDGBridge.dll").write_bytes(bundled)
        (payload / "MaiDGBridge.ini").write_text("Enabled=true\n", encoding="utf-8")
        (payload / "bridge.json").write_text(json.dumps({
            "plugin_version": "2.0.0",
            "bridge_version": "1.4.1",
            "sha256": bundled_hash,
        }), encoding="utf-8")

        result = ensure_bridge_installed(
            str(resource), str(package), auto_detect=False, running_packages=[]
        )
        assert result["state"] == "ok", result
        assert (package / "Mods" / "MaiDGBridge.dll").read_bytes() == installed
        assert not result["backup"], result


if __name__ == "__main__":
    test_config()
    test_card_state()
    test_bridge_coexistence()
    print("standalone ok: config, state machine, bridge coexistence")
