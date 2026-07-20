"""Threaded SSE reader used by the standalone service."""

import json
import socket
import threading
import urllib.request


class SseClient:
    def __init__(self, output_queue):
        self._output_queue = output_queue
        self._lock = threading.Lock()
        self._stop = None
        self._thread = None
        self._response = None
        self._generation = 0
        self.endpoint = None

    @property
    def generation(self):
        return self._generation

    def start(self, endpoint):
        self.stop()
        self._generation += 1
        generation = self._generation
        self.endpoint = endpoint
        stop_event = threading.Event()
        self._stop = stop_event
        self._thread = threading.Thread(
            target=self._run,
            args=(endpoint, generation, stop_event),
            daemon=True,
            name="maimai-vrchat-osc-sse",
        )
        self._thread.start()

    def stop(self):
        if self._stop is not None:
            self._stop.set()
        with self._lock:
            response = self._response
            self._response = None
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._stop = None

    def _emit(self, generation, event):
        self._output_queue.put((generation, event))

    def _run(self, endpoint, generation, stop_event):
        while not stop_event.is_set():
            try:
                self._read_once(endpoint, generation, stop_event)
                if not stop_event.is_set():
                    self._emit(generation, {"_error": "stream closed"})
            except Exception as exc:
                if not stop_event.is_set():
                    self._emit(generation, {"_error": str(exc)})
            finally:
                with self._lock:
                    response = self._response
                    self._response = None
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
            if stop_event.wait(3):
                return

    def _read_once(self, endpoint, generation, stop_event):
        request = urllib.request.Request(endpoint)
        request.add_header("Accept", "text/event-stream")
        request.add_header("Cache-Control", "no-cache")
        response = urllib.request.urlopen(request, timeout=15)
        with self._lock:
            self._response = response
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
        self._emit(generation, {"_connected": endpoint})
        data_lines = []
        while not stop_event.is_set():
            raw = response.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data_lines:
                    payload = "\n".join(data_lines)
                    data_lines = []
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        self._emit(generation, event)
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                value = line[5:]
                if value.startswith(" "):
                    value = value[1:]
                data_lines.append(value)
