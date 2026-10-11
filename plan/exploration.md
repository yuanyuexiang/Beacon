# T0/T1 技术探索记录

版本：v0.1，2026-09-30。执行人：Claude（研究执行），用户复核。本文件记录 T0 的取样规则与 T1 的实际结果；真实证据文件在受控目录 `data/`（不提交），本文只保留聚合数字、公开的商户官网和可复现命令。

## 一 T0 技术准备（已完成）

| 项 | 结论 |
|---|---|
| 研究行政区 | 伦敦 Islington（FSA LocalAuthorityId=106）。选择理由：规模中等（餐厅类 1014 条）、独立餐厅密集、研究笔记未用过（避免复用旧结论） |
| 目标类型 | FSA BusinessTypeId=1（Restaurant/Cafe/Canteen）中的独立或小型集团堂食餐厅；排除咖啡店、食堂、连锁、社区/机构、酒吧、已关闭 |
| 数据来源与许可 | FSA FHRS API v2，Open Government Licence v3；条款要求使用当前评级或注明数据日期，不得表现为 FSA 背书。本项目不展示评级，只用名录 |
| 取样规则 | 拉取全部 1014 条 → 排除 AwaitingInspection 59 条（新登记，官网/菜单常未就绪）→ 池 955 → 按 FHRSID 排序后 `random.Random(20260930).sample` 抽 60，按顺序逐家判断类型与官网 |
| 受控存储 | `data/raw/`（原始 API JSON）、`data/records/`（抽样与筛选表、探针输出、样稿）、`data/evidence/<FHRSID>/`（抓取文件 + `.meta.json`：URL、状态、时间、sha256、UA）；`data/` 已加入 `.gitignore` |
| 研究预算 | 现金 0（无付费 API、无模型密钥）；时间盒为本次会话；停止条件：抽样 60 家筛完，或至少 1 份真实菜单跑通提取→证据→样稿 |
| 主体核验 | 未做（T1 不联系任何餐厅） |

## 二 T1 结果（分子/分母）

抽样 60 家（种子 20260930，池 955）。筛选表 `data/records/t1_screening.csv`，逐家记录分类原因。

| 步骤 | 数量 | 说明 |
|---|---:|---|
| 抽样 | 60 | |
| 按名称/检索排除：咖啡店 | 15 | 名称含 Cafe/Coffee/Tearoom 等；其中 1 家名称同时含 Restaurant，规则可能误杀 |
| 排除：连锁 | 7 | Taco Bell、Itsu、Caffe Nero、Pizza Pilgrims 等 |
| 排除：食堂/社区/机构/酒吧/书店/已关闭 | 8 | |
| 未检索 | 3 | 时间盒内未查 |
| 检索后仍未知 | 16 | 名称+地址无网络记录，或地址已是别家 |
| **候选（独立或小型集团堂食餐厅）** | **12** | |
| 候选中找到官网 | 6 | 其余 6 家只有 OpenTable/外卖平台页面 |
| 官网可抓取 | 5 | 1 家（Shopify 站）对任何 UA 返回 429；1 家仅拦截非浏览器 UA，换 UA 可抓 |
| 取得菜单 | 5 | 文本 PDF 3、HTML 文本 1（套餐页，无单品）、图片 1（两张 2000×1414 webp） |
| 规则提取出菜品+价格 | 3 | 单栏 PDF 28/28 行正确；两份两栏 PDF 有跨栏合并错误（见已知问题） |
| 走完提取→位置证据→人工确认→局部样稿 | 1 | Vesper 晚餐菜单 p.1 前 8 项 → `templates/partial_menu.html` → Chrome 无头渲染 PNG |

官网覆盖率是本轮最大瓶颈：随机样本中独立餐厅仅一半有官网，且 60 家中只有 5 家最终拿到菜单（5/60）。V 阶段扩大到 50 家新候选时，应预期需要 Overture 或人工补官网。

## 三 各菜单的可测量发现（待人工确认，非最终结论）

| FHRSID | 餐厅 / 格式 | 测量值 | 证据位置 |
|---|---|---|---|
| 416314 | Fish Central / 图片 | 饮品区三项（Coffee、Cappuccino、Espresso）下方的描述文字与鱼类菜品描述相同（"flaky, white fish…"），疑为复制错误；价格符号不一致（Oysters "Each - £3.25" 带 £，其余无）；拼写 "LARGER"、"allegies"；菜单为整页图片，手机端需缩放 | 图片 2 左栏 Drinks；图片 1 左栏 Lobster & Oysters；图片 2 右栏、图片 1 左下 |
| 923947 | Zia Lucia / PDF 4 页 | 价格小数位混用：£15 / £14.5 / £2.25（0 位 19 项、1 位 17 项、2 位 4 项）；PDF 文件名含 "jan-2026 V9"，发布于 2026-05 目录 | p.2 l.14、l.17，p.3，p.4 |
| 1754073 | Macellaio RC / PDF A3 2 页 | 正文 10pt，整页缩放到 375px 宽时等效 4.5px；两栏排版 | 全页测量（`menu_probe.json`） |
| 1408999 | Vesper / PDF A4 | 正文 10pt，等效 6.3px；价格无货币符号但全篇一致；无格式问题 | 全页测量 |
| 1439879 | Dans le Noir / HTML | 套餐定价，无单品；未发现格式问题 | set-menus 页 |

