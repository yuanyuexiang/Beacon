"use client";
import { Alert, Button, Card, Checkbox, Descriptions, Image, Input, Modal, Popconfirm, Space, Table, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";
import type { PlacesCandidate, PlacesDetailsOut, PlacesLink, PlacesPhotoOut, PlacesSearchOut, PlacesState, ProviderAttribution } from "@/lib/google-places.generated";
import { BUSINESS_STATUS, PRICE_LEVEL, formatPriceRange } from "@/lib/google-places";

function GoogleAttribution({ providers = [] }: { providers?: ProviderAttribution[] }) {
  return <div style={{ borderTop: "1px solid #ddd", paddingTop: 8, marginTop: 12 }}>
    {/* eslint-disable-next-line @next/next/no-img-element */}
    <img src="/google-maps/attribution.svg" alt="Google Maps" style={{ height: 18, width: "auto", margin: "5px 5px 5px 0", verticalAlign: "middle" }} />
    {providers.map((p, i) => <span key={i}> · {p.providerUri ? <a href={p.providerUri} target="_blank" rel="noreferrer">{p.provider}</a> : p.provider}</span>)}
  </div>;
}

function GooglePhoto({ leadId, photo, expired }: { leadId: string; photo: PlacesPhotoOut; expired: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const objectUrl = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => { abort.current?.abort(); if (objectUrl.current) URL.revokeObjectURL(objectUrl.current); }, []);
  const load = async () => {
    setBusy(true); setError(null);
    abort.current = new AbortController();
    try {
      const response = await fetch(`/api/leads/${leadId}/google-places/photo`, { ...json({ token: photo.token }), credentials: "include", cache: "no-store", signal: abort.current.signal });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(typeof body.detail === "string" ? body.detail : "照片无法加载，请刷新信息后重试");
      }
      const blob = await response.blob();
      if (abort.current.signal.aborted) return;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = URL.createObjectURL(blob); setUrl(objectUrl.current);
    } catch (e) { if ((e as Error).name !== "AbortError") setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <Card size="small" style={{ width: 260 }}>
    {url ? <Image src={url} alt="Google 地点照片，未确认是否为现行菜单" width="100%" style={{ height: 190, objectFit: "contain" }} /> : <div style={{ height: 140, display: "grid", placeItems: "center", background: "#f5f5f5" }}><Button loading={busy} disabled={expired} onClick={load}>加载照片</Button></div>}
    {error && <Typography.Paragraph type="danger">{error}</Typography.Paragraph>}
    <div style={{ marginTop: 8 }}>{photo.width} × {photo.height} · 日期未知</div>
    <Space wrap>{(photo.authors ?? []).map((a, i) => <Space key={i} size={4}>
      {a.photoUri && <Image src={a.photoUri} alt={`${a.displayName ?? "作者"}头像`} width={22} height={22} preview={false} referrerPolicy="no-referrer" />}
      {a.uri ? <a href={a.uri} target="_blank" rel="noreferrer">{a.displayName || "照片作者"}</a> : <span>{a.displayName || "照片作者"}</span>}
    </Space>)}</Space>
    {photo.source_url && <div><a href={photo.source_url} target="_blank" rel="noreferrer">在 Google Maps 查看原图</a></div>}
    <GoogleAttribution />
  </Card>;
}

export default function GooglePlaces({ id, name, address, postcode }: { id: string; name: string; address: string | null; postcode: string | null }) {
  const [state, setState] = useState<PlacesState | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lookup, setLookup] = useState<PlacesSearchOut | null>(null);
  const [details, setDetails] = useState<PlacesDetailsOut | null>(null);
  const [query, setQuery] = useState(`${name} ${address ?? ""} ${postcode ?? ""} UK`);
  const [picked, setPicked] = useState<PlacesCandidate | null>(null);
  const [addressChecked, setAddressChecked] = useState(false);
  const [branchChecked, setBranchChecked] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    let active = true;
    api<PlacesState>(`/api/leads/${id}/google-places`, { cache: "no-store" }).then((v) => { if (active) setState(v); }).catch((e) => { if (active) setError(e.message); });
    const timer = setInterval(() => setNow(Date.now()), 15000);
    return () => { active = false; clearInterval(timer); };
  }, [id]);
  // 浏览器恢复旧页面时也清除实时内容；不使用 localStorage / sessionStorage。
  useEffect(() => {
    const clear = () => { setDetails(null); setLookup(null); setPicked(null); };
    window.addEventListener("pagehide", clear); window.addEventListener("pageshow", clear);
    return () => { window.removeEventListener("pagehide", clear); window.removeEventListener("pageshow", clear); };
  }, []);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally {
      setBusy(false);
      api<PlacesState>(`/api/leads/${id}/google-places`, { cache: "no-store" }).then(setState).catch(() => {});
    }
  };
  const search = () => run(async () => {
    setLookup(null); setPicked(null);
    setLookup(await api<PlacesSearchOut>(`/api/leads/${id}/google-places/search`, { ...json({ query: query.trim() || null }), cache: "no-store" }));
  });
  const confirm = () => run(async () => {
    if (!picked) return;
    const link = await api<PlacesLink>(`/api/leads/${id}/google-places/confirm`, json({ token: picked.token, address_checked: addressChecked, branch_checked: branchChecked }));
    setState((s) => s && { ...s, link }); setDetails(null); setLookup(null); setPicked(null); setOpen(false);
    message.success("已关联 Google 门店");
  });
  const view = () => run(async () => {
    setDetails(null);
    setDetails(await api<PlacesDetailsOut>(`/api/leads/${id}/google-places/details`, { ...json({}), cache: "no-store" }));
  });
  const unlink = () => run(async () => {
    await api(`/api/leads/${id}/google-places/unlink`, json({ expected_version: state?.link?.version }));
    setState((s) => s && { ...s, link: null }); setDetails(null); setLookup(null);
  });
  const searchExpired = !!lookup && new Date(lookup.expires_at).getTime() <= now;
  const photoExpired = !!details && new Date(details.expires_at).getTime() <= now;
  const p = details?.place;
  return <Card size="small" title="Google 门店参考" style={{ marginBottom: 16 }} extra={<Space><a href="/terms" target="_blank" rel="noreferrer">使用说明</a><a href="/privacy" target="_blank" rel="noreferrer">隐私说明</a></Space>}>
    <Typography.Paragraph type="secondary">核对门店后查看价格参考与地点照片。照片可能不是菜单或已过时；消费档位不能代表采购预算。</Typography.Paragraph>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {state && !state.configured && <Alert type="info" message="Google 查询尚未配置，请联系工作台管理员" style={{ marginBottom: 12 }} />}
    {state?.configured && <Typography.Paragraph type="secondary">今日查询尝试 {state.attempts_today} / {state.daily_limit}（含重试，照片加载另计；实际费用以 Google 账单为准）</Typography.Paragraph>}
    <Space wrap>
      <Button disabled={busy || !state?.configured} onClick={() => { setOpen(true); setLookup(null); setPicked(null); setError(null); }}>查找 / 更换 Google 门店</Button>
      {state?.link && <><Button loading={busy} disabled={!state.configured} onClick={view}>查看最新信息</Button><Popconfirm title="解除 Google 门店关联？" onConfirm={unlink}><Button disabled={busy}>解除关联</Button></Popconfirm></>}
    </Space>
    {state?.link && <Typography.Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}>已关联 · {state.link.reviewed_by} 于 {new Date(state.link.reviewed_at).toLocaleString("zh-CN")} 核对</Typography.Paragraph>}
    {p && <div style={{ padding: 16, marginTop: 16, border: "1px solid #dadce0", borderRadius: 8, background: "#fff" }}>
      <Descriptions size="small" column={{ xs: 1, md: 2 }} items={[
        { key: "name", label: "Google 门店", children: p.displayName?.text ?? "未知" },
        { key: "address", label: "地址", children: p.formattedAddress ?? "未知" },
        { key: "status", label: "营业状态参考", children: BUSINESS_STATUS[p.businessStatus ?? ""] ?? "未知" },
        { key: "level", label: "消费档位参考", children: PRICE_LEVEL[p.priceLevel ?? ""] ?? "未知" },
        { key: "range", label: "价格区间参考", children: formatPriceRange(p.priceRange) },
        { key: "time", label: "本次查询", children: new Date(details!.fetched_at).toLocaleString("zh-CN") },
      ]} />
      {p.googleMapsUri && <a href={p.googleMapsUri} target="_blank" rel="noreferrer">打开 Google Maps 核对</a>}
      <GoogleAttribution providers={p.attributions} />
      <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>地点照片（最多 10 张；点击才加载）</Typography.Paragraph>
      {photoExpired && <Alert type="warning" message="照片引用已过期，请点击“查看最新信息”刷新" style={{ marginBottom: 12 }} />}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>{details!.photos.map((photo) => <GooglePhoto key={photo.token} leadId={id} photo={photo} expired={photoExpired} />)}</div>
      {!details!.photos.length && <Typography.Text type="secondary">本次未返回照片</Typography.Text>}
    </div>}
    <Modal title="核对 Google 门店候选" open={open} footer={null} width={900} onCancel={() => { if (!busy) { setOpen(false); setLookup(null); setPicked(null); } }}>
      <Typography.Paragraph>当前门店：{name}<br />地址：{address ?? "未记录"} · {postcode ?? ""}</Typography.Paragraph>
      <Alert type="info" message="请核对地址和门店归属，留意同名店、其他分店与搬迁记录。" style={{ marginBottom: 12 }} />
      <Space.Compact style={{ width: "100%", marginBottom: 12 }}><Input aria-label="Google 门店搜索词" value={query} maxLength={600} onChange={(e) => setQuery(e.target.value)} onPressEnter={() => !busy && search()} /><Button type="primary" loading={busy} onClick={search}>搜索候选</Button></Space.Compact>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {searchExpired && <Alert type="warning" message="候选已过期，请重新搜索" />}
      <Table<PlacesCandidate> rowKey={(c) => c.place.id} pagination={false} loading={busy} dataSource={lookup?.candidates ?? []} locale={{ emptyText: lookup ? "未找到候选，可调整搜索词" : "点击搜索候选" }} columns={[
        { title: "Google 门店", render: (_, c) => c.place.googleMapsUri ? <a href={c.place.googleMapsUri} target="_blank" rel="noreferrer">{c.place.displayName?.text || c.place.id}</a> : c.place.displayName?.text },
        { title: "地址", render: (_, c) => c.place.formattedAddress ?? "未知" },
        { title: "", render: (_, c) => <Button disabled={busy || searchExpired} onClick={() => { setPicked(c); setAddressChecked(false); setBranchChecked(false); }}>核对该候选</Button> },
      ]} />
      {lookup && <GoogleAttribution providers={lookup.candidates.flatMap((c) => c.place.attributions ?? [])} />}
      {picked && <div style={{ borderTop: "1px solid #eee", paddingTop: 16, marginTop: 16 }}>
        <Typography.Paragraph>待确认：{picked.place.displayName?.text} · {picked.place.formattedAddress}</Typography.Paragraph>
        <Space direction="vertical"><Checkbox checked={addressChecked} onChange={(e) => setAddressChecked(e.target.checked)}>我已核对门牌、街道及邮编</Checkbox><Checkbox checked={branchChecked} onChange={(e) => setBranchChecked(e.target.checked)}>我已核对门店归属，确认不是同名异店或其他分店</Checkbox>
          <Button type="primary" loading={busy} disabled={!addressChecked || !branchChecked || searchExpired} onClick={confirm}>确认关联</Button>
        </Space>
      </div>}
    </Modal>
  </Card>;
}
