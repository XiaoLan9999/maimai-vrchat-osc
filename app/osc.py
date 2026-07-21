"""Small OSC/VRChat Chatbox sender with no third-party dependencies."""

import ipaddress
import math
import socket
import struct
import time

from i18n import DEFAULT_LANGUAGE, normalize_language, tr


CHATBOX_ADDRESS = "/chatbox/input"
MAX_CHATBOX_CHARS = 144
MAX_CHATBOX_LINES = 9
MIN_CHATBOX_INTERVAL = 1.0


def _metadata_text(value):
    text = str(value or "").strip()
    if text.casefold() == "manager.maistudio.stringid":
        return ""
    return text


def _osc_string(value):
    encoded = str(value).encode("utf-8") + b"\0"
    return encoded + (b"\0" * ((-len(encoded)) % 4))


def encode_osc_message(address, arguments):
    if not str(address).startswith("/"):
        raise ValueError("OSC address must start with /")

    type_tags = [","]
    payload = []
    for argument in arguments:
        if isinstance(argument, bool):
            type_tags.append("T" if argument else "F")
        elif isinstance(argument, str):
            type_tags.append("s")
            payload.append(_osc_string(argument))
        elif isinstance(argument, int):
            type_tags.append("i")
            payload.append(struct.pack(">i", argument))
        elif isinstance(argument, float):
            type_tags.append("f")
            payload.append(struct.pack(">f", argument))
        else:
            raise TypeError("unsupported OSC argument: {0}".format(type(argument).__name__))

    return _osc_string(address) + _osc_string("".join(type_tags)) + b"".join(payload)


