# 开源项目调研：菜单解析、设计渲染、触达、CRM 与 AI SDR（欧洲餐厅获客系统，2026-09）

> 数据口径：星数、许可证 SPDX、最近 push 日期、语言均来自 2026-09-25 通过 GitHub REST Search API 批量查询（`q=repo:a/b repo:c/d ...`）的结果，每个仓库的链接就是其来源。API 返回 `NOASSERTION` 表示许可证为自定义或混合文本，已尽量通过 raw LICENSE 文件或官方文档核实。"≤12 个月" = 2025-09-25 之后有 push。

## 问题 1：菜单/文档解析（HTML/PDF/图片 → 结构化菜单 JSON）用哪些开源组件？

### Takeaway
GitHub 上**没有成熟的"餐厅菜单专用"开源解析器或开放数据集**（按星数搜索"restaurant menu llm""menu extraction""menu parser"只返回个位数星的 demo 项目），所以应走"通用文档解析 → LLM + JSON Schema 结构化抽取"两段式：Docling（MIT）或 PaddleOCR（Apache-2.0）负责版面/OCR，Instructor / PydanticAI / LangExtract 负责按 Pydantic schema 抽取菜品、价格、分类、过敏原。Marker 和 MinerU 的**模型权重许可证有商用门槛**，交付给客户前需要评估。

