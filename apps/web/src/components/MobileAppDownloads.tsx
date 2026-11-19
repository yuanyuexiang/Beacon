"use client";
import { Alert, Button, Card, Collapse, Empty, Input, Modal, Progress, QRCode, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";
import { pairingAddress, pairingServer } from "@/lib/mobile-channels";
import { uploadMobileApp } from "@/lib/mobile-app-upload";
import { afterCommit } from "@/lib/after-commit";

type Release = {id:string;version_name:string;version_code:number;size:number;sha256:string;signer_sha256:string;uploaded_at:string;published_at?:string;notes?:string;development_signature?:boolean};
type Catalog = {current:Release|null;previous:Release|null;drafts:Release[];server?:string;max_bytes:number;validator_available?:boolean};
type Download = {path:string;expires_at:string};
const version = (r:Release) => `${r.version_name} · 构建 ${r.version_code}`;

export default function MobileAppDownloads() {
  const {me}=useOperator();
  const [data,setData]=useState<Catalog>();
  const [error,setError]=useState<string>(), [notice,setNotice]=useState<string>();
  const [busy,setBusy]=useState<string>(), [file,setFile]=useState<File>(), [notes,setNotes]=useState("");
  const [link,setLink]=useState<Download>(), [address,setAddress]=useState(""), [now,setNow]=useState(() => Date.now());
  const [uploadPercent,setUploadPercent]=useState(0);
  const [modal,context]=Modal.useModal();
  const refresh=useCallback(async () => {
    const response=await api<Catalog>("/api/mobile/app");setData(response);
    setAddress(old => old || pairingAddress("",localStorage.getItem("beacon-mobile-server"),window.location.origin,response.server));
  },[]);
  useEffect(() => afterCommit(() => {void refresh().catch(e => setError(e.message));}),[refresh]);
  useEffect(() => {if(!link) return; const timer=setInterval(() => setNow(Date.now()),1000);return () => clearInterval(timer);},[link]);
  const run=async (operation:string,fn:()=>Promise<void>,rethrow=false) => {
    setBusy(operation);setError(undefined);setNotice(undefined);
    try {await fn();} catch(e) {setError((e as Error).message);if(rethrow) throw e;} finally {setBusy(undefined);}
  };
  const makeLink=async (downloadNow:boolean) => {
    const value=await api<Download>("/api/mobile/app/download-link",json({}));
    setNow(Date.now());setLink(value);
    if(downloadNow) window.location.assign(value.path);
  };
  const publish=(item:Release,rollback=false) => {
    const expected=data?.current?.id || null;
    modal.confirm({title:rollback ? "回退到上一版本？" : "发布这个安装包？",okText:rollback ? "确认回退" : "发布此版本",cancelText:"取消",
      content:<><p>版本：{version(item)} · {(item.size/1024**2).toFixed(1)} MB</p>{item.development_signature && <p>此包使用开发签名。正式交付应使用固定的专用发布签名，已安装设备更换签名前需由技术方处理。</p>}<p>{rollback ? "回退会更换下载版本，不会自动更改手机已安装的 App。" : "发布后，用户会下载这个版本。请确认已完成测试，并妥善保管原签名密钥。"}</p>{data?.current?.version_code===item.version_code && !rollback && <p>版本号与当前一致；后续正式更新建议递增构建版本号。</p>}<p style={{whiteSpace:"pre-wrap",maxHeight:200,overflow:"auto"}}>{notes || "未填写更新说明"}</p></>,
      onOk:() => run("publish",async () => {await api(`/api/mobile/app/${item.id}/publish`,json({expected_current_id:expected,notes,rollback}));setNotes("");setLink(undefined);await refresh();setNotice(rollback ? "已回退下载版本" : "安装包已发布");},true),
    });
  };
  let qr="";
  const expired=!!link && now>=new Date(link.expires_at).getTime();
  if(link && !expired) {try {const base=pairingServer(address);if(!["127.0.0.1","localhost"].includes(new URL(base).hostname)) qr=new URL(link.path,base).href;} catch { /* Local development needs a phone-reachable LAN address. */ }}
  return <Card title="下载手机 App" style={{marginBottom:20}} extra={<Button disabled={!!busy} onClick={() => void run("refresh",refresh)}>刷新版本</Button>}>
    {context}
    {error && <Alert type="error" showIcon message={error} style={{marginBottom:12}} />}
    {notice && <Alert type="success" showIcon message={notice} style={{marginBottom:12}} />}
    {data?.current ? <>
      <Space wrap><Typography.Text strong>Beacon Android 手机助手</Typography.Text><Tag>{version(data.current)}</Tag><Typography.Text type="secondary">{(data.current.size/1024**2).toFixed(1)} MB · 更新于 {new Date(data.current.published_at || data.current.uploaded_at).toLocaleString("zh-CN")}</Typography.Text></Space>
      {data.current.notes && <Typography.Paragraph style={{whiteSpace:"pre-wrap",marginTop:12}}>{data.current.notes}</Typography.Paragraph>}
      <Space wrap style={{marginTop:12}}><Button type="primary" loading={busy==="download"} disabled={!!busy} onClick={() => void run("download",() => makeLink(true))}>下载 Android App</Button><Button loading={busy==="qr"} disabled={!!busy} onClick={() => void run("qr",() => makeLink(false))}>手机扫码下载</Button></Space>
      <Typography.Paragraph type="secondary" style={{marginTop:12}}>先下载安装 App，再扫描下方配对二维码绑定。Android 提示安装权限时，仅为本次下载使用的浏览器允许安装；当前不提供 iPhone 安装包。</Typography.Paragraph>
    </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={data ? "管理员尚未发布安装包，请联系管理员上传发布" : "正在读取 App 版本…"} />}
    {link && <Card size="small" title="扫码下载安装包 · 不是设备配对码" style={{marginTop:16}}>
      {expired ? <Alert type="info" message="下载二维码已过期，请重新点击“手机扫码下载”" /> : <Space align="start" wrap size="large">
        {qr ? <QRCode value={qr} size={180} /> : <Typography.Paragraph>请填写手机能访问的平台地址，生成下载二维码。</Typography.Paragraph>}
        <div style={{maxWidth:"100%",width:400}}><Typography.Paragraph>用手机浏览器或相机扫码下载，无需先登录或配对。链接在 {new Date(link.expires_at).toLocaleTimeString("zh-CN")} 前有效。</Typography.Paragraph><label>手机下载访问地址<Input aria-label="手机下载访问地址" value={address} onChange={e => setAddress(e.target.value)} placeholder="https://你的平台域名" /></label><Typography.Paragraph type="secondary">云端使用平台 HTTPS 地址，本地填写电脑的局域网地址，不能填 localhost。</Typography.Paragraph><a href={link.path} download>在本机下载同一安装包</a></div>
      </Space>}
    </Card>}
    {me?.role==="admin" && <Collapse style={{marginTop:16}} items={[{key:"manage",label:"安装包管理 · 仅管理员",children:<>
      {data?.validator_available===false && <Alert type="warning" showIcon message="服务器暂未配置 APK 校验工具，请联系技术方；已有版本仍可下载。" style={{marginBottom:12}} />}
      <p>上传完整 release APK。校验通过后为待发布状态，不会立即替换用户下载版本。首次发布的签名将用于后续一致性校验。</p>
      <Space wrap><input aria-label="选择 Android APK" type="file" accept=".apk,application/vnd.android.package-archive" disabled={!!busy} onChange={e => setFile(e.target.files?.[0])} /><Button loading={busy==="upload"} disabled={!!busy || !file || data?.validator_available===false} onClick={() => void run("upload",async () => {
        if(!file) return;
        if(!file.name.toLowerCase().endsWith(".apk")) throw new Error("请选择 .apk 安装包");
        if(file.size>(data?.max_bytes || 256*1024**2)) throw new Error("安装包不能超过 256 MB");
        setUploadPercent(0);
        const result=await uploadMobileApp(file,setUploadPercent);
        await refresh();setNotice(result.already_published ? "此安装包已发布，无需重复发布" : "上传校验通过，请核对版本并点击发布");
      })}>上传并校验</Button></Space>
      {busy==="upload" && <div role="status"><Progress percent={uploadPercent} status="active" /><Typography.Text type="secondary">{uploadPercent===100 ? "文件已传完，正在校验签名与版本…" : "正在分段上传安装包，请保持页面打开…"}</Typography.Text></div>}
      <Input.TextArea aria-label="App 更新说明" value={notes} onChange={e => setNotes(e.target.value)} maxLength={3000} rows={3} placeholder="填写这个版本的更新说明，发布后用户可见" style={{marginTop:16,marginBottom:12}} />
      {data?.drafts?.map(item => <Card key={item.id} size="small" title={<Space wrap><Tag>待发布</Tag>{version(item)}</Space>} style={{marginBottom:12}} extra={<Button type="primary" disabled={!!busy} onClick={() => publish(item)}>发布此版本</Button>}>
        <p>大小：{(item.size/1024**2).toFixed(1)} MB · 上传于 {new Date(item.uploaded_at).toLocaleString("zh-CN")}</p><Typography.Text type="secondary" style={{overflowWrap:"anywhere"}}>文件 SHA-256：{item.sha256}<br />签名 SHA-256：{item.signer_sha256}</Typography.Text>
      </Card>)}
      {data?.previous && <Space wrap><Typography.Text>上一版本：{version(data.previous)}</Typography.Text><Button disabled={!!busy} onClick={() => publish(data.previous!,true)}>回退到上一版本</Button></Space>}
    </>}]} />}
  </Card>;
}
