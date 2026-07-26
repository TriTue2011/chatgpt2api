"use client";

import { useEffect, useRef, useState } from "react";
import { Archive, Download, Upload, Trash2, RefreshCw, HardDrive, ArrowLeftRight, LoaderCircle } from "lucide-react";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { request } from "@/lib/request";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type BackupItem = {
  filename: string;
  path: string;
  size_bytes: number;
  created_at: string;
};

function BackupPageContent() {
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");
  const [importPath, setImportPath] = useState("");
  const [importing, setImporting] = useState(false);
  const [uploadDrag, setUploadDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [deletingBackup, setDeletingBackup] = useState<BackupItem | null>(null);
  const [deletingInFlight, setDeletingInFlight] = useState(false);

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
    setDeletingInFlight(true);
    try {
      await request.delete(`/api/v1/backups/${encodeURIComponent(filename)}`);
      setBackups((prev) => prev.filter((b) => b.filename !== filename));
      setMessage("Đã xóa sao lưu");
      setDeletingBackup(null);
    } catch (e: any) {
      setMessage(`Lỗi: ${e?.message || "Không thể xóa"}`);
    } finally {
      setDeletingInFlight(false);
    }
  }

  async function handleFileUpload(file: File) {
    setImporting(true);
    setMessage("");
    try {
      const text = await file.text();
      const json = JSON.parse(text);
      const data = await request.post("/api/v1/import-9router-upload", json);
      const result = data.data as any;
      if (result?.ok) {
        setMessage(result.message || `Đã import ${result.imported_tokens || 0} token từ ${file.name}`);
        await fetchBackups();
      } else {
        setMessage(`Lỗi: ${result?.errors?.join(", ") || "Import thất bại"}`);
      }
    } catch (e: any) {
      if (e instanceof SyntaxError) {
        setMessage("Lỗi: File không phải JSON hợp lệ");
      } else {
        setMessage(`Lỗi: ${e?.message || "Import thất bại"}`);
      }
    } finally {
      setImporting(false);
    }
  }

  async function import9Router() {
    const path = importPath.trim();
    if (!path) {
      setMessage("Vui lòng nhập đường dẫn file backup");
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
        <p className="text-[var(--muted-foreground)]">Đang tải...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between border-b border-black/[0.04] pb-5">
        <div className="flex flex-col gap-1">
          <h1 className="text-[24px] font-bold tracking-tight text-[var(--foreground)]">Sao lưu &amp; Phục hồi</h1>
          <p className="text-[14px] text-[var(--muted-foreground)]">
            Sao lưu toàn bộ state (tài khoản, config, provider, combo) ra file JSON
          </p>
        </div>
        <button
          type="button"
          onClick={createBackup}
          disabled={creating}
          className="inline-flex items-center gap-2 rounded-[12px] bg-slate-900 px-4 py-2.5 text-[14px] font-medium text-white transition hover:bg-slate-800 disabled:opacity-50"
        >
          {creating ? <RefreshCw className="size-4 animate-spin" /> : <Download className="size-4" />}
          {creating ? "Đang tạo..." : "Tạo sao lưu mới"}
        </button>
      </div>

      {message && (
        <div className={cn(
          "rounded-lg px-4 py-3 text-sm",
          message.startsWith("Lỗi") ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-600",
        )}>
          {message}
        </div>
      )}

      {/* Import từ 9router */}
      <div className="rounded-[16px] p-5 card-3d card-tint-amber">
        <div className="flex items-center gap-2 mb-3">
          <div className="flex size-9 items-center justify-center rounded-[10px] bg-amber-100">
            <ArrowLeftRight className="size-[18px] text-amber-600" />
          </div>
          <h3 className="text-[15px] font-bold text-[var(--foreground)]">Import từ 9router</h3>
        </div>
        <p className="text-xs text-[var(--muted-foreground)] mb-3">
          Nhập file backup từ 9router để lấy token Codex OAuth. Token được thêm vào cả pool chat (cx/) và pool ảnh.
        </p>

        {/* Chọn file + kéo thả */}
        <div
          className={cn(
            "rounded-xl border-2 border-dashed p-6 text-center transition cursor-pointer",
            uploadDrag ? "border-amber-400 bg-amber-100" : "border-[var(--border)] hover:border-amber-300 bg-[var(--card)]",
          )}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setUploadDrag(true); }}
          onDragLeave={() => setUploadDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setUploadDrag(false);
            const file = e.dataTransfer.files?.[0];
            if (file) handleFileUpload(file);
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".json,.json.gz"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileUpload(file);
              e.target.value = "";
            }}
          />
          <Upload className="size-6 text-[var(--foreground)] mx-auto mb-1" />
          <p className="text-sm text-[var(--muted-foreground)]">Click chọn file hoặc kéo thả vào đây</p>
          <p className="text-xs text-[var(--muted-foreground)] mt-1">Hỗ trợ .json và .json.gz</p>
        </div>

        {importing && (
          <div className="flex items-center gap-2 mt-3 text-amber-600 text-sm">
            <RefreshCw className="size-4 animate-spin" />
            Đang import...
          </div>
        )}
      </div>

      {/* Backup list */}
      {backups.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-[var(--muted-foreground)]">
          <HardDrive className="size-12 mb-3 opacity-30" />
          <p>Chưa có sao lưu nào</p>
          <p className="text-xs mt-1">Tạo sao lưu đầu tiên để bảo vệ dữ liệu</p>
        </div>
      ) : (
        <div className="space-y-2">
          {backups.map((backup) => (
            <div
              key={backup.filename}
              className={cn(
                "flex items-center justify-between rounded-[14px] px-5 py-4",
                "card-3d card-tint-indigo",
                "transition-all"
              )}
            >
              <div className="flex items-center gap-4">
                <div className="flex size-10 items-center justify-center rounded-[10px] bg-amber-50">
                  <Archive className="size-[18px] text-amber-500" />
                </div>
                <div>
                  <p className="text-[14px] font-semibold text-[var(--foreground)]">{backup.filename}</p>
                  <p className="text-[12px] text-[var(--muted-foreground)]">
                    {formatSize(backup.size_bytes)} · {formatDate(backup.created_at)}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setDeletingBackup(backup)}
                className="rounded-[10px] p-2 text-[var(--muted-foreground)] transition hover:bg-rose-50 hover:text-rose-500"
                title="Xóa"
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      <Dialog open={Boolean(deletingBackup)} onOpenChange={(open) => (!open ? setDeletingBackup(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>Xóa bản sao lưu</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              Bạn có chắc chắn muốn xóa bản sao lưu "{deletingBackup?.filename}"? Hành động này không thể hoàn tác.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" className="rounded-xl" onClick={() => setDeletingBackup(null)} disabled={deletingInFlight}>
              Hủy
            </Button>
            <Button
              className="rounded-xl bg-rose-600 text-white hover:bg-rose-700"
              onClick={() => deletingBackup && void deleteBackup(deletingBackup.filename)}
              disabled={deletingInFlight || !deletingBackup}
            >
              {deletingInFlight ? <LoaderCircle className="size-4 animate-spin" /> : null}
              Xác nhận xóa
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function BackupPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return <BackupPageContent />;
}
