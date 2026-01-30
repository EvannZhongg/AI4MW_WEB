"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
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

export default function Home() {
  const [sidebarPinned, setSidebarPinned] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [promptText, setPromptText] = useState("");
  const [attachments, setAttachments] = useState<
    { id: string; name: string; previewUrl: string }[]
  >([]);
  const [messages, setMessages] = useState<
    { id: string; role: "user" | "assistant"; content: string }[]
  >([]);
  const [user, setUser] = useState<{ authenticated: boolean; username?: string }>({
    authenticated: false
  });
  const [conversations, setConversations] = useState<
    { id: number; title: string; updated_at: string }[]
  >([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(
    null
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyMenuId, setHistoryMenuId] = useState<number | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<{
    id: number;
    title: string;
  } | null>(null);
  const [isSending, setIsSending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const streamBodyRef = useRef<HTMLDivElement | null>(null);
  const mainRef = useRef<HTMLDivElement | null>(null);
  const settingsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    document.body.dataset.theme = theme;
  }, [theme]);

  const loadSession = async () => {
    try {
      const response = await fetch(
        `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/session`,
        {
          credentials: "include"
        }
      );
      const data = (await response.json()) as {
        authenticated: boolean;
        username?: string;
      };
      setUser(data);
    } catch (error) {
      setUser({ authenticated: false });
    }
  };

  const loadConversations = async () => {
    if (!user.authenticated) {
      setConversations([]);
      return;
    }
    try {
      const response = await fetch(
        `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/conversations`,
        {
          credentials: "include"
        }
      );
      const data = (await response.json()) as {
        items: { id: number; title: string; updated_at: string }[];
      };
      setConversations(data.items ?? []);
    } catch (error) {
      setConversations([]);
    }
  };

  const loadConversationMessages = async (conversationId: number) => {
    try {
      const response = await fetch(
        `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/conversations/${conversationId}`,
        {
          credentials: "include"
        }
      );
      const data = (await response.json()) as {
        items: { id: number; role: "user" | "assistant"; content: string }[];
      };
      setMessages(
        (data.items ?? []).map((item) => ({
          id: String(item.id),
          role: item.role,
          content: item.content
        }))
      );
      setActiveConversationId(conversationId);
    } catch (error) {
      return;
    }
  };

  const renameConversation = async (conversationId: number) => {
    const title = renameValue.trim();
    setRenamingId(null);
    if (!title) {
      return;
    }
    const current = conversations.find((item) => item.id === conversationId);
    if (current && current.title === title) {
      return;
    }
    try {
      await fetch(
        `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/conversations/${conversationId}/rename`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ title })
        }
      );
      loadConversations();
    } finally {
      setHistoryMenuId(null);
    }
  };

  const deleteConversation = async (conversationId: number) => {
    try {
      await fetch(
        `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/conversations/${conversationId}/delete`,
        {
          method: "POST",
          credentials: "include"
        }
      );
      if (activeConversationId === conversationId) {
        setActiveConversationId(null);
        setMessages([]);
      }
      loadConversations();
    } finally {
      setHistoryMenuId(null);
    }
  };

  useEffect(() => {
    loadSession();
  }, []);

  useEffect(() => {
    loadConversations();
  }, [user.authenticated]);

  useEffect(() => {
    const target = mainRef.current ?? streamBodyRef.current;
    if (!target) {
      return;
    }
    target.scrollTop = target.scrollHeight;
  }, [messages, isSending]);

  useEffect(() => {
    if (!settingsOpen) {
      return;
    }
    const handler = (event: MouseEvent) => {
      if (settingsRef.current && settingsRef.current.contains(event.target as Node)) {
        return;
      }
      setSettingsOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
    };
  }, [settingsOpen]);

  useEffect(() => {
    if (historyMenuId === null) {
      return;
    }
    const handler = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && target.closest(".history-actions")) {
        return;
      }
      setHistoryMenuId(null);
    };
    document.addEventListener("mousedown", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
    };
  }, [historyMenuId]);

  const goToLogin = () => {
    const url = `${runtimeConfig.apiBase.replace(/\/$/, "")}/accounts/github/login/`;
    window.location.assign(url);
  };

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }
    const el = textareaRef.current;
    el.style.height = "auto";
    const maxHeight = 200;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [promptText]);

  useEffect(() => {
    if (renamingId === null) {
      return;
    }
    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [renamingId]);

  const normalizeContent = (text: string) => text.replace(/\n{2,}/g, "\n");

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

  const sendMessage = async () => {
    const text = promptText.trim();
    if (!text || isSending) {
      return;
    }
    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user" as const,
      content: text
    };
    setMessages((prev) => [...prev, userMessage]);
    setPromptText("");
    setAttachments([]);
    const assistantId = `assistant-${Date.now()}`;
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }]);
    setIsSending(true);

    try {
      const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream"
        },
        credentials: "include",
        body: JSON.stringify({
          message: text,
          conversation_id: activeConversationId,
          history: messages.map((item) => ({
            role: item.role,
            content: item.content
          }))
        })
      });

      if (!response.ok || !response.body) {
        throw new Error("stream_failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let eventLines: string[] = [];

      const flushEvent = () => {
        if (eventLines.length === 0) {
          return;
        }
        const dataLines = eventLines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.replace("data:", "").trim());
        eventLines = [];
        if (dataLines.length === 0) {
          return;
        }
        const payload = dataLines.join("\n").trim();
        if (!payload || payload === "[DONE]") {
          return;
        }
        try {
          const data = JSON.parse(payload) as {
            delta?: string;
            error?: string;
            detail?: string;
            conversation_id?: number;
          };
          if (data.conversation_id) {
            setActiveConversationId(data.conversation_id);
            loadConversations();
          }
          if (data.error) {
            const detail = data.detail ? `\n${data.detail}` : "";
            throw new Error(`${data.error}${detail}`);
          }
          if (data.delta) {
            setMessages((prev) =>
              prev.map((item) =>
                item.id === assistantId
                  ? { ...item, content: item.content + data.delta }
                  : item
              )
            );
          }
        } catch (err) {
          const message =
            err instanceof Error && err.message
              ? `流式错误：${err.message}`
              : "暂时无法获取回复，请稍后再试。";
          setMessages((prev) =>
            prev.map((item) =>
              item.id === assistantId ? { ...item, content: message } : item
            )
          );
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        let newlineIndex = buffer.indexOf("\n");
        while (newlineIndex !== -1) {
          const line = buffer.slice(0, newlineIndex).replace(/\r$/, "");
          buffer = buffer.slice(newlineIndex + 1);
          if (line === "") {
            flushEvent();
          } else {
            eventLines.push(line);
          }
          newlineIndex = buffer.indexOf("\n");
        }
      }
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? `流式错误：${error.message}`
          : "暂时无法获取回复，请稍后再试。";
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? { ...item, content: message }
            : item
        )
      );
    } finally {
      setIsSending(false);
    }
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
              </div>
              <div className="history-list">
                {conversations.length === 0 ? (
                  <div className="history-item">
                    <div className="history-line">
                      <strong>暂无会话</strong>
                    </div>
                  </div>
                ) : (
                  conversations.map((item) => (
                    <div key={item.id} className="history-item history-row">
                      {renamingId === item.id ? (
                        <div className="history-line">
                          <input
                            ref={renameInputRef}
                            className="history-rename-input"
                            value={renameValue}
                            onChange={(event) => setRenameValue(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onBlur={() => renameConversation(item.id)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                renameConversation(item.id);
                              }
                              if (event.key === "Escape") {
                                event.preventDefault();
                                setRenamingId(null);
                                setRenameValue("");
                              }
                            }}
                          />
                        </div>
                      ) : (
                        <div
                          className="history-line"
                          onClick={() => loadConversationMessages(item.id)}
                          role="button"
                        >
                          <strong>{item.title}</strong>
                        </div>
                      )}
                      <div className="history-actions">
                        <button
                          type="button"
                          className="history-menu-button"
                          aria-label="会话操作"
                          onClick={() =>
                            setHistoryMenuId((prev) => (prev === item.id ? null : item.id))
                          }
                        >
                          ⋯
                        </button>
                        {historyMenuId === item.id ? (
                          <div className="history-menu">
                            <button
                              type="button"
                              onClick={() => {
                                setRenamingId(item.id);
                                setRenameValue(item.title);
                                setHistoryMenuId(null);
                              }}
                            >
                              重命名
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setDeleteTarget({ id: item.id, title: item.title });
                                setHistoryMenuId(null);
                              }}
                            >
                              删除
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="sidebar-footer">
            {user.authenticated ? (
              <div className="user-menu-wrap" ref={settingsRef}>
                <button
                  type="button"
                  className="user-row user-row-button"
                  aria-label="账户菜单"
                  onClick={() => setSettingsOpen((prev) => !prev)}
                >
                  <div className="user-dot" />
                  <div>
                    <strong>{user.username ?? "User"}</strong>
                  </div>
                </button>
                {settingsOpen ? (
                  <div className="user-menu">
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await fetch(
                            `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/logout`,
                            {
                              method: "POST",
                              credentials: "include"
                            }
                          );
                        } finally {
                          setSettingsOpen(false);
                          loadSession();
                        }
                      }}
                    >
                      退出
                    </button>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="auth-actions">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={goToLogin}
                >
                  登录
                </button>
                <button
                  type="button"
                  className="solid-button"
                  onClick={goToLogin}
                >
                  注册
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      <main className="main" ref={mainRef}>
        <section className="stream">
          <div className="stream-body" ref={streamBodyRef}>
            {messages.length === 0 ? (
              <div className="empty-state">
                <p>暂无对话内容。</p>
              </div>
            ) : (
              <div className="chat-thread">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`chat-bubble ${message.role}`}
                  >
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {normalizeContent(message.content)}
                    </ReactMarkdown>
                  </div>
                ))}
              </div>
            )}
          </div>

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
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendMessage();
                  }
                }}
              />
              <button
                type="button"
                className="attach-button"
                onClick={() => fileInputRef.current?.click()}
                aria-label="添加图片"
              >
                +
              </button>
              <button
                type="button"
                className="send-button"
                aria-label="发送"
                disabled={!promptText.trim() || isSending}
                onClick={sendMessage}
              >
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

      {deleteTarget ? (
        <div
          className="modal-backdrop"
          onClick={() => setDeleteTarget(null)}
          role="presentation"
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>确认删除该会话？</h3>
            <p>{deleteTarget.title}</p>
            <div className="modal-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => setDeleteTarget(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="solid-button"
                onClick={async () => {
                  await deleteConversation(deleteTarget.id);
                  setDeleteTarget(null);
                }}
              >
                删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
