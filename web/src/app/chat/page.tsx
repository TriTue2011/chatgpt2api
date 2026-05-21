"use client";

import { useEffect, useState, useRef } from "react";
import { request } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Message = { role: "user" | "assistant"; content: string };

export default function ChatPage() {
  const { isCheckingAuth } = useAuthGuard(["admin"]);
  const [models, setModels] = useState<{ id: string }[]>([]);
  const [model, setModel] = useState("AI Agent");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    request.get("/v1/models").then((d: any) => {
      const list = d.data?.data || d.data || [];
      setModels(list.map((m: any) => ({ id: m.id })));
    }).catch(() => {});
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async () => {
    if (!input.trim() || streaming) return;
    const userMsg = input.trim();
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: userMsg }]);
    setStreaming(true);

    try {
      const resp = await fetch("/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${localStorage.getItem("auth_key") || ""}` },
        body: JSON.stringify({
          model, stream: true,
          messages: [...messages, { role: "user", content: userMsg }].map(m => ({ role: m.role, content: m.content })),
        }),
      });

      const reader = resp.body?.getReader();
      if (!reader) { setStreaming(false); return; }

      let assistantContent = "";
      setMessages(prev => [...prev, { role: "assistant", content: "" }]);

      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value);
        const lines = text.split("\n").filter(l => l.startsWith("data: "));
        for (const line of lines) {
          const data = line.slice(6);
          if (data === "[DONE]") continue;
          try {
            const json = JSON.parse(data);
            const delta = json.choices?.[0]?.delta?.content;
            if (delta) {
              assistantContent += delta;
              setMessages(prev => {
                const copy = [...prev];
                copy[copy.length - 1] = { role: "assistant", content: assistantContent };
                return copy;
              });
            }
          } catch (e) {}
        }
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: "assistant", content: "Lỗi kết nối." }]);
    }
    setStreaming(false);
  };

  if (isCheckingAuth) return <div className="p-6 text-muted-foreground">Đang tải...</div>;

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] p-4 max-w-3xl mx-auto">
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-lg font-bold">Chat</h1>
        <select value={model} onChange={e => setModel(e.target.value)}
          className="px-3 py-1.5 rounded-lg border bg-background text-sm">
          {models.map(m => <option key={m.id} value={m.id}>{m.id}</option>)}
        </select>
        <Button variant="outline" size="sm" onClick={() => setMessages([])}>Xóa</Button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 mb-4">
        {messages.length === 0 && (
          <div className="text-center text-muted-foreground mt-20">
            Chọn model, nhập câu hỏi để test MCP + search.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] px-4 py-2 rounded-xl whitespace-pre-wrap ${
              m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
            }`}>
              {m.content || (streaming && i === messages.length - 1 ? "▊" : "")}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2">
        <Input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && send()}
          placeholder="Hỏi gì đó..." disabled={streaming} />
        <Button onClick={send} disabled={streaming || !input.trim()}>
          {streaming ? "..." : "Gửi"}
        </Button>
      </div>
    </div>
  );
}
