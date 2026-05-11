"use client";

import { useEffect, useState } from "react";
import { Archive, Download, Upload, Trash2, RefreshCw, HardDrive, ArrowLeftRight } from "lucide-react";
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
  const [importPath, setImportPath] = useState("");
  const [importing, setImporting] = useState(false);

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

  async function import9Router() {
    const path = importPath.trim();
    if (!path) {
      setMessage("Vui lòng nhập đường dẫn file backup 9router");
      return;
    }
    setImporting(true);
    setMessage("");
    try {
      const data = await request.post("/api/v1/import-9router", { path });
      const result = data.data as any;
      if (result?.ok) {
        setMessage(result.message || `Đã import ${result.imported_tokens || 0} token`);
        await fetchBackups();
      } else {
        setMessage(`Lỗi: ${result?.errors?.join(", ") || "Import thất bại"}`);
      }
    } catch (e: any) {
      setMessage(`Lỗi: ${e?.message || "Import thất bại"}`);
    } finally {
      setImporting(false);
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

      {/* Import từ 9router */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-5">
        <div className="flex items-center gap-2 mb-3">
          <ArrowLeftRight className="size-5 text-amber-400" />
          <h3 className="text-sm font-semibold text-white">Import từ 9router</h3>
        </div>
        <p className="text-xs text-stone-400 mb-3">
          Nhập file backup từ 9router để lấy token Codex OAuth (ChatGPT qua OpenAI API).
          Token sẽ được tự động thêm vào pool với type "codex".
        </p>
        <div className="flex flex-wrap gap-3">
          <input
            type="text"
            value={importPath}
            onChange={(e) => setImportPath(e.target.value)}
            placeholder="Đường dẫn file backup 9router (vd: /app/data/db.json)"
            className="min-w-[320px] flex-1 rounded-lg border border-stone-700 bg-stone-800 px-3 py-2 text-sm text-white placeholder:text-stone-500 focus:border-amber-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={import9Router}
            disabled={importing || !importPath.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-500/20 px-4 py-2 text-sm font-medium text-amber-400 transition hover:bg-amber-500/30 disabled:opacity-40 border border-amber-500/30"
          >
            {importing ? (
              <RefreshCw className="size-4 animate-spin" />
            ) : (
              <Upload className="size-4" />
            )}
            {importing ? "Đang import..." : "Import từ 9router"}
          </button>
        </div>
      </div>
    </div>
  );
}
