"""Configuration persistence and validation for the standalone application."""

import ipaddress
import json
import math
import os
import tempfile
import urllib.parse


APP_NAME = "MaimaiVrchatOsc"
APP_VERSION = "2.0.2"
BRIDGE_VERSION = "1.4.3"

DEFAULT_CONFIG = {
    "game_package": "",
    "auto_detect_game": True,
    "auto_install_bridge": True,
    "endpoint": "http://127.0.0.1:8891/events",
    "osc_host": "127.0.0.1",
    "osc_port": 9000,
    "osc_player": 1,
    "osc_update_interval": 1.0,
    "osc_keepalive_interval": 5.0,
    "osc_show_artist": True,
    "osc_show_judgements": True,
    "osc_show_result": True,
    "osc_notification": False,
    "auto_start": True,
}


def app_data_dir():
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def default_config_path():
    return os.path.join(app_data_dir(), "config.json")


def _as_int(value, name, minimum, maximum):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError("{0} 必须是整数".format(name))
    if result < minimum or result > maximum:
        raise ValueError("{0} 必须在 {1} 到 {2} 之间".format(name, minimum, maximum))
    return result


def _as_float(value, name, minimum, maximum):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("{0} 必须是数字".format(name))
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError("{0} 必须在 {1} 到 {2} 之间".format(name, minimum, maximum))
    return result


def normalize_config(value):
    source = value if isinstance(value, dict) else {}
    config = dict(DEFAULT_CONFIG)
    for key in config:
        if key in source:
            config[key] = source[key]

    config["game_package"] = str(config["game_package"] or "").strip()
    config["endpoint"] = str(config["endpoint"] or "").strip()
    parsed = urllib.parse.urlparse(config["endpoint"])
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("桥接端点必须是本机 HTTP 地址")
    if not parsed.port or parsed.port < 1024 or parsed.port > 65535:
        raise ValueError("桥接端点端口必须在 1024 到 65535 之间")

    host = str(config["osc_host"] or "").strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("VRChat 地址必须是 IPv4")
    if address.version != 4:
        raise ValueError("VRChat 地址必须是 IPv4")
    if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
        raise ValueError("VRChat 地址不能是未指定、多播或广播地址")
    if not (address.is_private or address.is_loopback or address.is_link_local):
        raise ValueError("VRChat 地址必须是本机或局域网 IPv4")
    config["osc_host"] = str(address)

    config["osc_port"] = _as_int(config["osc_port"], "OSC 端口", 1, 65535)
    config["osc_player"] = _as_int(config["osc_player"], "玩家", 1, 2)
    config["osc_update_interval"] = _as_float(
        config["osc_update_interval"], "刷新间隔", 0.5, 30.0
    )
    config["osc_keepalive_interval"] = _as_float(
        config["osc_keepalive_interval"], "保活间隔", 2.0, 30.0
    )

    for key in (
        "auto_detect_game",
        "auto_install_bridge",
        "osc_show_artist",
        "osc_show_judgements",
        "osc_show_result",
        "osc_notification",
        "auto_start",
    ):
        config[key] = bool(config[key])
    return config


def load_config(path=None):
    destination = path or default_config_path()
    if not os.path.isfile(destination):
        return dict(DEFAULT_CONFIG)
    with open(destination, encoding="utf-8-sig") as source:
        return normalize_config(json.load(source))


def save_config(config, path=None):
    destination = path or default_config_path()
    normalized = normalize_config(config)
    directory = os.path.dirname(os.path.abspath(destination))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as output:
            json.dump(normalized, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return normalized
