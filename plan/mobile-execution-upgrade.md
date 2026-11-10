# 手机执行优化开工地图

2026-11-08 用户批准四轮优化。保留 Expo App、Beacon API、现有配对和任务日志；用户本地验证后自行推送发布。本轮不自动向真实客户发消息。

## 开发地图

| 编号 | 步骤与交付 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| R1.1 | 页面观察补齐角色、资源 ID、启用与窗口；沿用可见节点过滤；重要控件优先选取 | 无 | 复杂页面入口不因前 160 项截断丢失 | 开发完成／自动化通过／真机待验收 |
| R1.2 | 共用条件等待与导航点击；发送动作不使用重试补救 | R1.1 | 慢加载可等待、导航无效果可识别、取消及时 | 开发完成／自动化通过／真机待验收 |
| R1.3 | 保留精确快照校验，新增语义页面签名判断循环 | R1.1 | 动态页面不无限重复，旧引用不点击 | 开发完成／自动化通过／真机待验收 |
| R2.1 | 每步记录动作目标、执行结果、前后变化；限制历史大小 | R1 | 能说明为什么换策略或退出 | 开发完成／自动化通过／真机待验收 |
| R2.2 | 导航后验证与重复动作检测；用户切换 App 时交还操作 | R2.1 | 无变化不反复点，切换应用不继续导航 | 开发完成／自动化通过／真机待验收 |
| R3.1 | AI 读取结构化动作反馈、重要节点；截图仅在需要时补充 | R2 | 无效路径不重复建议，规则成功不额外调用模型 | 开发完成／自动化通过／真机待验收 |
| R3.2 | 新旧观察协议兼容，服务端验证新增字段 | R3.1 | 旧 APK 仍能工作，非法节点被拒绝 | 开发完成／自动化通过／真机待验收 |
| R4.1 | 网页／App 保留进度及可展开的执行步骤 | R2/R3 | 消息保留、人工联系／换渠道入口明确 | 开发完成／自动化通过／真机待验收 |
| R4.2 | 模拟回归矩阵及分平台真机验收记录 | 各轮 | 不把“已打开”算“已发送” | 自动化完成／真机待验收 |

每轮完成后更新本表与执行记录；开发完成与真机验收分开记录。

## 技术取舍

- 参考 Droidline 的条件等待与导航点击策略、DroidBridge 的观察生命周期、MobileAgent-Android 的动作反思、4AIs 的界面差异。首版独立实现，不引入其整套运行时或复制源码。
- 保留精确 screen_id 防止旧节点操作；语义签名仅用于判断无进展，不能授权旧坐标点击。
- 控件动作派发成功不等于页面达到预期，更不等于消息发送成功。
- 保留现有单次发送和未知不重放；不自动升级为公开评论、关注、连接邀请或付费 InMail。
- 采用现有服务端模型与用途路由，不另建手机 API Key 配置。Root／Shizuku／端侧小模型不纳入本轮。

## 验证矩阵

慢加载、无效果点击、非可点击子节点、禁用控件、弹窗、长页面、相同文字多按钮、动态内容、切换应用、取消、无障碍断开、断网／进程重启、发送结果不明。规则／AI／人工三条路径分别覆盖。

真机顺序：WhatsApp → Facebook → Instagram → LinkedIn → TikTok → X → YouTube。记录系统与 App 版本、目标、耗时、AI 次数、结果和待修问题；真实发送仅使用明确批准的目标和内容。测试期间避免 Mobile MCP UiAutomation 压制 Beacon 无障碍，使用不占用无障碍的检查方式。

## 参考源码

