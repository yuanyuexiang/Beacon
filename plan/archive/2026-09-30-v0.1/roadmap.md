# Beacon 路线图（Roadmap）

依据：《欧洲餐厅菜单设计与印刷获客系统方案》、CLAUDE.md。覆盖标准 MVP（一个国家、3～5 个城市、一种语言、2～3 类餐厅），试点默认英国。工作量对应方案第九节的 34～50 人日。

本文件回答“做什么、分几步、怎么验收、怎么测”。逐条任务与进度见 [tasks.md](tasks.md)，决策记录见 [decisions.md](decisions.md)。

状态：草稿 v0.1，2026-09-30，待审核。审核后按第十一节的决策项定稿，再开始 M0。

---

## 一 目标与验收口径

编码目标：交付一套可审计的固定工作流系统，完成“发现餐厅 → 采集 → 菜单分析 → 评分 → 内容生成 → 多渠道跟进 → 回复分类 → 销售接管”。

验收口径（与方案第十一节一致，不承诺成交数量）：

| 维度 | 验收标准 |
|---|---|
| 功能稳定 | 六周试运行期间核心任务链（同步、采集、分析、发送、跟进）无需人工干预连续运行 |
| 数据可追溯 | 每个线索字段、每个联系方式能查到来源、许可、采集时间；Google 字段不进主表 |
| 触达可控 | 所有首次触达经人工审批；WhatsApp/Instagram 每账号日上限生效；任一渠道回复后其余渠道停止 |
| 漏斗可统计 | 看板能按渠道、城市、餐厅类型、模板输出名单→触达→回复→预约→报价→成交 |

---

## 二 仓库结构与技术选型

单仓库（monorepo），Docker Compose 一键启动。

```
Beacon/
├── backend/                 # Python 3.12 + FastAPI
│   ├── app/
│   │   ├── core/            # 配置、日志、权限、审计
│   │   ├── db/              # SQLAlchemy 2.x 模型、Alembic 迁移
│   │   ├── api/             # 路由（按模块分文件）
│   │   ├── services/
│   │   │   ├── discovery/   # FSA、Overture、Companies House、OSM 同步与实体匹配
│   │   │   ├── enrichment/  # 官网采集、联系方式提取、校验
│   │   │   ├── menu/        # 菜单获取、解析、AI 分析
│   │   │   ├── scoring/     # 获客评分
│   │   │   ├── content/     # 各渠道文案、对比图、样品
│   │   │   ├── outreach/    # 跟进编排、邮件发送、每日任务清单、限额
│   │   │   ├── replies/     # 回复接收、分类、动作
│   │   │   └── dashboard/   # 漏斗统计
│   │   ├── llm/             # 可替换模型接口 + Instructor 结构化输出
│   │   └── tasks/           # Celery 任务与 beat 调度
│   ├── tests/               # 见第五节
│   └── pyproject.toml
├── frontend/                # Next.js 15 (App Router) + Ant Design 5 + TypeScript
├── templates/               # 对比图、样品的 HTML 模板；邮件 MJML 模板
├── infra/                   # docker-compose.yml、.env.example、Caddy/Nginx
├── scripts/                 # 试运行校准脚本、数据导入脚本
├── plan/                    # 路线图、任务清单、决策记录
│   ├── roadmap.md
│   ├── tasks.md
│   └── decisions.md
├── docs/                    # 接口文档、运维手册
├── 欧洲餐厅菜单设计与印刷获客系统方案.md
└── CLAUDE.md
```

工具链：

| 用途 | 选型 |
|---|---|
| Python 依赖管理 | uv |
| 代码规范 | ruff（lint + format）、mypy（strict 逐步开启） |
| Python 测试 | pytest、pytest-asyncio、respx（模拟 httpx）、testcontainers（PostgreSQL、Redis） |
| 前端包管理 | pnpm |
| 前端测试 | Vitest + Testing Library；Playwright 做端到端 |
| 数据库迁移 | Alembic |
| 许可证扫描 | pip-licenses + license-checker（CI 中阻断 AGPL/GPL） |
| CI | GitHub Actions |

