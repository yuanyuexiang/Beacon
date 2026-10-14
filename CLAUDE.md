# CLAUDE.md

与用户交流请使用中文。

## 当前状态与依据

Beacon 已完成 T0/T1 技术探索（Islington 60 家抽样，5 份菜单，见 `plan/exploration.md`）和 `plan/development.md` 的 D1～D10 最小工具（apps/api 57 个测试、apps/web 工作台已构建）。V 第一批已完成（`plan/validation-report-v1.md`：50 家，M/N=10/50，I/M=3/10），DeepSeek 视觉转录已评测。下一步：真人计时的第二批（人工基线），以及条件齐备后的 B。研究脚本在 `scripts/`，受控数据在 `data/`（已忽略，不提交）。当前未触达任何餐厅。

先阅读 `AGENTS.md`、`欧洲餐厅菜单设计与印刷获客系统方案.md`、`plan/roadmap.md`、`plan/development.md`、`plan/validation.md` 与 `plan/exploration.md`。任务状态在 `plan/tasks.md`，决策在 `plan/decisions.md`；开始/完成跟踪任务时同步更新。

`plan/archive/` 是历史快照；`reports/` 与 `research_notes/` 是研究输入，不能覆盖当前方案。研究中的“实测”若无可复现产物，应标为未在本仓库复核。汇报 PPT 尚未同步当前版本，不能直接作为当前承诺对外使用。

## 产品与当前范围

目标是减少菜单设计与印刷业务的线索研究、素材准备时间，并验证有效意向与成本。约 10 家技术探索后即可开发最小工具，再用约 50 家新候选扩大验证；人工商业验证可并行，不作为开发前置；下一步从 T0/T1 开始技术探索，国家已确定为英国；建议 FSA 公开名录底表，城市、样本、经营参数和负责人待落实。

首版保留名单获取（FSA 同步 + Overture 补官网 + 规则预筛，用户无自有名单；CSV 导入备用）、联系方式查找（官网与 Overture 的邮箱/电话/WhatsApp/社媒/联系表单，可批量自动记录或人工勾选，只记录，准入保持 unknown，D36/D38）、菜单分析与证据、人工审核、一个局部示例模板、人工联系任务及结果。Google Places 只给单家实时价格和照片参考，人工确认关联，仅保存 Place ID 与审核元数据（D41）；Exa 只给单家官网候选，人工核对地址与商家运营方、填写依据后保存官网及来源（D40）；Companies House 只给主体候选（官网披露的公司编号、注册邮编、店名检索三路合并），由人工确认（D34/D35，已真实调用验证，候选正确性未经人工核对）；暂缓 Companies House 主体自动判断、复杂评分、自动跟进、完整 CRM、生产印刷文件、多国、多租户。

取消旧六维评分和 70 分门槛，以目标类型、人工确认问题和至少一个允许渠道建立可联系集合。旧 41 人日及报价是历史估计，不作承诺。

## 实施原则

- 固定、可审计流程；模糊任务交模型，事实和对外内容由人确认。
- 桌面阶段使用现有工具、记录表与必要脚本，不先搭完整系统。
- 采用 Monorepo：`apps/api/` 为模块化 Python 后端，`apps/web/` 为前端，`packages/api-client/` 按需生成；目录与边界见 `plan/development.md`。
- 开发时优先 FastAPI + PostgreSQL；需要队列再用 Celery + Redis，需要 UI 再用 Next.js + Ant Design；不用 n8n 作重复核心。
- 实际模型 provider 为 DeepSeek（`deepseek-flash`，已真实评测，`plan/model-eval-v1.md`）+ FakeProvider；Anthropic 适配器保留未验证。接口可替换；模型结果一律 needs_review；模型只用于图片与图片 PDF，HTML/文本 PDF 用规则引擎。密钥只放 `apps/api/.env`。
- 模板生成局部样稿；菜名、价格需逐项核对，不用文生图生成整张菜单。
- Docker 全套：`docker compose -f infra/docker-compose.yml up -d --build`（含 web、api 与自动迁移；测试 `--profile test run --rm api-test`）。后端本机命令（已实测）：`docker compose -f infra/docker-compose.yml up -d postgres`；`cd apps/api && uv sync && uv run alembic upgrade head && uv run pytest && uv run ruff check . && uv run mypy app tests`。前端：`pnpm install && pnpm --filter beacon-web typecheck && pnpm --filter beacon-web test && pnpm --filter beacon-web build`。完整清单见 `AGENTS.md`，操作流程见 `docs/操作手册.md`。
- 研究脚本运行方式见 `plan/exploration.md` 六（`uv run --python 3.12 --no-project [--with pdfplumber] scripts/<name>.py`）；系统 Python 3.9 不用于抓取。

