"""Bridge SSE to VRChat OSC without a DGHub dependency."""

import queue
import threading
import time

from bridge_installer import ensure_bridge_installed
from osc import OscChatboxPublisher, format_playing, format_presence, format_result
from sse_client import SseClient


class CardState:
    def __init__(self, config):
        self.config = config
        self.version = ""
        self.presence_status = "MENU"
        self.gameplay_active = False
        self.text = format_presence(self._menu_event())
        self.kind = "MENU"
        self.result_hold_until = 0.0
        self.result_screen_active = False

    def _menu_event(self):
        return {"status": "MENU", "version": self.version}

    def _set(self, text, kind, force=False):
        changed = text != self.text or kind != self.kind
        self.text = text
        self.kind = kind
        return {"text": text, "force": bool(force or changed), "kind": kind}

    @staticmethod
    def _player(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _looks_like_live_play(self, event):
        if event.get("in_game") is True:
            return True
        progress = self._number(event.get("progress"))
        return (
            0.0 < progress < 0.999
            or self._number(event.get("achievement")) > 0
            or self._number(event.get("dx_score")) > 0
            or self._number(event.get("miss")) > 0
        )

    def handle(self, event, now=None):
        now = time.monotonic() if now is None else now
        name = event.get("event")
        if name == "state":
            status = str(event.get("status") or "").upper()
            if status == "PLAYING":
                self.gameplay_active = True
                self.presence_status = "PLAYING"
                self.result_screen_active = False
            elif status == "IDLE":
                self.gameplay_active = False
                if self.result_screen_active or now < self.result_hold_until:
                    return None
                self.presence_status = "MENU"
                return self._set(format_presence(self._menu_event()), "MENU")
            return None

        if name == "presence":
            status = str(event.get("status") or "MENU").upper()
            version = str(event.get("version") or "").strip()
            if version:
                self.version = version
            if status == "RESULT_SCREEN":
                self.gameplay_active = False
                self.result_screen_active = True
                return None
            was_result_screen = self.result_screen_active
            self.result_screen_active = False
            self.gameplay_active = False
            self.presence_status = status
            if status == "MENU" and not was_result_screen and now < self.result_hold_until:
                return None
            if status == "MENU":
                return self._set(format_presence(self._menu_event()), "MENU")
            current = dict(event)
            current["version"] = self.version
            return self._set(format_presence(current), status)

        if name == "settle":
            self.gameplay_active = False
            self.result_screen_active = False
            self.result_hold_until = now + 8.0
            if not self.config["osc_show_result"]:
                return None
            return self._set(
                format_result(
                    event,
                    show_artist=self.config["osc_show_artist"],
                    show_judgements=self.config["osc_show_judgements"],
                ),
                "RESULT",
                force=True,
            )

        if name == "counts" and event.get("status") == "PLAYING":
            if self._player(event.get("player", 1)) != self.config["osc_player"]:
                return None
            if not self.gameplay_active and not self._looks_like_live_play(event):
                return None
            self.gameplay_active = True
            self.presence_status = "PLAYING"
            self.result_screen_active = False
            return self._set(
                format_playing(
                    event,
                    show_artist=self.config["osc_show_artist"],
                    show_judgements=self.config["osc_show_judgements"],
                ),
                "PLAYING",
            )
        return None


class StandaloneService:
    def __init__(self, resource_root, status_queue=None):
        self.resource_root = resource_root
        self.status_queue = status_queue or queue.Queue()
        self._commands = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._config = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, config):
        self.stop()
        self._config = dict(config)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="maimai-vrchat-osc-service",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None

    def test_send(self):
        self._commands.put("test")

    def _emit(self, **payload):
        self.status_queue.put(payload)

    def _run(self):
        config = self._config
        events = queue.Queue()
        source = SseClient(events)
        osc = OscChatboxPublisher()
        try:
            osc.configure(
                True,
                config["osc_host"],
                config["osc_port"],
                config["osc_update_interval"],
                config["osc_notification"],
            )
            cards = CardState(config)
            last_sent = 0.0
            next_install = 0.0
            generation = 0
            self._emit(kind="service", state="starting", detail="正在启动独立 OSC")
            source.start(config["endpoint"])
            generation = source.generation
            sent = osc.publish(cards.text, force=True)
            if sent:
                last_sent = time.monotonic()
            self._emit(
                kind="card",
                state="sending" if sent else "ready",
                text=cards.text,
                card_kind=cards.kind,
                detail="正在持续发送到 {0}:{1}".format(osc.host, osc.port),
            )

            while not self._stop.is_set():
                now = time.monotonic()
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    command = None
                if command == "test":
                    if osc.publish(cards.text, force=True):
                        last_sent = now
                    self._emit(
                        kind="card",
                        state="sending",
                        text=cards.text,
                        card_kind=cards.kind,
                        detail="已发送测试卡片",
                    )

                if now >= next_install:
                    try:
                        install = ensure_bridge_installed(
                            self.resource_root,
                            config["game_package"],
                            config["auto_detect_game"],
                            config["auto_install_bridge"],
                        )
                        self._emit(kind="bridge", **install)
                    except Exception as exc:
                        self._emit(kind="bridge", state="fail", detail="桥接检查失败：" + str(exc))
                    next_install = now + 3.0

                try:
                    event_generation, event = events.get(timeout=0.25)
                except queue.Empty:
                    event_generation, event = generation, None
                if event_generation != generation or event is None:
                    pass
                elif "_connected" in event:
                    self._emit(kind="stream", state="connected", detail=event["_connected"])
                elif "_error" in event:
                    self._emit(kind="stream", state="pending", detail=event["_error"])
                else:
                    try:
                        publication = cards.handle(event, time.monotonic())
                    except Exception as exc:
                        self._emit(kind="stream", state="warn", detail="忽略无效事件：" + str(exc))
                        publication = None
                    if publication is not None:
                        sent = osc.publish(publication["text"], force=publication["force"])
                        if sent:
                            last_sent = time.monotonic()
                        self._emit(
                            kind="card",
                            state="sending" if sent else "ready",
                            text=publication["text"],
                            card_kind=publication["kind"],
                            detail=publication["kind"],
                        )

                if cards.text and time.monotonic() - last_sent >= config["osc_keepalive_interval"]:
                    if osc.publish(cards.text, force=True):
                        last_sent = time.monotonic()
                        self._emit(
                            kind="card",
                            state="sending",
                            text=cards.text,
                            card_kind=cards.kind,
                            detail="保活重发",
                        )
        except Exception as exc:
            self._emit(kind="service", state="fail", detail=str(exc))
        finally:
            source.stop()
            osc.close()
            self._emit(kind="service", state="stopped", detail="独立 OSC 已停止")
