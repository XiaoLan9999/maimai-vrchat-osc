# maimai DX · VRChat OSC

[English](README.md) | **简体中文**

这是不依赖 DGHub 的独立 Windows 程序。它直接读取游戏内 `MaiDGBridge` 提供的
本机 SSE 数据，并持续向 VRChat Chatbox 发送主界面、选歌、游玩和结算状态。

它可以和完整版 [maimai-dghub-link](https://github.com/XiaoLan9999/maimai-dghub-link)
同时运行：两者只会共同读取 `http://127.0.0.1:8891/events`，不会争用端口。
当前 DGHub 插件已剥离 OSC，仅负责桥接和郊狼判定；两个程序可以直接同时运行。

## 安装

1. 解压 `maimai-vrchat-osc-2.1.1-win64.zip`。
2. 运行 `MaimaiVrchatOsc.exe`。
3. 选择包含 `Sinmai.exe` 的游戏 `Package` 目录。
4. 填写运行 VRChat 的电脑 IPv4；同机填写 `127.0.0.1`，局域网电脑填写其地址，
   例如 `10.0.0.168`。端口通常保持 `9000`。
5. 点击“启动 OSC”。如果软件安装或更新了桥接，退出并重新启动一次游戏。

VRChat 中还需要打开 `Action Menu > OSC > Enabled`，接收电脑的专用网络防火墙
需要允许入站 UDP 9000。

## 界面与配置

程序使用轻简、留白为主的原生界面。简中、繁中、日文分别使用对应地区的
`Noto Sans` 字体，英文使用 `Segoe UI`，可以直接修改：

- 游戏 Package 目录和自动识别/安装；
- VRChat IPv4、OSC 端口和显示玩家；
- 普通刷新间隔与保活间隔；
- 机台失联后的重试次数；
- 简体中文、繁体中文、日文、英文四种界面与 OSC 语言；
- 是否在 OSC 卡片底部显示版本号；
- Artist、连击/MISS、结算卡片和通知音；
- 是否随软件启动自动连接。

界面底部的作者名是可点击链接，指向
[XiaoLan9999.net](https://XiaoLan9999.net)。歌曲名、谱面作者和曲师使用包体提供的
原始元数据；状态说明、字段名和难度名称会跟随所选语言切换。

配置保存在：

```text
%LOCALAPPDATA%\MaimaiVrchatOsc\config.json
```

所有输入框在停止输入后自动保存，行为类勾选项在点击时立即保存，不再提供单独的
“保存”按钮。OSC 已运行时，如需让已保存设置作用于当前连接，点击“重新连接”即可，
不需要重启 DGHub。

## OSC 状态

主界面：

```text
『舞萌DX』
机台启动中
版本号 读取中

『舞萌DX』 用户名
主界面挂机中
版本号 Ver.CN1.56-B
```

账号登录与模式选择：

```text
『舞萌DX』
账号登陆中 42s
版本号 Ver.CN1.56-B

『舞萌DX』 用户名
20s 正在选择模式
版本号 Ver.CN1.56-B

『舞萌DX』 用户名
游戏加载中
版本号 Ver.CN1.56-B
```

选歌：

```text
『舞萌DX』 用户名
42s 正在选歌：
歌曲名 MASTER
难度：14  定数：14.0
作者：谱面作者  曲师：曲师
版本号 Ver.CN1.56-B
```

游玩时显示曲名、谱面、进度、达成率、DX 分、连击和 MISS；结算画面存在期间
持续保持结算卡片，离开结算后才切换到主界面或选歌。当前卡片默认每 5 秒强制
重发一次，用于恢复临时 UDP 丢包。登录完成后，用户名固定显示在所有卡片顶部，
开启“显示版本号”时，版本号固定显示在所有卡片底部。

软件启动后会先发送“机台启动中”，并尝试连接本机桥接。连续达到设置的重试次数
仍未检测到机台活动时，软件会清空旧 Chatbox 卡片、关闭 OSC 套接字并停止所有
保活发送；机台恢复活动后会自动重新连接并继续发送。

## 桥接与共存

软件内置 `MaiDGBridge 1.4.6`，自动安装前会校验 SHA-256，并将旧文件备份到：

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
dist\maimai-vrchat-osc-2.1.1-win64.zip
```

旧的 DGHub-only 插件构建脚本保留为 `build-dghub-plugin.ps1`，`v1.4.1` 及更早
标签仍可用于复现旧版。

## 测试

仓库包含配置校验、四语 OSC 文案、版本号开关、OSC 编码、状态机、SSE→UDP
保活、有限重试与断开发送、结算生命周期、桥接共存、自动安装/备份以及独立 EXE
发布包检查。

## 许可证

版权所有 (C) 2026 XiaoLan9999。

本项目采用 [GNU General Public License v3.0](LICENSE) 许可证。