## 必须落实的边界

- 联系方式可用与渠道允许使用分别记录；`unknown` 不放行。主体未知不推断为公司。
- WhatsApp 不默认冷触达，记录 opt-in 证据；人工点击和每日限额不能替代授权。电话按目标市场规则筛查，英国包括 TPS/CTPS。Instagram、联系表单及样品邮寄当前暂缓。
- 所有对外内容先审核，修改后重新审核；不虚构到店经历、案例、身份、地址或菜单问题。
- 问题附来源和位置证据；不推断菜品利润、过敏原/素食成分，不拿缺双语作确定缺陷，不比较未取得的外卖菜单。
- 人工回复先暂停，拒绝/退订进入抑制记录。停发从系统收到/录入事件起计，不承诺系统实时看到人工平台回复。
- 未来自动发送需发送前复核准入/审批/抑制，处理重复事件、未知发送结果和竞态；外部已提交消息不承诺撤回。
- Google Places 作为人工触发的可选实时补充（D41）：只持久化 Place ID 与审核元数据；价格和照片不入证据库、不进模型。营销衍生用途仍需逐项确认适用许可，TTL 不是许可。
- 不提交真实联系人、凭证或菜单证据；按数据类别设保留期，抑制记录仅保留必要信息，不无限期保留原文。
- 项目依赖政策排除 AGPL/GPL、限制当前用途的托管组件和非官方 WhatsApp 群发库；核查版本与用途，不将包名列表当法律结论。

## 验证与完成

区分流程已设计、桌面验证已运行、商业效果已验证。没有名单和结果，不勾选验证任务。当前测试人工任务、审批与抑制，未来接入自动发送才测试发送超时、对账和竞态。关键规则测试优先于全局覆盖率；保留独立验收样本，报告实际分子/分母，不把样本零错误当线上保证。

T0/T1 只需研究范围、来源/数据条件、执行人和研究预算，不等待经营毛利或销售账号。T1 跑通后按 D1～D10 时间盒交付；成本分 setup/processing/outreach，人工与工具同质量对照。

真实联系须具备经营身份、预算、审核负责人、销售负责人、逐条渠道准入与明确执行安排。用户接受方案方向不自动授权代发营销消息。

Google Maps 菜单测试例外（D43，2026-10-10 用户明确授权）：单家 Playwright 探针允许在受控 data 目录保存测试菜单图片；当前不接正式资产与模型，也不自动批量运行。College Bar 有窗口自动链路已验证；后台模式仍受限，多家与多图验证后再决定界面集成，见 [测试记录](plan/maps-menu-probe-2026-10-10.md)。

