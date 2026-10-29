# AI 模型配置实施（2026-10-29）

用户批准“完整闭环，首版不做自动多模型调度或切换供应商”。仅本地实施，用户测试后自行提交推送。

## 配置与界面

设置增加「AI 模型」，管理员管理模型连接、默认模型与资料理解／菜单识别／文案生成三类用途。普通业务用户不接触凭据；原有功能按工作空间设置调用。连接包含供应商预设、接口协议、Base URL、模型 ID、只写 API Key、图片输入能力、JSON 模式、超时与启停。可保存未测试连接；测试失败保留具体原因，不强制放行或新增每日调用上限。

供应商预设：DeepSeek、OpenAI、Anthropic Claude、Gemini、通义千问、豆包、Kimi、智谱和自定义兼容接口。预设只提供起点，各区域／套餐／模型 ID 需按供应商控制台填写；模型列表支持读取与手工输入，不宣称任意模型均可处理图片。

## 运行与存储

- `ai_configuration` 保存不可变配置版本，PostgreSQL 中仅存加密 API Key。Fernet 主密钥位于数据卷 `ai/encryption.key`，文件权限600，备份必须同时保留数据库与该数据卷。下载接口禁止直接下载该目录。
- 无网页管理记录时继续使用环境配置；导入操作复制完整环境连接并加密。网页配置存在后不再静默回退到环境配置，实际来源在页面标明。
- 保存配置无须重启。后台批量／单家任务保存配置 revision；菜单自动研究保存相同引用。同步单次生成和重试固定调用配置，切换默认模型只影响新任务。停用或移除连接会阻止旧任务继续使用它。
- 当前环境配置保留旧方式。环境模式下变更环境仍需服务重启；迁入网页管理后使用持久化版本。
- 统一 `ai_runtime` 处理 Chat Completions、Responses 和 Anthropic Messages。Responses 使用结构化格式，Anthropic 使用约束工具结果，兼容接口按 JSON 模式与 Pydantic 再校验。供应商私有参数不发送给其他接口。
- 官网、经营识别、联系人筛选、公司订户证据、服务介绍整理、菜单、销售摘要、回复理解和英文起草均接入统一运行层。引用、人工核对、审批、发送与抑制检查继续由现有业务流程处理。
- 不自动切换供应商，不用 Fake 冒充真实分析。供应商失败保留已有业务结果和可重试原因。

## 诊断与验收

能力测试使用固定文本／结构化／图片样本，产生少量真实请求但不读取客户资料或发送消息。结果与当前配置绑定、刷新保留；配置修改后原结果作废。模型列表接口不支持时可手填。

最近100次调用展示供应商、连接／配置版本、模型、耗时、Token和脱敏错误，最多保留500次；不保留提示词、客户原文或密钥。真实价格随供应商及模型变化，首版不伪造费用估计。

迁移 `d178a0010001`，部署声明同时更新；不扩大未经验证的跨版本自动回滚范围。验收包括模拟三种协议、密钥不可回显、角色权限、失败持久化、用途分配、任务版本保护及设置页面模拟浏览器回归。

## 官方依据

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Gemini OpenAI 兼容接口](https://ai.google.dev/gemini-api/docs/openai)
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)
- [DeepSeek API](https://api-docs.deepseek.com/)
- [百炼区域 Base URL](https://help.aliyun.com/en/model-studio/base-url)
- [火山方舟 Base URL 与鉴权](https://docs.volcengine.com/docs/ark/base-url-and-authentication?lang=en)
- [Kimi API](https://platform.kimi.ai/docs/)
- [智谱开放平台](https://docs.bigmodel.cn/)

各模型是否启用、支持的输入与结构化能力，以配置后的能力测试及真实业务验收为准；模拟测试通过不等于所有供应商已真实联调。
