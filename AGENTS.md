# 仓库贡献指南

## 项目结构与模块组织

Beacon 是餐厅菜单销售线索工具。T0/T1 技术探索已完成（`plan/exploration.md`），研究脚本位于 `scripts/`，最小工具按 `plan/development.md` 开发中。

- `欧洲餐厅菜单设计与印刷获客系统方案.md`：主要产品方案。
- `plan/roadmap.md`：验证阶段、开发顺序与实施边界。
- `plan/validation.md`：抽样、证据、渠道准入、指标与阶段判定条件。
- `plan/development.md`：开发任务、依赖关系与验收用例。
- `plan/archive/`：历史方案，不作为当前执行指令。
- `plan/exploration.md`：T0/T1 探索记录、可测量发现、复现命令。
- `plan/validation-report-v1.md`：V 第一批 50 家的漏斗、提取质量、成本与工具问题。
- `plan/model-eval-v1.md`：DeepSeek 转录评测（准确率、观察精确率、成本）。
- `apps/web/public/brand/`：客户（南京小当家文化咨询有限公司）官网的 logo 与主视觉，仅用于客户自己的内部工作台；主题色红 #cf010e、金 #fab736 取自官网。
- 名单来源：`app/integrations/fsa.py`（FSA API）、`app/integrations/overture.py`（Overture Places，缓存在数据目录）；不使用 Google Maps 抓取；Google Places 官方 API 作为单家人工确认后的可选实时补充（D41），价格与照片不持久化；D44 允许经人工核对采用官网 URL，官网菜单发现复用现有抓取与分析，不依赖 Google 登录。
- `plan/tasks.md`、`plan/decisions.md`：任务进度与决策记录。
- `scripts/`：抽样、抓取、探针、提取、样稿渲染脚本；`templates/`：样稿模板；`data/`：受控数据（gitignore）。
- `reports/`：综合研究报告。
- `research_notes/`：按报告主题组织的研究资料。
- `汇报/`：演示材料（`.pptx`）。

采用 Monorepo：`apps/api/`（FastAPI，已实现 D1～D10）、`apps/web/`（Next.js + Ant Design，三组页面已实现），共享包按需放 `packages/`（尚未创建）；根目录 `templates/`（样稿模板）、`infra/`（compose、备份恢复脚本）、`scripts/`（研究脚本）、`docs/操作手册.md`。模块边界见 `plan/development.md`。

## 构建、测试与开发命令

研究脚本（已实测）：

- `python3 scripts/fsa_sample.py <raw.json> --seed N --n K --exclude-awaiting --out <csv>`
- `uv run --python 3.12 --no-project scripts/fetch_evidence.py --fhrsid <id> <url>...`
- `uv run --python 3.12 --no-project --with pdfplumber scripts/menu_probe.py data/evidence --out <json>`
- `uv run --python 3.12 --no-project --with pdfplumber scripts/extract_items.py <pdf> --out <json>`
- `python3 scripts/render_sample.py <spec.json> --out <path>`（本机 Chrome 无头渲染）
- `python3 scripts/assign_arms.py <leads.json> --seed N --prefix data/records/<batch> [--single-arm]`（真人计时工作表；`--single-arm` 全部进工具组，说明见 `docs/真人计时操作说明.md`）

Docker 全套（已实测）：`cp infra/.env.example infra/.env && docker compose -f infra/docker-compose.yml up -d --build`（postgres + api 自动迁移 + web，http://localhost:3000）；容器内测试 `docker compose -f infra/docker-compose.yml --profile test run --rm api-test`。

后端（`apps/api`，本机开发，需先 `docker compose -f infra/docker-compose.yml up -d postgres`）：

- `docker compose -f infra/docker-compose.yml up -d postgres`：只启动 PostgreSQL 16（端口 5433，开发库 `beacon`、测试库 `beacon_test`）。
- `cd apps/api && uv sync`：安装依赖（Python 3.12，`.python-version`）。
- `cp apps/api/.env.example apps/api/.env`：填写 `BEACON_*` 变量；`BEACON_DATA_DIR` 必须是绝对路径。模型转录需 `BEACON_LLM_PROVIDER=deepseek` 与 `BEACON_DEEPSEEK_API_KEY`（默认 fake，不调用模型；评测记录 `plan/model-eval-v1.md`）。主体候选检索需 `BEACON_COMPANIES_HOUSE_API_KEY`（可选；只给候选，人工确认，见 D34/D35）。
- `cd apps/api && uv run alembic upgrade head`：迁移；`uv run alembic revision --autogenerate -m "..."` 生成新迁移。
- `cd apps/api && uv run uvicorn app.main:app --reload --port 8000`：启动 API（`/api/health`、`/api/health/db`）。
- `cd apps/api && uv run pytest`：测试（自动对 `beacon_test` 做 upgrade/downgrade，不依赖网络与真实模型）。
- `cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`：lint 与类型检查。

