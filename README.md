# maimai DX · VRChat OSC

**English** | [简体中文](README.zh-CN.md)

This is the DGHub companion plugin for users who want maimai DX now-playing
information in VRChat but do not use DG-LAB / 郊狼 output. It contains no
device trigger, waveform, strength, or channel logic.

## Architecture

```text
Sinmai / MelonLoader
  -> MaiDGBridge.dll
  -> http://127.0.0.1:8891/events (loopback SSE)
  -> maimai_vrchat_osc DGHub plugin
  -> VRChat OSC UDP /chatbox/input
```

## Installation

1. Import `maimai_vrchat_osc-1.4.1.zip` into DGHub and enable it.
2. Let the plugin detect the running game, or set the `Package` directory in
   its configuration. The bundled bridge is installed with SHA-256 checking
   and backups; it is not replaced while the game is running.
3. Enable **VRChat OSC**, set the VRChat computer's LAN IPv4, and keep port
   `9000` unless VRChat uses a custom OSC port.
4. In VRChat, open the Action Menu and enable **OSC > Enabled**.

Use this package instead of the full [maimai-dghub-link](https://github.com/XiaoLan9999/maimai-dghub-link)
package. Do not run both variants at the same time because both manage the
same bridge service.

## OSC behavior

The plugin sends `/chatbox/input` with `(String, True, False)` over UDP. It
shows a persistent menu, song-select, now-playing, and result card. Messages
are limited to 144 characters and 9 lines, deduplicated, and throttled to one
update per second by default. The current card is force-sent every 5 seconds
to recover from temporary UDP loss. Menu and song-select cards look like:

```text
【舞萌DX】
在主界面中
版本号 1.55.00
```

```text
【舞萌DX】
42s 正在选歌：
Song Name MASTER
```

A result card is held briefly at track end; the next menu/select state then
takes over. Idle never sends an empty card.

VRChat's receiving computer must allow inbound UDP 9000 on its Private network
profile. OSC has no acknowledgement or retransmission, so use a stable LAN
IPv4 or DHCP reservation.

## Compatibility

The bridge is compiled against and member-checked with:

| Package | Result |
|---|---|
| `SDGB1.50/Package` | Compile compatible |
| `SDGB1.55-lazyPacker/Package` | Compile compatible and target runtime tested |
| `SDEZ160/Package` | Compile compatible |

## Building

```powershell
.\build.ps1 -GamePackage "D:\Games\maimai\Package"
```

The script creates `dist/maimai_vrchat_osc-1.4.1.zip` and a compiled game
mod directory. It does not include third-party or game assemblies.

## Tests

The repository includes OSC encoding/limits/UDP tests, a stripped-plugin
WebSocket + SSE + UDP integration test, installer backup/upgrade tests, a
bridge SSE harness, and package hash validation.

## License

Copyright (C) 2026 XiaoLan9999.

This project is licensed under the [GNU General Public License v3.0](LICENSE).
