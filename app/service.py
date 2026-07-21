"""Bridge SSE to VRChat OSC without a DGHub dependency."""

import queue
import threading
import time
import unicodedata

from bridge_installer import ensure_bridge_installed
from i18n import tr
from osc import OscChatboxPublisher, format_playing, format_presence, format_result
from sse_client import SseClient


class ActivityGate:
    """Stops OSC after a bounded number of failed bridge connections."""

    def __init__(self, retry_limit):
        self.retry_limit = max(1, int(retry_limit))
        self.failures = 0
        self.suspended = False

    def connected(self):
        resumed = self.suspended
        self.failures = 0
        self.suspended = False
        return resumed

    def failed(self):
        if self.suspended:
            return False
        self.failures = min(self.retry_limit, self.failures + 1)
        if self.failures >= self.retry_limit:
            self.suspended = True
            return True
        return False


class CardState:
    def __init__(self, config):
        self.config = config
        self.language = config["language"]
        self.show_version = config["osc_show_version"]
        self.version = ""
        self.user_name = ""
        self.presence_status = "STARTING"
        self.gameplay_active = False
        self.text = self._format_presence(self._presence_event("STARTING"))
        self.kind = "STARTING"
        self.result_hold_until = 0.0
        self.result_screen_active = False

    def _menu_event(self):
        return {"status": "MENU", "version": self.version, "user_name": self.user_name}

    def _presence_event(self, status):
        return {"status": status, "version": self.version, "user_name": self.user_name}

    def _format_presence(self, event):
        return format_presence(event, self.language, self.show_version)

    def reset_starting(self):
        self.user_name = ""
        self.presence_status = "STARTING"
        self.gameplay_active = False
        self.result_screen_active = False
        self.result_hold_until = 0.0
        return self._set(
            self._format_presence(self._presence_event("STARTING")), "STARTING", True
        )

    def _with_identity(self, event):
        current = dict(event)
        current["version"] = self.version
        current["user_name"] = self.user_name
        return current

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
    def _is_guest_name(value):
        name = unicodedata.normalize("NFKC", str(value or "")).strip()
        return not name or name.casefold() in {"游客", "guest", "ゲスト"}

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
            or self._number(event.get("duration_seconds")) > 0
            or self._number(event.get("achievement")) > 0
            or self._number(event.get("dx_score")) > 0
            or self._number(event.get("miss")) > 0
        )

    def handle(self, event, now=None):
        now = time.monotonic() if now is None else now
        name = event.get("event")
        version = str(event.get("version") or "").strip()
        user_name = str(event.get("user_name") or "").strip()
        if version:
            self.version = version
        status = str(event.get("status") or "").upper()
        if status in ("LOGIN", "MENU") or (status == "LOADING" and self._is_guest_name(user_name)):
            self.user_name = ""
        elif user_name and not self._is_guest_name(user_name):
            self.user_name = user_name
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
                return self._set(self._format_presence(self._menu_event()), "MENU")
            return None

        if name == "presence":
            status = str(event.get("status") or "MENU").upper()
            if status in ("LOGIN", "MENU"):
                self.user_name = ""
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
                return self._set(self._format_presence(self._menu_event()), "MENU")
            current = self._with_identity(event)
            return self._set(self._format_presence(current), status)

        if name == "settle":
            self.gameplay_active = False
            self.result_screen_active = False
            self.result_hold_until = now + 8.0
            if not self.config["osc_show_result"]:
                return None
            return self._set(
                format_result(
                    self._with_identity(event),
                    show_artist=self.config["osc_show_artist"],
                    show_judgements=self.config["osc_show_judgements"],
                    language=self.language,
                    show_version=self.show_version,
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
            event = self._with_identity(event)
            return self._set(
                format_playing(
                    event,
                    show_artist=self.config["osc_show_artist"],
                    show_judgements=self.config["osc_show_judgements"],
                    language=self.language,
                    show_version=self.show_version,
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

    @staticmethod
    def _bridge_message_key(result):
        if result.get("restart_required"):
            return "status.bridge_restart"
        state = result.get("state")
        if state == "ok":
            return "status.bridge_ready"
        if state == "pending":
            return "status.bridge_waiting"
        if state == "idle":
            return "status.bridge_disabled"
        if state == "warn":
            return "status.warning"
        return "status.failed"

    def _run(self):
        config = self._config
        events = queue.Queue()
        source = SseClient(events)
        osc = OscChatboxPublisher()
        try:
            language = config["language"]
            osc.configure(
                True,
                config["osc_host"],
                config["osc_port"],
                config["osc_update_interval"],
                config["osc_notification"],
            )
            cards = CardState(config)
            activity = ActivityGate(config["activity_retry_limit"])
            osc_active = True
            last_sent = 0.0
            next_install = 0.0
            generation = 0
            self._emit(
                kind="service",
                state="starting",
                message_key="status.service_starting",
                detail=tr(language, "status.service_starting"),
            )
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
                message_key="status.osc_target",
                message_values={"host": osc.host, "port": osc.port},
                detail=tr(language, "status.osc_target", host=osc.host, port=osc.port),
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
                        message_key="status.test_sent",
                        detail=tr(language, "status.test_sent"),
                    )

                if now >= next_install:
                    try:
                        install = ensure_bridge_installed(
                            self.resource_root,
                            config["game_package"],
                            config["auto_detect_game"],
                            config["auto_install_bridge"],
                        )
                        install["message_key"] = self._bridge_message_key(install)
                        self._emit(kind="bridge", **install)
                    except Exception as exc:
                        self._emit(
                            kind="bridge",
                            state="fail",
                            message_key="status.check_failed",
                            detail=tr(language, "status.check_failed"),
                            diagnostic=str(exc),
                        )
                    next_install = now + 3.0

                try:
                    event_generation, event = events.get(timeout=0.25)
                except queue.Empty:
                    event_generation, event = generation, None
                if event_generation != generation or event is None:
                    pass
                elif "_connected" in event:
                    resumed = activity.connected()
                    if resumed:
                        osc_active = True
                        if osc.publish(cards.text, force=True):
                            last_sent = time.monotonic()
                    self._emit(
                        kind="stream",
                        state="connected",
                        message_key="status.stream_connected",
                        detail=tr(language, "status.stream_connected"),
                        endpoint=event["_connected"],
                    )
                elif "_error" in event:
                    entered_suspended = activity.failed()
                    if entered_suspended:
                        osc.publish("", force=True)
                        osc.flush(wait=True)
                        osc.close()
                        osc_active = False
                        cards.reset_starting()
                        self._emit(
                            kind="stream",
                            state="disconnected",
                            message_key="status.osc_paused",
                            message_values={"limit": activity.retry_limit},
                            detail=tr(
                                language,
                                "status.osc_paused",
                                limit=activity.retry_limit,
                            ),
                            diagnostic=event["_error"],
                        )
                        self._emit(
                            kind="card",
                            state="stopped",
                            text=cards.text,
                            card_kind=cards.kind,
                            message_key="status.osc_paused",
                            message_values={"limit": activity.retry_limit},
                            detail=tr(
                                language,
                                "status.osc_paused",
                                limit=activity.retry_limit,
                            ),
                        )
                    elif not activity.suspended:
                        self._emit(
                            kind="stream",
                            state="pending",
                            message_key="status.retry",
                            message_values={
                                "current": activity.failures,
                                "limit": activity.retry_limit,
                            },
                            detail=tr(
                                language,
                                "status.retry",
                                current=activity.failures,
                                limit=activity.retry_limit,
                            ),
                            diagnostic=event["_error"],
                        )
                else:
                    try:
                        publication = cards.handle(event, time.monotonic())
                    except Exception as exc:
                        self._emit(
                            kind="stream",
                            state="warn",
                            message_key="status.invalid_event",
                            detail=tr(language, "status.invalid_event"),
                            diagnostic=str(exc),
                        )
                        publication = None
                    if publication is not None:
                        sent = False
                        if osc_active:
                            sent = osc.publish(
                                publication["text"], force=publication["force"]
                            )
                        if sent:
                            last_sent = time.monotonic()
                        self._emit(
                            kind="card",
                            state="sending" if sent else "ready",
                            text=publication["text"],
                            card_kind=publication["kind"],
                            detail=publication["kind"],
                        )

                if osc_active and osc.flush():
                    last_sent = time.monotonic()

                if (
                    osc_active
                    and cards.text
                    and time.monotonic() - last_sent >= config["osc_keepalive_interval"]
                ):
                    if osc.publish(cards.text, force=True):
                        last_sent = time.monotonic()
                        self._emit(
                            kind="card",
                            state="sending",
                            text=cards.text,
                            card_kind=cards.kind,
                            message_key="status.keepalive",
                            detail=tr(language, "status.keepalive"),
                        )
        except Exception as exc:
            self._emit(kind="service", state="fail", detail=str(exc))
        finally:
            source.stop()
            osc.close()
            self._emit(
                kind="service",
                state="stopped",
                message_key="status.service_stopped",
                detail=tr(config.get("language"), "status.service_stopped"),
            )
