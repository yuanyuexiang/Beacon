# Beacon 客户 Google 服务开通指南

适用对象：负责开通 Google 账号、邮箱及费用账户的客户管理员。  
更新日期：2026-11-17。控制台菜单可能随 Google 更新调整，可按括号中的英文名称查找。

本指南帮助您在自己的 Google Cloud 项目中创建 Gmail 授权和 Google Places API 密钥。项目、邮箱、账单及凭据由客户持有；技术方协助接入 Beacon，无需提供 Google 登录密码或短信验证码。

## 一、先分清需要开通什么

| 服务 | Beacon 用途 | 需要创建的凭据 | 是否需要登录邮箱授权 |
|---|---|---|---|
| Gmail API | 发送已确认邮件，以及可选的回复头同步 | Web application 类型 OAuth 客户端 JSON | 需要，由实际发件邮箱本人操作 |
| Places API (New) | 补充门店官网、电话及门店资料 | 服务器 API Key | 不需要 Gmail 授权，需要关联结算账户 |

两项服务可建在同一客户生产项目中，凭据分开创建。开发测试建议另建项目，避免与正式业务混用。Google Places 的 Key 不能代替 Gmail OAuth 客户端。

## 二、开始前准备

- 客户持有的 Google 账号；如使用公司 Google Workspace，准备组织管理员协助。
- 实际用于发信的 Gmail 或 Google Workspace 邮箱。
- Places 使用的 Cloud Billing 结算账户及有效付款方式，具体可用方式以账号所在地区为准。
- 正式工作台域名，以及由技术方确认的 Gmail 完整回调地址。
- 公司名称、支持邮箱；需要提交 OAuth 审核时，还需真实的应用首页、隐私政策等资料及域名管理权限。

填写以下信息，方便后续接入：

| 项目 | 客户填写／技术方确认 |
|---|---|
| Google Cloud 项目名称／Project ID | 待填写 |
| 正式工作台地址 | 待填写 |
| Gmail 完整回调地址 | 从 Beacon 设置页复制 |
| 发件邮箱 | 待填写 |
| Places 服务器固定公网出口 IP | 技术方提供，不能填电脑局域网地址 |
| 月度预算及费用告警接收邮箱 | 待填写 |

### 创建 Google Cloud 项目

