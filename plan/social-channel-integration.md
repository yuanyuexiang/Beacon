# 社媒渠道接入与后续开发指南

调研日期：2026-10-12。范围：TK（TikTok）、FB（Facebook）、INS（Instagram）、LIN（LinkedIn）。本文用于后续开发规划；社媒适配器尚未实施，整理文档不代表授权联系客户。

Beacon 已有 Gmail 独立服务，后续社媒接入应复用任务、审批、抑制、执行结果和回复处理，按平台分别实现账号认证及消息能力。餐厅公开主页可以用于研究和人工访问，但不能直接当作 API 收件人。官方社媒接口主要支持受条件限制的会话，不能照搬 Gmail 的邮箱发送流程。

## 一 平台能力与业务适用性

| 渠道 | 官方接入路径 | 对 Beacon 的主要用途 | 冷启动触达限制 |
|---|---|---|---|
| Facebook | Page 与 Messenger Platform | 接收本方主页咨询，回复已有会话 | 餐厅 Page URL 不等于可发送对象；需要当前发送主页下的 PSID 和有效消息条件 |
| Instagram | 专业账号消息接口，区分 Instagram Login 与 Facebook Login | 接收专业账号私信、回复会话，符合条件的评论私信回复 | 公开用户名不等于消息收件人 ID；普通消息流程由用户发起会话 |
| TikTok | Business Messaging API，申请访问并授权 Business Account | 在具备资质与地区支持的账号上管理会话 | 必须验证账号、应用、地区及具体动作能力，不能承诺向餐厅名单任意发私信 |
| LinkedIn | 受限的 Messages API，或 Page 消息合作伙伴 | 获批接口下的消息管理；个人获客先支持人工执行 | 普通开发者应用、Sales Navigator 或 InMail 订阅不等于消息 API 授权 |

平台依据：[Meta Messenger][meta-messenger]、[Meta Instagram][meta-instagram]、[TikTok 接入步骤][tiktok-start]、[LinkedIn Messages API][linkedin-messages]。业务准入与平台消息权限分别检查：内部允许联系，也可能因会话窗口或账号能力而无法执行。

### Facebook

官方方案以本方 Facebook Page 为发送身份，使用 Page Access Token 和 `pages_messaging` 等所需权限。收件人使用 Page-scoped ID（PSID），必须保留其所属发送主页；不能把餐厅公开 Page 链接转换成未经验证的 PSID。

标准发送规则要求对方在最近 24 小时内与该主页交互，或满足平台允许的窗口外消息条件。不能将审批通过、内部每日限额或 AI 判断作为窗口外发送依据。外部真实用户所需的访问级别与测试角色不同，开发测试成功后仍需确认对应权限的 Advanced Access。[发送规则][meta-messenger]、[会话与访问条件][meta-conversations]

个人 Facebook 账号的浏览器操作与官方 Page API 是不同路线。首期采用 Page 消息收发，不将个人账号自动私信纳入该适配器。

### Instagram

官方消息接口针对 Business 或 Creator 专业账号。Instagram Login 路线使用 `instagram_business_basic`、`instagram_business_manage_messages` 等权限；Facebook Login 路线涉及 Page 关联和另一组权限。两条路线分别处理 token、账号发现及 webhook 配置，不能混用权限清单。[Instagram Login][meta-instagram-login]、[消息接口][meta-instagram]

普通私信会话由 Instagram 用户先发起。公开主页或用户名仅作为线索来源，发送需使用实际接口返回的消息身份。群聊、历史查询范围和媒体类型也不能按 Gmail 推定。

评论私信回复作为独立动作评估，仅在平台允许的评论和媒体范围内执行。不能因为在其他餐厅帖子里发现评论，就推定本方可以主动私信该用户。具体回复期限、次数及后续消息窗口，实施前按选定登录路线的官方文档与测试账号确认，不在当前代码规划中冻结未经核实的数字。

### TikTok

Business Messaging API 的接入包括开发者注册、应用创建、访问申请、Business Account 授权和 webhook 配置。发送会话消息前，应调用可用的能力检查，并确认账号实际支持的消息类型。[官方接入步骤][tiktok-start]、[业务消息概览][tiktok-overview]

