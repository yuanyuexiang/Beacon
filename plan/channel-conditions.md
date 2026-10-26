# 全渠道联系条件调整（2026-10-26）

## 目标与分层

联系人归属、销售推荐、具体动作的联系依据、执行能力分别判断。AI 从有引用的原文识别归属和用途；程序核验来源、日期、规则和拒收记录；平台连接及窗口仍由对应执行器检查。准备待办可以缺项，只有条件齐备的准备才能转换为可执行任务。

## 本轮实现

- 复用 communication_draft，增加 queued：用户显式加入准备待办才显示在沟通页，未加入的草稿不污染工作台。负责人及提醒沿用草稿字段；移出不删除资料，不产生外部消息。
- ChannelEligibility 新增 conditions JSON，逐项保存来源、说明、实际核对时间、到期时间与操作者。原 evidence 和人工记录保留。新增审核采用 channel-review:v1；发送入口共用复核，不因人工执行而跳过。
- 主动业务联系和客户请求回复分开。后者必须引用实际请求，并绑定门店已确认的具体内容 ID 和 hash；改文案后重新核对。该依据不能代替平台 API 窗口或推导长期营销同意。
- 邮箱允许引用明确职务邮箱事实，免费邮箱不一票否决；具名个人不套用通用邮箱自动路径。AI 运营关系可用原文证明，不只依赖固定句式；增加有证据的 CIO/SCIO/Scottish partnership 形式识别。仍不凭慈善机构、FSA 或域名推断公司身份。
- 邮件 AI 规则 v3 兼容仍有效的 v2 记录，原 fingerprint、复核到期和拒收检查保留；v1 不被静默升级。
- 详情、准备、沟通页共用联系条件组件；联系方式录入不再顺带写“允许”。旧人工审核 API 为已有调用方保留，不能清除或绕过已存在的结构化条件。

## 渠道矩阵

| 渠道 | 联系依据 | 执行能力 |
| --- | --- | --- |
| 邮件 | 公司订户及联系归属，或适用同意／既有客户依据；涉及个人信息记录处理依据 | Gmail 连接、发送开关和发送前检查保持独立 |
| 人工电话 | TPS／CTPS 来源、时间与结果，或针对本方的有效同意 | tel 链接，人工拨打和回填；无自动语音 |
| WhatsApp | 同意来源、主体及用途；不得凭手机号推断 | 本轮人工入口；没有增加 WhatsApp API |
| FB／INS | 本次消息适用依据 | 人工主页入口或现有已授权会话 API；API 窗口仍复核 |
| TikTok／LinkedIn | 本次消息适用依据 | 当前人工；未持有相应官方权限不假装可用 API |
| 联系表单 | 商务／供应商用途和本次提交依据 | 人工打开 HTTPS 表单，不自动提交 |
| 邮寄 | 业务地址、处理依据及拒收检查 | 显示地址供人工寄送，不购买邮资 |
| 其他社媒 | 明确平台及本次消息依据 | 已有平台链接，未新增自动接口 |

电话筛查的 28 天为本系统复核上限，不称作全部场景的法定期限。筛查结果由用户从真实服务导入信息或录入，不由模型伪造；本轮提供逐项录入，未对接付费 TPS 数据服务。结构化人工审核记录证明“操作者已核对”，不宣称系统已替用户向第三方验证。凭据、接入许可缺失不影响保存研究或待办。

## 历史兼容和验收

迁移 d176a0010001 为可逆加列；旧草稿 queued=false，旧条件为空。不得重写已发任务或自动批准未知渠道。系统不自动转换草稿、不发送客户消息、不自动发布。

验证：后端全量 pytest／Ruff／mypy；重点 test_channel_conditions.py、test_admission.py、test_communication.py、test_assignment.py 及 Gmail／Meta 入口；前端 typecheck／lint／test／build；模拟 scripts/verify_channel_conditions_ui.py 与既有详情／沟通回归。

## 参考依据

- [ICO B2B 营销](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/)
- [ICO 电话营销](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guide-to-pecr/electronic-and-telephone-marketing/telephone-marketing/)
- [ICO 电子消息营销](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guidance-on-direct-marketing-using-electronic-mail/how-do-we-comply-with-the-pecr-electronic-mail-marketing-rules/)
- [WhatsApp 政策](https://business.whatsapp.com/policy)
- [Meta Messenger 官方 API](https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api)
- [TikTok Business Messaging](https://business-api.tiktok.com/portal/bm-api/education-hub)
- [LinkedIn Communication APIs](https://learn.microsoft.com/en-us/linkedin/shared/integrations/communications/overview)