"等效字号"是把整页缩放到手机宽度得到的数值，是否构成阅读困难要由人判断；不据此推断利润、过敏原或双语缺失。

## 四 已知问题与限制

- 无模型 API 密钥：图片菜单由 Claude 直接阅读并转录，未验证任何自动视觉模型；D5 的模型路径只能先用 FakeProvider。
- 规则提取对两栏 PDF 会把同一行的两个菜品合并（Macellaio、Zia Lucia）。D5 需按字符 x 坐标分栏后再逐行匹配。
- HTML 套餐页无单品，规则提取不适用；这类页面只做价格与文本记录。
- 官网查找靠通用网络检索（33 次查询），无法批量化；V 阶段需要 Overture 匹配或人工。
- Python 3.9 系统解释器对部分站点 TLS 握手失败（`SSLEOFError`），3.12 正常；脚本统一用 `uv run --python 3.12`。
- 人工基线耗时未测：本轮由 Claude 执行，无法给出人工每家分钟数；V 阶段需真人计时。
- 未联系任何餐厅；未做主体（公司/个体）核验。

## 五 T1.4 结论：首版支持范围与 D 阶段时间盒

首版支持格式：文本型 PDF（单栏；两栏在 D5 实现坐标分栏）和 HTML 文本；图片与扫描件进入人工/视觉队列，无模型时由人转录；抓取被拒（403/429）的站点记录原因并转人工下载。

D1～D10 估时（时间盒，超出先缩范围）：

| 任务 | 人日 | 依据 |
|---|---:|---|
| D1 骨架、schema、迁移、命令 | 1.0 | 已有脚本可迁入 |
| D2 访问保护与文件受控访问 | 0.5 | 单操作者 |
| D3 批次/CSV 导入与去重 | 1.0 | `fsa_sample.py` 已定义字段 |
| D4 菜单文件/URL 接入 | 1.0 | `fetch_evidence.py` 迁入，加 SSRF 阻断与超时 |
| D5 解析与证据（含分栏）、模型接口 | 2.0 | `extract_items.py` + `menu_probe.py` 迁入，补分栏 |
| D6 证据查看与人工修正 | 1.0 | |
| D7 局部样稿与审批 | 1.0 | `partial_menu.html` + Chrome/Playwright |
| D8 准入检查与人工任务 | 1.0 | |
| D9 事件、抑制、汇总导出 | 1.0 | |
| D10 批量续跑、测试、手册 | 1.5 | |
| 合计 | 11.0 | |

## 六 复现命令

```bash
# 1. 拉取 Islington 餐厅类原始数据（需网络）
curl -s -H 'x-api-version: 2' -H 'accept: application/json' \
  'https://api.ratings.food.gov.uk/Establishments?localAuthorityId=106&businessTypeId=1&pageNumber=1&pageSize=5000' \
  -o data/raw/fsa_islington_bt1_2026-09-30.json
# 2. 固定种子抽样
python3 scripts/fsa_sample.py data/raw/fsa_islington_bt1_2026-09-30.json --seed 20260930 --n 60 --exclude-awaiting --out data/records/t1_candidates_60.csv
# 3. 抓取证据（每域名 ≤1 rps）
uv run --python 3.12 --no-project scripts/fetch_evidence.py --fhrsid <FHRSID> <url> [<url> ...]
# 4. 测量探针
uv run --python 3.12 --no-project --with pdfplumber scripts/menu_probe.py data/evidence --out data/records/menu_probe.json
# 5. 规则提取菜品与价格
uv run --python 3.12 --no-project --with pdfplumber scripts/extract_items.py <pdf> --out data/records/items_<FHRSID>.json
# 6. 局部样稿
python3 scripts/render_sample.py data/records/sample_<FHRSID>.spec.json --out data/records/sample_<FHRSID>
```

## 七 D10 备份恢复演练（2026-09-30）

命令：`infra/backup.sh /tmp/beacon-data /tmp/beacon-backups` → `infra/restore.sh <dump> beacon_restore_drill <tgz> /tmp/beacon-restore`。

| 项 | 结果 |
|---|---|
| 源库表数 / 恢复库表数 | 19 / 19 |
| 恢复库 alembic 版本 | a54bba1f68ef（与源一致） |
| 文件包 | 161 个文件恢复，抽检文件内容一致 |
| 备份产物 | dump 36.8KB、tgz 114.8KB，均输出 sha256 |
| 演练库 | 完成后删除 |

限制：演练在开发库上进行，数据量小；生产恢复需先停 API，并按 `docs/操作手册.md` 第 11 节执行。

## D45 单家 AI 自动研究验收（2026-10-11）

本轮以 THE COLLEGE BAR AND DELI（9 Alford Place, Aberdeen AB10 1YD）做探索，不改写真实门店记录。单家被重复用于调整提示和排除社媒候选，不能视为独立验收集。模型为已配置的 DeepSeek `deepseek-flash`，证据提示版本 `research-2`；Google 价格与照片未送模型。