- [Droidline UiCommands](https://github.com/KnifeLemon/Droidline/blob/main/agent/app/src/main/java/dev/droidline/agent/a11y/UiCommands.kt)（MIT）
- [DroidBridge VisualExecutionCore](https://github.com/zephyr7030/DroidBridge/blob/main/standalone/src/main/java/com/droidbridge/standalone/execution/android/VisualExecutionCore.kt)（Apache-2.0）
- [MobileAgent AgentLoop](https://github.com/GiggleWang/MobileAgent-Android/blob/main/app/src/main/java/com/mobileagent/app/agent/AgentLoop.kt)（MIT）
- [4AIs](https://github.com/8crsk/openclaw-android)（MIT）

## 执行记录

- 2026-11-08：建立地图；源码检查发现固定等待、前序节点截断、导航反馈缺失及观察属性不足。开始 R1。

### 2026-11-08 首批实现与验证

- R1：重要导航节点优先，保留原节点编号；新增 enabled／role／resource_id／scrollable／window_id。精确 screen_id 仍校验旧引用，语义控件集合只判断进展。导航采用最多 4 秒条件等待、200ms 观察；取消及切换其他应用立即退出。导航控件点击失败可在本节点可见边界内尝试手势，发送不采用此补救。
- R2：记录最多 12 步、每步最多 240 字；保存动作、目标、派发结果及新增／消失控件。相同语义页面重复 AI 动作退出，规则入口每页只尝试一次。任务结算保留步骤，重复结果仍幂等。
- R3：模型读取实际导航结果，拒绝禁用节点；旧观察请求使用默认属性，旧 APK 不必同步升级。先升级 API 再安装新 APK：旧 API 对新增字段可能拒绝，不能反序发布。
- R4：网页手机执行面板和 App 历史记录加入折叠步骤；不增加必填项。已完成 Kotlin 单元测试及 release APK 构建，后端 53 项专项测试、Ruff、mypy、Web／App 类型检查和 App lint 均通过；新增 Kotlin 反馈测试 3 项通过。
- 仍待真机：慢加载、弹窗遮挡、多同名按钮、用户切换应用、各平台入口及发送回执。当前改动没有安装到手机、没有真实发送；上表“已实现基础”不代表整个平台验收成功。完整可见性／遮挡判断仍沿用原实现，本轮未宣称解决全部遮挡。

### 2026-11-08 第二批收尾

- R1.2：等待器抽离为可注入时钟的 NavigationWait，慢加载／过渡页／无变化超时／等待中取消／应用切换异常均有确定性测试。每次观察仍采用实时窗口，不持有旧 Android 节点。
- R1.3／R2.2：规则和 AI 共用动作尝试集合；不依赖临时节点编号识别重复动作。目标包含角色、资源 ID、文字和边界，允许同名不同位置入口；包名与窗口纳入语义签名。滚动方向分别记录。
- R3：新增有界 feedback 数组，明确 action／target／dispatched／changed／appeared／disappeared；旧 history 继续保留。仅规则找不到入口后才截图并请求 AI，截图并非每一步都调用。
- R4：模拟网页覆盖排队→需人工处理→展开步骤，完整消息仍可见；所有 API 模拟，没有连接真实手机或发送。

## 自动化覆盖与真机边界

| 场景 | 可复现自动化 | 尚需真机核验 |
|---|---|---|
| 慢加载、过渡页、导航无变化 | NavigationWaitTest：稳定窗口、4 秒超时 | 各 App 实际加载耗时 |
| 长页面与禁用入口 | NavigationFeedbackTest、test_mobile_navigation | 无障碍树是否真实提供入口 |
| 同名按钮、重复操作 | NavigationFeedbackTest：目标位置／方向区分、共用去重 | 弹窗、布局移动、重叠控件 |
| 切换 App、取消 | NavigationWaitTest：异常不重试、等待中取消 | 系统后台切换、无障碍服务中断 |
| AI 协议与旧 APK | test_mobile_navigation：旧缺省字段、非法引用、结构化反馈、图片边界 | 真实模型建议质量 |
| 断网／锁屏与结果不明 | ConnectionPolicyTest、AutomaticPolicyTest、test_mobile | 实际断网、系统杀进程、送达回执 |
| 导航记录与消息保留 | test_mobile_navigation、verify_mobile_channels_ui.py | 手机历史展示与人工接管体验 |

开发阶段交付完成后仅剩真机验收：先更新本地 API，再安装新 APK；不清除配对。APK 为 `apps/mobile-agent/android/app/build/outputs/apk/release/app-release.apk`。真机验收完成之前，不能把跨平台开发完成写成所有平台都能成功发送。

### 最终自动化结果

- API：mobile_navigation／mobile／mobile_channels／mobile_notifications／sendflow 共 68 项；mobile_assistance／mobile_journey 共 17 项，合计 85 项通过。相关 Python Ruff 和 mypy 通过。
- Android：原生 34 项测试全部通过，release APK 构建通过；App TypeScript 和 lint 通过。
- Web：38 项 Vitest 通过，模拟手机渠道 UI（含失败后消息／步骤保留）通过；`next build --no-lint` 打包及内置类型检查通过。
- 标准 `pnpm --filter beacon-web build` 尚被全仓既有 React Hooks lint 错误阻挡，例如 directory/page.tsx 的 set-state-in-effect、WebsiteSearch.tsx 的 purity；本轮未修改这些文件，也未关闭 lint 规则。该项不是“全量构建通过”，需后续单独清理。
- 未安装本版 APK、未操作真实社媒、未提交／推送。下一步由用户连接手机后按上表验收。

### 复查与清理

- 删除无人调用的 PlatformAdapters.messageButton 和 NavigationPolicy.request；不保留新旧两套私信入口查找器。
- 删除 PhoneService.clicked，WhatsApp 复用现有 PlatformAdapters.click；发送动作仍只派发一次。保留 clickableNode（发送按钮仍调用），以及 WhatsApp 专用号码／本人会话／回执适配。
- 删除循环顶部多余的历史裁剪，统一由新增步骤处维护最多 12 项，避免提前丢掉第 12 步。
- 修复规则导航把 editable 的 Message 输入框误当入口的问题，补充禁用控件／输入框测试。
- Android 生命周期、Expo 模块注册及通知回调由框架调用，不因普通文本引用数为零删除。旧 APK 的缺省字段与 WhatsApp 既有协议仍属于有效兼容代码。
- 补充结果重复回填测试：保留诊断历史时仍拒绝冲突结果，避免清理影响幂等。

清理后验证：Android 35 项单元测试／release APK 构建通过；后端手机、渠道、导航 54 项专项通过，新增冲突回填断言再次通过；git diff --check 通过。未安装手机或真实发送。

### 2026-11-09 真机测试准备与配对修复

- Xiaomi 14 Pro（ffff59a7）覆盖安装最新 APK；本地 API 更新成功，未通过 USB 转发。手机 192.168.86.34，电脑 192.168.86.32。
- 发现二维码仍使用旧配置 192.168.3.103；刷新配对码还会覆盖当前输入。修复网页地址优先级：当前编辑／已保存地址优先，刷新不覆盖；提供显式“使用服务器推荐地址”。本地配置通过 configure_mobile_lan.py 更新。
- Web 39 项测试和 Docker 标准构建通过，本地 3000 网页已更新（仅本地，没有推送云端）。真机仍等待用新二维码完成配对并重新开启无障碍；未发消息，尚不能登记执行闭环通过。

2026-11-09 配对复核：App“已连接”、后台新设备 paired 和新鲜心跳一致；Android 真实 Bound services 已出现 Beacon 手机执行，后台 accessibility=true。已安装 WhatsApp／FB／INS／LinkedIn／YouTube／X，未安装 TikTok。首次账号识别期间手机被切至其他 App，结果不作为失败或成功验收；等待独占测试窗口后重测，未新增任务或发送。

### 2026-11-09 只读账号识别复测

- 配对、局域网连接和无障碍绑定通过；测试结束 Android 仍显示 Beacon Bound service。
- Facebook：从官方 App 进入本人资料，Beacon 返回了规则识别的账号名称及“请确认识别结果”；未点击保存。此项通过，不代表发送验收。
- Instagram：能打开官方 App，但停留在首页，未自动进入本人资料，未返回账号候选。入口导航适配未通过。
- LinkedIn、YouTube、X：逐项触发识别后回 Beacon 未看到账号候选，不登记识别通过；需补充入口导航与失败诊断。YouTube 返回后保留画中画，后续测试需排除浮层干扰。
- TikTok 未安装，未测试；WhatsApp 本轮未重复发送验收。
- 本轮没有发送消息、没有保存识别候选、没有新增触达任务。手机已回 Beacon，用户可以恢复操作。

### 2026-11-09 Facebook 真实发送与回复检查

- 用户确认 Aberdeen Airport、正文“你好”。经现有准备、预览、确认链路入队，手机自动进入私信并发送。任务 6dcc3412-3751-4053-b0f8-62f4209d3870，执行 fae10a49-fc1e-4800-80b7-3320ac349a55。
- 屏幕观察到 14:57 新增本方消息及随后对方自动回复，真实发送通过；程序却报 unknown。回执依赖可见同文消息数量增加及附近状态，长历史／快速入站引发的窗口变化仍需诊断，尚未修复，没有重复发送。
- 租约到期后通过 resolve 记录人工核对已发送；真实自动回复经 inbound 人工确认回填，事件 8d58760f-d2c4-4b70-9823-93eb717339c7。这不是通知自动接收验收。
- 用户开启系统通知使用权，确认 NotificationMonitor 已授权；App 显示监听服务已连接，已开启 Facebook/Messenger，待上传 0。此前回复发生于监听开启之前；等待后续真实入站通知，不能宣称自动收发闭环通过。
- API mobile_notifications、mobile_channels、mobile_journey 共 35 项测试通过。未发送其他平台消息。
- 用户新增需求：无法私信时可使用作品公开评论。当前协议与执行器尚未实现评论动作；后续需保存作品链接、评论正文和独立执行结果，不能把私信状态当作评论支持。
### 2026-11-09 网页下发真实链路验收

- 用户指定 Facebook Aberdeen Airport，正文“你好”。通过本地网页客户会话“人工准备下一次跟进”选择 Facebook／手机执行，预览收件人与完整正文后确认下发；未使用后台脚本创建或确认本次任务。
- 任务 `14796d8b-ed32-4559-9039-a930d9ed334f`：网页排队后手机自动领取、打开 Facebook 并于 15:52 实际发出“你好”，截图 `data/devchecks/web-dispatch-phone.png` 显示新消息与对方头像回执。
- 自动结果回填仍为 unknown，未重复发送；15:57 经网页填写真实核对说明并“确认已发出”，界面显示“已发送”。因此下发与自动发送通过，自动回执判定未通过。
- 本轮未观察到新的入站通知，不能认定自动接收回填已验收。
- App 同时显示“自动执行已开启”和“待运行检查／开启自动执行”，状态提示需统一。

### 2026-11-09 结构化结果与执行截图

- App 回执新增 reason_code 与可选截图。WhatsApp 号码未注册须同时命中明确弹窗和邀请按钮；其他平台保留不可私信、需连接／登录、网络异常、入口缺失与发送待核对等原因。未发送不等于程序出错。
- 任务完成时仅截目标 App 非密码页面；系统拒绝截屏、锁屏或离开目标 App 时仍回填文字。回执与截图先存本机，网络恢复只补传回执，成功后移除本机截图，不重复发送。
- API 校验图片尺寸与大小，重编码 JPEG 去元数据；网页结果抽屉可展开并放大截图，访问按任务／门店权限隔离。沿用现有 JSON，无迁移。新回执到达时清理超过 30 天图片，保留原因和执行记录。
- 验证：API mobile_results／mobile／mobile_channels 共 45 项通过，Ruff／mypy 通过；Web typecheck、39 项测试与生产构建通过；模拟手机渠道 UI 截图展开通过；Android 单测与 release APK 构建通过。
- 本地 API／Web 已更新。电脑当前未检测到手机，新 APK 尚未覆盖安装；此次没有真实发送。旧记录无法追溯生成截图，其他平台全部真实异常场景尚未验收。FB 已发却返回 unknown 的回执判定仍需独立修复，本轮未宣称解决。

### 2026-11-09 结构化结果真机复测

- 新 APK 已覆盖安装，Xiaomi 14 Pro 通过局域网连接，无障碍已绑定。首轮查到 MIUI 拒绝后台打开 wa.me 深链；系统“后台弹出界面”原为拒绝，已通过权限页面改为允许。无障碍已连接不代表厂商后台启动权限已允许。
- 首轮回执因 public_job 的 reason_code=null 被 JSONObject.getString 转为字面量“null”而 HTTP 422；修复为空值时按实际结果生成原因，加入 null／空串回归。恢复回填失败现在显示具体服务端字段原因，不再静默吞错。未输出凭据或截图原文到诊断消息。
- 失败记录 e8022ded-7e55-49b0-8150-3ed3b4580f5e 通过手机“恢复并回填中断记录”上传原因与截图，随后结束该测试任务，保留原始记录。
- 修复后测试任务 74488fb1-1934-47be-9684-7863468b755c：手机自动领取、打开目标、识别“电话号码没有 WhatsApp 账户”弹窗；自动返回 unavailable／not_registered。发送前检查未启动，没有点击发送或邀请。
- 截图受保护接口返回 HTTP 200 image/jpeg，60389 字节，已查看服务端实际保存图片，弹窗和目标号码一致。产物 data/devchecks/mobile/server-result.jpg（受控、不提交）。本次任务由 API 预览确认下发，不冒称网页点击下发；网页截图组件此前模拟回归通过，真机后浏览器窗口控制失效，未再次目视验收网页弹窗。
- Android 单测与 release 构建再次通过，修复版已安装。此项验证未注册失败结果及截图回填，不代表其他社媒所有异常、成功发送回执或回复通知全部验收。

### 2026-11-10 多渠道真实网页复测（不是全平台通过）

全部新任务由已登录的 localhost:3000 网页选择联系方式、编辑固定测试消息、预览并确认下发；后台仅用于只读核对。独立测试门店 `d08f1fe5-15ea-4cf8-90a4-cc22ed484e24`，名称“Beacon 多渠道网页验收 20261110”，未覆盖客户历史。正文为英文 Beacon connection test，并保留 TOM／Xiaodangjia 署名和退出说明。

| 渠道 | 网页到手机实测 | 回填结果／限制 |
| --- | --- | --- |
| Instagram | Freshmex，任务 `4e70d005-3581-4769-a1bd-7f47deed1de8`，执行 `9338e956-cec3-4c4b-9ad4-6a1505dc7651` | 自动返回 sent，新增发出气泡且输入框清空；不代表送达或已读。网页结果抽屉显示已发送；回传截图近乎黑屏，截图内容验收未通过。 |
| LinkedIn | 3t 公司，任务 `8ff15221-15a6-4c54-908c-dab865e895a8`，执行 `5a7afb31-0c7a-4f63-b4bf-3f3282edcb4b` | 打开公司主页后停在 opening，最终 failed：HTTP 409 租约过期；未确认发送。手机截图可见“发消息”入口，需要继续定位执行停顿。 |
| X | Freshmex，任务 `6bc31f37-416e-41e0-98fd-8fa3dca544c1`，执行 `0ab4c5b2-4d71-4563-82c5-174f85e8febe` | 返回 unavailable，识别到的会话对象与目标不符，没有发送；此情况应归目标未核验，不能据此断言对方关闭私信。 |
| YouTube | AUSA，任务 `0a396b90-63b8-4001-88a9-caefa31658e2`，执行 `33a1bfaf-0fd6-460e-9f91-59c04378ee32` | 网页“查看频道联系入口”下发并打开频道，needs_action 回填；尚无自动公开评论实现，不能宣称发送通过。 |
| WhatsApp | 本人号码，任务 `2f9035ad-ed0b-493d-bb58-1e16e8ba8733`，执行 `7d494d76-8b03-4d04-9778-3e29b392af49` | 打开本人聊天，因本方 sender 为通用标签而非号码，自聊判断 target==sender 不成立；返回 failed，未发送。需补目标详情号码核对路径，不能仅凭昵称放行。 |
| TikTok | 网页添加 Freshmex TikTok 并选择手机触达 | 页面明确“未安装 TikTok”；本机 Douyin 不作为 TikTok。未下发、未发送，真实发送待安装后验收。 |

没有新的真实入站消息，其他平台“收到回复→自动关联门店”仍未验收。Facebook 本轮不重复发送，沿用此前网页链路记录。

本轮修复：准备草稿不再自动带入其他平台／其他联系人绑定的文案；历史异常草稿在预览阶段就显示原因。原文案保留，不删除。手机发送状态不再误标“已人工发送”，X／YouTube 任务标题按联系方式识别；下发提示改为自动执行说明。API communication/sendflow 27 项测试、前端 typecheck 与 Docker 生产构建通过；本地 API／Web 已更新，未推送或发布云端。

待修缺口：LinkedIn 打开后停顿、WhatsApp 本人聊天号码核对、X 会话导航失败的准确分类、失败后的显式重新准备入口、黑屏截图可用性判断、公开作品评论动作及真实入站回复验收。新建门店的国际号码验证与 X／YouTube 显式录入选项也需统一；详情手动添加这两类平台目前仍走通用平台项。
