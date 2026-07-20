"use client";

import { AlertTriangle, LoaderCircle, Plus, Play, RotateCcw, Save, Square, Trash2, UserPlus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { useSettingsStore } from "../../settings/store";

export function RegisterCard() {
  const config = useSettingsStore((state) => state.registerConfig);
  const isLoading = useSettingsStore((state) => state.isLoadingRegister);
  const isSaving = useSettingsStore((state) => state.isSavingRegister);
  const setProxy = useSettingsStore((state) => state.setRegisterProxy);
  const setTotal = useSettingsStore((state) => state.setRegisterTotal);
  const setThreads = useSettingsStore((state) => state.setRegisterThreads);
  const setMode = useSettingsStore((state) => state.setRegisterMode);
  const setTargetQuota = useSettingsStore((state) => state.setRegisterTargetQuota);
  const setTargetAvailable = useSettingsStore((state) => state.setRegisterTargetAvailable);
  const setCheckInterval = useSettingsStore((state) => state.setRegisterCheckInterval);
  const setMailField = useSettingsStore((state) => state.setRegisterMailField);
  const addProvider = useSettingsStore((state) => state.addRegisterProvider);
  const updateProvider = useSettingsStore((state) => state.updateRegisterProvider);
  const deleteProvider = useSettingsStore((state) => state.deleteRegisterProvider);
  const save = useSettingsStore((state) => state.saveRegister);
  const toggle = useSettingsStore((state) => state.toggleRegister);
  const reset = useSettingsStore((state) => state.resetRegister);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--primary)]/80 p-10">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (!config) return null;

  const stats = config.stats || { success: 0, fail: 0, done: 0, running: 0, threads: config.threads };
  const providers = config.mail.providers || [];
  const logs = config.logs || [];
  const updateProviderType = (index: number, type: string) => {
    updateProvider(index, {
      type,
      enable: true,
      ...(type === "cloudflare_temp_email" ? { api_base: "", admin_password: "", domain: [] } : {}),
      ...(type === "tempmail_lol" ? { api_key: "", domain: [] } : {}),
      ...(type === "moemail" ? { api_base: "", api_key: "", domain: [] } : {}),
      ...(type === "inbucket" ? { api_base: "", domain: [], random_subdomain: true } : {}),
      ...(type === "duckmail" ? { api_key: "", default_domain: "duckmail.sbs" } : {}),
      ...(type === "gptmail" ? { api_key: "", default_domain: "" } : {}),
      ...(type === "yyds_mail" ? { api_base: "https://maliapi.215.im/v1", api_key: "", domain: [], subdomain: "", wildcard: false } : {}),
    });
  };

  return (
    <div className="grid h-[calc(100vh-132px)] min-h-[640px] items-stretch gap-0 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]/70 xl:grid-cols-2">
      <section className="space-y-4 overflow-y-auto border-b border-[var(--border)] p-4 xl:border-r xl:border-b-0">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-md bg-[var(--secondary)]">
                <UserPlus className="size-5 text-[var(--muted-foreground)]" />
              </div>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Cấu hình đăng ký</h2>
              </div>
            </div>
            <Button className="h-9 rounded-xl bg-[var(--primary)] px-4 text-[var(--primary-foreground)] hover:brightness-110" onClick={() => void save()} disabled={isSaving || config.enabled}>
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
              Lưu cấu hình
            </Button>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Chế độ đăng ký</label>
              <Select value={config.mode || "total"} onValueChange={(value) => setMode(value as "total" | "quota" | "available")} disabled={config.enabled}>
                <SelectTrigger className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="total">Tổng số đăng ký</SelectItem>
                  <SelectItem value="quota">Hạn mức còn lại</SelectItem>
                  <SelectItem value="available">Số lượng tài khoản khả dụng</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Tổng số đăng ký</label>
              <Input value={String(config.total)} onChange={(event) => setTotal(event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled || config.mode !== "total"} />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Số luồng (Threads)</label>
              <Input value={String(config.threads)} onChange={(event) => setThreads(event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Proxy đăng ký</label>
              <Input value={config.proxy} onChange={(event) => setProxy(event.target.value)} placeholder="http://127.0.0.1:7890" className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Hạn mức mục tiêu</label>
              <Input value={String(config.target_quota || "")} onChange={(event) => setTargetQuota(event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled || config.mode !== "quota"} />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Tài khoản khả dụng mục tiêu</label>
              <Input value={String(config.target_available || "")} onChange={(event) => setTargetAvailable(event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled || config.mode !== "available"} />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--foreground)]">Khoảng thời gian kiểm tra (giây)</label>
              <Input value={String(config.check_interval || "")} onChange={(event) => setCheckInterval(event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled || config.mode === "total"} />
            </div>
          </div>

          <div className="space-y-3 border-t border-[var(--border)] pt-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-[var(--foreground)]">Cấu hình Email</h3>
                <p className="mt-1 text-xs text-[var(--muted-foreground)]">Có thể cấu hình nhiều nhà cung cấp, xoay vòng theo thứ tự kích hoạt.</p>
              </div>
              <Button type="button" variant="outline" className="h-9 rounded-xl border-[var(--border)] bg-[var(--card)] px-3 text-[var(--foreground)]" onClick={addProvider} disabled={config.enabled}>
                <Plus className="size-4" />
                Thêm
              </Button>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm text-[var(--foreground)]">Thời gian chờ yêu cầu</label>
                <Input value={String(config.mail.request_timeout || "")} onChange={(event) => setMailField("request_timeout", event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-[var(--foreground)]">Thời gian chờ mã xác nhận</label>
                <Input value={String(config.mail.wait_timeout || "")} onChange={(event) => setMailField("wait_timeout", event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-[var(--foreground)]">Khoảng thời gian thăm dò</label>
                <Input value={String(config.mail.wait_interval || "")} onChange={(event) => setMailField("wait_interval", event.target.value)} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
              </div>
            </div>

            <div className="space-y-3">
              {providers.map((provider, index) => {
                const type = String(provider.type || "tempmail_lol");
                const domains = Array.isArray(provider.domain) ? provider.domain.map(String).join("\n") : "";
                return (
                  <div key={index} className="space-y-3 border-t border-[var(--border)] pt-3 first:border-t-0 first:pt-0">
                    <div className="flex items-center justify-between gap-3">
                      <label className="flex items-center gap-3 text-sm text-[var(--foreground)]">
                        <Checkbox checked={Boolean(provider.enable)} onCheckedChange={(checked) => updateProvider(index, { enable: Boolean(checked) })} disabled={config.enabled} />
                        Kích hoạt
                      </label>
                      <button type="button" className="rounded-lg p-2 text-[var(--muted-foreground)] transition hover:bg-rose-50 hover:text-rose-500 disabled:opacity-50" onClick={() => deleteProvider(index)} disabled={config.enabled || providers.length <= 1} title="Xóa provider">
                        <Trash2 className="size-4" />
                      </button>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <label className="text-sm text-[var(--foreground)]">Loại</label>
                        <Select value={type} onValueChange={(value) => updateProviderType(index, value)} disabled={config.enabled}>
                          <SelectTrigger className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="cloudflare_temp_email">cloudflare_temp_email</SelectItem>
                            <SelectItem value="tempmail_lol">tempmail_lol</SelectItem>
                            <SelectItem value="moemail">moemail</SelectItem>
                            <SelectItem value="inbucket">inbucket_mail</SelectItem>
                            <SelectItem value="duckmail">duckmail</SelectItem>
                            <SelectItem value="gptmail">gptmail (Chưa kiểm tra)</SelectItem>
                            <SelectItem value="yyds_mail">yyds_mail</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      {type === "cloudflare_temp_email" || type === "moemail" || type === "inbucket" || type === "yyds_mail" ? (
                        <>
                          <div className="space-y-2">
                            <label className="text-sm text-[var(--foreground)]">API Base</label>
                            <Input value={String(provider.api_base || "")} onChange={(event) => updateProvider(index, { api_base: event.target.value })} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
                          </div>
                          {type === "cloudflare_temp_email" ? (
                            <div className="space-y-2">
                              <label className="text-sm text-[var(--foreground)]">Admin Password</label>
                              <Input value={String(provider.admin_password || "")} onChange={(event) => updateProvider(index, { admin_password: event.target.value })} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
                            </div>
                          ) : null}
                        </>
                      ) : null}
                      {type === "inbucket" ? (
                        <label className="flex items-center gap-3 pt-8 text-sm text-[var(--foreground)]">
                          <Checkbox checked={Boolean(provider.random_subdomain ?? true)} onCheckedChange={(checked) => updateProvider(index, { random_subdomain: Boolean(checked) })} disabled={config.enabled} />
                          Bật tên miền phụ ngẫu nhiên
                        </label>
                      ) : null}
                      {type === "tempmail_lol" || type === "moemail" || type === "duckmail" || type === "gptmail" || type === "yyds_mail" ? (
                        <div className="space-y-2">
                          <label className="text-sm text-[var(--foreground)]">API Key</label>
                          <Input value={String(provider.api_key || "")} onChange={(event) => updateProvider(index, { api_key: event.target.value })} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
                        </div>
                      ) : null}
                      {type === "duckmail" || type === "gptmail" ? (
                        <div className="space-y-2">
                          <label className="text-sm text-[var(--foreground)]">Default Domain</label>
                          <Input value={String(provider.default_domain || "")} onChange={(event) => updateProvider(index, { default_domain: event.target.value })} placeholder={type === "duckmail" ? "duckmail.sbs" : ""} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
                        </div>
                      ) : null}
                      {type === "yyds_mail" ? (
                        <>
                          <div className="space-y-2">
                            <label className="text-sm text-[var(--foreground)]">Subdomain</label>
                            <Input value={String(provider.subdomain || "")} onChange={(event) => updateProvider(index, { subdomain: event.target.value })} className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)]" disabled={config.enabled} />
                          </div>
                          <label className="flex items-center gap-3 pt-8 text-sm text-[var(--foreground)]">
                            <Checkbox checked={Boolean(provider.wildcard)} onCheckedChange={(checked) => updateProvider(index, { wildcard: Boolean(checked) })} disabled={config.enabled} />
                            Wildcard
                          </label>
                        </>
                      ) : null}
                    </div>

                    {type === "tempmail_lol" || type === "cloudflare_temp_email" || type === "moemail" || type === "inbucket" || type === "yyds_mail" ? (
                      <div className="space-y-2">
                        <label className="text-sm text-[var(--foreground)]">{type === "inbucket" ? "Danh sách tên miền cơ sở" : "Tên miền (Domain)"}</label>
                        <Textarea value={domains} onChange={(event) => updateProvider(index, { domain: event.target.value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean) })} placeholder={type === "inbucket" ? "Mỗi dòng một tên miền cơ sở, hệ thống sẽ tự động tạo tên miền phụ ngẫu nhiên" : type === "moemail" ? "Mỗi dòng một tên miền" : "Mỗi dòng một tên miền, để trống để sử dụng tên miền mặc định của dịch vụ"} className="min-h-20 rounded-xl border-[var(--border)] bg-[var(--card)] font-mono text-xs" disabled={config.enabled} />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>

      </section>

      <section className="flex min-h-0 flex-col p-4">
        <div className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Kết quả chạy</h2>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">Trạng thái hiện tại được đẩy qua SSE thời gian thực.</p>
              </div>
              <Badge variant={config.enabled ? "success" : "secondary"} className="rounded-md">
                {config.enabled ? "Đang chạy" : "Đã dừng"}
              </Badge>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {[
                ["Thành công / Tỉ lệ", `${stats.success} / ${stats.success_rate || 0}%`],
                ["Thất bại", stats.fail],
                ["Hoàn thành", stats.done],
                ["Đang chạy / Luồng", `${stats.running} / ${stats.threads}`],
                ["Thời gian chạy", `${stats.elapsed_seconds || 0}s`],
                ["Đăng ký TB mỗi tài khoản", `${stats.avg_seconds || 0}s`],
                ["Hạn mức hiện tại", stats.current_quota || 0],
                ["Tài khoản bình thường", stats.current_available || 0],
              ].map(([label, value]) => (
                <div key={label} className="border border-[var(--border)] bg-[var(--card)]/70 px-3 py-2">
                  <div className="text-xs text-[var(--muted-foreground)]">{label}</div>
                  <div className="mt-1 text-base font-semibold text-[var(--foreground)]">{value}</div>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Button className="h-10 rounded-xl bg-[var(--primary)] px-3 text-[var(--primary-foreground)] hover:brightness-110" onClick={() => void toggle()} disabled={isSaving}>
                {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : config.enabled ? <Square className="size-4" /> : <Play className="size-4" />}
                {config.enabled ? "Dừng" : "Bắt đầu"}
              </Button>
              <Button variant="outline" className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)] px-3 text-[var(--foreground)]" onClick={() => void reset()} disabled={isSaving || config.enabled}>
                <RotateCcw className="size-4" />
                Đặt lại
              </Button>
              <Button variant="outline" className="h-10 rounded-xl border-[var(--border)] bg-[var(--card)] px-3 text-[var(--foreground)]" onClick={() => void save()} disabled={isSaving || config.enabled}>
                <Save className="size-4" />
                Lưu
              </Button>
            </div>
            <div className="flex items-center gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <AlertTriangle className="size-4 shrink-0" />
              Lưu ý lưu cấu hình trước khi bắt đầu.
            </div>
        </div>

        <div className="mt-4 flex min-h-0 flex-1 flex-col space-y-3 overflow-hidden border-t border-[var(--border)] pt-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[var(--foreground)]">Nhật ký trực tiếp</h3>
                <p className="mt-1 text-xs text-amber-700">Nếu gặp lỗi như mã trạng thái HTTP 400, cơ bản là do email bị lạm dụng và bị chặn, bạn cần thay đổi tên miền email mới.</p>
              </div>
              <Badge variant="secondary" className="rounded-md">
                {logs.length}
              </Badge>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto border border-[var(--border)] bg-[var(--card)]/70 p-3 font-mono text-xs leading-6">
              {logs.length === 0 ? (
                <div className="text-[var(--muted-foreground)]">Chưa có nhật ký</div>
              ) : (
                logs.slice().reverse().map((item, index) => (
                  <div key={`${item.time}-${index}`} className={item.level === "red" ? "text-rose-600" : item.level === "green" ? "text-emerald-700" : item.level === "yellow" ? "text-amber-700" : "text-[var(--foreground)]"}>
                    <span className="text-[var(--muted-foreground)]">{new Date(item.time).toLocaleTimeString()}</span>
                    <span className="pl-2">{item.text}</span>
                  </div>
                ))
              )}
            </div>
        </div>
      </section>
    </div>
  );
}
