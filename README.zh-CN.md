# maimai DX · VRChat OSC

[English](README.md) | **简体中文**

这是给不使用 DG-LAB / 郊狼输出的用户准备的 DGHUB 插件。它不包含设备
触发、波形、强度或通道逻辑，只负责把舞萌 DX 的正在游玩信息发送到 VRChat。

## 架构

```text
Sinmai / MelonLoader
  -> MaiDGBridge.dll
  -> http://127.0.0.1:8891/events（本机 SSE）
  -> maimai_vrchat_osc DGHUB 插件
  -> VRChat OSC UDP /chatbox/input
```

## 安装

1. 将 `maimai_vrchat_osc-1.4.0.zip` 导入 DGHUB 并启用。
2. 让插件自动识别运行中的游戏，或在配置中填写 `Package` 目录。内置桥接会
   经过 SHA-256 校验后安装，并在升级前备份；游戏运行时不会覆盖正在使用的 DLL。
3. 启用“VRChat OSC”，填写运行 VRChat 的电脑局域网 IPv4，端口保持 `9000`。
4. 在 VRChat 动作菜单中打开 `OSC > Enabled`。

本包用于替代完整版 [maimai-dghub-link](https://github.com/XiaoLan9999/maimai-dghub-link)。
两个版本都会管理同一个桥接服务，请不要同时运行。

## OSC 行为

插件通过 UDP 发送 `/chatbox/input`，参数为 `(String, True, False)`。它会持续显示
主界面、选歌、正在游玩和结算卡片。如果包体提供元数据，正在游玩卡片还会显示曲名、
Artist、谱面、等级、定数、进度、达成率、DX 分、连击和 MISS。消息限制为 144 个字符、
9 行，默认每秒最多更新一次并合并重复内容；当前卡片每 5 秒强制重发，以便临时丢包后
恢复。主界面和选歌示例：

```text
【舞萌DX】
在主界面中
版本号 1.55.00
```

```text
【舞萌DX】
42s 正在选歌：
歌曲名 MASTER
```

曲目结束时会短暂保持结算卡片，随后切换到最新的主界面/选歌状态；空闲时不会发送空文本。

VRChat 电脑需要允许专用网络配置文件的入站 UDP 9000。OSC 没有确认和重传，建议
使用稳定的局域网 IPv4 或 DHCP 地址预约。

## 兼容性

桥接已针对以下包体编译和检查：

| 包体 | 结果 |
|---|---|
| `SDGB1.50/Package` | 编译兼容 |
| `SDGB1.55-lazyPacker/Package` | 编译兼容、目标版本实机验证 |
| `SDEZ160/Package` | 编译兼容 |

## 构建

```powershell
.\build.ps1 -GamePackage "D:\Games\maimai\Package"
```

脚本会生成 `dist/maimai_vrchat_osc-1.4.0.zip` 和编译后的游戏桥接目录，
不会把第三方或游戏程序集打进插件包。

## 测试

仓库包含 OSC 编码/限制/UDP 测试、剥离插件 WebSocket + SSE + UDP 端到端测试、
安装器备份/升级测试、桥接 SSE 测试以及 ZIP 哈希校验。

## 许可证

版权所有 (C) 2026 XiaoLan9999。

本项目采用 [GNU General Public License v3.0](LICENSE) 许可证。
