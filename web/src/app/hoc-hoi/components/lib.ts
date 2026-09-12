import { httpRequest } from "@/lib/request";
import { toast } from "sonner";

/** GET một endpoint Học hỏi, trả về data (đã có `ok`). */
export async function layGet<T = Record<string, unknown>>(path: string): Promise<T> {
  return httpRequest<T>(path, { method: "GET" });
}

/** POST một endpoint; báo toast lỗi nếu `ok=false`. Trả true khi thành công. */
export async function goiPost(
  path: string,
  body: Record<string, unknown>,
): Promise<boolean> {
  try {
    const res = await httpRequest<{ ok?: boolean; error?: string }>(path, {
      method: "POST",
      body,
    });
    if (!res?.ok) {
      toast.error(res?.error || "Không lưu được.");
      return false;
    }
    return true;
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "Lỗi mạng.");
    return false;
  }
}
