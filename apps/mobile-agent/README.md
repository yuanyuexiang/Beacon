# Beacon 手机助手（第一轮开发版）

React Native + Expo SDK 58。网页与后端仍是现有 Beacon；此 App 是 WhatsApp 执行终端。

## 当前实现

- 网页创建短时单次配对码；Android Keystore 加密设备凭据。
- 手机检查 WhatsApp、无障碍和解锁状态；本方账号由用户在官方应用核对后填写。
- 网页现有 WhatsApp 业务任务 → 手机预览确认 → 主动领取 → 手机逐条确认执行。
- 本地 SQLite 先记录、后点击；结果先落盘、再上传；中断恢复仅回填，不重复发送。
- 目标只有电话号码标题或可明确识别的“给自己发消息”时自动操作；仅昵称且无法核对的目标转人工。
- 发送后必须观察到新增文字及已发送／送达／已读状态，才回填已发送。
- 网页查询、停止和未知结果人工核对。失败记录保留，可切回人工执行。

尚未实现 FB／Instagram 适配、自动巡检回复、多设备调度和无人值守常驻。USB 发送验证不等同此 APK 实机验收；实际构建和测试状态见 [实施计划](../../plan/mobile-channel.md)。

2026-11-05：独立 APK 已在 Xiaomi 14 Pro（Android 16）完成本人 WhatsApp 会话单条发送和真实后台回填。陌生号码跳转曾出现 WhatsApp“无法连接”，不属于已通过范围。执行器可进入唯一匹配的近期号码会话或明确标注“你”的本人会话，进入后仍核对目标；不会凭普通昵称认定联系人。

## 开发和构建

根目录运行 `pnpm install --frozen-lockfile`。使用 Android SDK 37（平台包 `platforms;android-37.0`、Build Tools 37.0.0）、NDK 27.1.12297006、JDK 17 和 Android 11+ 设备。编译 SDK 37，运行目标 SDK 36：

```sh
pnpm --filter beacon-mobile typecheck
pnpm --filter beacon-mobile export
pnpm --filter beacon-mobile exec expo prebuild --platform android
pnpm --filter beacon-mobile android
```

原生服务来自 `modules/beacon-executor/`，Expo autolinking 自动发现；原生更改需重建 APK。Expo Go 无法运行此模块。开发安装后可用 `pnpm --filter beacon-mobile start` 启动 Metro；独立安装测试用 release 构建：

```sh
cd apps/mobile-agent/android
./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a
```

生成目录 `android/` 不提交，发布签名需另行配置受控密钥；模板默认的调试签名仅供内部验证，不作为正式分发签名。Android 禁止系统备份设备凭据和执行日志。

## 连接本机 Beacon

后端先执行 `cd apps/api && uv run alembic upgrade head`。网页“设置 → 手机执行”生成配对码。云端使用 HTTPS 根地址。

USB 本地验证可执行 `adb reverse tcp:8000 tcp:8000`，手机填写 `http://127.0.0.1:8000`；只允许此回环地址明文通信，其余地址要求 HTTPS。配对码从同一后端的网页生成。手机不接收模型 API Key 或社媒密码。

## 实机步骤

1. 安装 APK，在系统设置手动启用 Beacon 无障碍服务，回到 App。
2. 配对、核对 WhatsApp 本方号码，点击开启；首次领取前需网页确认一条已有消息。
3. 手机领取后显示完整目标及文字，点击核对并执行；实际发送须由用户明确授权的测试会话进行。
4. 查看“记录”和网页任务状态。锁屏、改目标、断网或进程结束后，不点击重复发送；先恢复回填，必要时人工核对。

首版不会清除第三方聊天里已有的草稿，不会解锁手机，不从私人聊天列表批量采集内容。

调试注意：Mobile MCP／UIAutomator 的 UiAutomation 会话可能压制普通无障碍服务。实测出现“系统已启用，但 Beacon 检测未连接”时，先退出该调试会话，再用 `adb shell dumpsys accessibility` 检查 Bound services 是否包含 Beacon。不能仅依据浮动图标判断服务已连接；实际执行期间不要同时运行会占用该通道的手机 UI 检查工具。