前端（`apps/web`，已实测）：

- `pnpm install`：根目录 workspace 安装（`pnpm-workspace.yaml` 的 `allowBuilds` 已放行 esbuild、unrs-resolver）。
- `pnpm --filter beacon-web dev`：开发服务器 3000 端口，`/api/*` 重写到 `BEACON_API_URL`（默认 http://localhost:8000）。
- `pnpm --filter beacon-web typecheck`、`lint`、`test`（Vitest）、`build`（Next 生产构建）。
- 名单流程界面回归：仓库根目录 `uv run --project apps/api --extra maps-worker python scripts/verify_list_workflows_ui.py`（需 localhost:3000 和本机 Chrome；全部 API 使用模拟数据，不写真实名单，截图在 `data/devchecks/`）。
- 门店池后台：`cd apps/api && uv run python -m app.modules.directory.worker`；Compose 服务 `directory-worker`。界面回归：仓库根目录 `uv run --project apps/api --extra maps-worker python scripts/verify_directory_ui.py`（模拟 API，不写真实数据）。
- 页面（管理系统布局：左侧导航 + 顶部面包屑）：`/login`、`/`（仪表盘：漏斗、渠道、成本）、`/leads`（批次与线索：统计、筛选、自动建名单抽屉、导入、批量运行、导出）、`/leads/[id]`（文件、证据与修正、审核、样稿与文案、审批）、`/tasks`（任务、渠道准入、回复回填、抑制名单页签）、`/settings`（流程与边界说明）。

文档工作可使用：

- `rg --files`：查看仓库文件。
- `git diff --check`：检查已跟踪文件改动中的空白字符错误。
- `git diff --stat`、`git status --short`：检查改动范围及新增文件。

项目骨架建立后，将验证过的命令同步到本文件和 `CLAUDE.md`。计划工具包括 uv、pnpm 和 Docker Compose，不应假定它们已经配置。

## 编码风格与命名约定

项目文档使用中文，采用清晰的标题、相对链接和对比表格。保留按主题命名的文件及现有列表缩进。研究结论注明来源，明确区分建议与已确认决策。

目前未配置格式化或代码检查工具。计划采用 Ruff 和 mypy；添加源码时再落实缩进和命名规范。

## 测试要求

文档修改需检查链接、路径，以及方案、路线图和任务清单的一致性，并预览修改后的 Markdown 或演示材料。

计划采用 pytest、Vitest/Testing Library 和 Playwright。优先覆盖渠道准入、审批、拒收抑制及重试规则的成功和失败路径，暂不设全局覆盖率目标。未来测试夹具放在 `apps/api/tests/fixtures/`；普通测试使用本地夹具和 `FakeProvider`。测试命名与实际运行命令待实现时确定。

## 提交与合并请求规范

沿用历史记录，以英文祈使句作为提交标题，例如 `Add proposal …`、`Refactor code structure …`，不强制添加前缀。

每次改动保持聚焦。PR 应说明目的、涉及的文档或里程碑、关联问题或任务，以及已完成的验证。演示材料或未来界面发生变化时附截图。

## 协作流程

开展功能工作前，阅读 `CLAUDE.md`、产品方案和路线图。开始或完成跟踪任务时，更新任务复选框与进度；确定的设计选择记录到 `plan/decisions.md`。

先做技术探索，再开发工具；销售验证独立推进。流程获认可不代表获准联系潜在客户。保留工作区中与当前任务无关的改动。

D45：单家 AI 自动补全允许真实 DeepSeek + 程序证据校验自动采用官网、导入菜单并生成待审核分析，异常才人工复核；Fake 不允许自动采用。原人工路径保留，Google 价格/照片不送模型，渠道与内容审批不变。API 后台任务首版仅支持单 worker；重启后手动重跑，hash 去重与既有审核保留。

