"""VRChat-only DGHub plugin for maimai DX now-playing OSC."""

import asyncio
import json
import os
import sys

from installer import ensure_bridge_installed
from sse import SseClient
from vrchat_osc import OscChatboxPublisher, format_playing, format_result

try:
    import websockets
except ImportError:
    print("websockets is required by this DGHub plugin", file=sys.stderr)
    raise


DEFAULT_CONFIG = {
    "game_package": "",
    "auto_detect_game": True,
    "auto_install_bridge": True,
    "endpoint": "http://127.0.0.1:8891/events",
    "debug": False,
    "osc_enabled": False,
    "osc_host": "127.0.0.1",
    "osc_port": "9000",
    "osc_player": "1",
    "osc_update_interval": 1.0,
    "osc_show_artist": True,
    "osc_show_judgements": True,
    "osc_show_result": True,
    "osc_notification": False,
}


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def main():
    host = os.environ["DGHUB_HOST"]
    port = os.environ["DGHUB_PORT"]
    token = os.environ["DGHUB_TOKEN"]
    plugin_root = os.environ.get(
        "DGHUB_PLUGIN_ROOT", os.path.dirname(os.path.abspath(__file__))
    )
    cfg = dict(DEFAULT_CONFIG)
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()
    source = SseClient(loop, events)
    osc = OscChatboxPublisher()
    install_wakeup = asyncio.Event()
    install_state = {
        "state": "pending", "detail": "等待识别游戏目录",
        "hint": "启动一次游戏即可自动识别，或在配置中填写 Package 目录",
        "path_state": "pending", "path_detail": "尚未找到游戏目录",
        "package": "", "detected": False, "game_running": False,
        "restart_required": False, "backup": "",
    }
    stream_state = {
        "state": "pending", "detail": "等待 MaiDGBridge 数据流",
        "hint": "安装桥接后启动游戏；插件会自动重连",
    }
    osc_state = {
        "state": "pending", "detail": "VRChat OSC 未启用",
        "hint": "启用后填写运行 VRChat 的电脑局域网 IPv4",
    }
    restart_notice = [False]
    last_status = [None]
    last_osc_error = [None]

    async def send_status(ws):
        bridge = dict(install_state)
        if restart_notice[0] and bridge.get("game_running"):
            bridge.update({
                "state": "warn",
                "detail": "桥接已安装，需要重启游戏后生效",
                "hint": "退出并重新启动一次游戏；之后无需重复安装",
            })
        display = "已连接，等待游戏判定" if stream_state["state"] == "ok" else (
            "桥接已安装，请重启游戏" if restart_notice[0] else
            "桥接安装失败" if bridge.get("state") == "fail" else
            "等待识别游戏目录" if not bridge.get("package") else "等待游戏"
        )
        fields = {
            "display_status": display,
            "startup_check": {
                "title": "maimai DX · VRChat OSC 启动检查",
                "steps": [
                    {"key": "plugin", "title": "DGHub 插件进程", "state": "ok", "detail": "已连接 DGHub"},
                    {"key": "game_path", "title": "游戏目录", "state": bridge.get("path_state", "pending"), "detail": bridge.get("path_detail", "尚未找到游戏目录"), "hint": "可在插件配置中填写包含 Sinmai.exe 的 Package 目录"},
                    {"key": "bridge_install", "title": "MaiDGBridge 自动安装", "state": bridge.get("state", "pending"), "detail": bridge.get("detail", "等待安装"), "hint": bridge.get("hint", "")},
                    {"key": "bridge_stream", "title": "游戏曲目数据", "state": stream_state["state"], "detail": stream_state["detail"], "hint": stream_state["hint"]},
                    {"key": "vrchat_osc", "title": "VRChat OSC", "state": osc_state["state"], "detail": osc_state["detail"], "hint": osc_state["hint"]},
                ],
            },
        }
        signature = json.dumps(fields, ensure_ascii=False, sort_keys=True)
        if signature == last_status[0]:
            return
        last_status[0] = signature
        await ws.send(json.dumps({"op": "status", "fields": fields}, ensure_ascii=False))

    async def log(ws, level, message):
        await ws.send(json.dumps({"op": "log", "level": level, "message": message}, ensure_ascii=False))

    def configure_osc():
        try:
            if as_int(cfg["osc_player"], 1) not in (1, 2):
                raise ValueError("OSC player must be 1 or 2")
            osc.configure(cfg["osc_enabled"], cfg["osc_host"], cfg["osc_port"], cfg["osc_update_interval"], cfg["osc_notification"])
        except (TypeError, ValueError) as exc:
            osc.enabled = False
            osc_state.update({"state": "fail", "detail": "OSC 配置无效：" + str(exc), "hint": "目标应为局域网 IPv4，端口通常为 9000"})
            return
        last_osc_error[0] = None
        if osc.enabled:
            osc_state.update({"state": "ok", "detail": "将发送到 {0}:{1}（UDP）".format(osc.host, osc.port), "hint": "VRChat 中需启用 OSC；UDP 无连接握手"})
        else:
            osc_state.update({"state": "pending", "detail": "VRChat OSC 未启用", "hint": "启用后填写运行 VRChat 的电脑局域网 IPv4"})

    async def publish(ws, text, force=False):
        try:
            sent = osc.publish(text, force=force)
        except OSError as exc:
            error = str(exc)
            osc_state.update({"state": "fail", "detail": "OSC 发送失败：" + error, "hint": "检查目标 IPv4、网络连接和 VRChat 机防火墙"})
            if error != last_osc_error[0]:
                last_osc_error[0] = error
                await log(ws, "error", "VRChat OSC 发送失败：" + error)
                await send_status(ws)
            return
        if sent and last_osc_error[0] is not None:
            configure_osc()
            await send_status(ws)

    async def install_loop(ws):
        nonlocal install_state
        logged_backup = ""
        while True:
            try:
                result = await asyncio.to_thread(ensure_bridge_installed, plugin_root, cfg["game_package"], bool(cfg["auto_detect_game"]), bool(cfg["auto_install_bridge"]))
            except Exception as exc:
                result = {"state": "fail", "detail": "自动安装检查失败：" + str(exc), "hint": "重新导入官方 ZIP", "path_state": "pending", "path_detail": "自动安装检查异常", "package": "", "detected": False, "game_running": False, "restart_required": False, "backup": ""}
            install_state = result
            if result.get("restart_required"):
                restart_notice[0] = True
            elif restart_notice[0] and not result.get("game_running"):
                restart_notice[0] = False
            package = result.get("package", "")
            if result.get("detected") and package != cfg["game_package"]:
                cfg["game_package"] = package
                await ws.send(json.dumps({"op": "set_config", "key": "game_package", "value": package}, ensure_ascii=False))
            backup = result.get("backup", "")
            if backup and backup != logged_backup:
                logged_backup = backup
                await log(ws, "info", "桥接旧文件已备份到 " + backup)
            await send_status(ws)
            install_wakeup.clear()
            try:
                await asyncio.wait_for(install_wakeup.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

    async def process_events(ws):
        while True:
            generation, event = await events.get()
            if generation != source.generation:
                continue
            if "_connected" in event:
                stream_state.update({"state": "ok", "detail": "已连接 " + event["_connected"], "hint": "已就绪；开始歌曲后会发送 VRChat Chatbox"})
                await send_status(ws)
            elif "_error" in event:
                stream_state.update({"state": "pending", "detail": "尚未连接；正在重试（{0}）".format(event["_error"]), "hint": "确认桥接已安装并启动游戏"})
                await send_status(ws)
            elif event.get("event") == "counts" and event.get("status") == "PLAYING" and osc.enabled and as_int(event.get("player"), 1) == as_int(cfg["osc_player"], 1):
                await publish(ws, format_playing(event, bool(cfg["osc_show_artist"]), bool(cfg["osc_show_judgements"])))
            elif event.get("event") == "settle" and osc.enabled and bool(cfg["osc_show_result"]) and as_int(event.get("player"), 1) == as_int(cfg["osc_player"], 1):
                await publish(ws, format_result(event, bool(cfg["osc_show_artist"]), bool(cfg["osc_show_judgements"])), force=True)

    uri = "ws://{0}:{1}/ws/plugin?token={2}".format(host, port, token)
    async with websockets.connect(uri) as ws:
        with open(os.path.join(plugin_root, "manifest.json"), encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        await ws.send(json.dumps({"op": "hello", "token": token, "manifest": manifest}, ensure_ascii=False))
        acknowledgement = json.loads(await ws.recv())
        if not acknowledgement.get("accepted"):
            raise RuntimeError(acknowledgement.get("reason", "hello rejected"))
        await send_status(ws)
        processor = asyncio.create_task(process_events(ws))
        installer = asyncio.create_task(install_loop(ws))
        try:
            async for raw in ws:
                message = json.loads(raw)
                operation = message.get("op")
                if operation == "stop":
                    break
                if operation == "config":
                    for key, value in message.get("data", {}).items():
                        if key in cfg:
                            cfg[key] = value
                    configure_osc()
                    source.start(str(cfg["endpoint"]))
                    install_wakeup.set()
                    await send_status(ws)
                elif operation == "config_changed":
                    key = message.get("key")
                    if key in cfg:
                        cfg[key] = message.get("value")
                        if key == "endpoint":
                            source.start(str(cfg["endpoint"]))
                        elif key in ("game_package", "auto_detect_game", "auto_install_bridge"):
                            install_wakeup.set()
                        elif key.startswith("osc_"):
                            configure_osc()
                            await send_status(ws)
                elif operation == "ping":
                    await ws.send(json.dumps({"op": "pong", "t": message.get("t")}))
        finally:
            source.stop()
            osc.close()
            processor.cancel()
            installer.cancel()
            for task in (processor, installer):
                try:
                    await task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