地区限制需区分发送账号注册地区、接收对象地区和服务商接入路径。Infobip 的 TikTok 接入文档对美国、EEA、瑞士、英国注册账号列有不可用限制；这是该服务商路径的条件，不能直接推广为所有 TikTok API 路径的统一结论，也不能仅因目标餐厅在英国就判定本方账号不可用。[Infobip 地区说明][infobip-tiktok]

先做账号资质与能力探针，成功后再建设独立服务。消息窗口、次数额度和地区支持使用已验证规则；不把第三方文章中的固定时长或次数作为平台事实。

### LinkedIn

官方 Messages API 受获批合作伙伴协议限制，文档描述的能力包括向一度联系人发消息及回复。一般 API 产品接入并不授予此消息能力。[Messages API][linkedin-messages]、[API 接入说明][linkedin-access]

Page 消息可考虑平台列出的合作伙伴，但它服务于 Page 会话，不能据此承诺个人账号的批量陌生人触达。[Page 消息合作伙伴][linkedin-pages]。Message Ads 是付费广告路线，应另建广告预算与投放流程，不混入普通私信队列。[Message Ads][linkedin-ads]

首期保留打开个人主页、复制已审核文案、人工发送和回填。LinkedIn 对未经批准的自动网站操作有明确限制，浏览器自动提交不作为长期服务器接入的默认路线。[自动化工具说明][linkedin-automation]

## 二 接入方案选择

| 方案 | 适用场景 | 开发取舍 |
|---|---|---|
| 官方 API 直连 | FB、INS；具备资质的 TK | 推荐主路径，能力和认证边界清晰；需要应用配置、权限与 webhook |
| Chatwoot 等会话平台 | 希望另设多人客服收件箱 | 可减少 FB、INS 收件箱建设，但会增加另一套会话状态；选型前核对版本、许可证和项目依赖政策 |
| Unipile 等聚合服务 | LIN 等渠道需要更快试验 | 作为可替换 provider，先验证真实账号及所需动作，不能视为平台官方授权的等价物 |
| 人工辅助 | 冷启动开发客户，或平台能力未取得 | Beacon 准备素材、打开链接、记录结果；打开页面和复制文案不记为已发送 |

Chatwoot 有 Facebook、Instagram 渠道说明；是否采用应以减少 Beacon 总维护成本为准，而非单看支持渠道数量。[Chatwoot 渠道文档][chatwoot]

Unipile 文档提供 LinkedIn、Instagram 消息和账号连接能力；其认证可以涉及托管连接、凭据或会话，不应统一标为官方 OAuth。所查 Hosted Auth 文档将 Facebook Messenger 标为不再维护，能力表未列出 TikTok，因此不能把它作为四个平台的一站式既定方案。[发送接口][unipile-send]、[账号连接][unipile-auth]、[Hosted Auth][unipile-hosted]、[能力表][unipile-features]

聚合服务进入实施前，至少验证连接与断线恢复、收件人解析、发送结果查询、回复事件、附件、费用和账号限制。供应商描述的“可发送”不保证当前账号或目标对象可发送。

## 三 建议服务结构

以下是后续结构建议，目录尚未新增：

```text
services/
  gmail/                 # 保留现有邮件服务
  meta/                  # 共用容器，Facebook 与 Instagram 各自适配器
  tiktok/                # 资质与能力验证通过后创建
  social-provider/       # 可选聚合服务适配，不绑定单一供应商
apps/api/app/modules/
  outreach/              # 统一任务执行、审批、队列及结果
  conversations/         # 会话、回复与平台消息条件
  sales/                 # 保留现有准入、抑制和销售业务
```

按“运行环境与认证依赖”拆容器，按“平台动作与身份”拆适配器。FB 与 INS 可共用 Meta 服务的部署与基础设施，但账号、权限、token 路线和收件人身份独立。不要为了目录整齐立即重写 Gmail；先提取确实被第二个渠道使用的接口。

