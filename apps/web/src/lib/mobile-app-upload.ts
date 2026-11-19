import { api, ApiError, json } from "@/lib/api";

export async function uploadMobileApp(file: Blob, progress: (percent: number) => void) {
  const session = await api<{upload_id:string;chunk_bytes:number}>("/api/mobile/app/uploads/start",json({size:file.size}));
  const base = `/api/mobile/app/uploads/${encodeURIComponent(session.upload_id)}`;
  try {
    if (!Number.isInteger(session.chunk_bytes) || session.chunk_bytes < 1 || session.chunk_bytes > 2*1024**2) {
      throw new Error("服务器返回的上传分段配置无效");
    }
    for (let offset=0; offset<file.size; offset+=session.chunk_bytes) {
      const body=file.slice(offset,offset+session.chunk_bytes);
      let response: {received:number}|undefined;
      // Each chunk is idempotent. Retry only transport errors, never publication.
      for (let attempt=0;attempt<2;attempt++) {
        try {
          response=await api<{received:number}>(`${base}/chunks?offset=${offset}`,{
            method:"PUT",headers:{"Content-Type":"application/octet-stream"},body,
          });
          break;
        } catch(e) {
          if(attempt || (e instanceof ApiError && ![408,502,503,504].includes(e.status))) throw e;
        }
      }
      const end=Math.min(offset+session.chunk_bytes,file.size);
      if(response?.received!==end) throw new Error("服务器收到的文件长度不一致，请重新上传");
      progress(Math.floor(end/file.size*100));
    }
    return await api<{already_published?:boolean}>(`${base}/finish`,json({}));
  } catch(e) {
    await api(base,{method:"DELETE"}).catch(() => undefined);
    throw e;
  }
}
