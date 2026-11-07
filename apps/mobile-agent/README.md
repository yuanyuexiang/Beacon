# Beacon 手机助手（多渠道开发版）

React Native + Expo SDK 58。网页与后端仍是现有 Beacon；此 App 是社媒执行终端，邮件继续使用 Gmail。

## 当前实现

- 网页创建短时单次二维码／6 位备用码，手机扫码核对服务器和账号后确认；Android Keystore 加密设备凭据。
- 手机检查已安装应用、无障碍和解锁状态；FB 等直接使用官方 App 当前登录账号，无需手工填写。WhatsApp 本方号码用于本人会话识别。
- 网页现有 WhatsApp 业务任务 → 手机预览确认 → 主动领取 → 手机逐条确认执行。
- 本地 SQLite 先记录、后点击；结果先落盘、再上传；中断恢复仅回填，不重复发送。
- 目标只有电话号码标题或可明确识别的“给自己发消息”时自动操作；仅昵称且无法核对的目标转人工。
- 发送后必须观察到新增文字及已发送／送达／已读状态，才回填已发送。
- 网页查询、停止和未知结果人工核对。失败记录保留，可切回人工执行。

2026-11-06：增加协议 v2 分平台账号及安装检查，Facebook／Messenger、Instagram、LinkedIn、TikTok、YouTube、X 目标入口、语义私信适配和人工接管。现有 WhatsApp v1 兼容。连接邀请、InMail、YouTube 联系发现交给用户处理；消息请求单独记录“请求已提交”，不计为私信已发送。

回复支持当前会话可识别入站候选或手动粘贴，由用户确认回填并去重；不支持自动巡检回复、多设备调度和无人值守常驻。通用语义控件尚未在其余真实社媒上验收，无法核对用户名、输入框或回执时转人工。开发与验收状态见 [多渠道实施计划](../../plan/mobile-multichannel.md)。本轮按用户要求仅模拟验证，不安装或执行真实平台测试。

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
./gradlew :beacon-executor:testDebugUnitTest :app:assembleRelease -PreactNativeArchitectures=arm64-v8a
```

生成目录 `android/` 不提交，发布签名需另行配置受控密钥；模板默认的调试签名仅供内部验证，不作为正式分发签名。Android 禁止系统备份设备凭据和执行日志。

## 连接本机 Beacon

后端先执行 `cd apps/api && uv run alembic upgrade head`。网页“设置 → 手机执行”点击“绑定新手机”，手机“设备与账号 → 扫码配对”，首次允许相机，扫描后核对服务器和绑定账号，点击“确认绑定”。相机被拒绝时可打开系统权限设置或选择手动配对。二维码 5 分钟有效、只能使用一次，刷新使旧码失效。云端自动使用当前 HTTPS 根地址。

USB 本地验证可执行 `adb reverse tcp:8000 tcp:8000`，二维码会自动填写 `http://127.0.0.1:8000`（手动入口仍可填写）；只允许此回环地址明文通信，其余地址要求 HTTPS。配对码从同一后端的网页生成。手机不接收模型 API Key 或社媒密码。

## 实机步骤

1. 安装 APK，在系统设置手动启用 Beacon 无障碍服务，回到 App。
2. 配对、核对 WhatsApp 本方号码，点击开启；首次领取前需网页确认一条已有消息。
3. 手机领取后显示完整目标及文字，点击核对并执行；实际发送须由用户明确授权的测试会话进行。
4. 查看“记录”和网页任务状态。锁屏、改目标、断网或进程结束后，不点击重复发送；先恢复回填，必要时人工核对。

首版不会清除第三方聊天里已有的草稿，不会解锁手机，不从私人聊天列表批量采集内容。

调试注意：Mobile MCP／UIAutomator 的 UiAutomation 会话可能压制普通无障碍服务。实测出现“系统已启用，但 Beacon 检测未连接”时，先退出该调试会话，再用 `adb shell dumpsys accessibility` 检查 Bound services 是否包含 Beacon。不能仅依据浮动图标判断服务已连接；实际执行期间不要同时运行会占用该通道的手机 UI 检查工具。

## 品牌素材

App 复用 `apps/web/public/brand/logo.png` 与 `banner.jpg`，移动端副本位于 `assets/brand/`，离线可展示。图标按原比例置于 1024 方形白底，标识宽 620，预留 Android 圆形裁切安全区；启动页使用 Expo SplashScreen 白底居中 logo（不人为延时），banner 仅作顶部低对比背景。Android 12+ 由系统控制启动页结构。

macOS 更新原图后运行 `sh scripts/prepare_mobile_brand.sh`，再执行 Expo prebuild 与 release APK 构建；修改图标或启动配置仅热更新 JS 不会生效。

App 各页面内容底部显示“© 当前年份 南京小当家文化咨询有限公司”，年份随设备日期自动更新。


### 回复通知

设备与账号 → 客户回复通知：选择渠道，给 **Beacon 手机助手** 开启系统“通知使用权”（不在系统列表找 Facebook）。默认未选择渠道；本轮先开 Facebook。网页“触达任务与回复 → 手机回复”关联首条通知；稳定 shortcut 会话后续入站通知自动回填，普通通知／无稳定标识继续人工确认。群聊／汇总／本方消息不自动记录，不自动打开应用或回复。

新消息通知不等于完整会话，静音／隐藏正文／系统后台限制可能漏收。手机保留加密待上传队列与重试；关闭清除本机待传，换账号先在网页解除通知会话关联。细节见 [实施计划](../../plan/mobile-notifications.md)。

### 2026-11-07 界面与导航

底部固定任务、记录、设备。顶部紧凑连接状态可打开诊断；账号与配对、权限和通知进入设备分组；版权位于关于页。记录点击展开完整消息、实际结果与回复回填，新增本机更新时间，旧记录不补造日期。任务计数来自后端队列和本机最近记录，不代表全平台今日统计。所有原执行确认保留。

新增检查 `pnpm --filter beacon-mobile lint`、`pnpm --filter beacon-mobile typecheck`；Expo Router 导航文件位于 `src/app/`，控制器复用 `App.tsx`，页面切换不重建任务执行状态。增加原生导航依赖后需执行 `pnpm --filter beacon-mobile exec expo prebuild --platform android --no-install` 并重新构建 APK。最低 Android 11（API 30）保持不变。