大模型接口：`app/llm/` 定义 `LLMProvider` 协议（`complete`、`complete_structured`、`vision`），提供 Anthropic、OpenAI 兼容两种实现和一个 `FakeProvider` 供测试。任何业务代码只依赖协议，厂商通过配置切换。

---

## 三 核心数据模型（首版）

只列关键表，字段在 M0 的迁移中细化。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `restaurant` | id、名称、地址、城市、国家、菜系、官网、法律形式、新开业信号及日期、google_place_id、状态 | 线索主表。**不含**评分、评论数、价位等 Google 字段 |
| `restaurant_source_record` | restaurant_id、source（FSA/Overture/CH/OSM/FSQ）、source_id、数据版本、原始 JSON、匹配置信度 | 多源匹配记录，一对多 |
| `contact` | restaurant_id、渠道（phone/whatsapp/instagram/facebook/email/contact_form/linkedin）、值、置信度（WhatsApp 三级）、状态（valid/invalid/suppressed）、is_personal | 每条联系方式一行 |
| `field_provenance` | entity_type、entity_id、field、source、source_url、license、storable、collected_at、expires_at | 字段级来源与许可，所有可存字段必须有记录 |
| `decision_maker` | restaurant_id、姓名、职务、来源、合法利益评估标记 | 老板/负责人 |
| `menu_asset` | restaurant_id、类型（html/pdf/image）、原始 URL、S3 key、抓取时间 | 菜单文件 |
| `menu_analysis` | menu_asset_id、结构化菜品 JSON、检测到的问题列表（每项带 issue_code、证据）、模型与提示词版本、人工修正记录 | 分析结果，支持人工修正 |
| `lead_score` | restaurant_id、六个维度分、总分、计算时间、权重版本 | 只用于排序 |
| `content_piece` | restaurant_id、渠道、语言、正文、引用的 issue_code 列表、模板版本、审批状态、审批人、审批时间 | 各渠道话术 |
| `asset_file` | restaurant_id、类型（对比图/样品 PDF/样品 PNG）、S3 key | 生成的文件 |
| `sequence` | restaurant_id、节奏模板版本、状态（active/paused/stopped/completed）、暂停到、停止原因 | 每家餐厅一条跟进序列 |
| `sequence_step` | sequence_id、天数、渠道、计划时间、状态（pending/sent/skipped/replaced）、替换原因 | 展开后的步骤 |
| `outreach_event` | sequence_step_id、渠道、账号、发送时间、内容快照、模板版本、message_id、送达状态 | 触达记录，不可修改 |
| `sales_task` | sequence_step_id、销售、日期、渠道、预填链接、状态、执行结果、备注 | 每日任务清单 |
| `channel_account` | 渠道、账号标识、每日上限、当日已发、状态（active/paused）、暂停原因 | 发送账号与限额 |
| `reply` | restaurant_id、渠道、原文、来源（auto/forwarded/manual）、分类、置信度、摘要、人工审核标记 | 回复 |
| `suppression` | 联系方式值或 restaurant_id、原因（unsubscribe/reject/dk_marker）、时间、来源 | 禁止联系名单，永久 |
| `template` | 渠道、语言、版本、正文、生效时间 | 模板版本管理 |
| `country_policy` | 国家、各渠道是否允许、频率上限、保留天数、法律形式限制 | 按国家配置 |
| `audit_log` | 操作人、动作、对象、前后快照、时间 | 审计 |

数据库约束（在迁移中落实，并有测试覆盖）：

- `restaurant` 表不允许出现 rating、review_count、price_level 列；实时字段只进 Redis 缓存。
- `contact.value` 与 `suppression` 联合校验：写入 `outreach_event` 前必须查禁止名单。
- `field_provenance.storable = false` 的字段不得写入主表。

---

## 四 开发阶段与里程碑

每个里程碑给出目标与验收标准，逐条任务在 [tasks.md](tasks.md) 中按里程碑分组并跟踪状态。工作量为估算人日。

### M0 项目骨架与基础设施（3 人日）

目标：可运行的空系统，所有基础设施、模型表、CI 与权限就绪。

任务清单见 [tasks.md](tasks.md)。

验收：`docker compose up` 后前后端可登录；CI 全绿；迁移可升降。

### M1 开放数据同步与实体匹配（5 人日）

