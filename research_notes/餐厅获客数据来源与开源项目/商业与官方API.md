# 餐厅获客：商业与官方 POI/地点数据 API 对比（EU + UK，截至 2026-09-25）

> 本文件是对 `欧洲餐厅菜单获客系统可行性/数据来源.md` 的补充，已知内容（Google SKU 价格、Foursquare Pro/Premium 字段与 CPM、Yelp 套餐价、Tripadvisor 免费 5,000 次、Outscraper 价格、OSM 覆盖率）不再重复，只补新发现与条款原文。
> 条款原文为 2026-09-25 用 curl 直接抓取官方页面后检索得到。标注"（二手）"的来自厂商博客或第三方汇总。

## 1. Google Places API (New) 与 Google Business Profile：存储条款原文、EEA 条款、"获客"用途、Text Search 上限、开业日期/社交字段

### Takeaway
**全球版条款**明确禁止"copy and save business names, addresses, or user reviews"（复制并保存商家名称、地址或用户评论），只有 place_id 可以长期保存、经纬度可以缓存 30 天，所以不能拿 Google 数据建一个长期保存的 CRM 线索库。**EEA 条款（适用于结算地址在 EEA 的账户）**反而有一条白名单用途：*"enable Customers to visualize and manage Places content related to a sales team's customers or opportunities"*，即"查看和管理与销售团队的客户或商机相关的 Places 内容"。这条可以支持在 CRM 界面里实时展示 Google 数据，但不等于允许存储；"不得缓存"和"不得复制保存"两条依然有效。Text Search 单个查询最多返回 60 条。没有社交链接字段。`openingDate` 只用于尚未开业的商家。

