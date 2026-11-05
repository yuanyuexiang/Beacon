"use client";
import { useState } from "react";
import { Alert, Input, Modal, Typography } from "antd";
import Button from "@/components/AccessButton";
import { api, json } from "@/lib/api";

export default function PhoneWhatsApp({ leadId, contactId, number, disabled, onPrepared }: {
  leadId: string; contactId: string; number: string | null; disabled: boolean;
  onPrepared: (contact: { id: string; channel: string }) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  return <><Button size="small" disabled={disabled} onClick={() => {
    const raw = (number || "").replace(/[\s()-]/g, "");
    setValue(raw.startsWith("00") ? `+${raw.slice(2)}` : raw.startsWith("0") ? `+44${raw.slice(1)}` : raw);
    setError(undefined); setOpen(true);
  }}>通过 WhatsApp 联系</Button>
    <Modal title="使用这个号码准备 WhatsApp 消息" open={open} onCancel={() => { if (!busy) setOpen(false); }}
      okText="确认号码并准备消息" confirmLoading={busy} onOk={async () => {
        setBusy(true); setError(undefined);
        try {
          const contact = await api<{ id: string; channel: string }>(`/api/leads/${leadId}/eligibility/${contactId}/whatsapp`, json({ contact_ref: value.trim() }));
          await onPrepared(contact); setOpen(false);
        } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
      }}>
      <Typography.Paragraph>请核对完整国际号码。英国本地号码已预填 +44，可修改区号。</Typography.Paragraph>
      <Input aria-label="WhatsApp 完整号码" value={value} onChange={e => setValue(e.target.value)} placeholder="例如 +44…" />
      <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>保留原电话，复用已有 WhatsApp 记录。此操作只进入消息准备，不验证是否注册、不发送消息。</Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
    </Modal></>;
}
