# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

与用户交流请使用中文。

## 项目状态

Beacon 目前处于规划阶段，还没有代码、构建系统或测试。依据是方案文档 `欧洲餐厅菜单设计与印刷获客系统方案.md` 和 `plan/` 目录：`plan/roadmap.md`（里程碑、验收、测试策略）、`plan/tasks.md`（逐条任务与进度）、`plan/decisions.md`（决策记录）。设计或开发任何功能前先阅读方案和 roadmap；开始或完成任务时更新 tasks.md 的复选框与进度行；代码出现后，把真实的构建、测试、lint 命令补充到本文件。

## 系统用途

为在欧洲提供餐厅菜单设计与印刷服务的客户建设主动获客系统，产品名暂定“餐厅菜单销售线索系统”（Restaurant Menu Sales Intelligence）。流程：

发现餐厅 → 采集官网、菜单和多渠道联系方式 → AI 菜单分析 → 获客评分 → 改版对比图和各渠道话术 → 多渠道跟进编排 → 回复汇总与分类 → 销售接管

MVP 范围：1 个国家、3～5 个城市、1 种语言、2～3 类餐厅，试运行 6 周（筛选约 1000 家，受控触达约 300 家）。明确不做：多国覆盖、用非官方工具自动群发 WhatsApp/Instagram、短信群发、WhatsApp Business API（第二阶段评估）、AI 自主报价、多租户计费、无人工审核的整套菜单自动生成。

## 计划技术架构

| 层级 | 技术 |
|---|---|
| 前端（线索、审批队列、销售工作台、看板） | Next.js + Ant Design |
| 后端 API、权限、审计 | Python FastAPI |
| 数据库 | PostgreSQL |
| 任务编排（采集、同步、分析、发送、跟进、通知） | Redis + Celery + Celery beat（不用 n8n 作核心：与 Celery 重复，且许可证限制托管给客户） |
| 开放数据层 | DuckDB + overturemaps-py 读取 Overture；定时同步 FSA、Companies House、SIRENE；quackosm 读 OSM |
| 官网采集与提取 | httpx，必要时 Crawl4AI/Playwright；extruct、phonenumbers、email-validator |
| 菜单解析 | HTML 取文本、PDF 用 Docling、图片用多模态大模型或 PaddleOCR，Instructor 按结构提取 |
| 大模型 | 可替换的模型接口，不要写死某家厂商 |
| 邮件收发与线程关联 | Google Workspace 或 Microsoft 365 |
| WhatsApp、Instagram | WhatsApp Business 应用、Instagram 企业账号（销售一键发送，系统生成 `wa.me` 预填链接和素材） |
| 改版对比图和实物样品 | HTML 模板渲染为 PDF/PNG，不用 AI 直接生成整张菜单图片 |
| 文件存储（菜单、分析结果、对比图、样品） | S3 兼容存储 |
| 部署 | Docker Compose |

设计原则：用固定、可审计的工作流，不做自主 Agent。只把模糊任务交给大模型：菜单分析、各渠道文案、翻译和回复分类。

多渠道原则：**系统自动准备，销售一键发送。** 邮件由系统自动发送；WhatsApp、Instagram、电话和寄样品由系统生成每日销售任务清单，销售逐条确认后执行，每个账号每天发送量有上限。

## 约束实现的业务规则

- **不虚构：** 各渠道内容只能引用系统实际检测到的菜单问题，不得虚构到店经历、案例、本地地址或客户身份。
- **数据来源：** 优先使用许可允许存储的开放数据和政府登记（Overture、FSA、Companies House、SIRENE、FSQ OS Places、OSM），联系方式和菜单从餐厅官网补全。Google Places 只能存 place_id，评分等字段只在详情页实时拉取、放缓存不入主表。不使用 Google Maps 抓取工具或数据集，外卖平台不抓菜单。数据库要有字段级的来源、许可和是否可存储记录。每条线索和每个联系方式都要记录来源和采集时间（GDPR 审计需要）。
- **评分权重：** 菜单质量问题 30、经营活跃度 20、预计客单价 15、评论数与规模 15、联系方式完整度 10（按电话、WhatsApp、Instagram、决策人等可用渠道计算，不只看邮箱）、近期改版迹象 10。初始触达阈值 70 分。评分只用于排序，不得展示为成交概率。
- **默认多渠道节奏：** 第 0 天 WhatsApp（没有则 Instagram）+ 高分线索寄实物样品，第 2 天邮件，第 5 天电话，第 10 天 Instagram 或邮件，第 14 天邮件收尾。缺少的渠道自动跳过或替换。任一渠道收到人工回复、退订或拒绝，立即停止所有渠道的跟进。
- **回复分类 → 动作：**
  - 有兴趣/询价/索要案例 → 停止所有渠道跟进并通知销售
  - 希望稍后联系 → 暂停到指定日期
  - 已有供应商/暂不需要 → 结束序列
  - 拒绝/退订 → 永久加入禁止联系名单，所有渠道停止
  - 自动回复 → 识别并处理
  - 退信/号码无效 → 标记该渠道无效，改用其他渠道
  - 无法判断 → 进入人工审核
- **回复来源：** 邮件回复自动接收；WhatsApp/Instagram 回复由销售转发或录入；电话结果由销售在任务中记录。
- **合规：** 每次触达说明发送方身份并提供清晰的退订方式。保存模板版本、发送记录、退订记录和人工审核日志。发送规则、频率和保留期限按国家可配置。优先使用通用商业邮箱，不使用购买的个人邮箱名单。
- **发送信誉：** 使用独立发送域名或子域名并配置 SPF/DKIM/DMARC，从低发送量逐步提升，退信率或投诉率异常时自动暂停。
- **WhatsApp/Instagram 账号安全：** 不自动批量发送，每账号每日上限（起步 20～30 条），内容必须个性化，账号出现限制或举报时暂停该账号任务。
- **第一阶段流程：** AI 生成首次触达内容 → 人工批量审核 → 邮件系统发送、WhatsApp/Instagram 销售一键发送 → 系统编排后续跟进任务。
- **菜单分析输入：** 网页、PDF 和图片。分析结果必须支持人工修正。
- **开源依赖许可证：** 不引入 AGPL/GPL 或限制托管的依赖（如 Firecrawl、PyMuPDF、listmonk、Mautic、NocoDB、Carbone 社区版），不用非官方 WhatsApp 自动发送库。
