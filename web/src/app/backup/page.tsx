"use client";

import { useEffect, useState } from "react";
import { Archive, Download, Upload, Trash2, RefreshCw, HardDrive } from "lucide-react";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";

type BackupItem = {
  filename: string;
  path: string;
  size_bytes: number;
  created_at: string;
};

export default function BackupPage() {
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetchBackups();
  }, []);

  async function fetchBackups() {
    try {
      const data = await request.get("/api/v1/backups");
      setBackups((data.data as any)?.backups || []);
    } catch (e) {
      console.error("Failed to fetch backups", e);
    } finally {
      setLoading(false);
    }
  }

  async function createBackup() {
    setCreating(true);
    setMessage("");
    try {
      const data = await request.post("/api/v1/backup");
      const result = data.data as any;
      setMessage(`Đã tạo sao lưu: ${Math.round((result?.size_bytes || 0) / 1024)} KB`);
      await fetchBackups();
    } catch (e: any) {
      setMessage(`Lỗi: ${e?.message || "Không thể tạo sao lưu"}`);
    } finally {
      setCreating(false);
    }
  }

  async function deleteBackup(filename: string) {
    try {
      await request.delete(`/api/v1/backups/${encodeURIComponent(filename)}`);
      setBackups((prev) => prev.filter((b) => b.filename !== filename));
      setMessage("Đã xóa sao lưu");
    } catch (e: any) {
      setMessage(`Lỗi: ${e?.message || "Không thể xóa"}`);
    }
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString("vi-VN");
    } catch {
      return iso;
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-stone-400">Đang tải...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Sao lưu & Phục hồi</h1>
          <p className="mt-1 text-sm text-stone-400">
            Sao lưu toàn bộ state (tài khoản, config, provider, combo, ảnh) ra file JSON
          </p>
        </div>
        <button
          type="button"
          onClick={createBackup}
          disabled={creating}
          className="inline-flex items-center gap-2 rounded-lg bg-stone-50 px-4 py-2.5 text-sm font-medium text-stone-950 transition hover:bg-white disabled:opacity-50"
        >
          {creating ? (
            <RefreshCw className="size-4 animate-spin" />
          ) : (
            <Download className="size-4" />
          )}
          {creating ? "Đang tạo..." : "Tạo sao lưu mới"}
        </button>
      </div>

      {message && (
        <div className={cn(
          "rounded-lg px-4 py-3 text-sm",
          message.startsWith("Lỗi") ? "bg-red-500/10 text-red-400" : "bg-emerald-500/10 text-emerald-400",
        )}>
          {message}
        </div>
      )}

      {backups.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-stone-500">
          <HardDrive className="size-12 mb-3 opacity-50" />
          <p>Chưa có sao lưu nào</p>
          <p className="text-xs mt-1">Tạo sao lưu đầu tiên để bảo vệ dữ liệu</p>
        </div>
      ) : (
        <div className="space-y-2">
          {backups.map((backup) => (
            <div
              key={backup.filename}
              className="flex items-center justify-between rounded-xl border border-stone-800 bg-stone-900/50 px-5 py-4"
            >
              <div className="flex items-center gap-4">
                <Archive className="size-5 text-stone-400" />
                <div>
                  <p className="text-sm font-medium text-white">{backup.filename}</p>
                  <p className="text-xs text-stone-500">
                    {formatSize(backup.size_bytes)} · {formatDate(backup.created_at)}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => deleteBackup(backup.filename)}
                className="rounded-md p-2 text-stone-500 transition hover:bg-red-500/10 hover:text-red-400"
                title="Xóa"
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
