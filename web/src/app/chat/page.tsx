"use client";

import { useEffect, useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Paperclip, X } from "lucide-react";

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Không đọc được ảnh"));
    reader.readAsDataURL(file);
  });
}

/** Màu nhấn markdown (giống HA Zalo Bot Markdown Color). */
type MdAccent = "none" | "orange" | "gold" | "red" | "yellow" | "green" | "blue";

const MD_ACCENT_CLS: Record<MdAccent, string> = {
  none: "",
  orange: "text-orange-400",
  gold: "text-amber-400",
  red: "text-red-400",
  yellow: "text-yellow-300",
  green: "text-emerald-400",
  blue: "text-sky-400",
};

const MD_ACCENT_BORDER: Record<MdAccent, string> = {
  none: "border-muted-foreground/40",
  orange: "border-orange-400/70",
  gold: "border-amber-400/70",
  red: "border-red-400/70",
  yellow: "border-yellow-300/70",
  green: "border-emerald-400/70",
  blue: "border-sky-400/70",
};

function makeMdComponents(accent: MdAccent) {
  const ac = MD_ACCENT_CLS[accent] || "";
  const strongCls = accent === "none" ? "font-semibold" : `font-semibold ${ac}`;
  const headCls = accent === "none" ? "font-bold" : `font-bold ${ac}`;
  const border = MD_ACCENT_BORDER[accent] || MD_ACCENT_BORDER.none;
  return {
    p: (props: any) => <p className="my-1 leading-relaxed" {...props} />,
    ul: (props: any) => <ul className="list-disc ml-5 my-1 space-y-0.5" {...props} />,
    ol: (props: any) => <ol className="list-decimal ml-5 my-1 space-y-0.5" {...props} />,
    li: (props: any) => <li className="leading-relaxed" {...props} />,
    strong: (props: any) => <strong className={strongCls} {...props} />,
    em: (props: any) => <em className="italic opacity-90" {...props} />,
    del: (props: any) => <del className="opacity-70 line-through" {...props} />,
    code: ({ inline, className, children, ...props }: any) =>
      inline || !className ? (
        <code className={`px-1 py-0.5 rounded bg-background/70 text-[0.9em] ${ac}`} {...props}>{children}</code>
      ) : (
        <code className="block p-2 rounded bg-background/70 text-[0.9em] overflow-x-auto" {...props}>{children}</code>
      ),
    pre: (props: any) => <pre className="my-2 rounded-lg bg-background/70 overflow-x-auto border border-border/40" {...props} />,
    h1: (props: any) => <h2 className={`text-base mt-2 mb-1 ${headCls}`} {...props} />,
    h2: (props: any) => <h3 className={`text-sm mt-2 mb-1 ${headCls}`} {...props} />,
    h3: (props: any) => <h4 className={`text-sm mt-1 mb-1 font-semibold ${ac}`} {...props} />,
    blockquote: (props: any) => (
      <blockquote className={`border-l-2 ${border} pl-3 my-1.5 opacity-90 italic`} {...props} />
    ),
    hr: () => <hr className="my-2 border-border/50" />,
    table: (props: any) => <table className="border-collapse my-2 text-xs w-full" {...props} />,
    th: (props: any) => <th className={`border px-2 py-1 bg-background/40 font-semibold ${ac}`} {...props} />,
    td: (props: any) => <td className="border px-2 py-1" {...props} />,
    a: ({ href, children, ...props }: any) => {
      const url = String(href || "");
      if (/\.(mp3|m4a|wav|ogg)([?#]|$)/i.test(url)) {
        return (
          <span className="block my-2 space-y-1">
            <audio controls preload="none" src={url} className="w-full max-w-md" />
            <a className="underline text-primary text-xs" href={url} target="_blank" rel="noreferrer">⬇️ Tải xuống</a>
          </span>
        );
      }
      if (/\.(mp4|webm|mov)([?#]|$)/i.test(url)) {
        return (
          <span className="block my-2">
            <video controls preload="metadata" src={url} className="w-full max-w-md rounded-lg" />
          </span>
        );
      }
      return <a className={`underline ${ac || "text-primary"}`} target="_blank" rel="noreferrer" href={url} {...props}>{children}</a>;
    },
  };
}

type Message = {
  role: "user" | "assistant";
  content: string;
  images?: string[];  // data URLs (vision) cho tin nhắn user
  ttft?: number;      // time-to-first-token (ms)
  duration?: number;  // total time (ms)
};

// Dựng content gửi API: có ảnh → mảng multi-part vision, không → string thường.
function buildApiContent(m: { content: string; images?: string[] }): any {
  if (m.images && m.images.length > 0) {
    return [
      ...(m.content ? [{ type: "text", text: m.content }] : []),
      ...m.images.map(url => ({ type: "image_url", image_url: { url } })),
    ];
  }
  return m.content;
}

export default function ChatPage() {
  const { isCheckingAuth } = useAuthGuard(["admin", "user"]);
  const [models, setModels] = useState<{ id: string }[]>([]);
  const [model, setModel] = useState("AI Agent");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [images, setImages] = useState<string[]>([]); // data URLs ảnh đính kèm
  const [streaming, setStreaming] = useState(false);
  const [elapsed, setElapsed] = useState(0); // ms, live counter while streaming
  // Markdown accent color (giống HA Zalo Bot — orange/gold/…)
  const [mdAccent, setMdAccent] = useState<MdAccent>("orange");
  useEffect(() => {
    try {
      const saved = localStorage.getItem("chatgpt2api_chat_md_accent") as MdAccent | null;
      if (saved && saved in MD_ACCENT_CLS) setMdAccent(saved);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem("chatgpt2api_chat_md_accent", mdAccent); } catch { /* ignore */ }
  }, [mdAccent]);
  const mdComponents = makeMdComponents(mdAccent);
  const bottomRef = useRef<HTMLDivElement>(null);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Đọc theo dòng chảy: chữ LLM sinh tới đâu, đọc tới đó ──────────────
  const [voiceOn, setVoiceOn] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [voices, setVoices] = useState<{ id: string; language_label: string; downloaded: boolean }[]>([]);
  const voiceOnRef = useRef(false);
  const voiceIdRef = useRef("");
  const authKeyRef = useRef("");
  const speakQueueRef = useRef<string[]>([]);   // câu chờ đọc
  const speakingRef = useRef(false);            // đang phát 1 câu
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const spokenLenRef = useRef(0);               // đã đẩy đi đọc tới ký tự nào
  useEffect(() => { voiceOnRef.current = voiceOn; }, [voiceOn]);
  useEffect(() => { voiceIdRef.current = voiceId; }, [voiceId]);

  // Bỏ markdown/URL để đọc cho tự nhiên (không đọc dấu *, #, ``` , link).
  const stripForSpeech = (s: string) => s
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[*_#>|~]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const playNext = () => {
    if (speakingRef.current) return;
    const next = speakQueueRef.current.shift();
    if (!next) return;
    speakingRef.current = true;
    const url = `/api/voice/stream?voice=${encodeURIComponent(voiceIdRef.current)}`
      + `&key=${encodeURIComponent(authKeyRef.current)}&text=${encodeURIComponent(next)}`;
    const a = new Audio(url);
    audioRef.current = a;
    const done = () => { speakingRef.current = false; audioRef.current = null; playNext(); };
    a.onended = done;
    a.onerror = done;
    a.play().catch(() => done());
  };

  const enqueueSpeech = (text: string) => {
    const t = stripForSpeech(text);
    if (t.length < 2) return;
    speakQueueRef.current.push(t);
    playNext();
  };

  const stopSpeech = () => {
    speakQueueRef.current = [];
    if (audioRef.current) { try { audioRef.current.pause(); } catch (e) {} audioRef.current = null; }
    speakingRef.current = false;
    spokenLenRef.current = 0;
  };

  // Lấy phần văn bản đã đủ câu (tính từ vị trí đã đọc) để đưa vào hàng đợi.
  const takeReadySpeech = (full: string) => {
    const tail = full.slice(spokenLenRef.current);
    let end = -1;
    for (let i = tail.length - 1; i >= 0; i--) {
      if (".!?…\n".includes(tail[i])) { end = i; break; }
    }
    if (end < 0) return;
    const chunk = tail.slice(0, end + 1);
    if (chunk.trim().length < 12) return;   // chưa đủ dài → chờ thêm
    spokenLenRef.current += chunk.length;
    enqueueSpeech(chunk);
  };

  useEffect(() => {
    request.get("/api/voice/catalog")
      .then((d: any) => {
        const vs = (d.data?.voices || []).filter((v: any) => v.downloaded);
        setVoices(vs);
        setVoiceId((cur) => cur || (vs.find((v: any) => v.id.startsWith("vieneu:"))?.id || vs[0]?.id || ""));
      })
      .catch(() => {});
  }, []);

  // Nạp sẵn auth key vào ref để nút mic/🔊 dùng được trước cả khi gửi tin đầu.
  useEffect(() => {
    (async () => {
      const { getStoredAuthKey } = await import("@/store/auth");
      let k = await getStoredAuthKey();
      if (!k) { try { k = localStorage.getItem("chatgpt2api_auth_key") || ""; } catch (e) {} }
      authKeyRef.current = k || "";
    })();
  }, []);

  // ── Nút mic: nói bằng mic máy/điện thoại → STT → điền vào ô nhập ──────
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Bridge cho app AI Ben Bap (micro native → inject text vào ô chat)
  useEffect(() => {
    const w = window as Window & { __aibenbapSetChatInput?: (t: string) => void };
    w.__aibenbapSetChatInput = (t: string) => {
      const text = String(t || "").trim();
      if (!text) return;
      setInput((prev) => (prev ? `${prev} ${text}` : text));
    };
    return () => {
      try {
        delete w.__aibenbapSetChatInput;
      } catch {
        /* ignore */
      }
    };
  }, []);

  const toggleMic = async () => {
    if (recording) {
      mediaRecRef.current?.stop();
      return;
    }
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      alert(
        "Trình duyệt/WebView không hỗ trợ micro.\n\nTrong app AI Ben Bap: dùng nút «Mic app» trên thanh công cụ (ghi âm native)."
      );
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      // Android WebView thường chỉ có audio/webm hoặc audio/mp4
      let mime = "";
      for (const c of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]) {
        if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported?.(c)) {
          mime = c;
          break;
        }
      }
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      audioChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size) audioChunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const type = mr.mimeType || mime || "audio/webm";
        const blob = new Blob(audioChunksRef.current, { type });
        if (blob.size < 800) return;
        setTranscribing(true);
        try {
          const ext = type.includes("mp4") || type.includes("m4a") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
          const fd = new FormData();
          fd.append("file", blob, `mic.${ext}`);
          const resp = await fetch("/v1/audio/transcriptions", {
            method: "POST",
            headers: { Authorization: `Bearer ${authKeyRef.current}` },
            body: fd,
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) {
            const err = (data as any)?.detail?.error || (data as any)?.detail || resp.statusText;
            alert(`STT lỗi (${resp.status}): ${typeof err === "string" ? err : JSON.stringify(err)}`);
          } else {
            const text = String((data as any)?.text || "").trim();
            if (text) setInput((prev) => (prev ? prev + " " : "") + text);
          }
        } catch {
          alert("Không gửi được audio lên server STT.");
        }
        setTranscribing(false);
      };
      mr.start(250);
      mediaRecRef.current = mr;
      setRecording(true);
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      const msg = e instanceof Error ? e.message : String(e || "");
      alert(
        `Không truy cập được micro (${name || "error"}).\n${msg}\n\n` +
          "• Chrome: ổ khóa URL → Micro → Cho phép.\n" +
          "• App AI Ben Bap: dùng nút «Mic app» trên thanh (native), không phụ thuộc WebView.\n" +
          "• Cần HTTPS."
      );
    }
  };

  const addFiles = async (files: File[]) => {
    const imgs = files.filter(f => f.type.startsWith("image/"));
    if (imgs.length === 0) return;
    const urls = await Promise.all(imgs.map(readFileAsDataUrl));
    setImages(prev => [...prev, ...urls.filter(Boolean)]);
  };

  useEffect(() => {
    request.get("/v1/models").then((d: any) => {
      const list = d.data?.data || d.data || [];
      setModels(list.map((m: any) => ({ id: m.id })));
    }).catch(() => {});
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Live timer while streaming
  useEffect(() => {
    if (streaming) {
      setElapsed(0);
      timerRef.current = setInterval(() => {
        setElapsed(Date.now() - startTimeRef.current);
      }, 100);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [streaming]);

  const send = async () => {
    if ((!input.trim() && images.length === 0) || streaming) return;
    const userMsg = input.trim();
    const userImages = images;
    setInput("");
    setImages([]);
    const outgoing: Message = { role: "user", content: userMsg, images: userImages.length ? userImages : undefined };
    setMessages(prev => [...prev, outgoing]);
    setStreaming(true);
    startTimeRef.current = Date.now();
    stopSpeech();   // dừng audio câu cũ, đọc lại từ đầu cho lượt mới

    try {
      const { getStoredAuthKey } = await import("@/store/auth");
      let authKey = await getStoredAuthKey();
      if (!authKey) {
        try { authKey = localStorage.getItem("chatgpt2api_auth_key") || ""; } catch(e) {}
      }
      authKeyRef.current = authKey;
      console.log("Chat: authKey available:", !!authKey, "length:", authKey.length);
      if (!authKey) {
        setMessages(prev => [...prev, { role: "assistant", content: "Lỗi: Chưa đăng nhập. Vui lòng refresh trang và đăng nhập lại." }]);
        setStreaming(false);
        return;
      }
      const resp = await fetch("/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": authKey ? `Bearer ${authKey}` : "" },
        body: JSON.stringify({
          model, stream: true,
          messages: [...messages, outgoing].map(m => ({ role: m.role, content: buildApiContent(m) })),
        }),
      });

      if (!resp.ok) {
        let errText = resp.statusText;
        try {
          const errData = await resp.json();
          errText = errData?.error?.message || errText;
        } catch (e) {}
        setMessages(prev => [...prev, { role: "assistant", content: `[Lỗi API: ${errText}]`, isError: true }]);
        setStreaming(false);
        return;
      }

      const reader = resp.body?.getReader();
      if (!reader) { setStreaming(false); return; }

      let assistantContent = "";
      let ttft: number | undefined;
      setMessages(prev => [...prev, { role: "assistant", content: "" }]);

      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // Keep the last incomplete line in buffer
        
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") continue;
          try {
            const json = JSON.parse(data);
            const delta = json.choices?.[0]?.delta?.content;
            if (delta) {
              if (ttft === undefined) ttft = Date.now() - startTimeRef.current;
              assistantContent += delta;
              setMessages(prev => {
                const copy = [...prev];
                copy[copy.length - 1] = { role: "assistant", content: assistantContent };
                return copy;
              });
              if (voiceOnRef.current) takeReadySpeech(assistantContent);
            }
          } catch (e) {}
        }
      }

      // Đọc nốt phần đuôi chưa đủ dấu câu (chữ cuối cùng LLM sinh ra).
      if (voiceOnRef.current && assistantContent.length > spokenLenRef.current) {
        const tail = assistantContent.slice(spokenLenRef.current);
        spokenLenRef.current = assistantContent.length;
        enqueueSpeech(tail);
      }

      // Stamp final timing on last message
      const totalMs = Date.now() - startTimeRef.current;
      setMessages(prev => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: assistantContent, ttft, duration: totalMs };
        return copy;
      });

    } catch (e) {
      setMessages(prev => [...prev, { role: "assistant", content: "Lỗi kết nối." }]);
    }
    setStreaming(false);
  };

  if (isCheckingAuth) return <div className="p-6 text-muted-foreground">Đang tải...</div>;

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] p-4 max-w-3xl mx-auto">
      <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-4">
        <h1 className="text-lg font-bold shrink-0">Chat</h1>
        <select value={model} onChange={e => setModel(e.target.value)}
          className="min-w-0 flex-1 sm:flex-none max-w-[55vw] sm:max-w-xs px-3 py-1.5 rounded-lg border bg-background text-sm truncate">
          {models.map(m => <option key={m.id} value={m.id}>{m.id}</option>)}
        </select>
        <Button variant="outline" size="sm" className="shrink-0" onClick={() => { stopSpeech(); setMessages([]); }}>Xóa</Button>
        {/* Đọc theo dòng chảy: bật 🔊 để nghe trợ lý đọc ngay khi đang gõ chữ */}
        <button
          type="button"
          onClick={() => { const v = !voiceOn; setVoiceOn(v); if (!v) stopSpeech(); }}
          title={voiceOn ? "Tắt đọc" : "Đọc theo dòng chảy khi trả lời"}
          className={`px-2 py-1.5 rounded-lg border text-sm ${voiceOn ? "bg-primary/15 border-primary" : "bg-background"}`}>
          {voiceOn ? "🔊" : "🔇"}
        </button>
        {voiceOn && (
          <select value={voiceId} onChange={e => setVoiceId(e.target.value)}
            className="px-2 py-1.5 rounded-lg border bg-background text-xs max-w-[11rem]"
            title="Giọng đọc">
            {voices.length === 0 && <option value="">(chưa tải giọng)</option>}
            {voices.map(v => (
              <option key={v.id} value={v.id}>{v.id}{v.language_label ? ` · ${v.language_label}` : ""}</option>
            ))}
          </select>
        )}
        <select
          value={mdAccent}
          onChange={e => setMdAccent(e.target.value as MdAccent)}
          className="px-2 py-1.5 rounded-lg border bg-background text-xs max-w-[9rem]"
          title="Màu markdown (đậm / tiêu đề) — giống HA Zalo Markdown Color"
        >
          <option value="orange">MD · orange</option>
          <option value="gold">MD · gold</option>
          <option value="yellow">MD · yellow</option>
          <option value="red">MD · red</option>
          <option value="green">MD · green</option>
          <option value="blue">MD · blue</option>
          <option value="none">MD · none</option>
        </select>
        {streaming && (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums animate-pulse">
            ⏱ {(elapsed / 1000).toFixed(1)}s...
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 mb-4">
        {messages.length === 0 && (
          <div className="text-center text-muted-foreground mt-20">
            Chọn model, nhập câu hỏi để test MCP + search.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex flex-col ${m.role === "user" ? "items-end" : "items-start"}`}>
            <div className={`max-w-[80%] px-4 py-2 rounded-xl ${
              m.role === "user"
                ? "bg-primary text-primary-foreground whitespace-pre-wrap"
                : "bg-muted text-foreground"
            }`}>
              {m.role === "assistant" ? (
                m.content ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                    {m.content}
                  </ReactMarkdown>
                ) : (
                  streaming && i === messages.length - 1 ? "▊" : ""
                )
              ) : (
                <div className="flex flex-col gap-1">
                  {m.images && m.images.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {m.images.map((src, k) => (
                        <img key={k} src={src} alt="" className="max-h-40 rounded-lg border border-primary-foreground/20" />
                      ))}
                    </div>
                  )}
                  {m.content && <span className="whitespace-pre-wrap">{m.content}</span>}
                </div>
              )}
            </div>
            {m.role === "assistant" && m.duration !== undefined && (
              <div className="flex gap-2 mt-1 px-1 text-[11px] text-muted-foreground/60">
                <span title="Tổng thời gian phản hồi">⏱ {(m.duration / 1000).toFixed(2)}s</span>
                {m.ttft !== undefined && (
                  <span title="Thời gian đến chữ đầu tiên (TTFT)">⚡ TTFT {(m.ttft / 1000).toFixed(2)}s</span>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {images.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {images.map((src, i) => (
            <div key={i} className="relative size-14 shrink-0">
              <img src={src} alt="" className="size-14 rounded-lg border object-cover" />
              <button type="button" onClick={() => setImages(prev => prev.filter((_, k) => k !== i))}
                className="absolute -right-1 -top-1 inline-flex size-5 items-center justify-center rounded-full border bg-background text-muted-foreground hover:text-foreground">
                <X className="size-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden"
          onChange={e => { void addFiles(Array.from(e.target.files || [])); e.target.value = ""; }} />
        <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}
          disabled={streaming} title="Đính kèm ảnh để phân tích">
          <Paperclip className="size-4" />
        </Button>
        <Button variant={recording ? "default" : "outline"} size="sm"
          onClick={() => void toggleMic()} disabled={streaming || transcribing}
          className={recording ? "animate-pulse" : ""}
          title={recording ? "Đang ghi — bấm để dừng & chuyển thành chữ" : "Nói bằng micro"}>
          {transcribing ? "…" : recording ? "⏺" : "🎤"}
        </Button>
        <Input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          onPaste={e => {
            const fs = Array.from(e.clipboardData.files).filter(f => f.type.startsWith("image/"));
            if (fs.length) { e.preventDefault(); void addFiles(fs); }
          }}
          placeholder="Hỏi gì đó, hoặc dán/đính kèm ảnh..." disabled={streaming} />
        <Button onClick={send} disabled={streaming || (!input.trim() && images.length === 0)}>
          {streaming ? "..." : "Gửi"}
        </Button>
      </div>
    </div>
  );
}