D44（2026-10-11）：Places websiteUri 经人工核对后采用；官网菜单发现最多读取 5 个 HTML 页面，PDF 优先，人工确认后复用现有抓取/分析。不依赖 Google 登录；Maps Playwright 仍仅研究脚本。见 [操作手册](docs/操作手册.md#places-官网与官方菜单d44)。

D45（2026-10-11）：单家 AI 自动补全官网与菜单已接入。真实 DeepSeek 判断 + 程序原文/地址检查，错误引用修正至多一次；匹配明确自动采用与导入，异常复核，新分析 needs_review。任务使用单 API worker 的 BackgroundTasks，状态在 lead.raw，重启后需重跑；hash 去重并保留已有审核。Google 价格/照片仍不送模型，批量未开放。见 [实施与限制](plan/development.md#d45ai-自动补全官网与菜单施工计划2026-10-11)。

D46（2026-10-11，用户授权）：单家 Maps 菜单探针已接工作台按钮、受控资产与真实模型转录，扩展 D43/D44 例外。专用执行器主动连接 API，核对名称/地址/邮编、菜单区前 5 张、hash 去重、异常提示；已有审核保留。未登录已有会话可获取，全新有界面/无头会话仍受限。运行命令见 [操作手册](docs/操作手册.md#google-maps-菜单获取d46)，不开放批量、不自动登录。


D47（2026-10-12 用户授权实施）：扩展此前“系统不发送”边界，Gmail 独立容器支持凭据管理、完整邮件预览确认、单家发送回填、已发送线程回复头同步及审批后批量队列；其他渠道仍人工。发送和批量队列默认暂停，执行前复核准入/审批/抑制，未知结果不自动重试。施工步骤见 [Gmail 服务计划](plan/gmail-service.md)。本次开发不授权向客户发送测试邮件。

Gmail 服务配置：首次 Compose 启动前运行 `python3 scripts/configure_gmail_service.py`；启动后可用 `python3 scripts/configure_gmail_service.py --import-opc` 导入本机已有授权（不发送邮件）。新增验证命令 `cd services/gmail && uv sync --python 3.12 && uv run pytest -q && uv run ruff check gmail_service tests`。详细步骤见 [Gmail 服务操作](docs/Gmail邮件服务.md)。


后续 TK、FB、INS、LIN 渠道开发先阅读 [社媒渠道接入与后续开发指南](plan/social-channel-integration.md)。D48 首期已实现 Meta 独立 HTTP 服务、FB／INS 普通文字回复、账号配置、Webhook 与审批队列，凭据待用户补齐；真实授权和收发尚未验收。公开主页 URL 不等于 API 收件人，平台消息权限与业务准入分别检查。操作见 [社媒服务](docs/社媒渠道服务.md)。

D49：测试阶段 main 提交自动 CI/CD，镜像使用 GHCR，不使用 ECR，也不设发布审批。服务器业务配置与 Traefik 分开，发布检查完整 digest、固定脚本 hash、备份与迁移、HTTPS 和实际提交版本。修改相关配置前读 [自动部署说明](docs/GitHub自动部署.md)。检查 `uv run --project apps/api python infra/deploy/validate.py`、`uv run --project apps/api python -m pytest tests/deploy -q`、`actionlint .github/workflows/ci-cd.yml`。不要在发布中删数据卷、自动数据库降级或覆盖未确认的 pending 发布。

D50：服务器独立 Maps worker 已纳入 GHCR CI/CD，Chrome + Xvfb、专用持久化会话、服务器独立密钥及心跳健康检查。服务器链路已实测，当前匿名 Google 会话仍可能 limited_view 或无 Menu，未证明菜单图片采集成功；见操作手册 D50 验收。

2026-10-14 发布策略调整（用户明确要求，取代 D49 的 main 自动上线规则）：先本地测试，用户明确确认后才发布服务器。main 自动 CI／GHCR 构建保留，部署仅 workflow_dispatch 且 deploy=true；默认 false。禁止在未确认时触发发布。


D54（2026-10-14）：名单建立、完善与追加采用持久化流水线；完善跳过 FSA，追加固定地区且先排除已有成员，再按新成员数量抽样。任务按请求推进，刷新后主动继续，成功步骤不重做；同一名单写操作互斥。CSV 导入与空名单保留。界面回归 `uv run --project apps/api --extra maps-worker python scripts/verify_list_workflows_ui.py` 使用模拟 API，不写实际名单。迁移 head `da54a0010001`，本地已更新，用户验收前不发布。详见操作手册 D54。

D55（2026-10-14 用户要求，取代 D51/D54 的客户抽样默认）：新建和追加获取所选地区／类型的全部商户，界面去掉数量输入，新任务不随机。前端完整分页读取，Overture／预筛处理全部成员。旧研究任务可按已存参数复现，现有抽样名单通过追加补齐。先本地验收，不据“准备给客户使用”自动发布服务器。

D56（2026-10-15）：失败任务不再锁定名单，可直接使用现有结果并重试失败项；运行／待继续保持互斥。开始新任务自动归档旧失败任务，保留错误与成果，避免旧任务重入。部分联系方式页面失败以警告显示，只更新本地。
