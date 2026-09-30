# CLAUDE.md

与用户交流请使用中文。

## 当前状态与依据

Beacon 已完成 T0/T1 技术探索（Islington 60 家抽样，5 份菜单，见 `plan/exploration.md`）和 `plan/development.md` 的 D1～D10 最小工具（apps/api 57 个测试、apps/web 工作台已构建）。下一步是 V（约 50 家新候选扩大验证）与 B（人工商业验证，条件未齐）。研究脚本在 `scripts/`，受控数据在 `data/`（已忽略，不提交）。当前未触达任何餐厅。

先阅读 `AGENTS.md`、`欧洲餐厅菜单设计与印刷获客系统方案.md`、`plan/roadmap.md`、`plan/development.md`、`plan/validation.md` 与 `plan/exploration.md`。任务状态在 `plan/tasks.md`，决策在 `plan/decisions.md`；开始/完成跟踪任务时同步更新。

`plan/archive/` 是历史快照；`reports/` 与 `research_notes/` 是研究输入，不能覆盖当前方案。研究中的“实测”若无可复现产物，应标为未在本仓库复核。汇报 PPT 尚未同步当前版本，不能直接作为当前承诺对外使用。

## 产品与当前范围

目标是减少菜单设计与印刷业务的线索研究、素材准备时间，并验证有效意向与成本。约 10 家技术探索后即可开发最小工具，再用约 50 家新候选扩大验证；人工商业验证可并行，不作为开发前置；下一步从 T0/T1 开始技术探索，国家已确定为英国；建议 FSA 公开名录底表，城市、样本、经营参数和负责人待落实。

首版仅保留名单导入、菜单分析与证据、人工审核、一个局部示例模板、人工联系任务及结果。暂缓多源同步、复杂评分、自动跟进、完整 CRM、生产印刷文件、多国、多租户。

取消旧六维评分和 70 分门槛，以目标类型、人工确认问题和至少一个允许渠道建立可联系集合。旧 41 人日及报价是历史估计，不作承诺。

## 实施原则

- 固定、可审计流程；模糊任务交模型，事实和对外内容由人确认。
- 桌面阶段使用现有工具、记录表与必要脚本，不先搭完整系统。
- 采用 Monorepo：`apps/api/` 为模块化 Python 后端，`apps/web/` 为前端，`packages/api-client/` 按需生成；目录与边界见 `plan/development.md`。
- 开发时优先 FastAPI + PostgreSQL；需要队列再用 Celery + Redis，需要 UI 再用 Next.js + Ant Design；不用 n8n 作重复核心。
- 一个实际模型 provider + FakeProvider，接口可替换，不提前接多个厂商。
- 模板生成局部样稿；菜名、价格需逐项核对，不用文生图生成整张菜单。
- 后端命令（已实测）：`docker compose -f infra/docker-compose.yml up -d`；`cd apps/api && uv sync && uv run alembic upgrade head && uv run pytest && uv run ruff check . && uv run mypy app tests`。前端：`pnpm install && pnpm --filter beacon-web typecheck && pnpm --filter beacon-web test && pnpm --filter beacon-web build`。完整清单见 `AGENTS.md`，操作流程见 `docs/操作手册.md`。
- 研究脚本运行方式见 `plan/exploration.md` 六（`uv run --python 3.12 --no-project [--with pdfplumber] scripts/<name>.py`）；系统 Python 3.9 不用于抓取。

## 必须落实的边界

- 联系方式可用与渠道允许使用分别记录；`unknown` 不放行。主体未知不推断为公司。
- WhatsApp 不默认冷触达，记录 opt-in 证据；人工点击和每日限额不能替代授权。电话按目标市场规则筛查，英国包括 TPS/CTPS。Instagram、联系表单及样品邮寄当前暂缓。
- 所有对外内容先审核，修改后重新审核；不虚构到店经历、案例、身份、地址或菜单问题。
- 问题附来源和位置证据；不推断菜品利润、过敏原/素食成分，不拿缺双语作确定缺陷，不比较未取得的外卖菜单。
- 人工回复先暂停，拒绝/退订进入抑制记录。停发从系统收到/录入事件起计，不承诺系统实时看到人工平台回复。
- 未来自动发送需发送前复核准入/审批/抑制，处理重复事件、未知发送结果和竞态；外部已提交消息不承诺撤回。
- 首版不接 Google Places；未来逐字段确认适用用途和存储许可，TTL 不是许可。原始响应、日志、文件和备份同样受约束。
- 不提交真实联系人、凭证或菜单证据；按数据类别设保留期，抑制记录仅保留必要信息，不无限期保留原文。
- 项目依赖政策排除 AGPL/GPL、限制当前用途的托管组件和非官方 WhatsApp 群发库；核查版本与用途，不将包名列表当法律结论。

## 验证与完成

区分流程已设计、桌面验证已运行、商业效果已验证。没有名单和结果，不勾选验证任务。当前测试人工任务、审批与抑制，未来接入自动发送才测试发送超时、对账和竞态。关键规则测试优先于全局覆盖率；保留独立验收样本，报告实际分子/分母，不把样本零错误当线上保证。

T0/T1 只需研究范围、来源/数据条件、执行人和研究预算，不等待经营毛利或销售账号。T1 跑通后按 D1～D10 时间盒交付；成本分 setup/processing/outreach，人工与工具同质量对照。

真实联系须具备经营身份、预算、审核负责人、销售负责人、逐条渠道准入与明确执行安排。用户接受方案方向不自动授权代发营销消息。
