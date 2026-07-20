import asyncio
import json
import pathlib
import queue
import socket
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from config_store import DEFAULT_CONFIG, normalize_config  # noqa: E402
from osc import CHATBOX_ADDRESS  # noqa: E402
from service import StandaloneService  # noqa: E402


def read_osc_string(packet, offset):
    end = packet.index(b"\0", offset)
    value = packet[offset:end].decode("utf-8")
    return value, (end + 4) & ~3


def decode_chatbox(packet):
    address, offset = read_osc_string(packet, 0)
    tags, offset = read_osc_string(packet, offset)
    text, _ = read_osc_string(packet, offset)
    assert address == CHATBOX_ADDRESS
    assert tags == ",sTF"
    return text


async def main():
    source_done = asyncio.Event()

    async def sse_handler(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Cache-Control: no-cache\r\n"
            b"Connection: keep-alive\r\n\r\n"
        )
        await writer.drain()

        async def event(payload):
            writer.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\r\n\r\n")
            await writer.drain()
            await asyncio.sleep(0.15)

        await event({"event": "presence", "status": "MENU", "version": "Ver.CN1.56-B"})
        await event({
            "event": "presence", "status": "SELECTING", "remaining": 42,
            "title": "Test Song", "difficulty": "MASTER",
        })
        await event({"event": "state", "status": "PLAYING"})
        await event({
            "event": "counts", "status": "PLAYING", "player": 1,
            "title": "Test Song", "achievement": 97.5, "miss": 1,
        })
        await event({
            "event": "settle", "status": "RESULT", "player": 1,
            "title": "Test Song", "achievement": 95.1234, "miss": 1,
        })
        await event({"event": "presence", "status": "RESULT_SCREEN", "version": "Ver.CN1.56-B"})
        source_done.set()
        await asyncio.sleep(4)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(sse_handler, "127.0.0.1", 0)
    sse_port = server.sockets[0].getsockname()[1]
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    osc_port = receiver.getsockname()[1]

    config = dict(DEFAULT_CONFIG)
    config.update({
        "endpoint": "http://127.0.0.1:{0}/events".format(sse_port),
        "auto_detect_game": False,
        "auto_install_bridge": False,
        "osc_host": "127.0.0.1",
        "osc_port": osc_port,
        "osc_update_interval": 0.5,
        "osc_keepalive_interval": 2.0,
    })
    status = queue.Queue()
    service = StandaloneService(str(ROOT / "app"), status)
    service.start(normalize_config(config))
    await asyncio.wait_for(source_done.wait(), timeout=5)
    await asyncio.sleep(2.4)
    await asyncio.to_thread(service.stop)

    packets = []
    while True:
        try:
            packet, _ = receiver.recvfrom(4096)
            packets.append(decode_chatbox(packet))
        except BlockingIOError:
            break
    receiver.close()
    server.close()
    await server.wait_closed()

    statuses = []
    while True:
        try:
            statuses.append(status.get_nowait())
        except queue.Empty:
            break
    assert any(item.get("kind") == "stream" and item.get("state") == "connected" for item in statuses)
    assert any("版本号 Ver.CN1.56-B" in text for text in packets), packets
    assert any("42s 正在选歌" in text for text in packets), packets
    assert any("ACH 97.5000%" in text for text in packets), packets
    results = [text for text in packets if "RESULT 95.1234%" in text]
    assert len(results) >= 2, packets
    print("standalone integration ok: SSE, cards, result screen, UDP keepalive")


if __name__ == "__main__":
    asyncio.run(main())
