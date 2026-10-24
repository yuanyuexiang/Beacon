"use client";
import { Alert, Card, Select, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import OutreachProfileSettings from "@/components/OutreachProfileSettings";
import LeadPolicySettings from "@/components/LeadPolicySettings";
import GmailSettings from "@/components/GmailSettings";
import SocialSettings from "@/components/SocialSettings";
import { HeroBand } from "@/components/ui";
import { SettingsState } from "@/components/SettingsState";

const groups = [
  { title: "业务设置", items: [{ key: "profile", label: "我们的服务", note: "AI 起草使用的真实服务资料" }, { key: "screen", label: "客户筛选与准入", note: "筛选规则及自动准入策略" }, { key: "data", label: "数据补充", note: "来源查询与结果复用" }] },
  { title: "渠道连接", items: [{ key: "gmail", label: "Gmail", note: "邮箱授权、测试与发送" }, { key: "meta", label: "Facebook / Instagram", note: "本方账号及已连接会话" }, { key: "manual", label: "TikTok / LinkedIn", note: "人工渠道" }] },
  { title: "帮助说明", items: [{ key: "guide", label: "操作指南", note: "从建立名单到沟通跟进" }, { key: "faq", label: "常见问题", note: "缺项、重试与授权" }, { key: "technical", label: "技术文档", note: "部署与接口参考" }] },
];
const items = groups.flatMap(g => g.items);
const valid = (key: string | null) => items.some(i => i.key === key);
function Help({ section }: { section: string }) {
  if (section === "manual") return <Card title="TikTok / LinkedIn"><Alert type="info" showIcon message="当前以人工方式执行触达" description="可以记录门店的真实社媒主页，准备并确认文案后由业务成员在平台操作，再回填沟通结果。当前没有可用的自动私信连接入口，无需填写 API Key。" /></Card>;
  if (section === "technical") return <Card title="技术文档"><Typography.Paragraph>接口文档供开发与运维人员查阅；日常业务操作无需配置接口。</Typography.Paragraph><a href="/api/docs" target="_blank" rel="noreferrer">打开 API 接口文档 ↗</a><Typography.Paragraph style={{ marginTop: 20 }}>部署与授权手册随项目维护：docs/操作手册.md、docs/Gmail邮件服务.md、docs/社媒API应用与授权配置指南.md。凭据由管理员在对应渠道配置。</Typography.Paragraph></Card>;
  const rows = section === "faq" ? [
    ["没有菜单可以继续吗？", "可以上传其他渠道取得的菜单，也可以先生成询问菜单或负责人的消息。无需等待抓取成功。"],
    ["读取失败怎么办？", "展开任务中的具体原因，修复网络或来源问题后只重试未完成项。已有结果保留，名单可继续使用。"],
    ["AI 已确认，为何还不能发送？", "联系方式归属、渠道准入和内容确认分别检查。系统会列出缺项；AI 自动准入仅在证据与规则满足时生效，发送前仍须复查。"],
    ["未配置社媒会影响其他功能吗？", "不会。可以先完成名单和资料准备，也可以单独连接 Gmail。Meta 身份核验不代表消息权限和订阅已验收。"],
    ["连接成功会自动发送吗？", "不会。Gmail 和已连接社媒会话需预览确认；批量队列另有开关，未确认的内容不会因此自动发送。"],
  ] : [
    ["1 · 建立名单与同步", "从门店池选择地区与类型建立名单，先同步 Overture、Google 来源候选；随后按需对整批或所选门店执行 AI 核验与完善。"],
    ["2 · 完善客户资料", "核验官网、识别经营类型、查找联系方式；AI 提供有证据的推荐与准入判断，缺项保留并允许补充。"],
    ["3 · 菜单与触达消息", "从官网、单家 Maps 获取或手动上传菜单，分析后核对事实；AI 结合服务资料和已核对信息起草消息，无菜单时可先询问菜单。"],
    ["4 · 确认发送", "选择联系方式、确认文案并检查准入，创建就绪任务。邮件和已连接社媒会话完整预览确认后发送，其余渠道人工执行。"],
    ["5 · 沟通跟进", "在触达任务与回复中查看记录、回填结果；回复暂停相关任务，拒绝或退订进入抑制名单。"],
  ];
  return <Card title={section === "faq" ? "常见问题" : "操作指南"}>{rows.map(([title, text]) => <section key={title} style={{ marginBottom: 24 }}><Typography.Title level={5}>{title}</Typography.Title><Typography.Paragraph>{text}</Typography.Paragraph></section>)}</Card>;
}

export default function SettingsPage() {
  const [active, setActive] = useState<string>();
  const [visited, setVisited] = useState<string[]>([]);
  const [dirtyRows, setDirtyRows] = useState<Record<string, boolean>>({});
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const dirty = useCallback((key: string, value: boolean) => setDirtyRows(old => old[key] === value ? old : { ...old, [key]: value }), []);
  const status = useCallback((key: string, value: string) => setStatuses(old => old[key] === value ? old : { ...old, [key]: value }), []);
  const context = useMemo(() => ({ dirty, status }), [dirty, status]);
  const show = useCallback((key: string) => { setActive(key); setVisited(old => old.includes(key) ? old : [...old, key]); }, []);
  useEffect(() => {
    const restore = () => {
      const p = new URLSearchParams(window.location.search);
      const key = p.has("gmail") ? "gmail" : p.has("meta") ? "meta" : p.get("section");
      let remembered: string | null = null;
      try { remembered = sessionStorage.getItem("beacon-settings-section"); } catch { /* storage unavailable */ }
      show(valid(key) ? key! : valid(remembered) ? remembered! : "profile");
    };
    restore(); window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, [show]);
  const changed = Object.values(dirtyRows).some(Boolean);
  useEffect(() => {
    if (!changed) return;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const leave = (e: MouseEvent) => {
      const link = (e.target as Element)?.closest("a");
      if (!link || link.target === "_blank") return;
      const url = new URL(link.href, window.location.href);
      if (url.pathname !== "/settings" && !window.confirm("设置中有未保存的修改，离开后将丢失。是否离开？")) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload); document.addEventListener("click", leave, true);
    return () => { window.removeEventListener("beforeunload", unload); document.removeEventListener("click", leave, true); };
  }, [changed]);
  const choose = (key: string) => {
    show(key);
    const url = new URL(window.location.href); url.searchParams.set("section", key); url.searchParams.delete("gmail"); url.searchParams.delete("gmail_error"); url.searchParams.delete("meta");
    window.history.pushState(null, "", url);
    try { sessionStorage.setItem("beacon-settings-section", key); } catch { /* storage unavailable */ }
  };
  const policyVisited = visited.includes("screen") || visited.includes("data");
  const badge = (key: string) => dirtyRows[key === "screen" || key === "data" ? "policy" : key] ? "未保存" : statuses[key] || (["gmail", "meta"].includes(key) ? "未检查" : "");
  return <SettingsState.Provider value={context}>
    <HeroBand kicker="SETTINGS" title="设置" subtitle="管理业务策略与渠道连接，按分类查看配置和操作说明。" />
    <div className="settings-workspace">
      <nav className="settings-categories" aria-label="设置分类">{groups.map(group => <div key={group.title} className="settings-group"><h2>{group.title}</h2>{group.items.map(item => <button key={item.key} type="button" aria-current={active === item.key ? "page" : undefined} onClick={() => choose(item.key)}><span>{item.label}{badge(item.key) && <Tag>{badge(item.key)}</Tag>}</span><small>{item.note}</small></button>)}</div>)}</nav>
      <div className="settings-mobile"><Select aria-label="设置分类" value={active} onChange={choose} style={{ width: "100%" }} options={groups.map(g => ({ label: g.title, options: g.items.map(i => ({ value: i.key, label: i.label })) }))} /></div>
      <main className="settings-detail" aria-label="当前设置">
        {changed && <Alert type="info" showIcon message="有未保存的修改；切换分类会保留当前输入，离开或刷新前请保存。" style={{ marginBottom: 16 }} />}
        {!active && <p>正在打开设置…</p>}
        {visited.includes("profile") && <div hidden={active !== "profile"}><OutreachProfileSettings /></div>}
        {policyVisited && <div hidden={active !== "screen" && active !== "data"}><LeadPolicySettings section={active === "data" ? "data" : "screen"} /></div>}
        {visited.includes("gmail") && <div hidden={active !== "gmail"}><GmailSettings /></div>}
        {visited.includes("meta") && <div hidden={active !== "meta"}><SocialSettings /></div>}
        {active && ["manual", "guide", "faq", "technical"].includes(active) && <Help section={active} />}
      </main>
    </div>
  </SettingsState.Provider>;
}
