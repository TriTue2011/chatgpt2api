"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, type ChangeEvent } from "react";
import {
  ArrowLeft,
  ExternalLink,
  FileJson,
  FileText,
  Files,
  KeyRound,
  LoaderCircle,
  ServerCog,
  Upload,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { createAccounts, createOAuthAccounts, type Account } from "@/lib/api";
import { cn } from "@/lib/utils";

type ImportMethod = "menu" | "token" | "session" | "cpa" | "oauth";

type AccountImportDialogProps = {
  disabled?: boolean;
  onImported: (items: Account[]) => void;
};

type PendingCpaImport = {
  tokens: string[];
  parsedFileCount: number;
  errorCount: number;
};

const sessionUrl = "https://chatgpt.com/api/auth/session";

function splitTokens(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function getSessionAccessToken(value: unknown) {
  const token = (value as { accessToken?: unknown })?.accessToken;
  return typeof token === "string" ? token.trim() : "";
}

function getCpaAccessToken(value: unknown) {
  const token = (value as { access_token?: unknown })?.access_token;
  return typeof token === "string" ? token.trim() : "";
}

function readFileAsText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error(`Đọc tệp thất bại: ${file.name}`));
    reader.readAsText(file);
  });
}

function MethodCard({
  title,
  description,
  icon: Icon,
  onClick,
}: {
  title: string;
  description: string;
  icon: typeof KeyRound;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-2xl border border-stone-200 bg-white p-0 text-left transition hover:border-stone-300 hover:bg-stone-50"
    >
      <Card className="rounded-2xl border-0 bg-transparent shadow-none">
        <CardContent className="flex items-start gap-4 p-4">
          <div className="rounded-xl bg-stone-100 p-3 text-stone-700">
            <Icon className="size-5" />
          </div>
          <div className="space-y-1">
            <div className="text-sm font-semibold text-stone-900">{title}</div>
            <div className="text-sm leading-6 text-stone-500">{description}</div>
          </div>
        </CardContent>
      </Card>
    </button>
  );
}

