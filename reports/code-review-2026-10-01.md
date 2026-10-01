# Beacon 代码审查与交付验收（2026-10-01）

审查基线：`bfdd0ac`，开始时工作区干净。结论：已形成可运行的内部试用版本，但不应将 D1～D10 全部验收视为关键边界已可靠；先修复以下 P1 问题再交给客户处理真实证据或开展销售试点。本轮未修改业务代码，也未调用真实模型或联系餐厅。

## 实际验证

- 后端：现有 82 个 pytest 全通过（10.67 秒）；Ruff 检查/格式、mypy 通过。
- 前端：typecheck、lint、生产 build 通过；lint 有 2 个普通 img 提示；Vitest 仅 3 个格式化函数测试。
- 新增 8 个针对正确行为的审查断言：当前代码全部失败，均在独立 `beacon_audit_20260930_1` 数据库与合成夹具上复现，不修改开发库。
- 本轮未重新执行浏览器端到端操作、完整镜像构建、真实数据抓取/模型评测或备份恢复。界面问题按源码审查确认；外部 HTML 问题复现了原始脚本和不隔离的响应头，未执行真实用户会话攻击。

## 必须优先修复（P1）

### R1 外部 HTML 在工作台同源执行，缺少隔离

位置：`apps/api/app/core/routes.py:59`、`apps/web/src/app/leads/[id]/page.tsx:119`。

抓取或上传的 HTML 原样通过 `FileResponse` 返回 `text/html`，没有 sandbox CSP 或强制下载。工作台用没有 sandbox 的 iframe 展示；直接“打开”链接也暴露同一内容。外部菜单中的脚本因而处于工作台同源，可携带当前登录 cookie 调用业务 API；HttpOnly 不阻止这类请求。

复现：上传仅包含无害脚本标记的 HTML，获取文件返回 200、原始脚本、无隔离头。修复：将不可信原件与应用隔离，可用不允许脚本/同源权限的预览与服务端响应策略，或安全渲染截图/强制下载；不能仅修 iframe 而保留直接访问漏洞。测试浏览器不能通过该内容访问应用 API。

### R2 内容可以引用另一家餐厅的分析

位置：`apps/api/app/modules/content/routes.py:100`。

创建内容只分别验证 lead 和 analysis 存在，没有校验 analysis → asset → lead 的归属。A 餐厅分析可以在 B 餐厅路径创建文案；当前返回 201。随后审批也没有补此关联校验，会产生错误门店的菜单问题和素材。

修复：生成样稿和文案的服务入口统一验证归属，返回明确 4xx；为两种内容都增加跨门店拒绝测试。

### R3 更新来源文件后，旧审批仍然有效，旧证据被覆盖

位置：`apps/api/app/modules/menus/service.py:20`、`apps/api/app/modules/content/service.py:278`。

重新抓取在同一 asset 路径覆盖字节并更新 sha256；审批有效性只检查分析版本和分析字段，不检查 `analysis.input_sha256` 与当前文件。复现中换成另一份 PDF 后，旧内容仍返回 `approval_valid=true`。历史分析的“原文件”也指向新内容，证据无法复原。

修复：文件内容版本不可变（内容 hash/版本化路径）；分析绑定确切版本。刷新后标记相关内容过期、阻断未完成任务，保留历史证据。增加刷新成功、刷新失败及历史版本下载测试。

### R4 收到回复仅暂停已有任务，新任务仍可创建

位置：`apps/api/app/modules/sales/service.py:80`、`:225`。

reply 只遍历现有 open_tasks，没有保存门店级暂停/接管状态。复现：先录入 reply，再为该门店创建任务，返回 201；有多渠道或新内容时也可绕开原任务暂停。

修复：持久化门店/跟进级暂停状态，创建和执行任务均检查；明确负责人解除暂停的操作与审计。测试“回复时无任务”“回复后新增渠道/内容”。

### R5 重用事件键会静默吞掉退订

位置：`apps/api/app/modules/sales/service.py:202`。

相同 event_key 直接返回旧记录，完全不校验 lead、kind 或 payload。工作台要求操作者手填事件键，因此冲突不是纯理论问题。复现：先 note，再用同一 key 提交 unsubscribe，得到 200 + duplicate，返回旧 note，未写抑制。

修复：只有同一作用域、同一语义请求才幂等成功；不同内容同键返回 409 并明确提示；事件键自动生成/关联原始消息，保留并发唯一约束。测试同键不同门店、不同事件类型和同时提交。

## 统计问题（P2，影响验证结论）

### R6 E 包含准入已过期或仅联系方式被抑制的对象

位置：`apps/api/app/modules/sales/summary.py:67`。