D46（2026-10-11 用户授权例外）：工作台支持单家 Maps 菜单浏览器获取、受控资产及待审核 AI 转录。名单仍来自 FSA/Overture；专用会话不复制日常 Chrome、不自动登录、不批量抓取。执行器命令：`python3 scripts/configure_maps_worker.py` 后重建 API，再运行 `uv run --project apps/api --extra maps-worker python scripts/maps_menu_worker.py --token-file data/browser-profiles/maps-worker.token`。配置、服务器与有限视图限制见 [手册](docs/操作手册.md#google-maps-菜单获取d46)。


D47（2026-10-12 用户授权实施）：扩展此前“系统不发送”边界，Gmail 独立容器支持凭据管理、完整邮件预览确认、单家发送回填、已发送线程回复头同步及审批后批量队列；其他渠道仍人工。发送和批量队列默认暂停，执行前复核准入/审批/抑制，未知结果不自动重试。施工步骤见 [Gmail 服务计划](plan/gmail-service.md)。本次开发不授权向客户发送测试邮件。

Gmail 服务配置：首次 Compose 启动前运行 `python3 scripts/configure_gmail_service.py`；启动后可用 `python3 scripts/configure_gmail_service.py --import-opc` 导入本机已有授权（不发送邮件）。新增验证命令 `cd services/gmail && uv sync --python 3.12 && uv run pytest -q && uv run ruff check gmail_service tests`。详细步骤见 [Gmail 服务操作](docs/Gmail邮件服务.md)。

D48 社媒服务：首次 Compose 启动前另运行 `python3 scripts/configure_meta_service.py`。FB／INS 独立 HTTP 服务与持久化队列已实现，默认暂停，凭据待用户配置；真实权限、Webhook 订阅及收发另行验收。操作见 [社媒渠道服务](docs/社媒渠道服务.md)，开发前读 [接入指南](plan/social-channel-integration.md)。服务测试：`cd services/meta && uv sync --python 3.12 && uv run pytest -q && uv run ruff check meta_service tests entrypoint.py`。

D49 GitHub 自动部署：main 提交自动检查、构建 GHCR 并部署测试服务器，PR 仅检查。生产文件 `infra/docker-compose.production.yaml` 与独立 Traefik 基础栈分开。操作及首次配置见 [GitHub 自动部署](docs/GitHub自动部署.md)。部署验证命令：`uv run --project apps/api python infra/deploy/validate.py`、`uv run --project apps/api python -m pytest tests/deploy -q`、`uv run --project apps/api ruff check --config apps/api/pyproject.toml infra/deploy tests/deploy`、`actionlint .github/workflows/ci-cd.yml`。禁止提交管理 PEM、CI 私钥、服务器登录文件或 runtime.env；Compose／gateway 修改需先同步服务器固定规范，不能自动绕过 hash 或 pending 检查。

D50 服务器 Maps 执行器：`services/maps/` 独立镜像，Playwright Chrome + Xvfb；纳入 production Compose、GHCR 发布与浏览器数据卷备份。验证 `shellcheck services/maps/entrypoint.sh`、`cd apps/api && uv run pytest tests/test_maps_menu.py -q`；服务器实际有限视图和菜单缺失不能算采集成功，见操作手册 D50。

D58：设置页可配置筛选与 Google 按需补充策略；任务冻结版本，人工官网和筛选保留。浏览器回归 `uv run --project apps/api --extra maps-worker python scripts/verify_lead_policy_ui.py`（全部 API 模拟）；后端专项 `cd apps/api && uv run pytest tests/test_lead_policy.py -q`。本地验收前不发布，详见操作手册 D58。

D59 用户与权限：`/account` 个人资料／改密，`/users` 管理员管理用户；管理员／业务／只读，同一工作空间。初始密码强制修改、版本化会话撤销、最后管理员保护。迁移 `d159a0010001`。专项 `cd apps/api && uv run pytest tests/test_users.py tests/test_auth.py tests/test_gmail.py tests/test_outreach.py -q`；界面 `uv run --project apps/api --extra maps-worker python scripts/verify_users_ui.py`（全模拟，无真实账号或外部发送）。详见操作手册 D59；只本地更新，用户确认前不发布。

D60 名单到沟通工作台：单家／批量准备草稿、严格转换任务、负责人／来源名单／执行方式／提醒、多渠道人工执行、会话回填及沟通进展。见 [操作说明](docs/客户沟通工作台.md)。界面回归 `uv run --project apps/api --extra maps-worker python scripts/verify_communication_ui.py`（模拟 API，不触达）。迁移 head `d160a0010001`；仅本地验收，未发布服务器。

D61 联系方式读取：任务保存独立快照与页面失败原因，区分完成／部分／失败，独立候选门店数；旧数据不能可靠还原时标记未知。当前迁移 head `d161a0010001`。界面 `uv run --project apps/api --extra maps-worker python scripts/verify_contact_read_ui.py`（全模拟、不写真实名单）。仅本地更新，未发布。详见操作手册 D61。

D62 官网 AI：已有官网独立核验与经营识别，必要时 Google 回退；保留原文、人工结果和 FSA，失败状态分流，混合餐食服务不单凭 cafe／pub 排除。名单／详情可单家 AI 重试。界面 `uv run --project apps/api --extra maps-worker python scripts/verify_website_review_ui.py`（全模拟）。无需迁移，仅本地更新；见操作手册 D62。

D63 客户流程：四个工作区域，菜单详情“获取菜单→AI 分析→核对事实→准备触达”；样稿可选、共用准备抽屉。`engine=auto` 自动选择规则提取或真实模型，运行中不可完成事实核对。界面 `uv run --project apps/api --extra maps-worker python scripts/verify_menu_journey_ui.py`（全模拟、不发送）。无迁移，只本地更新，见手册 D63。
