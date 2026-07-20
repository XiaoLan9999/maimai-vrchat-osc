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
    menu = cards.handle({
        "event": "presence",
        "status": "MENU",
        "version": "Ver.CN1.56-B",
        "user_name": "游客",
    }, 1.0)
    assert "Ver.CN1.56-B" in menu["text"]
    assert "主界面挂机中" in menu["text"]
    assert "游客" not in menu["text"]
    login = cards.handle({
        "event": "presence",
        "status": "LOGIN",
        "remaining": 37,
        "version": "Ver.CN1.56-B",
    }, 1.2)
    assert "账号登陆中 37s" in login["text"]
    assert "版本号 Ver.CN1.56-B" in login["text"]
    mode = cards.handle({
        "event": "presence",
        "status": "MODE_SELECT",
        "remaining": 18,
        "version": "Ver.CN1.56-B",
        "user_name": "小蓝",
    }, 1.3)
    assert "『舞萌DX』 小蓝" in mode["text"]
    assert "18s 正在选择模式" in mode["text"]
    loading = cards.handle({
        "event": "presence",
        "status": "LOADING",
        "user_name": "小蓝",
        "version": "Ver.CN1.56-B",
    }, 1.4)
    assert loading["text"] == "『舞萌DX』 小蓝\n游戏加载中\n版本号 Ver.CN1.56-B"
    preview = cards.handle({
        "event": "counts",
        "status": "PLAYING",
        "player": 1,
        "title": "Preview Song",
        "chart": "BASIC",
        "progress": 1.0,
        "achievement": 0,
        "dx_score": 0,
        "miss": 0,
    }, 1.5)
    assert preview is None
    selecting = cards.handle({
        "event": "presence",
        "status": "SELECTING",
        "remaining": 42,
        "title": "Test Song",
        "difficulty": "MASTER",
        "level": "14",
        "constant": 14.0,
        "author": "Chart Author",
        "composer": "Composer",
        "user_name": "小蓝",
        "version": "Ver.CN1.56-B",
    }, 2.0)
    assert "42s 正在选歌" in selecting["text"]
    assert "『舞萌DX』 小蓝" in selecting["text"]
    assert "难度：14  定数：14.0" in selecting["text"]
    assert "作者：Chart Author  曲师：Composer" in selecting["text"]
    assert "版本号 Ver.CN1.56-B" in selecting["text"]
    long_selecting = cards.handle({
        "event": "presence",
        "status": "SELECTING",
        "remaining": 40,
        "title": "Very Long Song Title " * 20,
        "difficulty": "Re:MASTER",
        "level": "14+",
        "constant": 14,
        "author": "Long Chart Author " * 10,
        "composer": "Long Composer " * 10,
        "user_name": "小蓝",
        "version": "Ver.CN1.56-B",
    }, 2.1)
    assert len(long_selecting["text"]) <= 144
    assert len(long_selecting["text"].splitlines()) <= 9
    assert long_selecting["text"].startswith("『舞萌DX』 小蓝\n")
    assert long_selecting["text"].endswith("版本号 Ver.CN1.56-B")
    assert cards.handle({"event": "counts", "status": "PLAYING", "player": 2}, 3.0) is None
    cards.handle({"event": "state", "status": "PLAYING"}, 3.0)
    playing = cards.handle({
        "event": "counts",
        "status": "PLAYING",
        "player": 1,
        "title": "Test Song",
        "achievement": 97.5,
        "miss": 1,
    }, 3.1)
    assert "ACH 97.5000%" in playing["text"]
    assert "『舞萌DX』 小蓝" in playing["text"]
    assert "版本号 Ver.CN1.56-B" in playing["text"]
    result = cards.handle({
        "event": "settle",
        "status": "RESULT",
        "player": 1,
        "title": "Test Song",
        "achievement": 95.1234,
    }, 4.0)
    assert "RESULT 95.1234%" in result["text"]
    assert "『舞萌DX』 小蓝" in result["text"]
    assert "版本号 Ver.CN1.56-B" in result["text"]
    assert cards.handle({"event": "presence", "status": "MENU", "version": "x"}, 5.0) is None
    assert cards.handle({"event": "presence", "status": "RESULT_SCREEN"}, 6.0) is None
    after_result = cards.handle({"event": "presence", "status": "MENU", "version": "x"}, 7.0)
    assert "版本号 x" in after_result["text"]

    late_cards = CardState(config)
    late_cards.handle({"event": "state", "status": "PLAYING"}, 8.0)
    late_playing = late_cards.handle({
        "event": "counts",
        "status": "PLAYING",
        "player": 1,
        "user_name": "中途启动",
        "version": "Ver.CN1.56-B",
        "title": "Late Start",
        "achievement": 1,
    }, 8.1)
    assert "『舞萌DX』 中途启动" in late_playing["text"]
    assert late_playing["text"].endswith("版本号 Ver.CN1.56-B")


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
            "bridge_version": "1.4.2",
            "dll_sha256": installed_hash,
        }), encoding="utf-8")
        (payload / "MaiDGBridge.dll").write_bytes(bundled)
        (payload / "MaiDGBridge.ini").write_text("Enabled=true\n", encoding="utf-8")
        (payload / "bridge.json").write_text(json.dumps({
            "plugin_version": "2.0.1",
            "bridge_version": "1.4.2",
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
    print("standalone ok: config, state machine, live-play gating, bridge coexistence")