目标：从开放数据建立英国餐厅底库，多源匹配去重，每条记录带来源与许可。

任务清单见 [tasks.md](tasks.md)。

验收：伦敦 500 家 FSA 抽样跑通，输出匹配率报告；重复率 < 2%（人工抽检 100 条）。

### M2 官网采集与多渠道联系方式（6 人日）

目标：从官网补全多渠道联系方式与法律形式，决定每家餐厅允许的渠道。

任务清单见 [tasks.md](tasks.md)。

验收：500 家抽样输出各渠道覆盖率；抽检 50 条联系方式准确率 ≥ 90%。

### M3 菜单获取、AI 分析与评分（6 人日）

目标：拿到菜单、结构化提取、检测真实问题、算出可排序的评分，支持人工修正。

任务清单见 [tasks.md](tasks.md)。

验收：30 份 golden 菜单（10 HTML、10 PDF、10 图片）提取准确率见第五节；评分可复算且幂等。

### M4 各渠道内容、对比图与样品（5 人日）

目标：基于真实问题生成各渠道文案、对比图和可印刷样品，经人工审批。

任务清单见 [tasks.md](tasks.md)。

验收：100 条生成文案人工抽检，虚构率 0；对比图在 3 种品牌风格模板下正确渲染。

### M5 邮件发送与多渠道跟进编排（7 人日）

目标：按可用渠道自动编排跟进，邮件自动发、其余渠道进销售任务清单，限额与停发生效。

任务清单见 [tasks.md](tasks.md)。

验收：模拟 300 家餐厅的序列展开，每家步骤与预期节奏一致；退订后 1 分钟内所有渠道待发步骤取消。

### M6 回复分类与销售工作台（5 人日）

目标：各渠道回复汇总分类并触发动作，销售在工作台接管，看板出漏斗。

任务清单见 [tasks.md](tasks.md)。

验收：100 条回复样本分类准确率 ≥ 90%，退订类召回率 100%；看板数字与数据库聚合一致。

### M7 测试收口、部署与试运行准备（4 人日）

目标：测试收口、上线试运行环境、完成第一周校准。

任务清单见 [tasks.md](tasks.md)。

验收：合规清单（5.6）全部通过；性能基线（5.5）达标；试运行环境可用；500 家校准报告产出。

合计 41 人日，处于方案 34～50 人日区间。

依赖关系：M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7。M4 与 M5 的节奏引擎可并行；前端页面随各里程碑同步交付。

---

## 五 测试策略

### 5.1 分层与覆盖目标

| 层 | 范围 | 工具 | 目标 |
|---|---|---|---|
| 单元 | 提取规则、评分、节奏展开、状态机、分类动作映射、反虚构校验器 | pytest | 行覆盖 ≥ 85%，核心规则分支 100% |
| 集成 | 数据库读写、Celery 任务链、外部接口（respx 模拟）、S3 | pytest + testcontainers | 每个 service 至少一条主路径和一条失败路径 |
| 契约 | LLM 结构化输出 schema、OpenAPI 快照、前后端接口 | pydantic、schemathesis | schema 变更必须更新快照 |
| 端到端 | 登录 → 线索 → 审批 → 任务清单 → 回复录入 → 接管 | Playwright | 5 条关键用户旅程 |
| 模型评测 | 菜单提取、问题检测、文案、回复分类 | golden set + 自定义评测脚本 | 见 5.3 |
| 合规 | 第 5.6 节清单 | pytest 专用标记 `@compliance` | 全部通过，CI 阻断 |
| 性能 | 采集吞吐、序列展开、看板查询 | locust / pytest-benchmark | 见 5.5 |

### 5.2 测试数据与夹具

存放于 `backend/tests/fixtures/`，全部为可重复的本地文件，不依赖真实网络：

- 官网样本 20 个：含 JSON-LD、页脚 `wa.me`、Impressum、联系表单、纯图片站、JS 渲染站、robots 禁抓站、个人邮箱站。
- 菜单样本 30 份：HTML 10、PDF 10（含扫描件）、图片 10（含模糊照片）；每份附人工标注的菜品、分类、价格、语言、问题列表。
- 回复语料 100 条：七类各 ≥ 10 条，含英语假期自动回复、退信、模糊表达、多语种。
- FSA / Overture / Companies House 小样本（各 200 条），含重复与近似重复。
- 国家策略：英国默认、一个虚构国家用于测试渠道禁止规则。