汇总只看 eligibility=allowed、非 invalid 及门店级 suppression；没有采用实际执行时的到期和联系方式抑制规则。复现：review_due_at 为昨日仍算 E=1，创建任务却会拒绝。

修复：抽取统一的“当前渠道可联系”判定，汇总与执行共用，但不要把素材审批混入 E 的定义；测试过期、联系方式级抑制和未知状态。

### R7 新批次继承旧批次的发送和回复

位置：`apps/api/app/modules/sales/summary.py:76`，以及任务/事件的数据关联。

任务和回复按 lead_id 查询全部历史，没有批次归属与时间边界。复现：b1 已人工发送一次，再把相同门店导入一个新批次，新批次未发送也显示 S=1。观测截止时间只回显，没有用于口径切分。

修复：保留全局拒收，同时为实验活动增加批次/活动归属和事件时间；历史关系可复用，但不能当新批次成果。测试跨批次重叠、晚录入和窗口外事件。

### R8 抓到任何网页即计入“取得菜单”M

位置：`apps/api/app/modules/sales/summary.py:62`、`:97`。

M 实际计算 `bool(fetched)`，无论是否菜单。复现：只有欢迎语、没有菜单的 HTML，分析后仍 M=1。V 报告也承认 10 家抓到网页/文件，只有 7 家取得可核对菜单，当前 10/50 不能直接称菜单覆盖率。

修复：区分文件获取、菜单确认、有效提取；菜单状态与确认依据可记录。保留旧指标更名，不静默改变历史报告口径。

## 其他需安排的交付缺口

- **P2 审核后没有正常修正入口。** `apps/web/src/app/leads/[id]/page.tsx:102` 将 reviewed 后所有编辑禁用，且无“修订”入口。后端支持生成新版本，前端应提供同样流程并明确旧审批失效；不应靠重新分析绕行。
- **P2 单位成本混入一次性投入。** `apps/api/app/modules/sales/summary.py:149` 用全部类别总额和分钟计算单位值，未另外提供计划要求的 processing/outreach 持续成本口径。报告 v1 中 processing=85 分钟、N=50 应为 1.7 分钟/家；写成“不含 setup 的 3.6”实际用了含 setup 的 180/50。
- **部署范围需标明。** compose 把数据库 5433、API 8000、web 3000 绑定所有网卡，并提供可预测的开发密码和会话密钥兜底。作为本机开发配置应绑定 localhost；网络试点应使用强制外部配置、限制数据库暴露并配置 HTTPS。未检查实际密钥内容，也未假设已公开上线。
- **前端测试不覆盖交互。** 仓库内只有 `apps/web/tests/format.test.ts`，不能用“3 tests passed”代表修正、审批、任务回填已做自动化验收。建议补审核→修订→审批失效、回复后新建任务阻断、准入过期三个流程。当前未发现 `.github` CI 配置。
- **范围及文档状态有漂移。** `AGENTS.md` 同时写已跑 Ruff/mypy 和“目前未配置”；`CLAUDE.md` 仍有旧阶段措辞；模型评测明确 HTML/文本 PDF 的 provider 路径尚未改，但指导文档写“只用于图片”。统一已实现、已测、未完成的表述。
- **真人操作与商业验证未完成。** 最新 D33 已取消强制纯人工对照，本审查不要求恢复该方案；仍需完成真人使用计时和用户复核。首批独立验收候选没有成功提取，不应将训练/调试样本结果描述为独立质量验证。

## 复现方法与修复顺序

审查用例在 [checks.py](code_review_20261001/checks.py)，以期望正确行为断言，因此修复前失败是预期结果。文件不位于默认 tests/，不会改变现有测试收集；修复时将对应场景移入正式测试。

先启动 PostgreSQL，在仓库根目录创建专用空审查库（不要使用开发或真实业务数据库）：

```sh
docker compose -f infra/docker-compose.yml up -d postgres
docker exec beacon-postgres createdb -U beacon beacon_audit_review
```

然后在 `apps/api/` 运行：

```sh
BEACON_TEST_DATABASE_URL=postgresql+psycopg://beacon:beacon@localhost:5433/beacon_audit_review uv run python -m pytest -p tests.conftest ../../reports/code_review_20261001/checks.py --tb=short -q
```

现有 conftest 会在该库执行迁移升降和清表；审查文件要求库名以 `beacon_audit_` 开头。日志见 [本次复现结果](code_review_20261001/results.txt)。本轮临时数据库检查后删除。

修复顺序：R1 → R2/R3 → R4/R5 → R6～R8 → 修正入口/成本/交互测试。每项先复现再修复，保持原 82 项通过；随后进行浏览器端到端复核及真人计时，再判断是否适合客户试点。