最终隔离数据库运行 `0b1db81dddf94009b4cb2d22f4cf4744` 从 `http://www.pbdevco.com` 起步，通过集团场馆页发现 `https://www.thecollegebar.co.uk/`，核对同页完整门牌/街道、邮编与引用后自动采用。发现 6 个菜单候选：饮品 PDF 和 Buffet PDF 自动确认、保存及分析；优惠 PDF 与优惠网页因日期不明留复核；菜单索引页没有实际菜单内容留复核；一张图片转录证据不足记失败。2/6 自动接入不能当成菜单覆盖率：分母含索引页、图片及重复类型。饮品规则结果 22 条、Buffet 2 条，均 needs_review，不能宣称提取完整。

该最终运行约 80.2 秒，记录 9 次模型响应/转录用量：输入 29,864 token、输出 1,946 token（含一次视觉证据转录及引用修正）；现金费用未计算，以模型平台账单为准。早期探索调用另计，不纳入此单次结果。运行 JSON 与菜单文件保存在受控数据目录 `records/college-ai-2026-10-11/`；隔离数据库已删除，真实门店未被写入。

界面用另一隔离库和模拟 Places/判断器验证：一键启动、运行进度、官网与编辑框刷新、自动 PDF 获取和分析、复核理由展示。此界面验证不能代替真实模型质量验证。后端 209 测试通过，Ruff 格式/检查与 mypy 通过，前端类型检查、5 测试与生产构建通过，Docker api/web 重建。10 家冻结样本及批量入口尚未完成。

## D46 单家 Maps 工作台验收（2026-10-11）

从工作台按钮真实执行，独立随机 QA 数据库中建立 College Bar 公开门店夹具，使用本机专用 profile 和真实 Maps/DeepSeek；未写真实线索。运行 f0de9c19080642a2b2297ed4b22dc470 成功获取 1 张 2976×3968 的菜单图片（455,188 bytes），真实转录 19 条候选、7 个未审核问题，状态 needs_review。模型输入 1,335 / 输出 1,248 tokens，cache hit 128；现金费用以服务商账单为准。图片仅当前菜单区一张，不宣称完整覆盖或准确率。产物在受控 data/records/maps-ui-qa-2026-10-11/report.json 及 evidence 目录。

真实页面地址显示“9 Alford Pl”，登记为“9 Alford Place”，最初安全拒收；补上常见街道缩写等价后验证通过，并用 9/99 门牌号负例防止子串误匹配。界面已验证：按钮可见、等待/运行状态、来源原图、日期未知、去重结果及待审核分析自动刷新。未点击完成审核，未发送任何联系。已配置本机执行器密钥并部署 API/web；专用执行器需保持运行，电脑重启后重新启动。

会话验证：用户在专用自动化 Chrome 的 Google 登录被拒，随后未登录却能看到菜单；复用该 profile 的有界面模式成功。全新 profile 的有界面与无头模式均为有限视图（0 张），所以不能以当前成功推出登录必要性或服务器成功率。官方说明列出自动化控制浏览器可能被拒绝登录：[Google 账号帮助](https://support.google.com/accounts/answer/7675428?hl=en)。

后端 225 测试、Ruff 与 mypy 通过；前端 5 测试、类型检查、生产构建通过（2 个已有 img lint 警告）。普通测试无网络/真实模型；真实 UI 验证另跑，隔离 QA 数据库验证后删除，受控报告和文件保留。服务器新会话、多家、多图覆盖率仍待评测。

### D46 门店不一致诊断修正

复现两项真实失败：Your Love Rara 的登记地址为 25 Castle Street / AB11 5BG，Maps 显示 12–14 Justice St / AB11 5HR；Second Home Studio + Cafe CIC 的登记为 Shop, 1 Gaelic Lane / AB10 1JF，Maps 名称为 Gaelic Lane Cafe + Bar、同一街道与邮编。前者实际地址不同，后者品牌名不同，现有证据不足以断言搬迁/更名。补上公司后缀与 Shop 前缀规范化并保留这些真实冲突；失败也记录观测名称/地址、界面显示逐项对照。测试加入以上两个真实文本反例及失败结果记录验证。

上述两次失败任务已在核对 run_id 与当前门店快照后回填本次真实观测及诊断审计；没有改变门店名称/地址/关联、没有导入冲突图片。后端 227 测试与 Ruff/mypy、前端类型检查/构建通过，执行器已重启载入修正。


### D46 来源并存实测（2026-10-11）

Your Love Rara 已确认 Place ID `ChIJ8-BNAJkPhEgRDTrJpEscwW8`：原线索地址 25 Castle Street / AB11 5BG 保留；Maps 观测名称 Your Love Rara、地址 12–14 Justice St / AB11 5HR、官网 https://www.yourloveraracic.com/ 独立保存。新流程未因地址差异阻止；本次浏览器返回 menu_unavailable（没有菜单页签），获取 0 张图片，不把缺菜单误判为错店。
