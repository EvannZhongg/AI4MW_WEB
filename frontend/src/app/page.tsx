"use client";

import { Suspense, useEffect, useRef, useState, type SyntheticEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { runtimeConfig } from "@/config/runtime";
import { dispatchConversationRefreshEvent } from "@/lib/workspaceEvents";

type ChatAttachment = {
  id: string;
  name: string;
  url: string;
  revokeOnDispose?: boolean;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments: ChatAttachment[];
  statusText?: string;
  traceItems?: string[];
  isStreaming?: boolean;
};

type PendingAttachment = ChatAttachment & { file: File };

type ConversationMessagePayload = {
  id: number;
  role: "user" | "assistant";
  content: string;
  attachments?: {
    name?: string;
    url?: string;
  }[];
};

type SessionInfo = {
  authenticated: boolean;
  username?: string;
};

function parseConversationId(value: string | null) {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function resolveApiUrl(value: string) {
  if (!value) {
    return "";
  }
  if (/^(https?:)?\/\//i.test(value) || value.startsWith("blob:") || value.startsWith("data:")) {
    return value;
  }
  const apiBase = runtimeConfig.apiBase.replace(/\/$/, "");
  return `${apiBase}${value.startsWith("/") ? value : `/${value}`}`;
}

function prepareMarkdownContent(text: string, role: Message["role"]) {
  const normalized = text.replace(/\r\n?/g, "\n").trim();
  if (!normalized || role !== "assistant") {
    return normalized;
  }

  const lines = normalized.split("\n");
  let inFence = false;

  return lines
    .map((line) => {
      const trimmed = line.trim();
      if (/^(```|~~~)/.test(trimmed)) {
        inFence = !inFence;
        return line;
      }
      if (inFence) {
        return line;
      }
      if (/^\\\[$/.test(trimmed)) {
        return line.replace("\\[", "$$");
      }
      if (/^\\\]$/.test(trimmed)) {
        return line.replace("\\]", "$$");
      }
      return line
        .replace(/\\\[(.+?)\\\]/g, (_match, expression: string) => `$$${expression}$$`)
        .replace(/\\\((.+?)\\\)/g, (_match, expression: string) => `$${expression}$`);
    })
    .join("\n");
}

function appendTraceItem(items: string[] | undefined, nextItem: string) {
  const trimmed = nextItem.trim();
  if (!trimmed) {
    return items ?? [];
  }
  const existing = items ?? [];
  if (existing.includes(trimmed)) {
    return existing;
  }
  return [...existing, trimmed];
}

function buildThinkDetails(message: Message) {
  const traceItems = message.traceItems ?? [];
  if (!message.statusText || traceItems.includes(message.statusText)) {
    return traceItems;
  }
  return [message.statusText, ...traceItems];
}

function buildThinkSummary(message: Message) {
  if (message.statusText) {
    return message.statusText;
  }
  const traceCount = message.traceItems?.length ?? 0;
  if (traceCount > 0) {
    return `已记录 ${traceCount} 条操作信息`;
  }
  return "点开查看本轮操作信息";
}

export default function Home() {
  return (
    <Suspense fallback={<HomeLoadingState />}>
      <HomeClient />
    </Suspense>
  );
}

function HomeClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [promptText, setPromptText] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [user, setUser] = useState<SessionInfo>({ authenticated: false });
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [expandedThinkIds, setExpandedThinkIds] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const bottomAnchorRef = useRef<HTMLDivElement | null>(null);
  const inflightConversationIdRef = useRef<number | null>(null);
  const activeObjectUrlsRef = useRef<Set<string>>(new Set());
  const isSendingRef = useRef(false);
  const selectedConversationId = parseConversationId(searchParams.get("conversation"));

  const loadSession = async () => {
    try {
      const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/session`, {
        credentials: "include"
      });
      if (!response.ok) {
        throw new Error(`session_${response.status}`);
      }
      const data = (await response.json()) as SessionInfo;
      setUser(data);
    } catch (error) {
      setUser({ authenticated: false });
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
      if (response.status === 401) {
        setMessages([]);
        setActiveConversationId(null);
        setUser({ authenticated: false });
        return;
      }
      if (!response.ok) {
        throw new Error(`conversation_${response.status}`);
      }
      const data = (await response.json()) as {
        items?: ConversationMessagePayload[];
      };
      setMessages(
        (data.items ?? []).map((item) => ({
          id: String(item.id),
          role: item.role,
          content: item.content,
          attachments: (item.attachments ?? [])
            .filter((attachment) => Boolean(attachment.url))
            .map((attachment, index) => ({
              id: `${item.id}-attachment-${index}`,
              name: attachment.name || `image-${index + 1}`,
              url: resolveApiUrl(String(attachment.url)),
            })),
          statusText: "",
          traceItems: [],
          isStreaming: false
        }))
      );
      setActiveConversationId(conversationId);
    } catch (error) {
      setMessages([]);
      setActiveConversationId(null);
    }
  };

  useEffect(() => {
    void loadSession();
  }, []);

  useEffect(() => {
    isSendingRef.current = isSending;
  }, [isSending]);

  useEffect(() => {
    if (selectedConversationId === null) {
      setMessages([]);
      setActiveConversationId(null);
      return;
    }
    if (!user.authenticated) {
      return;
    }
    if (
      isSendingRef.current &&
      inflightConversationIdRef.current !== null &&
      selectedConversationId === inflightConversationIdRef.current
    ) {
      return;
    }
    void loadConversationMessages(selectedConversationId);
  }, [selectedConversationId, user.authenticated]);

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
    bottomAnchorRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isSending]);

  useEffect(() => {
    setExpandedThinkIds((prev) => prev.filter((id) => messages.some((message) => message.id === id)));
  }, [messages]);

  useEffect(() => {
    const nextActiveUrls = new Set<string>();

    attachments.forEach((attachment) => {
      if (attachment.revokeOnDispose) {
        nextActiveUrls.add(attachment.url);
      }
    });
    messages.forEach((message) => {
      message.attachments.forEach((attachment) => {
        if (attachment.revokeOnDispose) {
          nextActiveUrls.add(attachment.url);
        }
      });
    });

    activeObjectUrlsRef.current.forEach((url) => {
      if (!nextActiveUrls.has(url)) {
        URL.revokeObjectURL(url);
      }
    });
    activeObjectUrlsRef.current = nextActiveUrls;
  }, [attachments, messages]);

  useEffect(
    () => () => {
      activeObjectUrlsRef.current.forEach((url) => {
        URL.revokeObjectURL(url);
      });
    },
    []
  );

  const handleThinkToggle = (messageId: string, event: SyntheticEvent<HTMLDetailsElement>) => {
    if (event.currentTarget.open) {
      setExpandedThinkIds((prev) => (prev.includes(messageId) ? prev : [...prev, messageId]));
      return;
    }
    setExpandedThinkIds((prev) => prev.filter((id) => id !== messageId));
  };

  const addFiles = (files: FileList | File[]) => {
    const next = Array.from(files)
      .filter((file) => file.type.startsWith("image/"))
      .map((file) => ({
        id: `${file.name}-${file.size}-${Date.now()}`,
        name: file.name,
        url: URL.createObjectURL(file),
        revokeOnDispose: true,
        file
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
        URL.revokeObjectURL(target.url);
      }
      return prev.filter((item) => item.id !== id);
    });
  };

  const sendMessage = async () => {
    if (!user.authenticated) {
      setMessages((prev) => [
        ...prev,
        {
          id: `assistant-auth-${Date.now()}`,
          role: "assistant",
          content: "请先登录后再发送消息。",
          attachments: []
        }
      ]);
      return;
    }
    const text = promptText.trim();
    if ((!text && attachments.length === 0) || isSending) {
      return;
    }

    const currentAttachments = attachments;

    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user" as const,
      content: text,
      attachments: currentAttachments.map((attachment) => ({
        id: attachment.id,
        name: attachment.name,
        url: attachment.url,
        revokeOnDispose: attachment.revokeOnDispose
      }))
    };
    const assistantId = `assistant-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      userMessage,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        attachments: [],
        statusText: "正在处理你的请求...",
        traceItems: ["消息已发送，正在等待模型响应。"],
        isStreaming: true
      }
    ]);
    setPromptText("");
    setAttachments([]);
    setIsSending(true);
    inflightConversationIdRef.current = activeConversationId;

    try {
      const formData = new FormData();
      formData.append("message", text);
      if (activeConversationId) {
        formData.append("conversation_id", String(activeConversationId));
      }
      formData.append(
        "history",
        JSON.stringify(
          messages.map((item) => ({
            role: item.role,
            content: item.content
          }))
        )
      );
      currentAttachments.forEach((attachment) => {
        formData.append("attachments", attachment.file, attachment.name);
      });

      const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/chat`, {
        method: "POST",
        headers: {
          Accept: "text/event-stream"
        },
        credentials: "include",
        body: formData
      });

      if (response.status === 401) {
        throw new Error("auth_required");
      }
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
            status?: string;
            trace?: string;
            tool_calls?: string[];
            interface?: string;
          };
          if (data.conversation_id) {
            inflightConversationIdRef.current = data.conversation_id;
            setActiveConversationId(data.conversation_id);
            router.replace(`/?conversation=${data.conversation_id}`);
            dispatchConversationRefreshEvent();
          }
          if (data.status || data.trace || data.interface || data.tool_calls?.length) {
            setMessages((prev) =>
              prev.map((item) => {
                if (item.id !== assistantId) {
                  return item;
                }
                let traceItems = item.traceItems ?? [];
                if (data.trace) {
                  traceItems = appendTraceItem(traceItems, data.trace);
                }
                if (data.interface) {
                  traceItems = appendTraceItem(traceItems, `模型接口：${data.interface}`);
                }
                if (data.tool_calls?.length) {
                  traceItems = appendTraceItem(
                    traceItems,
                    `已执行操作：${Array.from(new Set(data.tool_calls)).join(", ")}`
                  );
                }
                return {
                  ...item,
                  statusText: data.status ?? item.statusText,
                  traceItems,
                  isStreaming: true
                };
              })
            );
          }
          if (data.error) {
            const detail = data.detail ? `\n${data.detail}` : "";
            throw new Error(`${data.error}${detail}`);
          }
          if (data.delta) {
            setMessages((prev) =>
              prev.map((item) =>
                item.id === assistantId
                  ? {
                      ...item,
                      content: item.content + data.delta,
                      statusText: "正在输出回答...",
                      traceItems: appendTraceItem(item.traceItems, "模型已开始返回正文。"),
                      isStreaming: true
                    }
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
              item.id === assistantId
                ? {
                    ...item,
                    content: message,
                    statusText: "",
                    traceItems: appendTraceItem(item.traceItems, "请求失败，未能完成本轮回复。"),
                    isStreaming: false
                  }
                : item
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
      if (buffer.trim()) {
        eventLines.push(buffer.trim());
      }
      flushEvent();
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? `流式错误：${error.message}`
          : "暂时无法获取回复，请稍后再试。";
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                content: message,
                statusText: "",
                traceItems: appendTraceItem(item.traceItems, "请求失败，未能完成本轮回复。"),
                isStreaming: false
              }
            : item
        )
      );
    } finally {
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                statusText: item.content ? "" : item.statusText,
                isStreaming: false
              }
            : item
        )
      );
      setIsSending(false);
      inflightConversationIdRef.current = null;
      dispatchConversationRefreshEvent();
    }
  };

  return (
    <section className="stream chat-home">
      <div className="stream-body chat-body">
        {messages.length === 0 ? (
          <div className="empty-state-card chat-empty-state">
            <p className="empty-state-title">开始一轮新对话</p>
            <p>输入研究问题，或直接粘贴图片后发送。</p>
          </div>
        ) : (
          <div className="chat-thread">
            {messages.map((message) => {
              const thinkDetails = buildThinkDetails(message);
              const showThinkPanel = message.role === "assistant" && thinkDetails.length > 0;
              const isThinkExpanded = expandedThinkIds.includes(message.id);
              const shouldRenderBubble =
                showThinkPanel || Boolean(message.content) || message.role === "assistant";

              return (
                <div
                  key={message.id}
                  className={`chat-message ${message.role}${showThinkPanel ? " has-think-panel" : ""}`}
                >
                  {message.attachments.length > 0 ? (
                    <div className={`chat-attachments ${message.role}`}>
                      {message.attachments.map((attachment) => (
                        <a
                          key={attachment.id}
                          href={attachment.url}
                          target="_blank"
                          rel="noreferrer"
                          className="chat-attachment"
                          title={attachment.name}
                        >
                          <img src={attachment.url} alt={attachment.name} loading="lazy" />
                        </a>
                      ))}
                    </div>
                  ) : null}
                  {shouldRenderBubble ? (
                    <div
                      className={`chat-bubble ${message.role}${showThinkPanel ? " has-think-panel" : ""}`}
                    >
                      <div className={`chat-bubble-surface ${message.role}`}>
                        {showThinkPanel ? (
                          <details
                            className={`chat-think ${message.isStreaming ? "streaming" : ""}`}
                            open={isThinkExpanded}
                            onToggle={(event) => handleThinkToggle(message.id, event)}
                          >
                            <summary>
                              <span className="chat-think-main">
                                <span
                                  className={`chat-think-label ${message.isStreaming ? "streaming" : ""}`}
                                >
                                  Think...
                                </span>
                                <span className="chat-think-status">{buildThinkSummary(message)}</span>
                              </span>
                              <span className="chat-think-meta">{isThinkExpanded ? "收起" : "展开"}</span>
                            </summary>
                            {isThinkExpanded ? (
                              <div className="chat-think-body">
                                {thinkDetails.map((item, index) => (
                                  <div key={`${message.id}-trace-${index}`} className="chat-think-line">
                                    {item}
                                  </div>
                                ))}
                              </div>
                            ) : null}
                          </details>
                        ) : null}
                        {message.content ? (
                          <div className={`chat-markdown ${message.role}`}>
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm, remarkMath]}
                              rehypePlugins={[rehypeKatex]}
                            >
                              {prepareMarkdownContent(message.content, message.role)}
                            </ReactMarkdown>
                          </div>
                        ) : message.role === "assistant" && !showThinkPanel ? (
                          <p className="chat-placeholder">AI 正在处理，请稍候...</p>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
            <div ref={bottomAnchorRef} />
          </div>
        )}
      </div>

      <div className="chat-input-dock">
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
                  void sendMessage();
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
              disabled={(!promptText.trim() && attachments.length === 0) || isSending}
              onClick={() => void sendMessage()}
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
              event.target.value = "";
            }}
          />
          {attachments.length > 0 ? (
            <div className="attachment-row">
              {attachments.map((file) => (
                <div key={file.id} className="attachment-chip">
                  <img src={file.url} alt={file.name} />
                  <button type="button" onClick={() => removeAttachment(file.id)} aria-label="移除图片">
                    ×
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function HomeLoadingState() {
  return (
    <section className="stream chat-home">
      <div className="empty-state-card chat-empty-state">
        <p className="empty-state-title">页面加载中</p>
        <p>会话历史与聊天内容将在客户端准备完成后显示。</p>
      </div>
    </section>
  );
}