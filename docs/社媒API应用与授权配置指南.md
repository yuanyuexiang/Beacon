# 社媒 API 应用与授权配置指南

核对日期：2026-10-23。适用项目：Beacon。范围：Facebook（FB）、Instagram（INS）、TikTok（TK）、LinkedIn（LIN）。

本文说明如何准备账号、创建开发者应用、取得凭据及连接 Beacon。服务部署与维护另见[社媒渠道服务](社媒渠道服务.md)，选型依据见[社媒开发指南](../plan/social-channel-integration.md)。

**当前起点：只有个人账号。先完成 Facebook Page，再接 Instagram。TK／LinkedIn 先确认消息接口资格，不要把创建应用误当作已开通消息收发。**

本次核对了仓库代码与文末官方资料，没有登录用户的开发者后台，没有创建应用、申请权限或执行真实社媒收发。Meta 直接文档部分请求受限，接口能力以 Meta 官方 Postman 集合交叉核对；无法核实的后台菜单使用功能名称描述，不承诺固定按钮位置。平台可能按账号、地区及应用类型显示不同步骤。

## 一、先看需要准备什么

| 平台／路线 | 本方发送身份 | 应用凭据 | 账号授权凭据 | Beacon 当前支持 |
|---|---|---|---|---|
| Facebook Messenger | Facebook Page | Meta App ID、App Secret | Page Access Token | 浏览器授权或导入 Page Token，普通会话文字回复 |
| Instagram / Facebook Login | 关联 Facebook Page 的 Business／Creator 专业账号 | Meta App ID、App Secret | 关联 Page 的 Access Token | 浏览器授权或导入 Page Token |
| Instagram / Instagram Login | Business／Creator 专业账号 | 该路线的应用配置 | Instagram User Access Token | 当前仅导入账号 Token；未实现该路线浏览器授权 |
| TikTok Business Messaging | 获准使用消息接口的 TikTok 业务账号 | API for Business 应用凭据 | 相应产品的账号授权 Token | 尚未实现 provider，取得凭据不能直接填入 Meta 设置 |
| LinkedIn Messages | 获批协议范围内的成员／会话 | LinkedIn Client ID、Client Secret | 获批产品及 scopes 对应的 Token | 尚未实现消息 provider，现有人工流程可用 |

上表的 FB／INS 路线来自 Meta 官方集合；TK 来自 Business Messaging 官方接入步骤；LinkedIn 官方明确限制 Messages API 为获批伙伴使用。[M1]、[I1]、[I2]、[T1]、[L1]

“API Key”只是通俗叫法，实际有三层：

1. **应用身份**：App ID／Client ID 与 Secret，标识接入应用。
2. **账号授权**：Access Token，决定哪个 Page／专业账号授权应用做什么。
3. **消息条件**：真实收件人身份、会话、权限和允许的动作。前两层成功不自动满足第三层。

### 容易混淆的字段

| 字段 | 从哪里获得 | 填到哪里／用途 |
|---|---|---|
| Meta App ID | Meta 应用后台 | Beacon“配置 Meta 应用” |
| Meta App Secret | 同一应用的基本设置 | Beacon“配置 Meta 应用”；也用于验证 Webhook 签名 |
| Webhook Verify Token | 你自己生成，与平台 Token 无关 | Beacon 与 Meta Webhook 配置填写相同值；Beacon 要求至少 16 字符 |
| Facebook Page ID | 本方 Page 信息或 Meta 官方 Graph 工具 | Beacon 添加 Facebook 账号时的“发送账号 ID” |
| Instagram 专业账号 ID | 对应登录路线的官方 API 返回值 | Beacon 添加 Instagram 账号时的“发送账号 ID” |
| Page Access Token | Page 授权流程／Meta 应用后台／Graph API Explorer | Facebook 或 INS Facebook Login 账号凭据 |
| Instagram User Access Token | Instagram Login 授权流程 | 仅用于 INS Instagram Login 账号凭据 |
| Beacon 内部服务 Bearer | 部署脚本生成 | API 与 meta-service 内部认证；不要填入 Meta 控制台 |

App Secret 不是 Page Token；个人 User Token 不是 Page Token；个人主页链接不是 Page ID；Instagram 用户名不是专业账号 API ID。

## 二、先准备 Facebook Page

### 2.1 创建与确认身份