LLM 调用在测试中默认使用 `FakeProvider`（返回夹具中的预录响应）；模型评测单独运行，需显式设置真实厂商密钥，不进普通 CI。

### 5.3 模型评测指标

| 任务 | 指标 | 目标 |
|---|---|---|
| 菜品提取 | 菜品名 + 价格配对 F1 | HTML ≥ 0.95，PDF ≥ 0.90，图片 ≥ 0.80 |
| 语言检测 | 准确率 | ≥ 0.98 |
| 问题检测 | 每个 issue_code 的精确率 / 召回率 | 精确率 ≥ 0.85（宁可漏检不可误报） |
| 文案反虚构 | 校验器拦截率 + 人工抽检虚构率 | 人工抽检 0 |
| 回复分类 | 七类宏平均 F1；退订/拒绝召回率 | F1 ≥ 0.85；退订召回 1.0 |

评测脚本输出对比表，提示词或模型变更必须附评测结果。

### 5.4 关键单元测试清单

- 电话归一化：英国各种写法、国际前缀、分机号、假号码。
- WhatsApp 置信度：`wa.me` 链接 → 已公开；手机号段 → 可能；座机 → 否。
- 邮箱：个人域剔除、MX 失败、catch-all 分组、法定页优先级。
- 实体匹配：同名不同址、同址不同名、邮编缺失、名称含 “The”/“Ltd”。
- 评分：权重可配置、维度封顶、联系方式完整度按渠道计分、无菜单时的降级。
- 节奏展开：全渠道、缺 WhatsApp、缺 Instagram、只有电话、个体经营者（仅电话、样品、联系表单）、高分寄样品。
- 状态机：每种回复类型对应动作；暂停到期恢复；重复回复幂等；停止后不再产生任务。
- 限额：日上限、跨日重置、账号暂停后任务清单不再包含该账号。
- 禁止名单：写入后任何渠道不得再产生 `outreach_event`；名单匹配大小写与格式无关。
- 反虚构校验器：引用未检测问题、提到“上次到店”、虚构案例名、本地地址均被拒绝。

### 5.5 性能基线

| 场景 | 目标 |
|---|---|
| 官网采集 | 1000 个域名在 8 小时内完成（受每域名 1 rps 限制，并发 ≥ 50） |
| 菜单分析 | 单份 PDF ≤ 60 秒，图片 ≤ 90 秒（含模型调用） |
| 序列展开 | 300 家 ≤ 10 秒 |
| 看板查询 | 六周数据量下 ≤ 2 秒 |
| 每日任务生成 | ≤ 1 分钟 |

### 5.6 合规测试清单（CI 阻断）

- 每封邮件、每条 WhatsApp/Instagram 文案含发送方身份与退订方式。
- 退订、拒绝后：`suppression` 有记录，所有渠道 pending 步骤取消，后续任何渠道不再触达。
- `restaurant` 表无 Google 评分、评论数、价位列；Redis 缓存条目有过期时间。
- 所有主表可存字段在 `field_provenance` 有对应记录，`storable=false` 不入库。
- 个体经营者（sole trader）只允许电话、实物样品和联系表单，不生成邮件、WhatsApp、Instagram 步骤（与方案第三节法律形式规则一致）。
- 国家策略禁用的渠道不生成步骤。
- 模板版本、发送记录、审批日志不可删除（软删除 + 审计）。
- 数据保留：超过 `country_policy.retention_days` 的记录由定时任务匿名化，并有测试。
- 依赖许可证扫描：AGPL/GPL 出现即失败；黑名单包含 Firecrawl、PyMuPDF、listmonk、Mautic、NocoDB、Carbone、Baileys、whatsapp-web.js。

### 5.7 试运行验证（M7 后第 1 周）

M1、M2 验收使用同一批伦敦 500 家 FSA 抽样作开发期检查；本节是试运行第一周的正式校准，用同一脚本重跑并出报告。

脚本 `scripts/pilot_calibration.py` 对伦敦 500 家 FSA 记录执行：匹配 Overture → 抓取官网 → 提取联系方式与菜单，输出：

