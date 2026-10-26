"use client";
import { Alert, Button, Collapse, Drawer, Form, Input, Modal, Select, Space, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";

type Match = { id:string; name:string; address?:string; postcode?:string; reasons:string[] };
type Values = { name:string; website?:string; address?:string; postcode?:string; region?:string; contact_name?:string; notes?:string; batch_key?:string; assigned_to?:string; contacts?:{channel:string;contact_ref:string}[] };
type Saved = {id:string;batch_key:string;reused:boolean};
const channels = [{value:"email",label:"邮箱"},{value:"phone",label:"电话"},{value:"whatsapp",label:"WhatsApp"},{value:"facebook",label:"Facebook"},{value:"instagram",label:"Instagram"},{value:"linkedin",label:"LinkedIn"},{value:"tiktok",label:"TikTok"},{value:"contact_form",label:"联系表单"}];
export default function ManualLead({open,onClose,batches,batchKey,onSaved}:{open:boolean;onClose:()=>void;batches:{batch_key:string}[];batchKey?:string;onSaved:()=>void}) {
  const {me}=useOperator(), router=useRouter();
  const [form]=Form.useForm<Values>();
  const [action,setAction]=useState<"view"|"enrich"|null>(null),[error,setError]=useState<string>();
  const busy=action!==null;
  const [matches,setMatches]=useState<Match[]>([]),[saved,setSaved]=useState<Saved>();
  const [members,setMembers]=useState<{username:string;display_name?:string}[]>([]);
  const request=useRef("");
  const initialized=useRef(false);
  useEffect(()=>{
    if(!open){initialized.current=false;return;}
    if(initialized.current)return;
    initialized.current=true;
    request.current=crypto.randomUUID();setError(undefined);setMatches([]);setSaved(undefined);form.resetFields();
    form.setFieldsValue({batch_key:batchKey,contacts:[],assigned_to:me?.username});
    if(me?.role==="admin"||me?.role==="director") api<{username:string;display_name?:string}[]>("/api/communication/assignees").then(setMembers).catch(()=>setMembers([]));
  },[open,batchKey,me?.username,me?.role,form]);
  const destination=(r:Saved)=>`/leads/${r.id}?returnTo=${encodeURIComponent("/leads?batch="+encodeURIComponent(r.batch_key))}`;
  const submit=async(enrich:boolean,force=false)=>{
    let values:Values;
    try{values=await form.validateFields();}catch{return;}
    setAction(enrich?"enrich":"view");setError(undefined);
    try{
      const body={...values,contacts:(values.contacts||[]).filter(c=>c?.contact_ref?.trim()),request_id:request.current,allow_duplicate:force};
      if(!force){const r=await api<{duplicates:Match[]}>("/api/leads/manual/check",json(body));if(r.duplicates.length){setMatches(r.duplicates);return;}}
      const result=await api<Saved>("/api/leads/manual",json(body));setSaved(result);onSaved();
      if(enrich) {
        try { await api(`/api/leads/${result.id}/enrichment`,json({mode:"continue",items:["website","contacts"]})); }
        catch(e){setError("门店已保存，自动完善未启动："+(e as Error).message);return;}
      }
      router.push(destination(result));onClose();
    }catch(e){setError((e as Error).message);}finally{setAction(null);}
  };
  return <Drawer title="新增门店" width={620} open={open} onClose={()=>{if(busy)return;if(!saved&&form.isFieldsTouched())Modal.confirm({title:"放弃未保存的门店资料？",okText:"放弃",cancelText:"继续填写",onOk:onClose});else onClose();}} maskClosable={false} closable={!busy} destroyOnHidden
    footer={saved ? <Link href={destination(saved)}>进入已保存门店 →</Link> : <Space wrap><Button loading={action==="view"} disabled={busy} onClick={()=>submit(false,!!matches.length)}>{matches.length?"仍然新建并查看":"保存并查看"}</Button><Button type="primary" loading={action==="enrich"} disabled={busy} onClick={()=>submit(true,!!matches.length)}>{matches.length?"仍然新建并 AI 完善":"保存并 AI 完善"}</Button></Space>}>
    <Typography.Paragraph type="secondary">只需填写门店名称。官网、联系方式和菜单都可以之后补充；AI 完善会在后台查找官网及联系方式。</Typography.Paragraph>
    {error&&<Alert type="error" showIcon message={error} style={{marginBottom:16}}/>}
    {saved ? <Alert type="success" showIcon message="门店已保存" description="资料已保留，可进入门店详情继续完善或上传菜单。"/> : <>
    {!!matches.length&&<Alert type="warning" showIcon message="发现可能已有的门店" description={<><p>请先核对；不同分店可以选择下方“仍然新建”。</p>{matches.map(m=><div key={m.id} style={{marginBottom:12}}><Link href={`/leads/${m.id}`}>{m.name} ↗</Link><div>{m.address} {m.postcode}</div><Typography.Text type="secondary">{m.reasons.join("；")}</Typography.Text></div>)}</>} style={{marginBottom:16}}/>}
    <Form form={form} layout="vertical" disabled={busy} onValuesChange={()=>setMatches([])}>
      <Form.Item name="name" label="门店名称" rules={[{required:true,whitespace:true,message:"请填写门店名称"}]}><Input maxLength={256} placeholder="例如 Rose Garden Restaurant"/></Form.Item>
      <Form.Item name="batch_key" label="所属名单" extra="未选择时放入“我的手动录入”，之后可直接继续完善。"><Select allowClear placeholder="我的手动录入" options={batches.map(b=>({value:b.batch_key,label:b.batch_key}))}/></Form.Item>
      <Form.Item name="website" label="官网"><Input maxLength={512} placeholder="例如 www.restaurant.co.uk"/></Form.Item>
      <Space.Compact style={{display:"flex",gap:12}}><Form.Item name="region" label="城市／地区" style={{flex:1,minWidth:0}}><Input maxLength={128}/></Form.Item><Form.Item name="postcode" label="邮编" style={{flex:1,minWidth:0}}><Input maxLength={16}/></Form.Item></Space.Compact>
      <Form.Item name="address" label="门店地址"><Input maxLength={1000}/></Form.Item>
      <Form.Item name="contact_name" label="联系人"><Input maxLength={128} placeholder="姓名或职位（选填）"/></Form.Item>
      <Form.List name="contacts">{(fields,{add,remove})=><><Typography.Paragraph strong>联系方式</Typography.Paragraph>{fields.map(f=><Space key={f.key} align="start" style={{display:"flex"}}><Form.Item name={[f.name,"channel"]} rules={[{required:true}]}><Select aria-label="联系方式类型" style={{width:125}} options={channels}/></Form.Item><Form.Item name={[f.name,"contact_ref"]} rules={[{required:true,whitespace:true,message:"请填写联系方式"}]} style={{flex:1,minWidth:0}}><Input aria-label="联系方式" maxLength={512}/></Form.Item><Button onClick={()=>remove(f.name)}>移除</Button></Space>)}<Button disabled={busy||fields.length>=15} onClick={()=>add({channel:"email",contact_ref:""})}>添加联系方式</Button></>}</Form.List>
      <Collapse ghost style={{marginTop:16}} items={[{key:"extra",label:"负责人及备注",children:<>{me?.role!=="member"&&<Form.Item name="assigned_to" label="负责人"><Select options={members.map(m=>({value:m.username,label:m.display_name||m.username}))}/></Form.Item>}<Form.Item name="notes" label="备注"><Input.TextArea rows={3} maxLength={2000} placeholder="例如转介绍来源、交流情况"/></Form.Item></>} ]}/>
    </Form></>}
  </Drawer>;
}