1. 用自己的 Facebook 个人账号登录，找到“主页／Pages”中的创建主页入口，建立本方真实业务 Page。
2. 填写真实名称、业务介绍和联系方式。保留个人账号作为管理身份，不把餐厅客户 Page 当作本方发送账号。
3. 在 Page 管理权限中确认自己能管理消息。组织还有其他管理员时，确认应用授权由具有对应 Page 权限的人完成。
4. 从 Page 信息中的 Page ID 字段记录数字 ID；若当前界面不显示，用后面的官方 Graph 工具读取。不要使用个人账号数字 ID、用户名或主页 URL 代替。

现有 Beacon Facebook 适配器只接受 Page 身份，不支持把个人账号登录凭据用于个人私信。Messenger 官方集合要求 Facebook Page 与具备 `pages_messaging` 权限的应用。[M1]

### 2.2 准备应用审核信息

先准备开发者联系邮箱、真实业务说明、应用用途，以及可公开访问的隐私政策、用户数据删除说明／回调等材料。哪些字段或企业验证必须完成，以选定产品在控制台的要求为准；不能保证“个人开发者一定免验证”或“一定先要企业认证”。

Beacon 当前文档没有为这些审核材料提供已经上线的隐私政策／删除端点；不要把尚不存在的地址填写成已完成。需要公开审核时，另行实现并验收这些页面／端点。

## 三、创建 Meta 应用并取得 App ID／Secret