### Cited Findings
- **docling-project/docling**：约 67.9k★，MIT，2026-09-25 有 push，Python。"Get your documents ready for gen AI"：PDF/DOCX/HTML/图片 → Markdown/JSON，带版面、表格和 OCR 管线 — [GitHub](https://github.com/docling-project/docling)
- **microsoft/markitdown**：约 187k★，MIT，2026-09-21，Python。各种 Office/PDF/HTML 转 Markdown，偏轻量，扫描件 OCR 能力弱 — [GitHub](https://github.com/microsoft/markitdown)
- **PaddlePaddle/PaddleOCR**：约 90.2k★，Apache-2.0，2026-09-16。"Turn any PDF or image document into structured data for your AI"，多语言 OCR 工具包 — [GitHub](https://github.com/PaddlePaddle/PaddleOCR)
- **opendatalab/MinerU**：约 80.6k★，2026-09-24，SPDX 显示为 NOASSERTION。LICENSE 是 **Apache 2.0 加自定义商用限制**：月活超过 1 亿或月收入超过 2000 万美元须取得商业授权；如果基于 MinerU 提供在线服务，须在界面或公开文档中"clearly and prominently"注明使用了 MinerU — [LICENSE](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)
- **datalab-to/marker**：约 40k★，API 显示代码为 Apache-2.0，2026-09-13。支持 `--use_llm`（可接 Gemini、Claude、OpenAI 等），可输出 JSON 块树。**模型权重使用修改版 AI Pubs Open Rail-M 许可**，只对研究、个人使用以及融资或收入低于 500 万美元的初创公司免费，超出须购买商业授权 — [GitHub README](https://github.com/datalab-to/marker)
- **datalab-to/surya**（OCR、版面、阅读顺序、表格识别，覆盖 90+ 种语言；约 21.4k★，Apache-2.0 代码，2026-09-11）和 **datalab-to/chandra**（OCR 模型，擅长复杂表格和手写；约 12.3k★，2026-06-26）同属 Datalab。其权重许可是否与 marker 相同，本次未逐一核实 — [surya](https://github.com/datalab-to/surya)、[chandra](https://github.com/datalab-to/chandra)
- **allenai/olmocr**：约 19.7k★，Apache-2.0，最近 push 2026-03-25。定位是"linearizing PDFs for LLM datasets"，偏批量 PDF 转文本 — [GitHub](https://github.com/allenai/olmocr)
- **studio-dots-ai/dots.ocr**（原 rednote-hilab）：约 9.2k★，MIT，2026-03-24。单个 VLM 完成多语言版面解析 — [GitHub](https://github.com/studio-dots-ai/dots.ocr)
- **deepseek-ai/DeepSeek-OCR**：约 23.9k★，MIT，最近 push 2026-01-27 — [GitHub](https://github.com/deepseek-ai/DeepSeek-OCR)
- **Unstructured-IO/unstructured**：约 15.5k★，Apache-2.0，2026-09-25。文档 ETL（分区、切块） — [GitHub](https://github.com/Unstructured-IO/unstructured)
- **getomni-ai/zerox**：约 12.3k★，MIT，TypeScript。用视觉模型做 OCR 和抽取，但**最近 push 是 2025-05-20，已超过 12 个月** — [GitHub](https://github.com/getomni-ai/zerox)
- **run-llama/llama_cloud_services**（LlamaParse 客户端）：约 4.3k★，MIT，2026-05-18。解析本身是云端付费服务，不属于自托管开源 — [GitHub](https://github.com/run-llama/llama_cloud_services)
- **567-labs/instructor**：约 13.9k★，MIT，2026-09-24，"structured outputs for llms"，以 Pydantic 定义 schema — [GitHub](https://github.com/567-labs/instructor)
- **google/langextract**：约 38.8k★，Apache-2.0，2026-09-21。用 LLM 从非结构化文本抽取结构化信息，并带"precise source grounding"（可回溯到原文位置） — [GitHub](https://github.com/google/langextract)
- **pydantic/pydantic-ai**：约 20.2k★，MIT，2026-09-25，Python agent 框架，原生支持结构化输出 — [GitHub](https://github.com/pydantic/pydantic-ai)
- HTML 菜单页抓取转 LLM 友好 Markdown：**unclecode/crawl4ai** 约 84.3k★，Apache-2.0，2026-09-25；**ScrapeGraphAI/Scrapegraph-ai** 约 31.3k★，MIT，2026-09-25 — [crawl4ai](https://github.com/unclecode/crawl4ai)、[Scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai)
- 按星数搜索 "restaurant menu llm" "menu extraction"，结果都是个位数星的 demo（例如 `sachelsout/FoodLens` 1★），或与餐饮无关（游戏 mod menu 等），没有可用的菜单专用解析器 — [GitHub 搜索 restaurant menu llm](https://github.com/search?q=restaurant+menu+llm&type=repositories)
- 菜单结构化解析的现成方案目前以商业形式存在：Apify 上的 "AI Menu Parser" 类 Actor（输出菜名、价格、过敏原等）、Veryfi Restaurant Menu OCR API（官方宣称准确率 99%+），以及 Dotlas 的商业菜单数据集 — [Apify](https://apify.com/nomad-agent/ai-menu-parser)、[Veryfi](https://www.veryfi.com/restaurant-menu-ocr-api/)、[Dotlas](https://catalog.dotlas.com/restaurants/menus/)

### Inferences
- 推荐管线：HTML 菜单用 crawl4ai 转成 Markdown；PDF 用 Docling（MIT，最安全）；照片或扫描件用 PaddleOCR，或直接把图片交给多模态 LLM（Claude、GPT、Gemini 的 vision）。之后统一用 Instructor 或 PydanticAI，按自定义 `Menu{sections[{name, items[{name, description, price, currency, allergens[], dietary_tags[]}]}]}` schema 抽取。欧盟菜单依据 FIC 法规（EU 1169/2011）需标注 14 类过敏原，适合作为枚举字段。
- 大多数欧洲餐厅菜单只有 1–4 页，数量少、版式多样。在这种场景下，"多模态 LLM 直接读图加 schema 抽取"的工程量最小；Docling 和 PaddleOCR 作为降成本或兜底方案。
- MinerU 的商用门槛（1 亿 MAU 或 2000 万美元月收入）对本项目基本没有影响，但"在线服务须显著注明"是一项义务。Marker 的 500 万美元门槛要看客户规模，交付时应当避免把它设为默认组件，或者提示客户自行评估。
- 菜单专用数据集缺失，意味着需要自建 50–200 份欧洲多语言（法、意、西、德）菜单的黄金集，用来评测抽取准确率。

### Gaps
- 没有找到公开、可商用的欧洲餐厅菜单标注数据集（Hugging Face 上也没有检索到明确的数据集）。
- 未实测上述各工具在菜单版式（多栏、手写黑板菜单）上的准确率对比，也没找到可靠的第三方基准。
- surya、chandra 的权重许可细节本次未核实。

## 问题 2：菜单改版前后样张（模板 → PDF/PNG）用哪些渲染组件？

### Takeaway
最稳妥的组合有两种：用 **Playwright/Puppeteer（Apache-2.0）或 Gotenberg（MIT，Docker 化的 Chromium/LibreOffice PDF API）** 把 HTML/Tailwind 模板渲染成 PDF/PNG；如果追求印刷级排版，则用 **Typst（Apache-2.0）**。Python 侧可选 WeasyPrint（BSD-3）。**Carbone 社区版的 CCL 许可禁止以"文档生成即服务"方式对外提供**，wkhtmltopdf 已归档，两者都不建议采用。开源"菜单制作器"项目都很小、已停更，没有复用价值。

### Cited Findings
- **microsoft/playwright**：约 96.7k★，Apache-2.0，2026-09-25；**puppeteer/puppeteer**：约 95.6k★，Apache-2.0，2026-09-25。两者都支持 `page.pdf()` 和截图，可用于 HTML → PDF/PNG — [playwright](https://github.com/microsoft/playwright)、[puppeteer](https://github.com/puppeteer/puppeteer)
- **gotenberg/gotenberg**：约 13.2k★，MIT，Go，2026-09-25。"A developer-friendly API for converting many document formats into PDF" — [GitHub](https://github.com/gotenberg/gotenberg)
- **typst/typst**：约 56.2k★，Apache-2.0，Rust，2026-09-24。基于标记语言的排版系统 — [GitHub](https://github.com/typst/typst)
- **Kozea/WeasyPrint**：约 9.6k★，BSD-3-Clause，Python，2026-09-24。HTML/CSS 转 PDF，不依赖浏览器 — [GitHub](https://github.com/Kozea/WeasyPrint)
- **diegomura/react-pdf**：约 16.8k★，MIT，2026-09-23。用 React 组件生成 PDF — [GitHub](https://github.com/diegomura/react-pdf)
- **pdfme/pdfme**：约 4.8k★，MIT，2026-09-21。TypeScript/React PDF 生成库，带 WYSIWYG 模板设计器 — [GitHub](https://github.com/pdfme/pdfme)
- **vercel/satori**：约 14k★，MPL-2.0，2026-09-22。HTML/CSS 转 SVG，适合生成社交图 — [GitHub](https://github.com/vercel/satori)
- **carboneio/carbone**：约 2.1k★，最近 push 2026-04-07。社区版采用 CCL（Carbone Community License），禁止以"hosted Document-Generator-as-a-Service"形式提供；社区版比企业版落后一个大版本 — [GitHub](https://github.com/carboneio/carbone)
- **wkhtmltopdf/wkhtmltopdf**：LGPL-3.0，**archived=true**，最近 push 2022-11-22 — [GitHub](https://github.com/wkhtmltopdf/wkhtmltopdf)
- **Stirling-Tools/Stirling-PDF**：约 93k★，主体 MIT，但 `app/proprietary/`、`app/saas/` 目录另有许可。定位是 PDF 编辑工具箱（合并、压缩等），不是模板渲染引擎 — [LICENSE](https://github.com/Stirling-Tools/Stirling-PDF/blob/main/LICENSE)
- **jgm/pandoc**：约 46.4k★，GPL-2.0 — [GitHub](https://github.com/jgm/pandoc)
- 开源"restaurant menu maker"搜索结果最高只有 6★（例如 `arcanemachine/django-menu-maker`，最近 push 2024-06），其余多停在 2018–2022 年 — [GitHub 搜索](https://github.com/search?q=menu+maker+restaurant&type=repositories)

### Inferences
- 技术栈是 Next.js，因此"改版样张"建议直接写成 Next.js 页面（Tailwind 模板加菜单 JSON），由 Playwright 在 FastAPI 或 worker 里渲染出 A4/A3 PDF 和缩略 PNG。这样模板和前端预览是同一份代码，所见即所得。
- 如果要做印刷交付（出血、CMYK、专色），Chromium PDF 的能力有限。Typst 对精确排版更友好，但 CMYK 支持仍需实测；这属于印刷工艺层面的风险。
- Gotenberg 适合作为独立的无状态渲染微服务（Docker），方便扩容，许可也是 MIT。
- pandoc 是 GPL-2.0，但只作为独立命令行工具调用时，一般不会"传染"调用方代码（这是常见解读，并非法律意见）。

### Gaps
- Typst 和 Chromium 输出 CMYK/PDF-X 印刷文件的能力未查证。
- 没有找到开源的菜单设计模板库；设计模板需要自建或采购。

## 问题 3：开源冷邮件、序列、预热和 WhatsApp 触达工具有哪些？

### Takeaway
**成熟的开源项目主要是 newsletter 或营销自动化平台**（Mautic GPL-3.0、listmonk AGPL-3.0、BillionMail AGPL-3.0、Postal MIT）。它们并不是为 Instantly/lemlist 式的"多邮箱轮换 + 个性化 + 回复即停"冷邮件序列设计的。这个领域唯一看起来较完整的开源项目是 **warmbly**（Apache-2.0，约 319★，项目很年轻），其余都只是几十星的小项目。建议**自建轻量序列引擎**（Postgres + Celery/n8n，通过 SMTP/IMAP 或 Gmail/Graph API 发送），邮件模板用 MJML 或 react-email（MIT）。WhatsApp 应坚持用 wa.me 链接由销售一键发送；Baileys、whatsapp-web.js、Evolution API（Baileys 模式）**有明确的封号风险**，只作为记录，不推荐使用。

### Cited Findings
- **mautic/mautic**：约 10.6k★，**GPL-3.0**（LICENSE.txt 写明 "GNU General Public License ... version 3 ... or later"），PHP，2026-09-25，已在开发 7.x 分支。提供营销自动化、drip campaign、线索评分和 API — [LICENSE](https://github.com/mautic/mautic/blob/7.x/LICENSE.txt)、[GitHub](https://github.com/mautic/mautic)
- **knadh/listmonk**：约 23.6k★，**AGPL-3.0**，Go 单二进制，2026-09-25。自托管的 newsletter 和邮件列表管理工具 — [GitHub](https://github.com/knadh/listmonk)
- **Billionmail/BillionMail**：约 15.6k★，**AGPL-3.0**，Go，2026-06-11。集邮件服务器、newsletter 和邮件营销于一体 — [GitHub](https://github.com/Billionmail/BillionMail)
- **postalserver/postal**：约 16.8k★，MIT，Ruby，2026-09-19。自建 MTA 投递平台（相当于 SendGrid 的替代） — [GitHub](https://github.com/postalserver/postal)
- **useplunk/plunk**：约 5.5k★，AGPL-3.0，2026-09-21；**usesend/useSend**：约 4.7k★，AGPL-3.0，2026-09-08，Resend/Sendgrid 的替代 — [plunk](https://github.com/useplunk/plunk)、[useSend](https://github.com/usesend/useSend)
- **dittofeed/dittofeed**：约 3k★，MIT，2026-03-28。多渠道客户触达（email、SMS、push 等） — [GitHub](https://github.com/dittofeed/dittofeed)
- **parcelvoy/platform**：MIT，**已归档**，最近 push 2025-09-04 — [GitHub](https://github.com/parcelvoy/platform)
- **warmbly/warmbly**：约 319★，Apache-2.0，Go，2026-09-25。README 称提供"multi-step sequences with per-mailbox caps and spacing"、统一收件箱、CRM、基于自有邮箱的预热、送达率追踪，以及 HubSpot/Slack/Zapier 集成；技术栈为 Go + PostgreSQL + Redis + Docker Compose；约 2,893 次 commit、71 fork — [GitHub](https://github.com/warmbly/warmbly)
- 其他冷邮件开源项目都很小：PaulleDemon/Email-automation（178★）、OutreachStud-io/studio（83★）、AbdelftahZowail/Quickly（41★，MIT，自称 Instantly/Smartlead/Lemlist 替代）、pypesdev/coldflow（18★，GPL-3.0）、nahumoore/lightreach（17★，MIT）。邮件预热类项目都不超过 6★ — [GitHub 搜索 cold email open source](https://github.com/search?q=cold+email+open+source&type=repositories)、[warmup 搜索](https://github.com/search?q=email+warmup&type=repositories)
- 邮件模板：**mjmlio/mjml** 约 18.2k★，MIT；**resend/react-email** 约 19.8k★，MIT — [mjml](https://github.com/mjmlio/mjml)、[react-email](https://github.com/resend/react-email)
- **chatwoot/chatwoot**：约 37.2k★，`enterprise/` 目录以外采用 MIT Expat；是全渠道收件箱（email、WhatsApp 等），可用作回复汇总台 — [LICENSE](https://github.com/chatwoot/chatwoot/blob/develop/LICENSE)
- wa.me 官方格式为 `https://wa.me/<国际号码纯数字>?text=<URL 编码消息>`。消息**只会预填，不会自动发送**，必须由用户点击发送 — [WhaTools](https://wha.tools/whatsapp-link-format)、[BusinessChat Help](https://help.businesschat.io/en/articles/6517838-how-to-build-a-whatsapp-click-to-chat-url-wa-me)
- **WhiskeySockets/Baileys**：约 11.1k★，MIT，2026-09-20。基于 WhatsApp Web 协议的非官方 socket API — [GitHub](https://github.com/WhiskeySockets/Baileys)
- **evolution-foundation/evolution-api**（已从 EvolutionAPI 组织迁出）：约 9.7k★，2026-07-14。许可是 Apache 2.0 加附加条件：不得移除前端 LOGO 和版权信息；用于任何项目（包括闭源项目）时有使用告知义务 — [LICENSE](https://github.com/evolution-foundation/evolution-api/blob/main/LICENSE)
- Evolution API 同时支持 Baileys 模式和官方 WhatsApp Cloud API；Baileys 连接器违反 WhatsApp 服务条款，风险属于"合同层面而非刑事层面" — [pasqualepillitteri.it](https://pasqualepillitteri.it/en/news/12969/integrate-whatsapp-evolution-api-vs-cloud-api)
- 有博客称，使用非官方 API 的号码通常在 2–8 周内被 Meta 识别，封禁是永久的且无法申诉；另有"68% 印度小企业 12 个月内至少被封一次"的说法。**这些来源是厂商或博客，数据可信度一般** — [SporeSec](https://sporesec.com/en/blog/whatsapp-unofficial-api-ban-risk)、[pasqualepillitteri.it](https://pasqualepillitteri.it/en/news/12969/integrate-whatsapp-evolution-api-vs-cloud-api)
- 同一来源称官方 Cloud API 自 2025-07-01 起按条计费，并且从 2026-10-01 起 24 小时窗口内的免费消息也将取消（未在 Meta 官方页面核实） — [pasqualepillitteri.it](https://pasqualepillitteri.it/en/news/12969/integrate-whatsapp-evolution-api-vs-cloud-api)
- **open-wa/wa-automate-nodejs**：约 3.7k★，自定义许可，2026-09-10。**pedroslopez/whatsapp-web.js** 查询时 API 返回 "Moved Permanently"（仓库已迁移或改名），星数未获取 — [open-wa](https://github.com/open-wa/wa-automate-nodejs)、[whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js)

### Inferences
- 冷邮件自建即可：一张 `sequence_steps` 表，Celery beat 或 n8n Cron 驱动，每个发信邮箱设日上限和随机间隔，IMAP 轮询检测回复后停止序列，再由 LLM 做回复分类。开源平台（Mautic 等）的"联系人必须 opt-in"数据模型与 B2B 冷启动场景不匹配，改造成本比自建还高。
- 欧盟冷邮件合规方面（GDPR 正当利益 + 各国 ePrivacy 对 B2B 的规定差异）不属于本次范围，但序列引擎应内置退订链接和 suppression list。
- WhatsApp 和 Instagram 维持"系统生成文案 + wa.me/ig.me 链接 + 销售手动发送"，零封号风险，也符合用户原设计。如果将来要自动化，应接官方 Cloud API（付费、须用模板消息、冷触达受限），而不是 Baileys。
- warmbly 功能最贴近需求，但项目只有 319★，时间也短，建议先 PoC 验证稳定性，而不是作为核心依赖。邮件预热在 2026 年普遍被视为效果有限，送达率更依赖 SPF/DKIM/DMARC 配置、独立的发信域名和低发送量；这一点只是推断，没有找到权威来源。

### Gaps
- Instagram DM 没有官方的冷触达 API，开源方案只有非官方私有 API 库（本次未检索），风险高于 WhatsApp。
- Meta 2026 年 Cloud API 定价未在官方页面核实。
- 未找到开源 warmup 网络的实际效果数据。

## 问题 4：哪些开源 CRM 适合作为销售工作台？许可证和 API 情况如何？

### Takeaway
在"现代 UI、API 优先、可接 Next.js/FastAPI"这一需求下，**Twenty**（AGPL-3.0，但官方附加了"通过 API 开发的应用不受 AGPL 约束"的例外）和 **Krayin**（MIT，Laravel）是首选候选；**Atomic CRM**（MIT，React + Supabase）适合作为可以直接 fork 的轻量代码底座。EspoCRM、SuiteCRM、Frappe CRM 都是 AGPL；Odoo 社区版是 LGPL-3。NocoDB **已于 2026-01 从 AGPL 转为 Sustainable Use License**，不再适合替客户托管。Baserow 核心 MIT，premium 目录另有许可。本系统工作台高度定制（菜单样张、wa.me 一键发送），**更推荐自建 Next.js 工作台，外部 CRM 只作为可选同步目标**。

### Cited Findings
- **twentyhq/twenty**：约 57.5k★，2026-09-25，TypeScript。主体为 AGPLv3；标注 `@license Enterprise` 的文件属于商业许可；twenty-sdk、twenty-ui 等包为 MIT。另有例外条款：通过其公开 API（REST/GraphQL/webhook/SDK）开发应用，"does not, by itself, cause the Application to be governed by the AGPLv3" — [LICENSE](https://github.com/twentyhq/twenty/blob/main/LICENSE)
- **krayin/laravel-crm**：约 23.9k★，**MIT**，PHP/Laravel，2026-09-21。面向线索和销售管理 — [GitHub](https://github.com/krayin/laravel-crm)
- **marmelab/atomic-crm**：约 1.3k★，**MIT**，React + shadcn/ui + Supabase，2026-09-25 — [GitHub](https://github.com/marmelab/atomic-crm)
- **espocrm/espocrm**：约 3.4k★，**AGPL-3.0**，PHP，2026-09-24 — [GitHub](https://github.com/espocrm/espocrm)
- **SuiteCRM/SuiteCRM**：约 5.8k★，**AGPL-3.0**，PHP，2026-09-17 — [GitHub](https://github.com/SuiteCRM/SuiteCRM)
- **frappe/crm**：约 3.6k★，**AGPL-3.0**，Vue，2026-09-25 — [GitHub](https://github.com/frappe/crm)
- **odoo/odoo**：约 54.6k★，社区版为 **LGPLv3**（企业版模块另有专有许可），Python，2026-09-25 — [LICENSE](https://github.com/odoo/odoo/blob/master/LICENSE)
- **erxes/erxes**：约 4.1k★，AGPLv3 加 `-ee` 插件商业许可，并额外规定"not permitted to be hosted as a SaaS version to compete with erxes Inc." — [LICENSE](https://github.com/erxes/erxes/blob/main/LICENSE.md)
- **nocodb/nocodb**：约 65.1k★。据其许可说明和社区讨论，自 2026-01-09 起从 AGPL-3.0 转为 Sustainable Use License：只允许"internal business purposes"或非商业使用，向第三方提供托管服务可能需要商业授权 — [NocoDB License](https://nocodb.com/docs/self-hosting/license)、[Cloudron 论坛](https://forum.cloudron.io/topic/14918/heads-up-nocodb-is-no-longer-open-source.)
- **baserow/baserow**：约 6k★，2026-09-25。`premium/` 目录另有许可，文档为 CC BY-SA 4.0，其余部分未在截取的 LICENSE 片段中完整看到（历史上核心为 MIT，需核实） — [LICENSE](https://github.com/baserow/baserow/blob/develop/LICENSE)
- **nocobase/nocobase**：约 24.4k★，采用自定义的"NocoBase License Agreement"（2026-02-24 更新），不是标准 OSI 许可 — [LICENSE](https://github.com/nocobase/nocobase/blob/main/LICENSE.txt)

### Inferences
- 交付客户时，AGPL 的主要义务是：如果**修改**了 AGPL 软件并通过网络提供给用户，须向这些用户提供修改后的源码。不修改、只通过 API 集成，通常风险较低；Twenty 更是明文给出了 API 例外。这是常见解读，不构成法律意见。
- 自建工作台（Next.js + FastAPI + Postgres）的理由：需要"菜单前后对比、一键 wa.me、LLM 回复分类、任务队列"这些高度定制的视图，通用 CRM 都要二次开发。Krayin 和 Atomic CRM 可以作为数据模型和 UI 的参考，Atomic CRM 的 MIT 代码可直接借用。
- 如果客户已经在用 CRM（如 HubSpot、Pipedrive），做单向同步即可。如果客户想要"开箱即用的 CRM"，推荐由客户自己部署 Twenty（仍须遵守 AGPL，不修改源码最省事）。
- NocoDB 转为 SUL 之后，不宜由乙方托管给客户；Baserow 的 premium 功能需付费。作为"轻量表格后台"的选项，二者优先级都下降。

### Gaps
- Baserow 核心许可的完整文本未确认（截取片段不完整）。
- Twenty 企业功能（如 SSO、审计日志）的具体清单和价格未查。

## 问题 5：n8n 模板、编排选型以及 SUL 许可对交付客户的影响

### Takeaway
n8n 官方模板库的 Lead Generation 分类有 881 个工作流，其中多个模板覆盖"Google Maps 抓取 → AI 富化 → 个性化外联"，可以作为 PoC 参考。但 n8n 采用 **Sustainable Use License（fair-code，非 OSI 开源）**：**乙方在自己的实例上为客户构建、运行、维护工作流并收费是允许的**，客户在自有基础设施上为内部业务部署 n8n 也允许；**白标转售、托管 n8n 让客户自己编辑工作流、嵌入工作流编辑器**则需要商业或 Embed 许可。如果希望核心编排不受约束，可以用 **Celery（BSD-3）** 做主干，n8n 只作为可替换的"胶水层"，或者改用 Activepieces（MIT 核心）。

### Cited Findings
- n8n 仓库约 205.9k★，2026-09-25，自称"Fair-code workflow automation platform" — [GitHub](https://github.com/n8n-io/n8n)
- SUL 条款：允许"use, copy, distribute, make available, and prepare derivative works"，但仅限内部业务或非商业用途；分发只能免费且面向非商业用途；文件名或路径中含 `.ee.` 的文件不在 SUL 范围内，需要 n8n Enterprise License — [LICENSE.md](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)
- 官方 FAQ 允许的用法："Build automations for your clients on your instance, as long as your clients do not have the possibility to create or edit them"；在自有基础设施上用社区版支撑自身业务；把 n8n 作为自己产品的后台引擎，让用户触发你搭建好的自动化 — [n8n License FAQ](https://docs.n8n.io/n8n-community-license/community-license/license-faq)
- 官方 FAQ 禁止的用法：白标 n8n、"Host n8n as a service and allow your clients to build workflows"、让外部用户通过你的产品构建或配置自己的工作流（即使 n8n 对用户不可见，也需要 Enterprise 许可） — [n8n License FAQ](https://docs.n8n.io/n8n-community-license/community-license/license-faq)
- **来源冲突**：有二手搜索摘要称"在你运营的实例上永久托管客户的工作流或凭据"就需要付费许可，这与官方 FAQ 中"在你的实例上为客户构建"的表述存在张力。官方社区对"B2B 咨询使用客户凭据"也有专门讨论。建议以官方 FAQ 为准，边界情况发邮件到 license@n8n.io 确认 — [社区帖](https://community.n8n.io/t/is-b2b-consulting-with-client-credentials-allowed-under-sustainable-use-license/233319)、[n8n License FAQ](https://docs.n8n.io/n8n-community-license/community-license/license-faq)
- 相关模板示例：#6091 Google Maps lead scraper & enrichment with AI-powered personalized outreach（Apify + Firecrawl + AI 生成外联内容）、#5743 Apify + GPT + Airtable、#2567 不依赖第三方 API 抓取 Google Maps 商家邮箱、#6993 按区域抓取 Google Maps 并生成外联消息、#13582 用 Apify + Jina AI + GPT-5.2 富化 Google Maps 线索；Lead Generation 分类共 881 个工作流 — [#6091](https://n8n.io/workflows/6091-google-maps-lead-scraper-and-enrichment-with-ai-powered-personalized-outreach/)、[#5743](https://n8n.io/workflows/5743-scrape-google-maps-leads-email-phone-website-using-apify-gpt-airtable/)、[#2567](https://n8n.io/workflows/2567-scrape-business-emails-from-google-maps-without-the-use-of-any-third-party-apis/)、[#6993](https://n8n.io/workflows/6993-scrape-google-maps-by-area-and-generate-outreach-messages-for-lead-generation/)、[#13582](https://n8n.io/workflows/13582-enrich-b2b-google-maps-leads-with-apify-jina-ai-gpt-52-and-google-sheets/)、[分类页](https://n8n.io/workflows/categories/lead-generation/)
- 社区模板合集：**Zie619/n8n-workflows** 约 56.8k★，MIT，最近 push 2026-06-24；**enescingoz/awesome-n8n-templates** 约 25.6k★，2026-09-12，含 280+ 模板 — [n8n-workflows](https://github.com/Zie619/n8n-workflows)、[awesome-n8n-templates](https://github.com/enescingoz/awesome-n8n-templates)
- 替代方案：**activepieces/activepieces** 约 24.7k★，`packages/ee` 以外为 MIT；**windmill-labs/windmill** 约 18k★，默认 AGPL，部分 Apache，另有企业专有功能；**celery/celery** 约 28.9k★，BSD-3-Clause — [activepieces LICENSE](https://github.com/activepieces/activepieces/blob/main/LICENSE)、[windmill LICENSE](https://github.com/windmill-labs/windmill/blob/main/LICENSE)、[celery LICENSE](https://github.com/celery/celery/blob/main/LICENSE)

### Inferences
- 交付模式建议：
  - **(A)** 产品核心（抓取、解析、序列、分类）写在 FastAPI + Celery 中，许可干净，可以整体交付源码；n8n 只用于客户可见性不高的集成胶水（如 Slack/Sheets 通知），由客户在其自有服务器部署，属于"内部业务用途"。
  - **(B)** 如果系统要给客户提供"自定义自动化"界面，就不能基于 n8n 社区版，应改用 Activepieces（MIT）或自研。
- n8n 模板多依赖 Apify、Firecrawl 等付费 SaaS，只适合作为流程参考，不宜直接照搬为生产方案。

### Gaps
- 未取得 n8n Embed/Enterprise 的 2026 年报价。
- "乙方托管 n8n、客户只看结果"与"永久托管客户凭据"之间的边界，官方 FAQ 与二手解读不完全一致。

## 问题 6：端到端开源 AI SDR / 线索富化 Agent 项目成熟度如何？

### Takeaway
**成熟度普遍偏低**。最有名的 SalesGPT（MIT，约 2.8k★）**最近 push 是 2024-09-17，已停更 2 年**；其余 "AI SDR" 仓库大多是个位数到几百星的 demo 或 n8n 工作流，没有能直接复用为生产主干的项目。可取的是设计思路（多 agent：调研 → 评分 → 撰写 → 跟进 → 回复分类），实现上用 LangGraph（MIT）或 PydanticAI（MIT）自建。

### Cited Findings
- **filip-michalsky/SalesGPT**：约 2.8k★，MIT，最近 push 2024-09-17。"Context-aware AI Sales Agent to automate sales outreach" — [GitHub](https://github.com/filip-michalsky/SalesGPT)、[LICENSE](https://github.com/filip-michalsky/SalesGPT/blob/main/LICENSE)
- **kaymen99/sales-outreach-automation-langgraph**：约 392★，无许可证，最近 push 2025-01-15。用 LangGraph 做线索调研、资格判定和外联（**没有许可证就不能合法复用代码**） — [GitHub](https://github.com/kaymen99/sales-outreach-automation-langgraph)
- **iPythoning/b2b-sdr-agent-template**：约 188★，MIT，2026-08-20。面向 B2B 外贸的 AI SDR 模板，号称 10 阶段销售管线、多渠道（WhatsApp + Telegram + Email），基于 OpenClaw 构建 — [GitHub](https://github.com/iPythoning/b2b-sdr-agent-template)
- **MatthewDailey/open-sdr**：约 26★，无许可证，2025-05-18。一个提供调研和线索生成工具的 MCP server — [GitHub](https://github.com/MatthewDailey/open-sdr)
- **thefalc/multi-agent-ai-sdr-flink-orchestrator**：约 45★，MIT，2025-05-19，事件驱动的多 agent 线索处理 demo — [GitHub](https://github.com/thefalc/multi-agent-ai-sdr-flink-orchestrator)
- 线索富化类：**masteranime/enrichment-kit**（约 39★，MIT，2026-08-29，自称开源 Clay 替代，支持多供应商瀑布式富化）、**codyschneiderx/waterfall-gtm**（约 36★，MIT）、**getbeton/beton-ai**（约 75★，MIT）、**Astoriel/LeadGenius**（约 32★，无许可证，线索评分和路由） — [enrichment-kit](https://github.com/masteranime/enrichment-kit)、[waterfall-gtm](https://github.com/codyschneiderx/waterfall-gtm)、[beton-ai](https://github.com/getbeton/beton-ai)、[LeadGenius](https://github.com/Astoriel/LeadGenius)
- Google Maps 抓取（相邻模块）：**gosom/google-maps-scraper** 约 6.1k★，MIT，Go，2026-09-24；**omkarcloud/google-maps-scraper** 约 3.5k★，MIT，2026-09-21 — [gosom](https://github.com/gosom/google-maps-scraper)、[omkarcloud](https://github.com/omkarcloud/google-maps-scraper)
- 回复分类方面没有成熟的开源专用项目，搜索 "email reply classification" 最高只有 28★（ericporres/email-triage-plugin，一个 Claude 插件模板） — [GitHub](https://github.com/ericporres/email-triage-plugin)
- 编排框架：**langchain-ai/langgraph** 约 42.3k★，MIT，2026-09-23 — [GitHub](https://github.com/langchain-ai/langgraph)
- Hugging Face 博客在 2025-02 汇总了 30 个线索生成和外联开源项目（SalesGPT、Dittofeed、theHarvester、LeadGenPy、Chatwoot、whatsapp-web.js、Mautic、Krayin 等），可作为补充清单，但部分项目已停更 — [HF Blog](https://huggingface.co/blog/samihalawa/automating-lead-generation-with-ai)

### Inferences
- "AI SDR"部分应作为本系统自研的核心能力（这也是差异化所在）：用 PydanticAI 或 Instructor 完成结构化的调研、评分和文案生成，回复分类用 LLM zero/few-shot，标签固定为 interested / not_now / not_interested / wrong_contact / out_of_office / unsubscribe，再用 Celery 调度跟进任务。
- 所有没有 LICENSE 的仓库只能作为思路参考，不能复制代码。

### Gaps
- 没有找到任何开源 AI SDR 项目的生产使用案例或转化数据。

---

## 附：推荐的 build vs reuse 架构（汇总）

| 模块 | 推荐 | 许可 | 做法 |
|---|---|---|---|
| (a) 菜单解析 | crawl4ai（HTML）+ Docling（PDF）+ PaddleOCR 或多模态 LLM（图片）+ Instructor/PydanticAI（schema 抽取） | Apache/MIT | **复用组件，自建管线和 schema** |
| (a') 备选 | MinerU（须注明使用）、Marker（500 万美元门槛）、LangExtract（需要溯源到原文时） | 带条件 | 评估后启用 |
| (b) 样张渲染 | Next.js 模板 + Playwright（或 Gotenberg 微服务）生成 PDF/PNG；印刷级需求用 Typst | Apache/MIT | **复用引擎，自建模板** |
| (c) 邮件发送 | 自建序列引擎（Postgres + Celery），SMTP/Gmail/Graph API 发信；MJML/react-email 模板；需要自建 MTA 时用 Postal（MIT） | MIT/BSD | **自建**；warmbly 做 PoC 对照 |
| (c') WhatsApp/IG | 生成文案 + wa.me/ig.me 链接，销售一键发送 | — | **自建（很简单）**；Baileys/Evolution 不采用 |
| (d) 任务与回复分类 | Celery beat + IMAP 轮询 + LLM 分类；统一收件箱可选 Chatwoot（MIT 部分） | BSD/MIT | **自建** |
| (e) CRM 工作台 | 自建 Next.js 工作台（参考或借用 Atomic CRM 的 MIT 代码）；客户想要独立 CRM 时选 Twenty（API 例外）或 Krayin（MIT） | MIT/AGPL+例外 | **自建为主，外部 CRM 只做同步** |
| 编排 | Celery 做主干；n8n 只做内部胶水，由客户自托管，或改用 Activepieces（MIT） | BSD / SUL | 避免把 n8n 放在交付物核心 |

### 排序后的短名单（按采用优先级）
1. **Docling**（MIT，67.9k★，活跃）：PDF 菜单解析主力，许可最干净。
2. **Instructor / PydanticAI**（MIT）：schema 化抽取、评分和回复分类的统一底座。
3. **Playwright**（Apache-2.0）：HTML 模板渲染 PDF/PNG，与 Next.js 同源。
4. **crawl4ai**（Apache-2.0，84k★）：官网菜单页转 Markdown。
5. **PaddleOCR**（Apache-2.0）：图片菜单 OCR，成本低的兜底方案。
6. **Celery**（BSD-3）：序列和跟进调度主干，没有许可顾虑。
7. **Gotenberg**（MIT）：独立 PDF 渲染微服务（可选）。
8. **Twenty**（AGPL + API 例外）或 **Krayin**（MIT）：客户需要独立 CRM 时选用。
9. **Postal**（MIT）或 **MJML/react-email**（MIT）：发信基础设施和模板。
10. **warmbly**（Apache-2.0）：冷邮件序列和预热的 PoC 对照，成熟度待验证。
- 不推荐作为核心：n8n（SUL）、NocoDB（2026 年起 SUL）、listmonk/BillionMail/Plunk/useSend（AGPL，且不是冷邮件场景）、Carbone 社区版（CCL）、wkhtmltopdf（已归档）、zerox（停更）、SalesGPT（停更）、Baileys/whatsapp-web.js/Evolution-Baileys 模式（封号风险）。

### 全部候选表（2026-09-25 GitHub API 数据）

| 类别 | 仓库 | ★ | 许可 | 最近 push | 语言 | 适配度 | 风险 |
|---|---|---|---|---|---|---|---|
| 解析 | [docling-project/docling](https://github.com/docling-project/docling) | 67.9k | MIT | 2026-09-25 | Py | 高 | 低 |
| 解析 | [microsoft/markitdown](https://github.com/microsoft/markitdown) | 187k | MIT | 2026-09-21 | Py | 中（OCR 弱） | 低 |
| 解析 | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | 90.2k | Apache-2.0 | 2026-09-16 | Py | 高（图片） | Paddle 依赖较重 |
| 解析 | [opendatalab/MinerU](https://github.com/opendatalab/MinerU) | 80.6k | Apache+附加 | 2026-09-24 | Py | 高 | 在线服务须注明；超大规模门槛 |
| 解析 | [datalab-to/marker](https://github.com/datalab-to/marker) | 40k | 代码 Apache / 权重 Rail-M | 2026-09-13 | Py | 高 | 权重 500 万美元商用门槛 |
| 解析 | [google/langextract](https://github.com/google/langextract) | 38.8k | Apache-2.0 | 2026-09-21 | Py | 中高（文本抽取+溯源） | 低 |
| 解析 | [deepseek-ai/DeepSeek-OCR](https://github.com/deepseek-ai/DeepSeek-OCR) | 23.9k | MIT | 2026-01-27 | Py | 中 | 需 GPU |
| 解析 | [datalab-to/surya](https://github.com/datalab-to/surya) | 21.4k | Apache（代码） | 2026-09-11 | Py | 中 | 权重许可未核实 |
| 解析 | [allenai/olmocr](https://github.com/allenai/olmocr) | 19.7k | Apache-2.0 | 2026-03-25 | Py | 中 | 需 GPU，偏批量处理 |
| 解析 | [Unstructured-IO/unstructured](https://github.com/Unstructured-IO/unstructured) | 15.5k | Apache-2.0 | 2026-09-25 | Py | 中 | 较重 |
| 解析 | [567-labs/instructor](https://github.com/567-labs/instructor) | 13.9k | MIT | 2026-09-24 | Py | 高 | 低 |
| 解析 | [datalab-to/chandra](https://github.com/datalab-to/chandra) | 12.3k | Apache（代码） | 2026-06-26 | Py | 中 | 权重许可未核实 |
| 解析 | [getomni-ai/zerox](https://github.com/getomni-ai/zerox) | 12.3k | MIT | 2025-05-20 | TS | 中 | 停更超过 12 个月 |
| 解析 | [studio-dots-ai/dots.ocr](https://github.com/studio-dots-ai/dots.ocr) | 9.2k | MIT | 2026-03-24 | Py | 中 | 需 GPU |
| 解析 | [run-llama/llama_cloud_services](https://github.com/run-llama/llama_cloud_services) | 4.3k | MIT（客户端） | 2026-05-18 | TS | 低 | 云端付费 |
| 解析 | [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 20.2k | MIT | 2026-09-25 | Py | 高 | 低 |
| 抓取 | [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai) | 84.3k | Apache-2.0 | 2026-09-25 | Py | 高 | 低 |
| 抓取 | [ScrapeGraphAI/Scrapegraph-ai](https://github.com/ScrapeGraphAI/Scrapegraph-ai) | 31.3k | MIT | 2026-09-25 | Py | 中 | 低 |
| 渲染 | [microsoft/playwright](https://github.com/microsoft/playwright) | 96.7k | Apache-2.0 | 2026-09-25 | TS | 高 | 低 |
| 渲染 | [puppeteer/puppeteer](https://github.com/puppeteer/puppeteer) | 95.6k | Apache-2.0 | 2026-09-25 | TS | 高 | 低 |
| 渲染 | [typst/typst](https://github.com/typst/typst) | 56.2k | Apache-2.0 | 2026-09-24 | Rust | 中高（印刷） | 模板需另学 |
| 渲染 | [diegomura/react-pdf](https://github.com/diegomura/react-pdf) | 16.8k | MIT | 2026-09-23 | TS | 中 | CSS 子集有限 |
| 渲染 | [vercel/satori](https://github.com/vercel/satori) | 14k | MPL-2.0 | 2026-09-22 | TS | 中（PNG 缩略图） | 低 |
| 渲染 | [gotenberg/gotenberg](https://github.com/gotenberg/gotenberg) | 13.2k | MIT | 2026-09-25 | Go | 高 | 低 |
| 渲染 | [Kozea/WeasyPrint](https://github.com/Kozea/WeasyPrint) | 9.6k | BSD-3 | 2026-09-24 | Py | 中高 | 不支持 JS |
| 渲染 | [pdfme/pdfme](https://github.com/pdfme/pdfme) | 4.8k | MIT | 2026-09-21 | TS | 中（WYSIWYG） | 低 |
| 渲染 | [carboneio/carbone](https://github.com/carboneio/carbone) | 2.1k | CCL | 2026-04-07 | JS | 低 | 禁止以服务形式提供 |
| 渲染 | [wkhtmltopdf/wkhtmltopdf](https://github.com/wkhtmltopdf/wkhtmltopdf) | 14.6k | LGPL-3.0 | 2022-11（已归档） | C++ | 不用 | 已归档 |
| 渲染 | [Stirling-Tools/Stirling-PDF](https://github.com/Stirling-Tools/Stirling-PDF) | 93k | MIT+专有目录 | 2026-09-25 | Java | 低（后处理） | 部分专有 |
| 触达 | [mautic/mautic](https://github.com/mautic/mautic) | 10.6k | GPL-3.0 | 2026-09-25 | PHP | 中低 | GPL；opt-in 模型 |
| 触达 | [knadh/listmonk](https://github.com/knadh/listmonk) | 23.6k | AGPL-3.0 | 2026-09-25 | Go | 低 | AGPL；newsletter 定位 |
| 触达 | [Billionmail/BillionMail](https://github.com/Billionmail/BillionMail) | 15.6k | AGPL-3.0 | 2026-06-11 | Go | 低 | AGPL |
| 触达 | [postalserver/postal](https://github.com/postalserver/postal) | 16.8k | MIT | 2026-09-19 | Ruby | 中（自建 MTA） | IP 信誉需自行运维 |
| 触达 | [useplunk/plunk](https://github.com/useplunk/plunk) | 5.5k | AGPL-3.0 | 2026-09-21 | TS | 低 | AGPL |
| 触达 | [usesend/useSend](https://github.com/usesend/useSend) | 4.7k | AGPL-3.0 | 2026-09-08 | TS | 低 | AGPL |
| 触达 | [dittofeed/dittofeed](https://github.com/dittofeed/dittofeed) | 3k | MIT | 2026-03-28 | TS | 中 | 偏 B2C 生命周期营销 |
| 触达 | [warmbly/warmbly](https://github.com/warmbly/warmbly) | 319 | Apache-2.0 | 2026-09-25 | Go | 高（功能） | 年轻、社区小 |
| 触达 | [PaulleDemon/Email-automation](https://github.com/PaulleDemon/Email-automation) | 178 | 自定义 | 2026-08-20 | JS | 低 | 小项目 |
| 触达 | [AbdelftahZowail/Quickly](https://github.com/AbdelftahZowail/Quickly) | 41 | MIT | 2026-09-22 | Py | 低 | 小项目 |
| 触达 | [mjmlio/mjml](https://github.com/mjmlio/mjml) | 18.2k | MIT | 2026-09-25 | JS | 高（模板） | 低 |
| 触达 | [resend/react-email](https://github.com/resend/react-email) | 19.8k | MIT | 2026-09-23 | TS | 高（模板） | 低 |
| 收件箱 | [chatwoot/chatwoot](https://github.com/chatwoot/chatwoot) | 37.2k | MIT+enterprise 目录 | 2026-09-25 | Ruby | 中 | 部署较重 |
| WhatsApp | [WhiskeySockets/Baileys](https://github.com/WhiskeySockets/Baileys) | 11.1k | MIT | 2026-09-20 | JS | 不推荐 | **违反 WhatsApp 服务条款，封号风险** |
| WhatsApp | [evolution-foundation/evolution-api](https://github.com/evolution-foundation/evolution-api) | 9.7k | Apache+附加条件 | 2026-07-14 | TS | 仅官方 Cloud API 模式可考虑 | Baileys 模式有封号风险；LOGO/告知义务 |
| WhatsApp | [open-wa/wa-automate-nodejs](https://github.com/open-wa/wa-automate-nodejs) | 3.7k | 自定义 | 2026-09-10 | TS | 不推荐 | 同上 |
| WhatsApp | [pedroslopez/whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) | 未获取（仓库已迁移） | — | — | JS | 不推荐 | 同上 |
| CRM | [twentyhq/twenty](https://github.com/twentyhq/twenty) | 57.5k | AGPL+API 例外+EE | 2026-09-25 | TS | 高 | 修改源码须开源 |
| CRM | [odoo/odoo](https://github.com/odoo/odoo) | 54.6k | LGPL-3（社区版） | 2026-09-25 | Py | 中 | 较重 |
| CRM | [krayin/laravel-crm](https://github.com/krayin/laravel-crm) | 23.9k | MIT | 2026-09-21 | PHP | 中高 | 与主栈（PHP）不同 |
| CRM | [SuiteCRM/SuiteCRM](https://github.com/SuiteCRM/SuiteCRM) | 5.8k | AGPL-3.0 | 2026-09-17 | PHP | 低 | AGPL；老旧 |
| CRM | [erxes/erxes](https://github.com/erxes/erxes) | 4.1k | AGPL+禁止竞争性 SaaS | 2026-09-25 | TS | 低 | 许可限制 |
| CRM | [frappe/crm](https://github.com/frappe/crm) | 3.6k | AGPL-3.0 | 2026-09-25 | Vue | 中 | AGPL；需要 Frappe 框架 |
| CRM | [espocrm/espocrm](https://github.com/espocrm/espocrm) | 3.4k | AGPL-3.0 | 2026-09-24 | PHP | 中 | AGPL |
| CRM | [marmelab/atomic-crm](https://github.com/marmelab/atomic-crm) | 1.3k | MIT | 2026-09-25 | TS | 高（可 fork 的底座） | 社区小 |
| 表格后台 | [nocodb/nocodb](https://github.com/nocodb/nocodb) | 65.1k | **SUL（2026-01 起）** | 2026-09-25 | TS | 低 | 不能替客户托管 |
| 表格后台 | [baserow/baserow](https://github.com/baserow/baserow) | 6k | 核心开源+premium 另授权 | 2026-09-25 | Py | 中 | premium 付费 |
| 表格后台 | [nocobase/nocobase](https://github.com/nocobase/nocobase) | 24.4k | 自定义协议 | 2026-09-25 | TS | 低 | 非 OSI 许可 |
| 编排 | [n8n-io/n8n](https://github.com/n8n-io/n8n) | 205.9k | SUL + .ee | 2026-09-25 | TS | 中（胶水） | 不能白标、不能让客户编辑工作流 |
| 编排 | [activepieces/activepieces](https://github.com/activepieces/activepieces) | 24.7k | MIT+ee 目录 | 2026-09-25 | TS | 中高 | ee 功能付费 |
| 编排 | [windmill-labs/windmill](https://github.com/windmill-labs/windmill) | 18k | AGPL/Apache+专有 | 2026-09-25 | Rust | 中 | AGPL |
| 编排 | [celery/celery](https://github.com/celery/celery) | 28.9k | BSD-3 | 2026-09-24 | Py | 高 | 低 |
| 模板 | [Zie619/n8n-workflows](https://github.com/Zie619/n8n-workflows) | 56.8k | MIT | 2026-06-24 | Py | 参考 | 质量参差 |
| 模板 | [enescingoz/awesome-n8n-templates](https://github.com/enescingoz/awesome-n8n-templates) | 25.6k | 未声明 | 2026-09-12 | — | 参考 | 质量参差 |
| AI SDR | [filip-michalsky/SalesGPT](https://github.com/filip-michalsky/SalesGPT) | 2.8k | MIT | 2024-09-17 | — | 参考 | **停更 2 年** |
| AI SDR | [kaymen99/sales-outreach-automation-langgraph](https://github.com/kaymen99/sales-outreach-automation-langgraph) | 392 | 无 | 2025-01-15 | Py | 参考 | 无许可证，不能复用 |
| AI SDR | [iPythoning/b2b-sdr-agent-template](https://github.com/iPythoning/b2b-sdr-agent-template) | 188 | MIT | 2026-08-20 | Shell | 参考 | 依赖 OpenClaw；小项目 |
| AI SDR | [MatthewDailey/open-sdr](https://github.com/MatthewDailey/open-sdr) | 26 | 无 | 2025-05-18 | TS | 低 | 无许可证 |
| 富化 | [masteranime/enrichment-kit](https://github.com/masteranime/enrichment-kit) | 39 | MIT | 2026-08-29 | TS | 参考 | 小项目 |
| 富化 | [getbeton/beton-ai](https://github.com/getbeton/beton-ai) | 75 | MIT | 2026-05-22 | TS | 低 | 小项目 |
| 抓取 | [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) | 6.1k | MIT | 2026-09-24 | Go | 高（相邻模块） | 违反 Google 服务条款 |
| 抓取 | [omkarcloud/google-maps-scraper](https://github.com/omkarcloud/google-maps-scraper) | 3.5k | MIT | 2026-09-21 | — | 中 | 同上 |
| 编排 | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 42.3k | MIT | 2026-09-23 | Py | 中高 | 抽象层较重 |