1. 打开 [Google Cloud 控制台](https://console.cloud.google.com/)，登录客户自己的账号。
2. 点击顶部项目选择器 → **新建项目（New project）**。
3. 输入名称，例如 `Beacon Production`；有公司组织时选正确组织，创建后切换到该项目。
4. 后续启用 API、创建凭据、配置 OAuth 时，均核对顶部项目是否正确。

## 三、开通 Gmail 网页授权

### 1. 启用 Gmail API

进入 **API 和服务（APIs & Services）→ 库（Library）**，搜索 **Gmail API**，打开并点击 **启用（Enable）**。

### 2. 配置 Google Auth Platform

在控制台搜索 **Google Auth Platform**，首次进入点击开始配置：

1. **品牌信息（Branding）**：填写应用名称（例如“公司名称 Beacon 工作台”）、支持邮箱和开发者联系邮箱。
2. **目标对象（Audience）**：按实际使用范围选择：
   - **Internal（内部）**：仅适用于项目所属 Google Workspace／Cloud Identity 组织内的用户。普通个人 Gmail 账号不适用；组织外邮箱无法授权。
   - **External（外部）**：需要个人 Gmail 或组织外账号授权时选此项。
3. 填写控制台要求的应用域名、首页和隐私政策等信息。域名验证由域名持有人配合，不填写不存在的页面。

“只在本公司使用”不自动等同于 Google 的 Internal；必须满足组织归属条件。参考 [目标对象与发布状态说明](https://support.google.com/cloud/answer/15549945?hl=en)。

### 3. 声明实际需要的权限

在 **数据访问（Data Access）→ 添加或移除权限（Add or remove scopes）** 中，按实际功能选择：

| 权限 | 用途 | 本系统使用方式 |
|---|---|---|
| `openid`、`https://www.googleapis.com/auth/userinfo.email` | 识别授权邮箱 | 基础身份权限 |
| `https://www.googleapis.com/auth/gmail.send` | 发送邮件 | 发信功能需要，属于敏感权限 |
| `https://www.googleapis.com/auth/gmail.metadata` | 读取邮件头、标签等元数据 | 开启回复头同步时才申请，属于受限权限 |

当前新版网页连接不需要申请 `gmail.modify` 或全邮箱 `https://mail.google.com/`。`gmail.metadata` 不提供邮件正文；不要将回复头同步理解为已开启正文读取。旧连接可能保留 `gmail.readonly`，新建时按本表配置。权限级别以 [Gmail 官方权限表](https://developers.google.com/workspace/gmail/api/auth/scopes) 为准。

### 4. 决定 Testing 还是正式发布

**临时联调**：External 项目可以先保持 **Testing**，在 Audience 的 **测试用户（Test users）** 中添加实际授权邮箱。涉及 Gmail 的此类测试授权通常在授权后 7 天失效，刷新令牌也会失效。[官方期限说明](https://support.google.com/cloud/answer/15549945?hl=en)

**长期使用**：在 Audience 中点击 **发布应用（Publish app）**，确认发布状态为 **In production**，然后重新在 Beacon 连接 Gmail。此操作移除 Testing 专属的 7 天期限，不保证授权永久有效。

**正式发布不等于完成 Google 审核**：

- 不符合审核例外的应用，应按控制台要求完成品牌及敏感／受限权限审核；不能把点击 Publish app 当作已获得全部权限的审核批准。
- 个人自用、符合条件的组织内部使用等可能适用例外，应按真实用途确认，不能仅因为用户少就随意认定免审。
- 未审核应用可能出现“未经 Google 验证”提示或授权限制。
- 向外部客户开放且涉及服务器处理受限数据时，可能还需要第三方安全评估；由 Google 按具体使用方式决定。

参考 [敏感权限审核](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)、[受限权限审核与例外](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)。需要审核时，准备真实操作演示视频、权限用途说明、公开隐私政策及域名证明，按 Verification Center 的反馈提交。

### 5. 创建 Web OAuth 客户端并下载 JSON

1. 进入 **Google Auth Platform → 客户端（Clients）→ 创建客户端（Create client）**。
2. 应用类型选择 **Web application（Web 应用）**，不要选 Desktop 或 Android。
3. 名称填写 `Beacon Production Web`。
4. 在 **已获授权的重定向 URI（Authorized redirect URIs）** 添加 Beacon 设置页显示的完整回调地址。

例如当前部署在 `https://beacon.ai-onestep.com` 时，通常为：

```text
https://beacon.ai-onestep.com/api/gmail/oauth/callback
```

以上只是现有域名示例；换成客户独立域名后，必须以该部署设置页显示值为准。协议、域名、端口、路径及末尾斜杠应完全匹配。不要把回调地址填到“JavaScript origins”中。

5. 点击创建，下载客户端 **JSON 文件**，妥善保存。Beacon 需要包含 `web` 配置的原始 JSON，不需要客户手工拼接。

参考 [Gmail 服务器端 OAuth 接入](https://developers.google.com/workspace/gmail/api/auth/web-server)。

### 6. 在 Beacon 中连接邮箱

1. 以 Beacon 管理员身份进入 **设置 → 邮件 · Gmail**。
2. 展开首次配置区域，上传刚下载的 Web OAuth 客户端 JSON，点击保存 Web 客户端。
3. 点击 **连接 Gmail**，由实际发件邮箱本人选择账号并授权。
4. 返回 Beacon，检查显示的邮箱是否正确、是否获得发送权限。
5. 需要回复头同步时，再点击 **开启／重新授权回复同步**，授予对应权限。
6. 首次验收使用自己可控的收件邮箱：完整预览内容后确认发送一封，核对发送记录及实际收件结果。先不要打开批量队列。

保存客户端 JSON 本身不代表邮箱授权成功；应看到实际邮箱和有效连接状态。

## 四、开通 Google Places API

### 1. 关联结算账户

进入 **结算（Billing）**，为项目关联客户自己的结算账户，按控制台提示完善付款资料。Places 按使用功能和请求计费，需要启用结算；免费用量、价格和地区条款以当前账号及官方页面为准，不承诺长期免费。[计费说明](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing)

### 2. 启用 Places API (New)

进入 **API 和服务 → 库**，搜索 **Places API (New)** 并启用。Beacon 当前使用 `places.googleapis.com/v1`，请确认启用的是新版服务，不只启用 Legacy，也不需要为此额外开通 Maps JavaScript API 或 Gemini API。[官方开通步骤](https://developers.google.com/maps/documentation/places/web-service/get-api-key)

### 3. 创建并限制 API Key

1. 进入 **API 和服务 → 凭据（Credentials）→ 创建凭据 → API 密钥（API key）**。
2. 命名为 `Beacon Places Server`，进入该密钥的编辑页面。
3. **API 限制（API restrictions）**：选择限制密钥，仅允许 **Places API (New)**。
4. **应用限制（Application restrictions）**：本系统由服务器调用，使用 **IP addresses**，填写技术方提供的固定公网出口 IP。
5. 保存，等待配置生效后交给技术方接入。

这里应填服务器访问 Google 时的实际出口 IP；若使用代理／网关，须核对其出口。不要填写 `192.168.*` 等局域网地址，也不要选择“网站／HTTP referrers”限制——本系统使用服务器端 Web Service，网站来源限制不适用。[Google Maps 官方说明](https://developers.google.com/maps/faq)

如果没有固定出口 IP，请先让技术方确认部署方案，再确定限制方式；不要把未受限制的正式 Key 长期用于生产。

### 4. 设置预算与用量监控

1. **Billing → Budgets & alerts** 创建预算，范围限定本项目。
2. 按客户预算设置告警，例如 50%、80%、100%，确认通知邮箱有人接收。
3. 在 Places API 的 **配额（Quotas）** 页面检查可配置额度，初期结合业务量设置较低的可用配额，避免一次大批量任务消耗过多。
4. 上线初期每天核对 API 用量、错误及 Billing 费用。

预算告警只是通知，不会自动停止调用，也不是费用硬上限；配额是否可设、统计粒度和生效时间以 Google 控制台为准。[预算说明](https://docs.cloud.google.com/billing/docs/how-to/budgets)

### 5. 交给技术方接入并验收

Places Key 当前由技术方配置到 Beacon 服务器，不是在 Gmail 页面上传，也不需要客户粘贴进浏览器控制台。客户提供项目 ID、Key 和限制信息，技术方完成服务配置。

验收先使用一家已知门店，核对门店名称、地址、官网及电话；同时确认 Google 控制台有正常请求记录，无权限、结算或配额报错。一次失败不能直接说明门店没有资料，需区分查询结果与配置错误。

## 五、交付清单

| 项目 | 交付内容 | 推荐方式 |
|---|---|---|
| 项目归属 | Project ID、客户管理员、账单联系人 | 普通交付记录 |
| Gmail 客户端 | Web OAuth 原始 JSON | 客户自行上传 Beacon；确需代配时用双方约定的安全渠道 |
| Gmail 授权 | 客户本人在 Google 页面完成 | 不交付密码、验证码或 Token |
| 发布状态 | Internal 或 External；Testing 或 In production；审核状态 | 控制台截图，遮挡凭据 |
| Places Key | Key、允许 API、允许出口 IP | 安全渠道交给技术方服务器配置 |
| 费用 | 预算、告警邮箱及可配置配额 | 双方确认 |
| 验收 | 自有邮箱收信结果、单家 Places 查询结果 | 保存验收记录 |

客户端 JSON 内含 Client Secret，API Key 也属于凭据，不提交 Git，不放公开群聊、工单截图或公开文档。客户保留所有权；如需技术方协助，可授予最小必要项目权限，交付结束后复查并移除不再需要的访问。

## 六、常见问题

| 现象 | 优先检查 |
|---|---|
| Gmail 每隔约 7 天要求重新连接 | External 项目是否仍为 Testing；正式发布后重新授权 |
| `redirect_uri_mismatch` | Google 客户端中登记的回调是否与 Beacon 页面完全一致；是否选错客户端／项目 |
| `invalid_grant`／授权失效或授权码不可用 | 重新发起连接，不刷新或重复使用旧回调页；检查 Testing、撤销授权及账号变更，不应只归因于 Testing |
| 未验证应用／访问被阻止 | 发布与审核状态、测试用户、Workspace 管理员策略；按 Google 提示处理，不要求用户绕过组织限制 |
| JSON 上传不接受 | 是否下载了 Web application 客户端；是否误选 Desktop、服务账号或 Places Key |
| Places 403／PERMISSION_DENIED | API 是否启用、结算是否有效、Key 是否属于正确项目、允许 API 和实际出口 IP 是否匹配 |
| Places 429／RESOURCE_EXHAUSTED | 检查官方配额和请求速率，降低并发；核对项目是否被其他系统共用 |
| 有预算告警却仍产生费用 | 预算告警不会自动停用服务，需另外调整用量／配额或暂停业务调用 |

完成以上配置后，先联合验收，再开始正式批量业务。客户无需安装 Android Studio，也无需创建 Google 服务账号私钥来完成本指南中的两项配置。