HTTP 与 MCP 共用执行核心。MCP 只是调用方式，不增加账号权限，也不跳过业务审批。服务发现和能力查询可以返回不支持的动作，前端据此展示人工路径。

## 四 数据与接口约定

| 对象 | 建议字段与约束 |
|---|---|
| ChannelAccount | 平台、provider、发送身份、认证路线、地区、credential_ref、授权 scopes、实际 capabilities、状态、有效期、授权版本；不在业务表保存明文 token |
| PlatformContact | lead_id、公开主页来源、平台收件人 ID、所属发送账号、关联证据；公开 URL 与发送 ID 分列 |
| Conversation | 发送账号、平台会话 ID、对方身份、最近入站时间、窗口截止时间、已验证动作条件、规则版本、人工接管状态 |
| OutreachDelivery | 任务、账号、动作类型、内容版本与 hash、审批记录、幂等键、平台消息 ID、会话 ID、执行状态与时间、失败原因 |
| ConversationEvent | 平台、账号、事件 ID、消息 ID、方向、发生时间、接收时间、必要的回复信息；幂等入库 |

收件人及会话以平台和发送账号划定命名空间。相同显示名称不自动合并为同一餐厅；未匹配回复进入待关联列表。LinkedIn 后续应拥有独立渠道类型，对历史 `other_social` 中的记录按 URL 和证据迁移，无法判断的保留待核对。

适配器至少提供 `auth_status`、`capabilities`、`preflight_action`、`send_approved`、`get_send_status` 和规范化入站事件。`preflight_action` 区分普通回复、评论私信回复、个人消息、广告等动作，避免一个 `send_message` 掩盖不同限制。

执行前重新检查三组条件：业务准入及抑制、当前内容与账号授权版本、平台动作及会话条件。排队时允许发送不保证执行时仍允许；会话过期、授权撤回、内容变化或身份改变后停止旧任务。

发送状态区分待审批、排队、发送中、平台接受、送达、已读、失败、结果未知、条件过期、需重新授权和需人工执行。平台返回消息 ID 不必然等于送达；人工打开链接不产生发送结果。

## 五 认证部署与事件处理

正式服务器使用适合所选平台路线的认证流程。设置页展示连接状态、有效能力、地区和重连入口；Compose 内部 Bearer 用于服务间认证，与平台 OAuth token 分开管理。聚合服务的托管登录单独标识，不伪装成官方授权。

凭据放受控持久化存储或 secrets，业务数据库保留引用。明确每个服务的备份、恢复、撤销授权和日志脱敏规则。不要把日常浏览器 Cookie、账号密码或 OAuth token 写入 Git、前端配置及普通任务日志。

Webhook 通过 API 的公开 HTTPS 入口接收，内部适配器不直接暴露控制端口。按平台规范处理验证 challenge 和原始请求签名；事件先去重持久化，再触发会话更新、暂停跟进及销售回填。拒收事件继续沿用现有抑制规则。

GET 查询和认证刷新可以有界重试。发送 POST 超时或连接中断应记为结果未知，查询平台结果或进入人工对账；只有接口明确支持且正确使用幂等键时才依其约定重试。查询不到历史记录不能自动证明未发送。

图片、PDF 和其他附件按平台实际能力分别处理，包括上传接口、可访问 URL 及有效期；不假设 Gmail 支持的 PDF 可以直接发到所有社媒。AI 可生成文案、分类回复和提出关联建议，但不创造收件人 ID、不延长消息窗口，也不替代认证或审批。

## 六 建议实施步骤

| 顺序 | 工作 | 进入下一步的条件 |
|---|---|---|
| 0 | 完成现有 Gmail 的真实账号连接验收 | 区分本地模拟链路与真实授权、发送验证；独立处理当前授权问题 |
| 1 | 增加渠道账号、能力、收件人映射及统一执行接口 | Gmail 行为保持可用；无能力的动作展示清晰原因；LinkedIn 渠道迁移规则明确 |
| 2 | FB 与 INS 官方单账号试点 | 本方 Page／专业账号、应用权限和测试收件人具备；入站到审批回复闭环验证通过 |
| 3 | TK 资质与能力探针 | 账号地区、应用访问、目标范围和消息动作均验证；失败时保留人工路径 |
| 4 | LIN 人工辅助与可选 provider 试点 | 先支持人工回填；第三方或合作伙伴接入以实际账号验证为前提 |
| 5 | 扩展社媒队列与统一回复处理 | 单家发送、消息条件失效、未知结果和回复暂停已验证，再开放批量 |