export function AccountImportDialog({ disabled, onImported }: AccountImportDialogProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<ImportMethod>("menu");
  const [tokenInput, setTokenInput] = useState("");
  const [sessionInput, setSessionInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingCpaImport, setPendingCpaImport] = useState<PendingCpaImport | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const txtInputRef = useRef<HTMLInputElement | null>(null);
  const cpaInputRef = useRef<HTMLInputElement | null>(null);

  const resetState = () => {
    setMethod("menu");
    setTokenInput("");
    setSessionInput("");
    setPendingCpaImport(null);
    setConfirmOpen(false);
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      resetState();
    }
  };

  const submitTokens = async (tokens: string[], successText?: string) => {
    const normalizedTokens = tokens.map((item) => item.trim()).filter(Boolean);

    if (normalizedTokens.length === 0) {
      toast.error("Vui lòng cung cấp ít nhất một Token khả dụng");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await createAccounts(normalizedTokens);
      onImported(data.items);
      setOpen(false);
      resetState();

      if ((data.errors?.length ?? 0) > 0) {
        const firstError = data.errors?.[0]?.error;
        toast.error(
          `${successText ?? "Nhập hoàn tất"}，Thêm mới ${data.added ?? 0} mục，Đã làm mới ${data.refreshed ?? 0} mục，Thất bại ${data.errors?.length ?? 0} mục${firstError ? `，Lỗi đầu tiên: ${firstError}` : ""}`,
        );
      } else {
        toast.success(
          `${successText ?? "Nhập hoàn tất"}，Thêm mới ${data.added ?? 0} mục，Bỏ qua ${data.skipped ?? 0} mục trùng lặp，Đã tự động làm mới thông tin tài khoản`,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Nhập tài khoản thất bại";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleImportTokenText = async () => {
    await submitTokens(splitTokens(tokenInput), "Nhập Access Token hoàn tất");
  };

  const handleTxtSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";

    if (!file) {
      return;
    }

    try {
      const content = await readFileAsText(file);
      const tokens = splitTokens(content);

      if (tokens.length === 0) {
        toast.error("Không tìm thấy Token hợp lệ trong tệp TXT");
        return;
      }

      setTokenInput((prev) => {
        const next = [...splitTokens(prev), ...tokens];
        return next.join("\n");
      });
      toast.success(`Đã đọc ${tokens.length} Token từ ${file.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Đọc tệp TXT thất bại";
      toast.error(message);
    }
  };

  const handleImportSessionJson = async () => {
    if (!sessionInput.trim()) {
      toast.error("Vui lòng dán Session JSON đầy đủ");
      return;
    }

    try {
      const payload = JSON.parse(sessionInput) as unknown;
      const token = getSessionAccessToken(payload);

      if (!token) {
        toast.error("Không trích xuất được accessToken từ Session JSON");
        return;
      }

      await submitTokens([token], "Nhập Session JSON hoàn tất");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Phân tích Session JSON thất bại";
      toast.error(message);
    }
  };

  const handleImportOAuth = async () => {
    const oauthTokens = splitTokens(tokenInput);
    if (oauthTokens.length === 0) {
      toast.error("Vui lòng nhập ít nhất một OAuth Token");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await createOAuthAccounts(oauthTokens, "codex");
      onImported(data.items);
      setOpen(false);
      resetState();
      toast.success(`Đã thêm ${data.added ?? 0} tài khoản Codex OAuth, bỏ qua ${data.skipped ?? 0} trùng lặp`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Nhập OAuth thất bại";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCpaSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";

    if (files.length === 0) {
      return;
    }

    try {
      const results = await Promise.all(
        files.map(async (file) => {
          const raw = await readFileAsText(file);
          const parsed = JSON.parse(raw) as unknown;
          const token = getCpaAccessToken(parsed);
          return {
            token,
          };
        }),
      );

      const tokens = results.map((item) => item.token).filter((item): item is string => Boolean(item));
      const parsedFileCount = tokens.length;
      const errorCount = results.length - parsedFileCount;

      if (parsedFileCount === 0) {
        toast.error("Không tìm thấy access_token hợp lệ trong các tệp CPA JSON này");
        return;
      }

      setPendingCpaImport({
        tokens,
        parsedFileCount,
        errorCount,
      });
      setConfirmOpen(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Đọc tệp CPA JSON thất bại";
      toast.error(message);
    }
  };

  const renderMethodBody = () => {
    if (method === "token") {
      const tokenCount = splitTokens(tokenInput).length;

      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setMethod("menu")}
              className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
            >
              <ArrowLeft className="size-4" />
              Quay lại
            </button>
            <span className="text-xs text-stone-400">Đã nhận diện {tokenCount} Token</span>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">Danh sách Access Token</label>
            <Textarea
              placeholder="Mỗi dòng một Access Token..."
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              className="min-h-56 resize-none rounded-xl border-stone-200"
            />
          </div>
          <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="text-sm font-medium text-stone-800">Nhập từ tệp TXT</div>
                <div className="text-sm leading-6 text-stone-500">Hỗ trợ tệp `.txt`, nội dung tệp mỗi dòng một Token.</div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="rounded-xl border-stone-200 bg-white"
                onClick={() => txtInputRef.current?.click()}
                disabled={isSubmitting}
              >
                <FileText className="size-4" />
                Chọn TXT
              </Button>
            </div>
          </div>
          <input
            ref={txtInputRef}
            type="file"
            accept=".txt,text/plain"
            className="hidden"
            onChange={(event) => void handleTxtSelected(event)}
          />
        </div>
      );
    }

    if (method === "oauth") {
      const tokenCount = splitTokens(tokenInput).length;

      return (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setMethod("menu")}
              className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
            >
              <ArrowLeft className="size-4" />
              Quay lại
            </button>
            <span className="text-xs text-stone-400">Đã nhận diện {tokenCount} Token OAuth</span>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
            <div className="font-medium">Token OAuth từ 9router</div>
            <div>
              Dán Codex OAuth token từ backup 9router. Các token này gọi thẳng OpenAI API (api.openai.com) — không giới hạn 24KB, không cần browser impersonation.
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">OAuth Token (Codex)</label>
            <Textarea
              placeholder="Mỗi dòng một OAuth Token (JWT: eyJ...)..."
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              className="min-h-56 resize-none rounded-xl border-stone-200 font-mono text-xs"
            />
          </div>
          <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <div className="text-sm font-medium text-stone-800">Nhập từ tệp TXT</div>
                <div className="text-sm leading-6 text-stone-500">Hỗ trợ tệp `.txt`, mỗi dòng một Token.</div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="rounded-xl border-stone-200 bg-white"
                onClick={() => txtInputRef.current?.click()}
                disabled={isSubmitting}
              >
                <FileText className="size-4" />
                Chọn TXT
              </Button>
            </div>
          </div>
          <input
            ref={txtInputRef}
            type="file"
            accept=".txt,text/plain"
            className="hidden"
            onChange={(event) => void handleTxtSelected(event)}
          />
        </div>
      );
    }

    if (method === "session") {
      return (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMethod("menu")}
            className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
          >
            <ArrowLeft className="size-4" />
            Quay lại
          </button>
          <div className="rounded-2xl border border-stone-200 bg-stone-50 p-4 text-sm leading-6 text-stone-600">
            Mở
            {" "}
            <a
              href={sessionUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-medium text-stone-900 underline underline-offset-4"
            >
              {sessionUrl}
              <ExternalLink className="size-3.5" />
            </a>
            , sao chép toàn bộ JSON trả về từ trang web, hệ thống sẽ tự động trích xuất `accessToken` để nhập.
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
            <div className="font-medium">Cảnh báo rủi ro</div>
            <div>
              Đừng sử dụng tài khoản chính, hãy cố gắng sử dụng tài khoản phụ để nhập nhằm tránh rủi ro bị khóa tài khoản. Dự án này không chịu trách nhiệm cho bất kỳ rủi ro khóa tài khoản nào.
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium text-stone-700">Session JSON</label>
            <Textarea
              placeholder='Dán toàn bộ JSON, ví dụ đối tượng chứa "accessToken"...'
              value={sessionInput}
              onChange={(event) => setSessionInput(event.target.value)}
              className="min-h-56 resize-none rounded-xl border-stone-200 font-mono text-xs"
            />
          </div>
        </div>
      );
    }

    if (method === "cpa") {
      return (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMethod("menu")}
            className="inline-flex items-center gap-1 text-sm text-stone-500 transition hover:text-stone-800"
          >
            <ArrowLeft className="size-4" />
            Quay lại
          </button>
          <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50 p-5">
            <div className="space-y-2">
              <div className="text-sm font-medium text-stone-800">Chọn nhiều tệp CPA JSON từ máy tính</div>
              <div className="text-sm leading-6 text-stone-500">
                Mỗi tệp phải là một đối tượng JSON. Hệ thống sẽ tự động trích xuất `access_token` hoặc `accessToken` từ đối tượng.
              </div>
            </div>
            <Button
              type="button"
              className="mt-4 rounded-xl bg-stone-950 text-white hover:bg-stone-800"
              onClick={() => cpaInputRef.current?.click()}
              disabled={isSubmitting}
            >
              <Files className="size-4" />
              Chọn nhiều tệp JSON
            </Button>
          </div>
          <input
            ref={cpaInputRef}
            type="file"
            accept=".json,application/json"
            multiple
            className="hidden"
            onChange={(event) => void handleCpaSelected(event)}
          />
          {pendingCpaImport ? (
            <div className="rounded-2xl border border-stone-200 bg-white p-4 text-sm leading-6 text-stone-600">
              Lần đọc gần nhất tìm thấy {pendingCpaImport.parsedFileCount} Token
              {pendingCpaImport.errorCount > 0 ? `，ngoài ra có ${pendingCpaImport.errorCount} tệp không trích xuất thành công` : ""}。
            </div>
          ) : null}
        </div>
      );
    }

    return (
      <div className="space-y-3">
        <MethodCard
          title="Nhập Access Token"
          description="Hỗ trợ dán trực tiếp hoặc đọc từ tệp TXT, mỗi dòng một Token."
          icon={KeyRound}
          onClick={() => setMethod("token")}
        />
        <MethodCard
          title="Nhập Session JSON"
          description="Sao chép toàn bộ JSON từ API session của chatgpt.com, tự động trích xuất accessToken."
          icon={FileJson}
          onClick={() => setMethod("session")}
        />
        <MethodCard
          title="Nhập tệp CPA JSON"
          description="Hỗ trợ chọn nhiều tệp JSON cùng lúc, tự động đọc access_token từ từng tệp."
          icon={Files}
          onClick={() => setMethod("cpa")}
        />
        <MethodCard
          title="Nhập từ máy chủ CPA từ xa"
          description="Vào trang cài đặt để cấu hình máy chủ CPA từ xa trước khi thực hiện nhập."
          icon={Files}
          onClick={() => {
            setOpen(false);
            resetState();
            router.push("/settings");
          }}
        />
        <MethodCard
          title="Nhập OAuth Token (9router)"
          description="Dán Codex OAuth token từ backup 9router. Gọi thẳng OpenAI API — không giới hạn 24KB."
          icon={KeyRound}
          onClick={() => setMethod("oauth")}
        />
        <MethodCard
          title="Đăng nhập Codex OAuth"
          description="Mở trang OpenAI để đăng nhập và lấy token OAuth tự động."
          icon={KeyRound}
          onClick={async () => {
            try {
              const { request: req } = await import("@/lib/request");
              const data = await req.get("/api/oauth/codex/start");
              const url = (data.data as any)?.auth_url;
              if (url) window.open(url, "_blank", "width=600,height=700");
              else toast.error("Không thể tạo URL OAuth");
            } catch (e) { toast.error("Lỗi tạo OAuth URL"); }
          }}
        />
        <MethodCard
          title="Lấy token tạo ảnh"
          description="Mở chatgpt.com — đăng nhập → copy JSON → paste vào mục Session JSON ở trên."
          icon={KeyRound}
          onClick={() => window.open("https://chatgpt.com/api/auth/session", "_blank")}
        />
        <MethodCard
          title="Nhập từ máy chủ Sub2API"
          description="Vào trang cài đặt để cấu hình máy chủ Sub2API, sau đó chọn tài khoản OpenAI để nhập."
          icon={ServerCog}
          onClick={() => {
            setOpen(false);
            resetState();
            router.push("/settings");
          }}
        />
      </div>
    );
  };

  const footerDisabled = disabled || isSubmitting;

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <Button
          className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
          onClick={() => setOpen(true)}
          disabled={disabled}
        >
          <Upload className="size-4" />
          Nhập tài khoản
        </Button>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>
              {method === "menu"
                ? "Nhập tài khoản"
                : method === "token"
                  ? "Nhập Access Token"
                  : method === "session"
                    ? "Nhập Session JSON"
                    : "Nhập CPA JSON"}
            </DialogTitle>
            <DialogDescription className="text-sm leading-6">
              {method === "menu"
                ? "Chọn một phương thức nhập. Sau khi nhập thành công, hệ thống sẽ tự động lấy thông tin email, loại và hạn mức."
                : method === "token"
                  ? "Hỗ trợ dán thủ công hoặc nhập từ tệp TXT, mỗi dòng một Token."
                  : method === "session"
                    ? "Dán toàn bộ Session JSON, hệ thống sẽ tự động trích xuất accessToken."
                    : "Hỗ trợ đọc nhiều tệp JSON cùng lúc và xác nhận số lượng trước khi gửi."}
            </DialogDescription>
          </DialogHeader>

          {renderMethodBody()}

          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setOpen(false)}
              disabled={footerDisabled}
            >
              Hủy
            </Button>
            {method === "token" ? (
              <Button
                className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                onClick={() => void handleImportTokenText()}
                disabled={footerDisabled}
              >
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                Nhập Token
              </Button>
            ) : null}
            {method === "session" ? (
              <Button
                className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                onClick={() => void handleImportSessionJson()}
                disabled={footerDisabled}
              >
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                Nhập JSON
              </Button>
            ) : null}
            {method === "cpa" ? (
              <Button
                className={cn(
                  "h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800",
                  !pendingCpaImport ? "hidden" : "",
                )}
                onClick={() => setConfirmOpen(true)}
                disabled={footerDisabled || !pendingCpaImport}
              >
                Xem xác nhận nhập
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>Xác nhận nhập CPA Token</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              {pendingCpaImport
                ? `Xác nhận đã nhận diện ${pendingCpaImport.parsedFileCount} Token, bạn có chắc chắn muốn nhập?`
                : "Chưa đọc được Token nào khả dụng để nhập."}
              {pendingCpaImport?.errorCount
                ? `，ngoài ra có ${pendingCpaImport.errorCount} tệp không trích xuất thành công.`
                : "."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setConfirmOpen(false)}
              disabled={isSubmitting}
            >
              Quay lại
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void submitTokens(pendingCpaImport?.tokens ?? [], "Nhập CPA JSON hoàn tất")}
              disabled={isSubmitting || !pendingCpaImport}
            >
              {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
              Xác nhận nhập
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