### Cited Findings
- 全球版 Google Maps Platform ToS §3.2.3(a) No Scraping 原文："Customer will not export, extract, or otherwise scrape Google Maps Content for use outside the Services. For example, Customer will not: (i) pre-fetch, index, store, reshare, or rehost Google Maps Content outside the services; (ii) bulk download … places information …; (iii) copy and save business names, addresses, or user reviews"。§3.2.3(b) No Caching："Customer will not cache Google Maps Content except as expressly permitted under the Maps Service Specific Terms"。§3.2.3(c) 禁止基于 Google Maps Content 创建内容。§3.2.3(e) 禁止在非 Google 地图上显示或使用 Places 内容。页面标注 Last modified 2026-08-26 — [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms)
- 全球版 Service Specific Terms §14 Places API (Legacy and New)：14.1 可以在没有 Google 地图的应用中使用 Places 内容；14.2 不得与非 Google 地图一起使用；14.3 "Customer may temporarily cache latitude and longitude values from the Places API for up to 30 consecutive calendar days"。页面最后修改日期为 2026-06-10 — [Maps Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)
- EEA ToS §3.3.2(a) No Scraping 与全球版基本相同，同样写有"(iii) copy and save business names, addresses, or user reviews"；(b) No Caching 也相同。最后修改日期为 2026-08-26 — [Google Maps Platform EEA ToS](https://cloud.google.com/terms/maps-platform/eea)
- EEA Service Specific Terms §15：15.1 除 lat/lng 和 place_id 外，Places 内容不得与**任何**地图一起使用；15.2 除 lat/lng 和 place_id 外，只能用于 "Places API EEA Permitted Uses"；15.4 lat/lng 可以缓存 30 天；通用缓存条款允许缓存 place_id。最后修改日期为 2026-06-10 — [EEA Service Specific Terms](https://cloud.google.com/terms/maps-platform/eea/maps-service-terms)
- EEA 允许的 9 类用途（白名单），其中第 (3) 类为："enable Customers to visualize and manage Places content related to a sales team's customers or opportunities"。其余包括地址自动补全、展示自家门店、生产力工具中给地点关联任务/备注、房产周边 POI、金融交易地点、游戏、社交标记、智能家居。页面最后修改日期为 2025-06-04 — [Places API EEA Permitted Uses](https://cloud.google.com/terms/maps-platform/eea-places-api-permitted-uses)
- Text Search (New)：每页最多 20 条，"Text Search (New) returns a maximum of 60 results across all pages, although this limit is subject to change"；`places.openingDate`（year/month/day）是"the anticipated opening date of the business"，需要在请求中设置 `includeFutureOpeningBusinesses`；文档中没有社交媒体字段，URL 类字段只有 websiteUri、googleMapsUri、searchUri — [Text Search (New)](https://developers.google.com/maps/documentation/places/web-service/text-search)
- （二手）一家厂商的汇总认为，Google 只有 place ID 可以无限期保存，其他展示字段都没有缓存例外 — [Open Places API 博客 2026-08-04](https://openplacesapi.com/blog/can-you-store-places-api-results)

### Inferences
- **两种"获客"用途的边界**：(a) 把 Google 返回的名称、电话、网站、评分写进自建 CRM 长期保存：全球版与 EEA 版都有"copy and save business names, addresses"与"No Caching"条款，**不允许**。(b) CRM 只存 place_id，打开线索页时实时调用 Places API 展示 Google 字段：全球版允许在无地图的应用中使用（§14.1）；EEA 版需要落在白名单第 (3) 类，而"销售团队的客户或商机"与"对潜在客户的销售跟进"字面上相符，灰度小于 (a)。但如果用 Google 批量"发现"商机本身，仍可能被视为 bulk download places information。建议结构：Google 只作为发现渠道和实时展示层，CRM 只保存 place_id 与从餐厅官网自采的数据。
- 按城市铺开时，受 60 条上限影响，需要按"网格 × 菜系关键词"切分查询；5,000 家约需 300–1,000 次请求（考虑重叠）。
- `openingDate` 不能用来识别"最近开业"的餐厅：它只覆盖尚未开业、有预期开业日期的商家。这个信号可用于找"即将开业、需要新菜单"的高意向线索，但覆盖量未知。
- Google Business Profile API 只能管理自己拥有或被授权管理的商家资料（依据对该 API 权限模型的一般了解，本次未抓取原文），不能用于发现第三方餐厅。

### Gaps
- 未找到 Google 官方对"lead generation / 销售获客"用例的正面或反面表述，EEA 白名单第 (3) 类是最接近的条款。
- `includeFutureOpeningBusinesses` 在欧洲的实际覆盖量没有数据。
- Google Business Profile API 访问范围未取得官方原文。

## 2. Foursquare：Places API 条款与 FSQ OS Places 开放数据集（重大发现）

### Takeaway
Foursquare 付费 API 的自助（PAYG）许可只允许长期保存 ID，不适合入库。但 Foursquare 的**开放数据集 FSQ OS Places 采用 Apache 2.0 许可**，字段包含 **tel、website、email、facebook_id、instagram、twitter、date_created、date_refreshed、date_closed**，可以免费下载并存入自己的数据库。按"每欧元能拿到多少电话、网站和社交账号"算，它是所有来源里最划算的（边际成本为 0）。缺点是没有 rating、price、hours，这些字段属于付费 Premium。

### Cited Findings
- 2026 年官方价格：Pro 端点 0–500 次免费，501–100k 次 $15/1000，100k–500k 次 $12/1000，>500k 次 $9/1000；Premium 端点 $18.75 / $15 / $11.25 每千次；新增 "Ask" 端点，Pro 档 $30/1000，Premium 档 $36/1000；另有最多 10,000 次 Pro 端点沙箱免费调用 — [Foursquare Pricing](https://foursquare.com/pricing/)
- Places API（自助版）EULA（Last Updated 2024-02-29）：许可为 "limited, non-exclusive, revocable, non-sublicensable … without rights to create any derivative works"；§2.1 必须遵守 Usage Guidelines 中的缓存限制；§2.2 展示时须标注 "Powered by Foursquare"；§2.3 须防止展示 Places Data 的页面被爬取；制作对外报告时 "no material portions of the Places Data are exposed to third parties"（"material portions" 指可以单独售卖的数据集）— [Foursquare Places API EULA](https://foursquare.com/legal/terms/apilicenseagreement/)
- （二手）按现行 Usage Guidelines，PAYG 账户只能无限期缓存 fsq_place_id、photo ID 和 address ID，其他字段都不能缓存 — [Open Places API 博客](https://openplacesapi.com/blog/can-you-store-places-api-results)；官方页面 [Usage Guidelines](https://docs.foursquare.com/docs/usage-guidelines) 由 JS 渲染，未能直接核对原文
- FSQ OS Places 数据集采用 Apache License 2.0，可以通过 Foursquare Places Portal（Iceberg 数据目录）、Hugging Face `foursquare/fsq-os-places`、Snowflake Marketplace 和 S3 PMTiles 获取 — [Access FSQ OS Places](https://docs.foursquare.com/data-products/docs/access-fsq-os-places)
- FSQ OS Places 字段定义（官方 schema）：tel（本地格式电话）、website（"URL to the POI's (or the chain's) publicly available website"）、email（"Primary contact email address of organization, if available"）、facebook_id、instagram、twitter、fsq_category_ids、date_created（"The date the POI entered our database. This does not necessarily mean the POI actually opened on this date"）、date_refreshed、date_closed、unresolved_flags（Placemaker 报告、尚待核实的质量问题标记）— [Places OS Data Schemas](https://docs.foursquare.com/data-products/docs/places-os-data-schema)

### Inferences
- FSQ OS Places 可以作为免费"种子库"，其作用与 OSM 类似，但字段更适合获客（直接带 email 和 Instagram）。Apache 2.0 只要求保留许可与版权声明，允许商用、存储和修改，与 ODbL 不同，没有"衍生数据库必须共享"的义务。
- `date_created` 可以近似"新店"信号（新近进入数据库），但官方明确说明不等于开业日期。建议与 date_refreshed、date_closed 和 unresolved_flags 一起过滤。
- 付费 Places API 可以只在线索详情页实时补 rating/price/hours（Premium $18.75/1000），这部分不入库。

### Gaps
- FSQ OS Places 在欧洲餐厅上的 email/instagram/website 填充率没有官方数字，需要下载后自己统计（例如按国家过滤 Dining and Drinking 类目）。
- 数据集更新频率、欧洲 POI 数量本次未确认。

## 3. HERE、TomTom、Mapbox、Apple Maps Server API、Azure Maps

### Takeaway
这 5 家都是"地图与导航型"POI 数据：一般有电话和网址，没有 email、社交账号、评分、价位、菜单或开业日期，对获客的边际价值低。存储条款普遍比 Google 宽松不了多少：Mapbox Search Box 只允许临时使用；HERE 据二手资料限存 30 天。Apple 每天 25,000 次免费调用，适合用于"电话/网址交叉校验"。

### Cited Findings
- Mapbox Search Box："all data returned by the Search Box API endpoints is only available for temporary use. If your use case requires storing position data, contact Mapbox sales"；默认限速 10 次/秒；支持 `show_closed_pois`、`open_now`、`minimum_rating` 等参数 — [Mapbox Search Box API](https://docs.mapbox.com/api/search/search-box/)
- （二手）Mapbox 的永久地理编码为 $5/1000，只覆盖地址，不覆盖 POI 搜索 — [Open Places API 博客](https://openplacesapi.com/blog/can-you-store-places-api-results)；Mapbox 临时地理编码 100k 次以上 $1.70→$1.25/1000 — [Mapbox Pricing](https://www.mapbox.com/pricing)
- TomTom POI Search 返回示例包含 `poi.name`、`poi.phone`、`poi.url`、brands、categorySet，可按 openingHours 参数请求营业时间 — [TomTom Points of Interest Search](https://developer.tomtom.com/search-api/documentation/search-service/points-of-interest-search)；Places Search Details 每月免费 5K 次，Search Suggest 每月免费 10K 次（每千次单价需在 "Pricing details" 中查看，本次未取到）— [TomTom Pricing](https://developer.tomtom.com/pricing)
- （二手）HERE Base Plan 每月免费 30,000 次；地理编码超出后 $0.88/1000（≤5M）；2026-04-01 起新签和续约价格上调约 6% — [Placematic HERE Pricing 2026](https://placematic.com/here-technologies-api-pricing/)；HERE 标准条款把搜索结果的保存期限限为 30 天，Base 计划不含永久存储权 — [Open Places API 博客](https://openplacesapi.com/blog/can-you-store-places-api-results)（二手）
- Apple Maps Server API：每个开发者团队每天 25,000 次调用（与 MapKit JS 共享），超出返回 HTTP 429，可以申请提额 — [WWDC22 Meet Apple Maps Server APIs](https://developer.apple.com/videos/play/wwdc2022/10006/)；[Apple Maps Server API 文档](https://developer.apple.com/documentation/applemapsserverapi)
- Azure Maps：Search v1.0 已被 Search API 2026-01-01 版取代，新版映射表只列出地理编码、自动补全和反向地理编码等端点 — [Azure Maps Search v1 迁移](https://learn.microsoft.com/en-us/azure/azure-maps/migrate-search-v1-api)

### Inferences
- Azure 新版 Search API 的映射表中看不到 POI/Fuzzy 类别搜索的对应项，说明 Azure Maps 已基本不适合做餐厅发现（需进一步确认）。Bing Maps for Enterprise 已进入退役流程（依据一般了解，本次未取到原文）。
- Apple 的 Place 对象在本次抓取的 JSON 中只看到 name、coordinate、formattedAddressLines、structuredAddress、alternateIds 等属性，**未见 phone/url 字段**（与第三方描述"返回电话和网站"相矛盾，需实测确认）。

### Gaps
- HERE Discover 的 `contacts`（phone/www/email）字段在欧洲的填充率、每千次价格和条款原文均未取到（官方定价页由 JS 渲染）。
- TomTom 每千次单价和 POI 数据存储条款未取到。
- Apple Maps Server API 对数据存储和商业用途的具体许可条款未取到。

## 4. Yelp、Tripadvisor、TheFork/OpenTable

### Takeaway
Yelp 的新条款（2026-09-22 更新）规定 Yelp Content 缓存不得超过 **24 小时**，并禁止批量下载，不能入 CRM。Tripadvisor 同样以展示和署名为前提，禁止爬取。TheFork/OpenTable 没有公开的发现类数据 API。这三类只适合"实时查看"，不适合建库。

### Cited Findings
- Yelp API Terms（Last Updated 2026-09-22）§5(a)：不得 "cache, record, pre-fetch, or otherwise store any portion of the Yelp Content for a period longer than twenty-four (24) hours from receipt … or attempt or provide a means to execute any scraping or 'bulk download' operations"，但非商业分析除外 — [Yelp API Terms of Use](https://terms.yelp.com/developers/api_terms/)
- 同一条款的禁止用途清单中列有与 "direct marketing and/or telemarketing activities" 相关的内容（原文上下文是"Your Site 不得包含或推广……"）— [Yelp API Terms of Use](https://terms.yelp.com/developers/api_terms/)

### Inferences
- 用 Yelp 数据做对餐厅本身的直销外呼/邮件，与 24 小时缓存限制、禁止直销类用途的精神都有冲突，风险高。Yelp 在欧洲覆盖较弱（前一份笔记已记录），不建议投入。
- Tripadvisor 的 rating 和 review count 在欧洲覆盖很好，但只能实时展示，适合在线索详情页中作为参考。

### Gaps
- TheFork、OpenTable 的联盟或合作伙伴 API 是否对非预订类合作方开放，没有找到公开文档（与前一份笔记结论一致）。

## 5. 商业 B2B/POI 数据商与抓取型服务：价格与法律风险

### Takeaway
抓取型服务（Outscraper、SerpApi、Bright Data、Apify）按条数算最便宜：Bright Data 的 Google Maps 数据集最高 $0.0025/条，最低订单 $250。但数据来源违反 Google 的 No Scraping 条款，买方存储后的合规风险需要自己承担。SMB 获客平台 Openmart 声称覆盖英国、爱尔兰、西班牙、法国的 50 万+ 餐厅店主联系方式，$149/月起，是少数针对"餐厅店主邮箱"的现成产品。Dataplor 等 POI 数据商面向企业，价格需询价。

### Cited Findings
- Bright Data Google Maps 数据集：共 3 个数据集，325.4M+ 条记录；"Starts at Up to $0.0025 per record, Min Order $250"；可以投递到 S3、GCS、Snowflake 等，提供免费样本；Scraper API 起价 $0.75–$1/1000 条 — [Bright Data Google Maps Datasets](https://brightdata.com/products/datasets/google-maps)
- SerpApi：Starter $25/月（1,000 次搜索），Developer $75/月（5,000 次），Production $150/月，Big Data $275/月（30,000 次）；附带 "U.S. Legal Shield"，对搜索引擎数据的抓取和解析提供最高 $2M 保障（前提是用户对数据的使用不违法）— [SerpApi Pricing](https://serpapi.com/pricing)
- Openmart：覆盖 16 个国家；欧洲部分约 8.9M 家企业，限英国、爱尔兰、西班牙、法国；餐厅店主联系人 500K+，每周刷新；免费起步，付费版 $149/月起；员工邮箱 3 credits，员工电话 8 credits — [Openmart Restaurants](https://www.openmart.com/databases/restaurants)；[Openmart Pricing](https://www.openmart.com/pricing)（摘要来自搜索结果，未逐页核对）
- Dataplor：宣称覆盖 250+ 国家和地区的 370M+ 地点，以结构化数据集或 AI 平台交付，需要预约演示或询价 — [Dataplor](https://www.dataplor.com/)
- Apify 上有多个"餐厅店主邮箱"类 actor（如 restaurant-lead-scraper、restaurant-leads），本质上是 Google Maps 加官网抓取 — [Apify Restaurant Lead Scraper](https://apify.com/samstorm/restaurant-lead-scraper)

### Inferences
- 1,000–10,000 家的成本粗估：Bright Data 按 $0.0025/条算约 $2.5–$25，但最低订单 $250，实际至少 $250。SerpApi 按每次搜索约 20 条算，1 万家约需 500–1,500 次搜索，$75–$150 的套餐可以覆盖一个月。Outscraper 含邮箱约 $9/1000（见前一份笔记）。Openmart 按 $149/月起步（不含 Germany）。
- 法律风险排序（从低到高）：FSQ OS Places / OSM（开放许可）< 官网自采 < Openmart 等 SMB 数据商（数据来源不透明，GDPR 由供应商和买方共同承担）< 抓取 Google Maps 的数据集或 API（违反 Google §3.2.3，并且涉及以数据库权利保护的 EU 数据库）。
- Cognism、Apollo、Hunter、Snov、D&B、Kompass 以公司和职员为中心，对独立小餐厅的覆盖通常较弱。它们适合给连锁或集团型餐厅找决策人，不适合作为主发现源（推断，本次未取得覆盖数据）。

### Gaps
- SafeGraph/Advan、Precisely、Data Axle、Veraset、Kompass、Dun & Bradstreet、Cognism、Apollo、Hunter、Snov 的欧洲餐厅覆盖和具体报价本次均未取得（受检索预算限制）；多数需要询价。
- Openmart 的数据来源与 GDPR 合规说明未核对。
- Bright Data Google Maps 数据集的具体字段（website/phone/社交）和欧洲覆盖未从页面中提取到。

## 6. 结论：谁的"电话 + 官网 + 社交"每欧元覆盖最好

### Takeaway
在"合规且允许入库"的前提下，**FSQ OS Places（免费、Apache 2.0，含 tel/website/email/instagram/facebook/twitter/date_created）明显最优**，其次是 OSM。付费官方 API（Google、Foursquare、Yelp、Tripadvisor、HERE、Mapbox）都禁止或限制长期存储，只能做实时补充展示。抓取类服务单价最低，但合规成本不透明。

### Cited Findings
- FSQ OS Places 字段与许可 — [Places OS Data Schemas](https://docs.foursquare.com/data-products/docs/places-os-data-schema)；[Access FSQ OS Places](https://docs.foursquare.com/data-products/docs/access-fsq-os-places)
- 各家存储期限：Google 只允许保存 place_id，lat/lng 30 天；Yelp 24 小时；Mapbox 仅临时使用；Foursquare PAYG 只允许保存 ID — [Google Service Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)；[Yelp API Terms](https://terms.yelp.com/developers/api_terms/)；[Mapbox Search Box](https://docs.mapbox.com/api/search/search-box/)；[Open Places API 博客](https://openplacesapi.com/blog/can-you-store-places-api-results)（二手）

### Inferences
- 推荐的组合：(1) FSQ OS Places 加 OSM，建免费、可存储的种子库（电话、官网、邮箱、社交）；(2) Google Places 只存 place_id，线索详情页实时拉 rating、priceLevel、userRatingCount 和 businessStatus；EEA 账户依据白名单第 (3) 类，并且不与地图一起展示；(3) 用官网自采补全和校验邮箱、菜单 URL 与 WhatsApp，这些都没有任何 API 提供；(4) 连锁或集团型餐厅再用 Apollo、Cognism 等找决策人。
- 没有任何官方 API 提供菜单 URL 或 WhatsApp 字段；"最近开业/变更"信号可以用 FSQ date_created、date_refreshed 和 Google openingDate（仅限未开业商家）来近似。

### Gaps
- 没有各来源在同一欧洲城市的字段填充率横向对比；建议选 1–2 个城市，下载 FSQ OS Places 后与前一份笔记中的 OSM 数据实测对比。
