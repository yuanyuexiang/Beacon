# 手机回复通知闭环

2026-11-06 用户授权实施，扩展既有 Beacon，不新增独立业务系统。

- [x] Android NotificationListenerService：系统授权、选择渠道、只接收新消息、断网缓冲与重试、关闭清理。
- [x] API：持久化待关联通知、设备内幂等、手动关联门店、稳定会话后续自动回填、交接复查及解除关联。
- [x] 网页沟通工作台：新回复提醒、待关联列表、查看来源和处理结果；不自动发送后续消息。
- [x] 模拟回归、数据库迁移／部署兼容检查、APK 安装；真实回复监听另行验收，再测其他社媒。

Android 通知权限由用户在系统设置开启，应用内只选社媒渠道，默认关闭。排除群组、汇总及本方消息；没有明确消息结构的文本只作为待确认通知。平台不发通知、隐藏正文、系统杀后台时不能保证收到，保留原手工回复入口。

首条会话需人工关联；只有带稳定 shortcutId 的明确入站消息才沿用已确认绑定自动记录。名称只作为提示，不作为自动匹配依据。关闭监听不影响已保存回复；换登录账号需先解除旧会话关联。本机待上传最多 200 条／7 天，服务端未关联 7 天、已处理通知副本 30 天，正式沟通事件按既有策略保留。

依据：[Android NotificationListenerService](https://developer.android.com/reference/android/service/notification/NotificationListenerService)、[MessagingStyle](https://developer.android.com/reference/android/app/Notification.MessagingStyle)、[Expo 58](https://docs.expo.dev/versions/v58.0.0/)。使用本地 Expo 原生模块，不新增第三方消息 SDK。

## 本轮验证

后端全量 663 项、Web 35 项、原生 6 项测试通过；迁移 roundtrip 与模型一致性、部署 18 项测试、Compose 迁移声明、Ruff／mypy／类型检查与 Web 构建通过。Web ESLint 仅原有两条头像 img 警告。模拟 UI `scripts/verify_mobile_notifications_ui.py` 完成首次关联与回填，无真实外部消息，截图在忽略的 `data/devchecks/mobile/`。

本地 API／Web 已更新并应用迁移，最终 APK `data/devchecks/mobile/Beacon-mobile-0.3.0.apk` 已覆盖安装；用户手动开启通知使用权，已确认 Facebook 选中。2026-11-06 用户选择“稍后验收真实回复”，因此本轮不声明真实通知采集／自动回填实测通过，不再发送测试消息；其余社媒实测等待用户指定目标和内容。没有提交、推送或云部署。
