"use client";

import { Globe, LoaderCircle, Save } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

import { useSettingsStore } from "../store";

export function BaseUrlCard() {
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setBaseUrl = useSettingsStore((state) => state.setBaseUrl);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  const baseUrl = String(config?.base_url || "");

  return (
    <Card className="rounded-2xl card-3d card-tint-slate">
      <CardContent className="space-y-6 p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-[var(--secondary)]">
              <Globe className="size-5 text-[var(--muted-foreground)]" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">Địa chỉ cơ sở</h2>
              <p className="text-sm text-[var(--muted-foreground)]">Thiết lập giá trị `CHATGPT2API_BASE_URL`, lưu lại có hiệu lực ngay.</p>
            </div>
          </div>
          <Badge variant={baseUrl.trim() ? "success" : "secondary"} className="w-fit rounded-md px-2.5 py-1">
            {baseUrl.trim() ? "Đã cấu hình" : "Chưa cấu hình"}
          </Badge>
        </div>

        {isLoadingConfig ? (
          <div className="flex items-center justify-center py-10">
            <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : (
          <>
            <div className="space-y-2">
              <label className="text-sm font-medium text-[var(--foreground)]">Base URL</label>
              <Input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://example.com"
                className="h-11 rounded-xl border-[var(--border)] bg-[var(--card)]"
              />
              <p className="text-sm text-[var(--muted-foreground)]">留空则使用环境变量或默认值，Lưu时会自动去掉首尾空格。</p>
            </div>

            <div className="flex justify-end">
              <Button
                className="h-10 rounded-xl bg-[var(--primary)] px-5 text-[var(--primary-foreground)] hover:brightness-110"
                onClick={() => void saveConfig()}
                disabled={isSavingConfig}
              >
                {isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                Lưu
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}