不把应用审批时长或供应商试用结果提前当作交付保证。后续实施需要另行确定范围；本次仅完成调研归档，没有连接社媒账号或向任何客户发送消息。

## 七 验收要求

- 公开主页 URL 不能直接进入 API 发送；不同发送账号下的收件人 ID 不能串用。
- 窗口内测试回复可返回真实平台消息 ID；窗口过期及不支持的动作在执行前阻断。
- token 失效、账号更换、权限撤回和内容修改使旧审批失效，不自动切换发送身份。
- webhook 重复、乱序、回放及本方发出的消息不会产生重复回复或错误暂停；未知对象不会自动绑定餐厅。
- 发送结果未知不重复 POST；可对账结果有真实证据，无法确认的保持未知。
- 对方回复会暂停后续任务；拒收更新抑制状态，执行时再次检查。
- 附件不支持时给出可执行的替代路径，不静默丢弃；人工操作与 API 结果分别记录。
- 测试使用本方控制的账号和明确允许的测试对象；真实客户发送与开发验收分别授权。

## 八 实施前待确认事项

| 项目 | 要确认的内容 |
|---|---|
| Meta 账号 | 本方 Page、Instagram 账号类型及登录路线，应用权限和外部用户访问级别 |
| TikTok | 本方账号注册地区、Business Account、应用访问及目标地区／动作能力 |
| LinkedIn | 个人客户开发还是 Page 咨询；是否已有获批合作伙伴或愿意试验聚合服务 |
| 会话规则 | 选定路径的当前消息窗口、评论回复条件、次数限制及附件能力 |
| 运行维护 | 公网 HTTPS webhook、密钥与授权管理、备份、服务费用和失败对账责任 |

## 九 参考与维护

平台能力按调研日期记录；实际开发时复核所选路线的当前权限和限制，并将探针结果、规则版本与确定选择写入 [决策记录](decisions.md)。实施任务进入 [开发计划](development.md) 和 [任务清单](tasks.md)。邮件现状参见 [Gmail 服务计划](gmail-service.md) 与 [操作说明](../docs/Gmail邮件服务.md)。

以下引用均为平台或服务商自己的文档。Meta 链接为 Meta 官方 Postman 工作区；供应商说明仅证明其自身接入能力与限制。

[meta-messenger]: https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api
[meta-conversations]: https://www.postman.com/meta/messenger-platform-api/folder/22794852-255610cd-47f5-4f4d-b3fa-71aec360be9a
[meta-instagram]: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-3a63181c-e5c6-4890-96dd-e4d425bef5e0
[meta-instagram-login]: https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login
[tiktok-start]: https://business-api.tiktok.com/portal/docs/business-messaging-api-get-started/v1.3
[tiktok-overview]: https://business-api.tiktok.com/portal/bm-api/education-hub
[infobip-tiktok]: https://www.infobip.com/docs/tiktok
[linkedin-messages]: https://learn.microsoft.com/en-us/linkedin/shared/integrations/communications/messages
[linkedin-access]: https://www.linkedin.com/help/linkedin/answer/a526048
[linkedin-pages]: https://www.linkedin.com/help/linkedin/answer/a6246714
[linkedin-ads]: https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/advertising-targeting/version/message-ads-integrations
[linkedin-automation]: https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions
[unipile-send]: https://developer.unipile.com/docs/send-messages
[unipile-auth]: https://developer.unipile.com/docs/connect-accounts
[unipile-hosted]: https://developer.unipile.com/docs/hosted-auth
[unipile-features]: https://developer.unipile.com/docs/list-provider-features
[chatwoot]: https://www.chatwoot.com/hc/user-guide/en/categories/other-channels