- Overture 匹配率、官网抓取成功率；
- 电话、WhatsApp、Instagram、邮箱、联系表单、菜单各自覆盖率；
- 菜单类型分布（HTML / PDF / 图片）。

结果用于调整评分权重与默认节奏，调整前后各存一份权重版本。

---

## 六 CI/CD 与分支策略

- 分支：`main` 受保护；功能分支 `feat/<里程碑>-<主题>`；每个里程碑一个合并 PR。
- CI（每次 PR）：ruff → mypy → pytest（单元 + 集成 + 合规）→ vitest → Playwright 冒烟 → 许可证扫描 → Docker 构建。
- 模型评测：手动触发或提示词变更时触发。
- 部署：`main` 合并后构建镜像，手动发布到试运行环境。
- 密钥：`.env` 不入库，`.env.example` 维护全部变量；CI 使用 GitHub Secrets。

---

## 七 定义完成（Definition of Done）

一个任务视为完成需同时满足：

1. 代码合并到 `main`，CI 全绿。
2. 对应单元与集成测试已写，覆盖主路径和至少一条失败路径。
3. 涉及数据字段的改动有 `field_provenance` 处理和迁移。
4. 涉及触达的改动通过合规测试。
5. 接口变更更新 OpenAPI 快照与前端类型。
6. CLAUDE.md 或 docs 中的命令、配置说明同步更新。

---

## 八 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 官网 JS 渲染比例高，Playwright 成本大 | 采集慢 | 静态优先，回落有配额；试运行第一周测比例 |
| 图片菜单识别质量不稳定 | 问题误报 → 文案不可信 | 精确率优先；低置信度问题不进文案；人工修正入口 |
| Smartlead/Instantly 接口变更或不可用 | 邮件链路中断 | 发送层抽象接口，Gmail 路径作备选 |
| 模型厂商切换导致结构化输出漂移 | 分类和提取退化 | 契约测试 + 评测基线，切换前必须跑评测 |
| Instagram 官方接口权限申请周期长 | 核验功能延后 | 核验作为可选步骤，不阻塞主流程 |
| 合规规则在法律确认后变化 | 节奏与渠道规则改动 | 全部规则放 `country_policy` 配置，不写死 |

---

## 九 明确不做（与方案第七节一致）

多国覆盖、非官方 WhatsApp/Instagram 自动发送、短信、WhatsApp Business API、AI 自主报价、多租户计费、代理分销、无人工审核的整套菜单生成。计划中任何任务涉及以上内容均视为范围外。

---

## 十 里程碑时间表（按 1 名全职开发估算）

| 里程碑 | 人日 | 累计 |
|---|---:|---:|
| M0 骨架 | 3 | 3 |
| M1 数据同步与匹配 | 5 | 8 |
| M2 官网采集 | 6 | 14 |
| M3 菜单分析与评分 | 6 | 20 |
| M4 内容与样品 | 5 | 25 |
| M5 跟进编排与邮件 | 7 | 32 |
| M6 回复与工作台 | 5 | 37 |
| M7 收口与试运行准备 | 4 | 41 |

两名开发时，M1/M2 与前端骨架、M4 与 M5 可并行，日历周期约缩短 30%。

---

## 十一 需要你决策的事项

1. 试点国家默认英国、城市伦敦优先，是否确认？
2. 邮件发送：试点期用 Smartlead / Instantly 接口，还是直接自研 Gmail / Microsoft Graph？
3. 大模型默认厂商与图片菜单的处理方式（多模态模型优先还是 PaddleOCR 优先）？
4. 前端范围：MVP 第一期做完整 Ant Design 工作台，还是先做审批队列 + 任务清单 + 看板三页？
5. 测试覆盖率目标 85% 是否接受，还是只对核心规则模块要求？
6. 工作量 41 人日是否认可，是否需要压缩到验证版（人工导入名单、去掉 M1 自动同步）？
7. 是否引入 Smartlead 等第三方前先做许可证与数据处理协议（DPA）确认？
8. Instagram Business Discovery 核验是否纳入第一期？

审核意见请直接批注在本文件或在对话中逐条回复；定稿后的结论记入 [decisions.md](decisions.md)。
