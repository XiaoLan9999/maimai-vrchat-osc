# maimai DX · VRChat OSC

[English](README.md) | **简体中文**

这是不依赖 DGHub 的独立 Windows 程序。它直接读取游戏内 `MaiDGBridge` 提供的
本机 SSE 数据，并持续向 VRChat Chatbox 发送主界面、选歌、游玩和结算状态。

它可以和完整版 [maimai-dghub-link](https://github.com/XiaoLan9999/maimai-dghub-link)
同时运行：两者只会共同读取 `http://127.0.0.1:8891/events`，不会争用端口。
同时使用时请在 DGHub 插件配置中关闭 VRChat OSC，避免两边重复向 Chatbox 发包。

## 安装

1. 解压 `maimai-vrchat-osc-2.0.1-win64.zip`。
2. 运行 `MaimaiVrchatOsc.exe`。
3. 选择包含 `Sinmai.exe` 的游戏 `Package` 目录。
4. 填写运行 VRChat 的电脑 IPv4；同机填写 `127.0.0.1`，局域网电脑填写其地址，
   例如 `10.0.0.168`。端口通常保持 `9000`。
5. 点击“保存并启动”。如果软件安装或更新了桥接，退出并重新启动一次游戏。

VRChat 中还需要打开 `Action Menu > OSC > Enabled`，接收电脑的专用网络防火墙
需要允许入站 UDP 9000。

## 界面与配置

程序内可以直接修改：

- 游戏 Package 目录和自动识别/安装；
- VRChat IPv4、OSC 端口和显示玩家；
- 普通刷新间隔与保活间隔；
- Artist、连击/MISS、结算卡片和通知音；
- 是否随软件启动自动连接。

配置保存在：

```text
%LOCALAPPDATA%\MaimaiVrchatOsc\config.json
```

修改配置后点击“保存并启动”会重启独立 OSC 服务，不需要重启 DGHub。

## OSC 状态

主界面：

```text
『舞萌DX』
主界面挂机中
版本号 Ver.CN1.56-B
```

选歌：

```text
『舞萌DX』
42s 正在选歌：
歌曲名 MASTER
```

游玩时显示曲名、谱面、进度、达成率、DX 分、连击和 MISS；结算画面存在期间
持续保持结算卡片，离开结算后才切换到主界面或选歌。当前卡片默认每 5 秒强制
重发一次，用于恢复临时 UDP 丢包。

## 桥接与共存

软件内置 `MaiDGBridge 1.4.2`，自动安装前会校验 SHA-256，并将旧文件备份到：

```text
Package\MaiDGBridge.backups\<时间戳>
```

游戏运行中不会覆盖已加载的 DLL。独立程序会接受 DGHub 安装的同版本桥接，
即使两个发布包里的 DLL 构建哈希不同，也不会反复互相覆盖。

已完成编译兼容检查：

| 包体 | 结果 |
|---|---|
| `SDGB1.50/Package` | 编译兼容 |
| `SDGB1.55-lazyPacker/Package` | 编译兼容、实机数据验证 |
| `SDEZ160/Package` | 编译兼容 |

## 构建

```powershell
python -m pip install --target .builddeps -r requirements-build.txt
.\build.ps1 -GamePackage "D:\Games\maimai\Package" -Python "C:\Path\python.exe"
```

输出：

```text
dist\standalone-stage\MaimaiVrchatOsc.exe
dist\maimai-vrchat-osc-2.0.1-win64.zip
```

旧的 DGHub-only 插件构建脚本保留为 `build-dghub-plugin.ps1`，`v1.4.1` 及更早
标签仍可用于复现旧版。

## 测试

仓库包含配置校验、OSC 编码、状态机、SSE→UDP 保活、结算生命周期、桥接共存、
自动安装/备份以及独立 EXE 发布包检查。

## 许可证

版权所有 (C) 2026 XiaoLan9999。

本项目采用 [GNU General Public License v3.0](LICENSE) 许可证。
