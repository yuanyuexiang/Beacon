# Google Maps 菜单测试（2026-10-10）

## 范围

用户明确授权测试阶段通过浏览器页面结构获取菜单。仅单家研究探针，不接批次、不写正式菜单资产、不调用模型；不复制日常 Chrome 的 Cookie，不改变系统代理。自动化使用独立 Chrome 配置目录（受 gitignore 的 data 内）。

## 已确认

- 从 Beacon 数据库读取 College Bar 已由 admin 确认的 Place ID；以官方 Maps URL 的 query_place_id 精确打开同一地址：9 Alford Place, Aberdeen AB10 1YD。
- 独立 Playwright Chrome 成功打开 College Bar，但匿名模式显示 limited view，只有 Overview/About；点击 See more 后提示登录才能完整访问评价和照片。该结果为访问受限，不能记为没有菜单。
- 用当前已登录 Chrome 的原生界面核对用户截图：菜单页签存在，菜单区有“第 1 张照片，共 1 张”；打开后进入独立照片查看器。
- 由这个已确认菜单查看器的实际 URL 提取 Google 图片资源，以 Playwright 探针脚本的下载路径成功保存 1 张 JPEG（455,188 字节，2976×3968）。不是缩略图或页面截图；文件为 `data/records/maps-menu-test/d4d09b5612fd4150.jpg`，哈希和来源位于同目录 result.json。
- 视觉核对确为饮品菜单，能读到名称和价格；照片存在斜拍、局部裁切和饮品遮挡，不能作为完整菜单。页面显示照片发布于 2019 年 12 月、拍摄于 2019 年 11 月，不能视为当前价格。

## 尚未完成

用户登录独立测试配置后，有窗口 Playwright 的完整链路已通过：Place ID URL→门店核对→菜单页签→菜单缩略图→查看器→下载。取得 1 张图片，SHA-256 与前述人工确认图片一致。首轮下载出现 TLS EOF，第二轮成功；脚本已补充至多两次传输失败重试。

相同 profile 的后台模式仍返回 limited_view_login_required，因此脚本默认有窗口运行，后台模式显式使用 --headless。尚未取得 10 家覆盖率、多图翻页真实验收或前端模块验收。

## 复现

依赖通过 uv 临时环境安装，Playwright 1.63.0（Apache-2.0）；使用本机已安装 Chrome，无需安装浏览器副本。

```sh
uv run --no-project --with playwright==1.63.0 --with 'httpx[socks]' scripts/maps_menu_probe.py --name 'College Bar' --place-id ChIJd5CEACcOhEgRtviq8N4u-8g --address '9 Alford Place Aberdeen AB10 1YD'
```

初次登录独立配置：

```sh
uv run --no-project --with playwright==1.63.0 --with 'httpx[socks]' python -u scripts/maps_menu_probe.py --name 'College Bar' --place-id ChIJd5CEACcOhEgRtviq8N4u-8g --setup-login
```

在专用测试窗口手动登录 Google，然后在终端回车。不要将现有 Chrome 的 User Data 指定为 profile；不要提交 profile。若 Google 拒绝该自动化窗口登录，记录该限制并采用人工窗口测试，不绕过验证。

`--proxy ''` 表示不使用显式代理；默认 SOCKS5 127.0.0.1:7890。`--out` 指定独立实验目录，`--max-photos` 限制 1～20 张。`--viewer-url` 接受人工从菜单区打开的照片查看器 URL，结果明确标为 downloaded_from_confirmed_viewer；此模式不能用于声称完成自动菜单分类。脚本输出区分有限视图、门店待核对、无菜单页签、无菜单图片、超时和失败。仅支持观察到的查看器资源格式，不保证其他页面布局。

参考：[Maps URLs](https://developers.google.com/maps/documentation/urls/get-started)、[Playwright 代理](https://playwright.dev/python/docs/network)。