def sanitize_chatbox_text(text):
    lines = (
        str(text)
        .replace("\0", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )
    normalized = "\n".join(lines[:MAX_CHATBOX_LINES])
    return normalized[:MAX_CHATBOX_CHARS]


def _fit_lines(lines):
    normalized = []
    for value in lines:
        normalized.extend(
            str(value)
            .replace("\0", "")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
        )
    if len(normalized) > MAX_CHATBOX_LINES:
        normalized = normalized[: MAX_CHATBOX_LINES - 1] + [normalized[-1]]
    if not normalized:
        return ""
    if len(normalized) == 1:
        return normalized[0][:MAX_CHATBOX_CHARS]

    first = normalized[0]
    last = normalized[-1]
    middle = "\n".join(normalized[1:-1])
    available = MAX_CHATBOX_CHARS - len(first) - len(last) - 2
    if available < 0:
        first_available = max(0, MAX_CHATBOX_CHARS - len(last) - 1)
        return first[:first_available] + "\n" + last
    return "\n".join((first, middle[:available], last))


def _number(value, digits=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    if digits is None:
        return str(int(number))
    return ("{0:." + str(digits) + "f}").format(number)


def _song_time(value):
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return "{0}:{1:02d}:{2:02d}".format(hours, minutes, seconds)
    return "{0}:{1:02d}".format(minutes, seconds)


def _song_line(event, fallback):
    title = str(event.get("title") or "").strip()
    if title:
        return "♪ " + title
    track = event.get("track")
    return "♪ {0} · TRACK {1}".format(fallback, _number(track))


def _localized_chart(value, language):
    chart = str(value or "").strip()
    normalized_language = normalize_language(language)
    upper_chart = chart.upper()
    if upper_chart == "UTAGE" or upper_chart.startswith("UTAGE "):
        suffix = chart[5:].strip()
        localized = {
            "zh-CN": "宴会场",
            "zh-TW": "宴會場",
            "ja-JP": "宴会場",
        }.get(normalized_language)
        if localized:
            return "【UTAGE{0}{1}】".format(localized, " " + suffix if suffix else "")
        return "UTAGE" + (" " + suffix if suffix else "")
    if normalized_language == "zh-CN":
        translated = {
            "BASIC": "基础",
            "ADVANCED": "高级",
            "EXPERT": "专家",
            "MASTER": "大师",
            "RE:MASTER": "宗师",
            "REMASTER": "宗师",
        }.get(chart.upper())
        if translated:
            english = "Re:MASTER" if chart.upper() in ("RE:MASTER", "REMASTER") else chart.upper()
            return "【{0}{1}】".format(english, translated)
        return chart
    if normalized_language == "zh-TW":
        translated = {
            "BASIC": "基礎",
            "ADVANCED": "進階",
            "EXPERT": "專家",
            "MASTER": "大師",
            "RE:MASTER": "宗師",
            "REMASTER": "宗師",
        }.get(chart.upper())
        if translated:
            english = "Re:MASTER" if chart.upper() in ("RE:MASTER", "REMASTER") else chart.upper()
            return "【{0}{1}】".format(english, translated)
        return chart
    if chart.upper() == "REMASTER":
        return "Re:MASTER"
    return chart


def _chart_line(event, language=DEFAULT_LANGUAGE, include_time=True):
    parts = []
    chart = _localized_chart(event.get("chart") or event.get("difficulty"), language)
    level = str(event.get("level") or "").strip()
    if chart:
        parts.append(chart)
    if level:
        parts.append("Lv " + level)
    try:
        constant = float(event.get("constant"))
    except (TypeError, ValueError):
        constant = 0.0
    if math.isfinite(constant) and constant > 0.0:
        parts.append(tr(language, "osc.constant", value=_number(constant, 1)))
    track = event.get("track")
    if track is not None:
        parts.append("TRACK " + _number(track))
    try:
        elapsed_seconds = max(0, int(float(event.get("elapsed_seconds"))))
        duration_seconds = max(0, int(float(event.get("duration_seconds"))))
    except (TypeError, ValueError):
        elapsed_seconds = 0
        duration_seconds = 0
    if include_time and duration_seconds > 0:
        parts.append(tr(
            language,
            "osc.song_time",
            elapsed=_song_time(min(elapsed_seconds, duration_seconds)),
            duration=_song_time(duration_seconds),
        ))
    return " · ".join(parts)


def _identity_header(event, language=DEFAULT_LANGUAGE):
    username = str(event.get("user_name") or "").strip()
    return tr(language, "osc.brand") + (" " + username if username else "")


def _version_line(event, language=DEFAULT_LANGUAGE, show_version=True):
    if not show_version:
        return ""
    value = str(event.get("version") or tr(language, "osc.version_loading")).strip()
    return tr(language, "osc.version", value=value)


def _constant(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number) or number <= 0.0:
        return ""
    return "{0:.1f}".format(number)


def _compose_lines(
    event,
    header,
    artist,
    chart,
    score,
    judgements,
    language=DEFAULT_LANGUAGE,
    show_version=True,
):
    prefix = [header]
    if artist:
        prefix.append(artist)
    if chart:
        prefix.append(chart)
    suffix = [score]
    if judgements:
        suffix.append(judgements)
    version = _version_line(event, language, show_version)
    if version:
        suffix.append(version)

    def rendered():
        return "\n".join(prefix + suffix)

    if len(rendered()) > MAX_CHATBOX_CHARS and artist in prefix:
        prefix.remove(artist)
    if len(rendered()) > MAX_CHATBOX_CHARS:
        excess = len(rendered()) - MAX_CHATBOX_CHARS
        prefix[0] = prefix[0][:max(16, len(prefix[0]) - excess)]
    if len(rendered()) > MAX_CHATBOX_CHARS and len(prefix) > 1:
        excess = len(rendered()) - MAX_CHATBOX_CHARS
        prefix[-1] = prefix[-1][:max(8, len(prefix[-1]) - excess)]
    return _fit_lines(prefix + suffix)


def format_presence(event, language=DEFAULT_LANGUAGE, show_version=True):
    status = str(event.get("status") or "MENU").upper()
    header = _identity_header(event, language)
    version = _version_line(event, language, show_version)

    def lines(*values):
        return _fit_lines([value for value in values if value])

    if status == "STARTING":
        return lines(header, tr(language, "osc.starting"), version)
    if status == "LOGIN":
        header = tr(language, "osc.brand")
        if bool(event.get("timer_infinite")):
            countdown = "∞"
        else:
            countdown = "{0}s".format(max(0, int(_number(event.get("remaining")))))
        return lines(header, tr(language, "osc.login", countdown=countdown), version)
    if status == "MODE_SELECT":
        if bool(event.get("timer_infinite")):
            countdown = "∞"
        else:
            countdown = "{0}s".format(max(0, int(_number(event.get("remaining")))))
        return lines(header, tr(language, "osc.mode_select", countdown=countdown), version)
    if status in ("MAP_SELECT", "TICKET_SELECT", "CHARACTER_SELECT"):
        if bool(event.get("timer_infinite")):
            countdown = "∞"
        else:
            countdown = "{0}s".format(max(0, int(_number(event.get("remaining")))))
        keys = {
            "MAP_SELECT": "osc.map_select",
            "TICKET_SELECT": "osc.ticket_select",
            "CHARACTER_SELECT": "osc.character_select",
        }
        return lines(header, tr(language, keys[status], countdown=countdown), version)
    if status == "GAME_INFO":
        return lines(header, tr(language, "osc.game_info"), version)
    if status == "PRESENTS":
        return lines(header, tr(language, "osc.presents"), version)
    if status == "LOADING":
        return lines(header, tr(language, "osc.loading"), version)
    if status == "SELECTING":
        if bool(event.get("timer_infinite")):
            countdown = "∞"
        else:
            countdown = "{0}s".format(max(0, int(_number(event.get("remaining")))))
        unknown = tr(language, "osc.unknown")
        title = str(event.get("title") or tr(language, "osc.unknown_song")).strip()
        difficulty = _localized_chart(
            event.get("difficulty") or event.get("chart") or unknown, language
        )
        level = str(event.get("level") or unknown).strip()
        constant = _constant(event.get("constant")) or unknown
        author = _metadata_text(event.get("author")) or unknown
        composer = _metadata_text(event.get("composer") or event.get("artist")) or unknown
        return lines(
            header,
            tr(language, "osc.selecting", countdown=countdown),
            title + " " + difficulty,
            tr(language, "osc.level_constant", level=level, constant=constant),
            tr(language, "osc.author_composer", author=author, composer=composer),
            version,
        )

    return lines(header, tr(language, "osc.menu"), version)


def format_playing(
    event,
    show_artist=True,
    show_judgements=True,
    language=DEFAULT_LANGUAGE,
    show_version=True,
):
    header = _identity_header(event, language) + "\n" + _song_line(event, "maimai DX")
    artist = str(event.get("artist") or "").strip()
    if not show_artist:
        artist = ""
    chart = _chart_line(event, language)
    score = "ACH {0}% · DX {1}".format(
        _number(event.get("achievement"), 4)[:12],
        _number(event.get("dx_score"))[:12],
    )
    judgements = ""
    if show_judgements:
        judgements = "COMBO {0} · MISS {1}".format(
            _number(event.get("combo"))[:12],
            _number(event.get("miss"))[:12],
        )
    return _compose_lines(
        event, header, artist, chart, score, judgements, language, show_version
    )


def format_result(
    event,
    show_artist=True,
    show_judgements=True,
    language=DEFAULT_LANGUAGE,
    show_version=True,
):
    header = _identity_header(event, language) + "\n" + _song_line(event, "maimai DX RESULT")
    artist = str(event.get("artist") or "").strip()
    if not show_artist:
        artist = ""
    chart = _chart_line(event, language, include_time=False)
    score = tr(
        language,
        "osc.result",
        achievement=_number(event.get("achievement"), 4)[:12],
        dx_score=_number(event.get("dx_score"))[:12],
    )
    judgements = ""
    if show_judgements:
        judgements = "COMBO {0} · MISS {1}".format(
            _number(event.get("combo"))[:12],
            _number(event.get("miss"))[:12],
        )
    return _compose_lines(
        event, header, artist, chart, score, judgements, language, show_version
    )


class OscChatboxPublisher:
    def __init__(self):
        self.enabled = False
        self.host = "127.0.0.1"
        self.port = 9000
        self.interval = 1.0
        self.notification = False
        self._socket = None
        self._last_text = None
        self._last_sent = 0.0
        self._pending_text = None
        self._pending_force = False
        self._clock = time.monotonic

    def configure(self, enabled, host, port, interval, notification=False):
        if not bool(enabled):
            self.enabled = False
            self._last_text = None
            self._last_sent = 0.0
            self._pending_text = None
            self._pending_force = False
            self.close()
            return

        host = str(host).strip()
        if not host:
            raise ValueError("OSC target host is empty")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError("OSC target must be an IPv4 address")
        if address.version != 4:
            raise ValueError("OSC target must be an IPv4 address")
        if address.is_unspecified or address.is_multicast or str(address) == "255.255.255.255":
            raise ValueError("OSC target cannot be unspecified, multicast, or broadcast")
        if not (address.is_private or address.is_loopback or address.is_link_local):
            raise ValueError("OSC target must be a local or private IPv4 address")
        port = int(port)
        if port < 1 or port > 65535:
            raise ValueError("OSC target port must be between 1 and 65535")
        interval = float(interval)
        if interval < 0.5 or interval > 30.0:
            raise ValueError("OSC update interval must be between 0.5 and 30 seconds")

        host = str(address)
        changed = (self.host, self.port) != (host, port)
        self.enabled = bool(enabled)
        self.host = host
        self.port = port
        self.interval = max(MIN_CHATBOX_INTERVAL, interval)
        self.notification = bool(notification)
        if changed:
            self._last_text = None
            self._last_sent = 0.0
            self._pending_text = None
            self._pending_force = False

    def publish(self, text, force=False):
        if not self.enabled:
            return False

        text = sanitize_chatbox_text(text)
        now = self._clock()
        elapsed = now - self._last_sent
        required_interval = MIN_CHATBOX_INTERVAL if force else self.interval
        if elapsed < required_interval:
            self._pending_text = text
            self._pending_force = bool(force)
            return False
        if not force and text == self._last_text and elapsed < max(5.0, self.interval * 3.0):
            self._pending_text = None
            self._pending_force = False
            return False

        return self._send(text, now)

    def flush(self, wait=False):
        if not self.enabled or self._pending_text is None:
            return False

        now = self._clock()
        elapsed = now - self._last_sent
        text = self._pending_text
        force = self._pending_force
        required_interval = MIN_CHATBOX_INTERVAL if force else self.interval
        remaining = required_interval - elapsed
        if remaining > 0.0:
            if not wait:
                return False
            time.sleep(remaining)
            now = self._clock()
            elapsed = now - self._last_sent
            if elapsed < required_interval:
                return False

        if not force and text == self._last_text and elapsed < max(5.0, self.interval * 3.0):
            self._pending_text = None
            self._pending_force = False
            return False
        return self._send(text, now)

    def _send(self, text, now):
        if self._socket is None:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packet = encode_osc_message(
            CHATBOX_ADDRESS,
            [text, True, self.notification],
        )
        self._socket.sendto(packet, (self.host, self.port))
        self._last_text = text
        self._last_sent = now
        self._pending_text = None
        self._pending_force = False
        return True

    def close(self):
        self._pending_text = None
        self._pending_force = False
        if self._socket is not None:
            self._socket.close()
            self._socket = None
