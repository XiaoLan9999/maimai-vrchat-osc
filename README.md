# maimai DX · VRChat OSC

**English** | [简体中文](README.zh-CN.md)

This is a standalone Windows application with no DGHub runtime dependency. It
reads the local SSE stream exposed by `MaiDGBridge` and continuously publishes
menu, song-select, playing, and result cards to the VRChat Chatbox.

It can run alongside the full
[maimai-dghub-link](https://github.com/XiaoLan9999/maimai-dghub-link) plugin.
Both programs may read `http://127.0.0.1:8891/events` concurrently. The current
DGHub plugin no longer contains an OSC publisher, so there is no duplicate
Chatbox sender to disable.

## Installation

1. Extract `maimai-vrchat-osc-2.0.3-win64.zip`.
2. Run `MaimaiVrchatOsc.exe`.
3. Select the game `Package` directory containing `Sinmai.exe`.
4. Set the IPv4 address of the VRChat computer. Use `127.0.0.1` on the same
   computer, or its LAN address such as `10.0.0.168`. Keep port `9000` unless
   VRChat uses a custom OSC port.
5. Click **Save and start**. Restart the game once if the bridge was installed
   or updated.

Enable `Action Menu > OSC > Enabled` in VRChat. The receiving computer must
allow inbound UDP 9000 on its Private network profile.

## Configuration

The native settings window controls the game path, bridge installation,
VRChat target, player, update and keepalive intervals, Artist/judgement/result
fields, notification sound, and automatic startup. Configuration is stored at:

```text
%LOCALAPPDATA%\MaimaiVrchatOsc\config.json
```

Applying settings restarts only the standalone OSC service; DGHub does not
need to be restarted.

## OSC behavior

Menu:

```text
『舞萌DX』 User Name
主界面挂机中
版本号 Ver.CN1.56-B
```

Login and mode select:

```text
『舞萌DX』
账号登陆中 42s
版本号 Ver.CN1.56-B

『舞萌DX』 User Name
20s 正在选择模式
版本号 Ver.CN1.56-B

『舞萌DX』 User Name
游戏加载中
版本号 Ver.CN1.56-B
```

Song select:

```text
『舞萌DX』 User Name
42s 正在选歌：
Song Name MASTER
难度：14  定数：14.0
作者：Chart Author  曲师：Composer
版本号 Ver.CN1.56-B
```

Playing cards include song/chart metadata, progress, achievement, DX score,
combo, and MISS when available. The result card remains active for the full
result-process lifetime and changes only after entering menu or song select.
The current card is force-sent every 5 seconds by default to recover from
temporary UDP loss. After login, the user name remains in the header and the
game version remains in the footer for every card.

## Bridge coexistence

The application bundles `MaiDGBridge 1.4.4`. Installation verifies SHA-256,
backs up replaced files under `Package/MaiDGBridge.backups/<timestamp>`, and
never replaces a DLL while the game is running. A same-version bridge installed
by DGHub is accepted by version and its recorded hash, preventing replacement
loops between the two applications.

Compile compatibility is covered for `SDGB1.50`, `SDGB1.55`, and `SDEZ160`.
The target 1.55 package has runtime SSE and OSC coverage.

## Building

```powershell
python -m pip install --target .builddeps -r requirements-build.txt
.\build.ps1 -GamePackage "D:\Games\maimai\Package" -Python "C:\Path\python.exe"
```

Outputs:

```text
dist\standalone-stage\MaimaiVrchatOsc.exe
dist\maimai-vrchat-osc-2.0.3-win64.zip
```

The legacy DGHub-only build remains available as `build-dghub-plugin.ps1` and
in tags up to `v1.4.1`.

## License

Copyright (C) 2026 XiaoLan9999.

This project is licensed under the [GNU General Public License v3.0](LICENSE).
