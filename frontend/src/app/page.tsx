"use client";

import { useEffect, useRef, useState } from "react";
import { runtimeConfig } from "@/config/runtime";

const coreModules = [
  { name: "天线", desc: "辐射体设计与阵列综合" },
  { name: "超材料", desc: "色散调控与等效介质" },
  { name: "微波电路", desc: "传输线与滤波器设计" }
];

const atomicTools = [
  { name: "电路识别", desc: "从图像识别电路结构" },
  { name: "曲线提取", desc: "从图表提取多维曲线" },
  { name: "参数反推", desc: "拟合模型与关键参数" }
];

const historyItems = [
  { title: "GaN PA 热管理策略", time: "2026-01-25", tag: "Power" },
  { title: "超材料单元等效参数", time: "2026-01-22", tag: "Meta" },
  { title: "毫米波阵列波束赋形", time: "2026-01-18", tag: "Antenna" }
];

export default function Home() {
  const isAuthenticated = true;
  const [sidebarPinned, setSidebarPinned] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [promptText, setPromptText] = useState("");
  const [attachments, setAttachments] = useState<
    { id: string; name: string; previewUrl: string }[]
  >([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    document.body.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }
    const el = textareaRef.current;
    el.style.height = "auto";
    const maxHeight = 200;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [promptText]);

  const addFiles = (files: FileList | File[]) => {
    const next = Array.from(files)
      .filter((file) => file.type.startsWith("image/"))
      .map((file) => ({
        id: `${file.name}-${file.size}-${Date.now()}`,
        name: file.name,
        previewUrl: URL.createObjectURL(file)
      }));
    if (next.length === 0) {
      return;
    }
    setAttachments((prev) => [...prev, ...next]);
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!event.clipboardData?.items) {
      return;
    }
    const imageItems = Array.from(event.clipboardData.items).filter((item) =>
      item.type.startsWith("image/")
    );
    if (imageItems.length === 0) {
      return;
    }
    event.preventDefault();
    const files = imageItems
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (files.length > 0) {
      addFiles(files);
    }
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((item) => item.id === id);
      if (target) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((item) => item.id !== id);
    });
  };

  return (
    <div
      className={`workspace ${sidebarPinned ? "sidebar-pinned" : "sidebar-minimized"}`}
    >
      <aside className={`sidebar ${sidebarPinned ? "" : "minimized"}`}>
        <div className="sidebar-shell">
          <div className="sidebar-top">
            <div className="logo-badge">AI</div>
            <button
              className="theme-toggle"
              type="button"
              onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? "LIGHT" : "DARK"}
            </button>
            <button
              className="pin-toggle"
              type="button"
              onClick={() => setSidebarPinned((prev) => !prev)}
              aria-label={sidebarPinned ? "折叠侧栏" : "展开侧栏"}
            >
              <img
                src="/assets/sidebar-toggle.png"
                alt="toggle"
                className={`pin-icon ${sidebarPinned ? "pinned" : "unpinned"}`}
              />
            </button>
          </div>

          <div className="sidebar-body">
            <div className="nav-group">
              <div className="nav-header">
                <h4>研究能力工具箱</h4>
                <span className="muted">固定入口</span>
              </div>
              <div className="nav-list">
                {coreModules.map((item) => (
                  <div key={item.name} className="nav-item">
                    <div>
                      <strong>{item.name}</strong>
                      <p>{item.desc}</p>
                    </div>
                    <span className="nav-pill">module</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="nav-group">
              <div className="nav-header">
                <h4>Tools</h4>
                <span className="muted">原子级工具</span>
              </div>
              <div className="nav-list">
                {atomicTools.map((tool) => (
                  <div key={tool.name} className="tool-item">
                    <strong>{tool.name}</strong>
                    <p>{tool.desc}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="nav-group">
              <div className="nav-header">
                <h4>History</h4>
                <span className="muted">可追溯</span>
              </div>
              <div className="history-list">
                {historyItems.map((item) => (
                  <div key={item.title} className="history-item">
                    <div className="history-line">
                      <strong>{item.title}</strong>
                      <span>{item.time}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="sidebar-footer">
            {isAuthenticated ? (
              <div className="user-row">
                <div className="user-dot" />
                <div>
                  <strong>Researcher ZJ</strong>
                  <p className="muted">在线</p>
                </div>
              </div>
            ) : (
              <div className="auth-actions">
                <button type="button" className="ghost-button">
                  登录
                </button>
                <button type="button" className="solid-button">
                  注册
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      <main className="main">
        <section className="stream">
          <div className="stream-header">
            <div>
              <p className="eyebrow">Research Dialogue</p>
              <h1>能力 × 推理 × 结果</h1>
              <p className="muted">
                单列、宽内容的研究流式输出，适合长文本、公式与结构化结果。
              </p>
            </div>
            <div className="stream-meta">
              <span>API Base: {runtimeConfig.apiBase}</span>
              <span>Parser: MinerU @ 8002</span>
              <span>Store: PostgreSQL + pgvector</span>
            </div>
          </div>

          <div className="stream-body" />

          <div className="chat-input">
            <div className="input-surface">
              <textarea
                rows={1}
                placeholder="在这里输入研究问题或指令..."
                aria-label="对话输入"
                value={promptText}
                ref={textareaRef}
                onChange={(event) => setPromptText(event.target.value)}
                onPaste={handlePaste}
              />
              <button
                type="button"
                className="attach-button"
                onClick={() => fileInputRef.current?.click()}
                aria-label="添加图片"
              >
                +
              </button>
              <button type="button" className="send-button" aria-label="发送">
                ↑
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="file-input"
              onChange={(event) => {
                if (event.target.files) {
                  addFiles(event.target.files);
                }
              }}
            />
            {attachments.length > 0 ? (
              <div className="attachment-row">
                {attachments.map((file) => (
                  <div key={file.id} className="attachment-chip">
                    <img src={file.previewUrl} alt={file.name} />
                    <button
                      type="button"
                      onClick={() => removeAttachment(file.id)}
                      aria-label="移除图片"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </section>
      </main>
    </div>
  );
}
