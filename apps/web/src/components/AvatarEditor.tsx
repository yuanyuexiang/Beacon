"use client";
import { Alert, Button, Space, Typography } from "antd";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { useOperator } from "@/lib/auth";
import { UserAvatar } from "./UserAvatar";

export function AvatarEditor() {
  const { me, refresh } = useOperator();
  const input = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<"upload" | "remove" | null>(null);
  const [error, setError] = useState<string>();
  const [preview, setPreview] = useState<{ file: File; url: string }>();
  const clear = () => { setPreview(undefined); if (input.current) input.current.value = ""; };
  const save = async (kind: "upload" | "remove") => {
    setPending(kind); setError(undefined);
    try {
      const body = new FormData();
      if (preview) body.append("file", preview.file);
      await api("/api/auth/avatar", kind === "upload" ? { method: "PUT", body } : { method: "DELETE" });
      await refresh(); clear();
    } catch (e) { setError((e as Error).message); } finally { setPending(null); }
  };
  return <div style={{ marginBottom: 24 }}>
    <Space align="center" wrap>
      <UserAvatar user={preview && me ? { ...me, avatar_url: preview.url } : me} size={80} />
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" hidden aria-label="选择头像" onChange={(e) => {
        setError(undefined); const file = e.target.files?.[0]; if (!file) return;
        if (file.size > 5 * 1024 * 1024) { setError("头像不能超过 5 MB"); e.target.value = ""; return; }
        const reader = new FileReader(); reader.onload = () => setPreview({ file, url: String(reader.result) }); reader.readAsDataURL(file);
      }} />
      <Button disabled={!!pending || me?.must_change_password} onClick={() => input.current?.click()}>选择／更换头像</Button>
      {preview && <><Button type="primary" loading={pending === "upload"} disabled={!!pending || me?.must_change_password} onClick={() => void save("upload")}>保存头像</Button><Button disabled={!!pending} onClick={clear}>取消</Button></>}
      {me?.avatar_url && <Button loading={pending === "remove"} disabled={!!pending || me.must_change_password} onClick={() => void save("remove")}>恢复默认头像</Button>}
    </Space>
    <Typography.Paragraph type="secondary">支持 JPG、PNG、WebP，最大 5 MB；保存时居中裁切为正方形。</Typography.Paragraph>
    {error && <Alert type="error" showIcon message={error} />}
  </div>;
}