1. 打开 [Meta Developers 应用后台](https://developers.facebook.com/apps/)，用管理 Page 的身份登录；首次使用按平台提示完成开发者注册。
2. 选择创建应用，填写名称和联系邮箱。按控制台提供的用例选择支持 Page 消息／Messenger 的路径；不要选成只有普通网站登录或广告而没有消息产品的应用。
3. 如果要求绑定业务资产／Business Portfolio，选择本方组织并按实际要求完成验证。用例、应用类型和资产选择会影响可见的权限，不能用某篇旧教程中的“Other → Business”作为所有账号的固定步骤。
4. 应用创建后，在应用的基本设置（通常为 App settings／Settings → Basic）取得 **App ID** 与 **App Secret**。需要身份确认时按 Meta 提示操作；记录到密码管理器，勿粘贴到源码或聊天截图。
5. 在产品／用例配置中完成 Messenger 及相应 Facebook 登录配置。若后台只提供需要额外 `config_id` 的登录产品，先让开发核对兼容性，不要将其视为现有 Beacon OAuth 自动支持。
6. 核对应用 Graph API 版本。Beacon 代码默认 `v25.0`；这只是代码默认值，不代表最新版本或当前应用已获兼容验证。选择后应与 Beacon 配置一致，并完成真实接口验收。

获取 App ID／Secret 不需要 Google 的 OAuth JSON 文件。Meta 在 Beacon 中使用表单配置，不要上传 Google `client_secret_*.json`。

### 3.1 配置授权回调与应用域名

在所选 Facebook 登录产品的设置中，找到授权重定向 URI（通常为 Valid OAuth Redirect URIs），登记完整地址：

```text
https://beacon.ai-onestep.com/api/outreach/oauth/callback
```

如要求 App Domains，填写域名 `beacon.ai-onestep.com`；网站 URL 按真实部署填写。三个字段用途不同，不把完整回调 URL 填进域名字段。

本机代码的默认回调是 `http://localhost:3000/api/outreach/oauth/callback`。是否允许 localhost 取决于该产品的开发配置；不能把 Google 支持 localhost 推广到所有 Meta 产品。本项目真实消息联调优先在云端 HTTPS 环境完成，Webhook 也使用公网 HTTPS。

**上述 `/api/outreach/oauth/callback` 当前是 Meta 回调。不得拿它配置 TikTok 或 LinkedIn。Gmail 的 `/api/gmail/oauth/callback` 也不能与它互换。**

### 3.2 权限：现有代码与平台所需分开看

| 用途 | Beacon 现有授权请求 | 配置注意事项 |
|---|---|---|
| Facebook Page 授权 | `pages_show_list`、`pages_messaging`、`pages_manage_metadata`、`pages_read_engagement` | 在对应产品／权限中申请并让管理员实际同意 |
| Instagram / Facebook Login | `pages_show_list`、`pages_manage_metadata`、`pages_read_engagement`、`instagram_basic`、`instagram_manage_messages` | 使用关联 Page 的身份；不是 `instagram_business_*` 路线 |
| Instagram / Instagram Login | 当前无浏览器授权请求 | 后续适配应按该路线申请 `instagram_business_basic`、`instagram_business_manage_messages` 等实际动作权限 |

这是仓库代码现状，不是 Meta 所有 API 的完整权限清单。当前身份检查读取 Page 的 `id,name`，也需 `pages_read_engagement`；云端已复现缺少此权限会返回 code=100。以后增加历史会话读取／同步时，仍须按具体端点补齐权限。[M2]

开发角色联调通过不代表所有外部账号可用。对外服务应按控制台针对具体权限的 Standard／Advanced Access、App Review、业务验证及应用状态要求办理；不要只切换 Live 就认定消息权限已获批准。[M2]

## 四、把 Facebook 应用与 Page 添加到 Beacon

### 4.1 保存应用配置

打开 [云端设置页](https://beacon.ai-onestep.com/settings)，展开“配置 Meta 应用”，填写：

| Beacon 字段 | 填写内容 |
|---|---|
| App ID | 第三节创建的 Meta 应用 ID |
| App Secret | 同一应用的 Secret |
| Webhook Verify Token | 自己生成并保存的随机值，至少 16 字符 |
| Graph API 版本 | 当前应用选择并准备验收的版本 |
| OAuth 回调地址 | `https://beacon.ai-onestep.com/api/outreach/oauth/callback` |

保存应用会影响既有账号授权／发送状态，后续更换 Secret 或应用时按[操作说明](社媒渠道服务.md)重新核验，不要作为普通刷新操作反复保存。

### 4.2 添加发送账号

1. 展开“添加发送账号”。
2. 账号名称填本方 Page 的可识别名称。
3. 渠道选择 **Facebook**；认证路线选择 **Facebook Login**。
4. 发送账号 ID 填本方 **Page ID**；Facebook 账号不需要填写 Instagram 关联 Page ID。
5. 保存后点击该账号的“浏览器授权”，选择管理 Page 的身份并同意实际请求的权限。
6. 返回 Beacon 后点击“检查连接”，核对所连接的身份。

现有代码会用已知 Page ID 换取 Page Token；尚没有完整的“授权后列出所有 Page 供选择”向导。若无法换取 Token，应核对 Page 权限、授权资产和产品兼容性，不要把任意 User Token 反复导入。

### 4.3 备用：使用已有 Page Token

Meta 官方集合列出 Facebook Login、应用后台和 Graph API Explorer 等取 Token 路径。[M1]

仅在调试或已有明确凭据时使用：

1. 打开 [Graph API Explorer](https://developers.facebook.com/tools/explorer/)，确认选中**本方刚创建的应用**。
2. 通过授权取得该应用权限范围内的 User Token；如工具提供 Page Token 选择，切换为目标 Page。不是只复制默认 Token 就结束。
3. 若需读取自己可管理的 Page，可在官方工具使用相应 API 版本的只读请求 `GET /me/accounts?fields=id,name,tasks`；权限不足或资产不可见时先修复授权，不用客户 Page 代替。
4. Page Token 通过该产品的 Page 授权／Token 生成功能取得；涉及返回 `access_token` 的响应属于凭据，不能整段截图或保存进仓库。
5. 用 [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) 核对关联应用、身份、有效性、权限和过期信息。只在 Meta 官方工具使用真实 Token。
6. Beacon 中该账号选择“导入 Token”，填写 Page Token，再执行连接检查。

不把调试生成 Token 当作永久部署凭据；不承诺某种 Token 永不过期。身份、权限、撤销和资产变化都会影响后续调用。

## 五、配置 Webhook：不仅是填一个 Token

### 5.1 回调和验证

在对应 Meta 产品的 Webhook 设置中填写：

```text
Callback URL: https://beacon.ai-onestep.com/api/outreach/webhook
Verify Token: 与 Beacon 应用配置完全相同的自设值
```

Webhook Verify Token 用于平台 GET 验证握手；App Secret 用于 POST 消息签名校验；Page Access Token 用于授权的 Graph API 调用。三者不能互换。实现位置为 `services/meta/meta_service/core.py` 的 `webhook_challenge` 与 `webhook`。

验证前先在 Beacon 保存相同的 Verify Token。验证失败先查 HTTPS 路由、服务是否配置和 token 是否一致，不因没有登录工作台就认定 Webhook 不可用；Webhook 是平台公开回调。

### 5.2 应用事件订阅与 Page 订阅

回调验证成功只证明能握手，还需：

1. 为对应产品／对象订阅所需事件。当前 Beacon 处理普通消息事件，优先验证 `messages`。
2. 将**目标 Page／专业账号**订阅到该应用。配置应用回调与让实际账号向该应用推送消息是两个步骤；按产品 API setup／Webhook 页面完成账号订阅。
3. 控制台测试事件只能验证部分接收链路，必须再由真实测试身份给目标 Page 发消息，确认 Beacon 出现会话。

`messaging_postbacks`、已读、送达、评论等不等于当前已支持的普通入站文字消息。当前 parser 只处理具有消息 ID 的 `entry.messaging[].message`，忽略 echo；不要仅因成功勾选订阅字段就声明对应功能已实现。

### 5.3 消息验收

使用本方控制且符合当前开发／访问级别条件的测试身份发消息，不向客户执行测试发送。

- Beacon 出现正确账号下的会话。
- 将会话关联到测试门店，完成现有渠道准入、审批及任务准备。
- 验收前仅为该测试账号按需开启“允许发送”，队列保持关闭；明确预览最终正文和收件人，再确认回复一封。验收结束恢复暂停。
- 核对平台消息 ID 及测试接收端实际收到；随后再发入站消息，确认任务暂停。
- 身份检查、Webhook 握手、平台接受、实际收件分别记录，不合并成一个“已连接”结论。

Beacon 当前普通回复采用最近入站后 24 小时范围，不启用窗口外例外。Meta 官方发送条件以对应产品要求为准，公开主页链接不能直接当作会话收件人。[M3]

## 六、Instagram 怎么准备与授权

### 6.1 推荐先用 Facebook Login

适合当前“先 FB、后 INS”的 Beacon 路径：

1. 创建本方 Instagram 账号，按 Instagram 设置中的专业账号功能转换为 Business 或 Creator。
2. 按 Meta 的账号关联流程，将其关联到第二节建立的 Facebook Page；确认授权者能管理对应资产。
3. 通过该路线的官方工具读取专业账号 ID；已授权 Page 可查询 `GET /{PAGE_ID}?fields=instagram_business_account{id,username}`。若没有对象返回，先核对关联和权限，不把 Instagram 用户名填进 ID 字段。
4. Beacon 添加账号：渠道 **Instagram**，认证路线 **Facebook Login**，发送账号 ID 填专业账号 ID，关联 Facebook Page ID 填 Page ID。
5. 用该账号“浏览器授权”，核对请求的 Instagram 权限，再检查连接。
6. 按 Instagram 产品对象完成 Webhook 和账号订阅，使用测试身份先给专业账号发私信，再验收入站与确认回复。

Facebook Login 官方集合要求专业账号与 Page 关联，普通 Instagram 消费者账号不能替代。[I1]

### 6.2 Instagram Login 是另一条路线

该路线针对专业账号，不沿用 Facebook Login 的 Page 关联前置条件；权限名称、Token、授权及接口主机分别按官方资料处理。[I2]

Beacon **尚未实现这条路线的浏览器授权和长期 Token 自动刷新**。只有已通过官方流程取得该专业账号 Token 的维护人员，才使用当前“Instagram Login → 导入 Token”路径。不要把普通 Instagram 网站密码／Cookie 或 Page Token 填进去。

准备全新账号时，先按 6.1 完成当前主路径；不要同时创建两条路线，再混用 App ID、Secret、Token 和权限。如果选择独立 Instagram Login，应先补齐并测试对应适配，不承诺 Meta 应用配置表单能直接承接全部 Instagram 专属配置。

## 七、TikTok：先申请消息接口访问，再准备 Token

### 7.1 正确入口

使用 [TikTok API for Business](https://business-api.tiktok.com/portal/) 的 **Business Messaging API**。不要把 TikTok for Developers 的 Login Kit／Content Posting 凭据或广告 API Token 当作私信权限。[T1]、[T2]

官方接入顺序包括账号、开发者注册、应用创建、Business Messaging 访问、授权及 Webhook。按以下里程碑操作：

1. 准备本方 TikTok 业务账号及 TikTok For Business 身份。
2. 在 API for Business 门户注册开发者并创建应用，填写真实主体与接入用途。
3. 按应用后台取得 App ID／Secret 等凭据。**具体字段名称以该产品后台为准**，不要将其他 TikTok 产品的 `client_key` 强行映射。
4. 在 Business Messaging 访问申请中提交真实业务场景，按门户要求完成隐私、安全、数据访问或地区审查。账号建立／应用审核与消息产品访问分开核对。
5. 获批后，按**Business Messaging 自己的授权文档**让本方业务账号授权，核对应用、账号身份、实际 scopes、过期字段及可用刷新机制。
6. 根据官方接口做账号／会话能力检查、测试会话读取与 Business Messaging Webhook 配置；确认发件账号注册地区及当前动作支持后再安排发送开发。

不在文档中固定消息窗口、每天可发数量、Token 有效期或英国支持结论；这些必须从所选产品当前文档、应用授权和账号能力响应确认。[T1]、[T2]

### 7.2 Beacon 当前填写位置

目前**没有 TikTok provider、凭据表单或专用回调实现**。取得 App ID／Secret 后只存密码管理器，不填到 Facebook／Instagram 配置，也不要在 TikTok 后台登记 Meta 的回调。

下一阶段开发须明确：TikTok 专用回调／Webhook、验签、Token 生命周期、能力探针、收件身份、发送账本与结果未知处理。专用路径实施并验收后再登记，不在本文虚构一个当前不存在的可用 URL。

## 八、LinkedIn：Client ID 不等于 Messages 权限

### 8.1 创建应用与获取凭据

1. 打开 [LinkedIn Developer Apps](https://www.linkedin.com/developers/apps)，使用本方账号创建应用。
2. 按当前表单准备应用名称、Logo、隐私政策及本方 LinkedIn Page；需要 Page 管理员验证时完成验证。创建应用与验证 Page 不是开通消息权限。
3. 进入应用 **Auth** 页，取得 **Client ID／Client Secret**，保存到密码管理器。
4. 在 **Products** 页查看实际可申请产品和已批准权限。记录审批结果，不能仅记录已点击“申请”。
5. 只有对应产品已获批、Beacon 适配已有可用回调时，才登记其 HTTPS 回调并执行成员 OAuth。[L2]、[L3]

### 8.2 消息权限的判断

LinkedIn 官方 Messages API 仅面向获批伙伴，并受 API 协议限制；官方文档描述一度联系人的消息及已有会话回复，还要求明确成员发送动作。[L1]

普通 OIDC 登录权限和 `w_member_social` 不表示取得私信能力。没有消息产品访问时，创建 Client ID、订阅 Premium／Sales Navigator 或拿到普通 Token，都不能把现有应用变成消息发送接口。[L2]

### 8.3 Beacon 当前用法

保留线索 LinkedIn 主页、准备已审批文案、人工发送和回填。当前没有 LinkedIn 消息 provider／OAuth 回调，不把凭据填入 Meta 表单。未来若获得 Messages API 权限，再按协议接入；普通自动排队发送不能直接套用 LinkedIn 要求明确成员动作的接口。[L1]

## 九、常见错误及检查顺序

| 现象 | 优先检查 | 不应采取的处理 |
|---|---|---|
| Meta 应用里没有 Messenger 权限／产品 | 应用用例、产品和当前账号资格是否匹配 | 反复换 Token，希望自动出现产品 |
| OAuth 回调被拒绝 | 产品中登记的完整地址、应用 ID、当前 HTTPS 域名 | 用 Gmail 回调替换 Meta 回调 |
| 有 Token，但身份不匹配 | 是否选对应用、Page／专业账号 ID、Token 路线 | 跳过身份核对直接开启发送 |
| App Secret 校验正常但不能发消息 | 账号 Token、实际 scopes、消息产品访问 | 将 App Secret 当作 Access Token |
| Webhook 验证成功却没有消息 | 对象事件、Page／专业账号订阅、测试身份资格、真实入站 | 将握手成功当作订阅和收件成功 |
| 角色账号能用，外部账号不能用 | 对应权限访问级别、审核、资产和应用发布状态 | 仅提高 Beacon 的每日限额 |
| 权限错误或 Token 过期 | 官方调试工具的权限与过期信息、是否撤权／更换资产 | 认定所有 403 都是网络故障 |
| 请求超时但发送结果未知 | 请求账本、平台实际记录、消息 ID | 自动重发或删除失败记录 |
| TK／LIN 有 Client ID 但不能添加 | Beacon provider 尚未实现；消息产品资格可能未取得 | 把凭据填入 FB／INS 表单 |
| GitHub 拦截 secret 文件 | 从未推送提交中移除，保留本地并加入忽略规则 | 使用解除保护链接提交真实 Secret |

## 十、验收记录：以后每个平台都按此填写

记录放受控位置，不填写真实 Secret／Token：

| 项目 | 记录内容 |
|---|---|
| 平台与认证路线 | Facebook Login／Instagram Login／具体消息产品 |
| 应用与发送身份 | 应用名称／ID、Page／专业账号 ID，禁止 Secret |
| 实际权限 | 已获批及已同意的 scopes、访问级别、未通过项 |
| 回调 | 当前环境实际地址、OAuth 是否完成 |
| Token | 身份匹配、有效／过期、检查时间，禁止 Token 原文 |
| Webhook | 握手、对象事件、账号订阅、真实消息是否到达 |
| 收发测试 | 本方测试身份、平台消息 ID、实际收件、回复暂停 |
| 失败路径 | 过期、撤权、重复事件、窗口截止、未知结果 |
| 最终状态 | 仅应用创建／仅身份连接／测试收发通过／外部访问待批准 |

只有“真实测试会话收发通过”才能写已完成消息接入。本文是准备与配置指南，不代表这四个平台已完成真实授权验收。

## 十一、官方资料与核对范围

下列资料于 2026-10-23 核对。Meta Postman 链接属于 Meta 发布的官方集合，不采用第三方博客代替权限依据。部分后台／动态页面需要登录，未在用户账号内逐屏验证；操作时以当前产品显示为准。

- [M1：Meta Messenger 官方集合](https://www.postman.com/meta/messenger-platform-api/collection/iyp204x/messenger-platform-api)：Page、应用、Token 获取路径。
- [M2：Meta Conversations API](https://www.postman.com/meta/messenger-platform-api/folder/22794852-255610cd-47f5-4f4d-b3fa-71aec360be9a)：会话权限与外部访问条件。
- [M3：Meta Messenger 官方发送说明](https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api)：消息身份与标准回复条件。
- [Meta Developers 应用后台](https://developers.facebook.com/apps/)：实际应用设置入口；需登录操作。
- [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/)：官方调试工具；不在本文代用户生成凭据。
- [Meta Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)：核对应用、身份、权限和有效性。
- [I1：Instagram API with Facebook Login](https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login)：专业账号与 Page 关联要求。
- [I2：Instagram API with Instagram Login](https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login)：独立登录路线与权限。
- [T1：TikTok Business Messaging 接入步骤](https://business-api.tiktok.com/portal/docs/business-messaging-api-get-started/v1.3)：开发者、访问申请、授权与 Webhook 的顺序。
- [T2：TikTok API for Business 官方文档目录](https://business-api.tiktok.com/portal/docs?id=1736271785207810)：Business Messaging、能力检查及 Webhook 接口。
- [L1：LinkedIn Messages API](https://learn.microsoft.com/en-us/linkedin/shared/integrations/communications/messages)：获批伙伴及明确成员动作要求。
- [L2：LinkedIn API 访问权限](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access)：开放产品与需申请产品的区别。
- [L3：LinkedIn OAuth 授权码流程](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow)：Auth 页凭据、HTTPS 回调和授权过程。

代码核对位置：`services/meta/meta_service/core.py`、`services/meta/meta_service/server.py`、`apps/api/app/modules/outreach/routes.py`、`apps/web/src/components/SocialSettings.tsx`。后续代码变化时同步更新本指南的“当前支持”部分。

[M1]: https://www.postman.com/meta/messenger-platform-api/collection/iyp204x/messenger-platform-api
[M2]: https://www.postman.com/meta/messenger-platform-api/folder/22794852-255610cd-47f5-4f4d-b3fa-71aec360be9a
[M3]: https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api
[I1]: https://www.postman.com/meta/instagram/folder/u4g5a2a/instagram-api-with-facebook-login
[I2]: https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login
[T1]: https://business-api.tiktok.com/portal/docs/business-messaging-api-get-started/v1.3
[T2]: https://business-api.tiktok.com/portal/docs?id=1736271785207810
[L1]: https://learn.microsoft.com/en-us/linkedin/shared/integrations/communications/messages
[L2]: https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
[L3]: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow
