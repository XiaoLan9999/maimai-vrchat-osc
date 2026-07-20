import asyncio
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
    unused = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    unused.bind(("127.0.0.1", 0))
    unused_port = unused.getsockname()[1]
    unused.close()

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    osc_port = receiver.getsockname()[1]

    config = dict(DEFAULT_CONFIG)
    config.update({
        "endpoint": "http://127.0.0.1:{0}/events".format(unused_port),
        "auto_detect_game": False,
        "auto_install_bridge": False,
        "osc_host": "127.0.0.1",
        "osc_port": osc_port,
        "osc_update_interval": 0.5,
        "osc_keepalive_interval": 2.0,
        "activity_retry_limit": 2,
    })
    statuses = queue.Queue()
    service = StandaloneService(str(ROOT / "app"), statuses)
    service.start(normalize_config(config))

    loop = asyncio.get_running_loop()
    received = []
    deadline = loop.time() + 10.5
    while loop.time() < deadline:
        try:
            packet, _ = await asyncio.wait_for(loop.sock_recvfrom(receiver, 4096), 0.5)
            received.append((loop.time(), decode_chatbox(packet)))
        except asyncio.TimeoutError:
            pass
    await asyncio.to_thread(service.stop)
    receiver.close()

    emitted = []
    while True:
        try:
            emitted.append(statuses.get_nowait())
        except queue.Empty:
            break

    assert received and "机台启动中" in received[0][1], received
    clears = [item for item in received if item[1] == ""]
    assert len(clears) == 1, received
    cleared_at = clears[0][0]
    assert not [item for item in received if item[0] > cleared_at and item[1]], received
    disconnected = [
        item for item in emitted
        if item.get("kind") == "stream" and item.get("state") == "disconnected"
    ]
    assert len(disconnected) == 1, emitted
    assert disconnected[0].get("message_values", {}).get("limit") == 2
    print("activity disconnect ok: starting card, bounded retries, clear, no keepalive")


if __name__ == "__main__":
    asyncio.run(main())
