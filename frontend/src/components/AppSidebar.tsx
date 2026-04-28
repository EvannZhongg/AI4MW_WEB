"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { runtimeConfig } from "@/config/runtime";
import {
  CONVERSATIONS_REFRESH_EVENT,
  dispatchConversationRefreshEvent
} from "@/lib/workspaceEvents";

const coreModules = [
  { name: "天线", desc: "辐射体设计与阵列综合" },
  { name: "超材料", desc: "色散调控与等效介质" },
  { name: "微波电路", desc: "传输线与滤波器设计" }
];

const atomicTools = [
  { name: "论文检索", desc: "检索并筛选学术论文", href: "/paper-search", status: "已接通" },
  { name: "曲线提取", desc: "从图表提取多维曲线", href: "/curve-extraction", status: "已接通" },
  { name: "参数反推", desc: "拟合模型与关键参数", status: "规划中" }
];

const chatActions = [
  { name: "新聊天", href: "/", icon: "compose" as const },
  { name: "搜索聊天", href: "/chat-search", icon: "search" as const }
];

type SidebarProps = {
  sidebarPinned: boolean;
  theme: "dark" | "light";
  onThemeToggle: () => void;
  onSidebarToggle: () => void;
};

type SessionInfo = {
  authenticated: boolean;
  username?: string;
};

type ConversationSummary = {
  id: number;
  title: string;
  updated_at: string;
};

function parseConversationId(value: string | null) {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function ChatActionIcon({ kind }: { kind: "compose" | "search" }) {
  if (kind === "compose") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true" className="chat-action-icon">
        <path
          d="M12 20h9"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.8"
        />
        <path
          d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.8"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="chat-action-icon">
      <circle
        cx="11"
        cy="11"
        r="6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="m16 16 4.5 4.5"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export function AppSidebar({
  sidebarPinned,
  theme,
  onThemeToggle,
  onSidebarToggle
}: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [user, setUser] = useState<SessionInfo>({ authenticated: false });
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyMenuId, setHistoryMenuId] = useState<number | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const settingsRef = useRef<HTMLDivElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const activeConversationId =
    pathname === "/" ? parseConversationId(searchParams.get("conversation")) : null;

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
      if (response.status === 401) {
        setUser({ authenticated: false });
        setConversations([]);
        return;
      }
      if (!response.ok) {
        throw new Error(`conversations_${response.status}`);
      }
      const data = (await response.json()) as {
        items?: ConversationSummary[];
      };
      setConversations(data.items ?? []);
    } catch (error) {
      setConversations([]);
    }
  };

  useEffect(() => {
    void loadSession();
  }, []);

  useEffect(() => {
    void loadConversations();
  }, [user.authenticated]);

  useEffect(() => {
    const refreshConversations = () => {
      void loadConversations();
    };
    window.addEventListener(CONVERSATIONS_REFRESH_EVENT, refreshConversations);
    return () => {
      window.removeEventListener(CONVERSATIONS_REFRESH_EVENT, refreshConversations);
    };
  }, [user.authenticated]);

  useEffect(() => {
    if (!settingsOpen) {
      return;
    }
    const handler = (event: MouseEvent) => {
      if (settingsRef.current?.contains(event.target as Node)) {
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
      if (target?.closest(".history-actions")) {
        return;
      }
      setHistoryMenuId(null);
    };
    document.addEventListener("mousedown", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
    };
  }, [historyMenuId]);

  useEffect(() => {
    if (renamingId === null) {
      return;
    }
    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [renamingId]);

  const goToLogin = () => {
    const url = new URL(`${runtimeConfig.apiBase.replace(/\/$/, "")}/auth/github/login/`);
    url.searchParams.set("frontend_url", window.location.href);
    window.location.assign(url.toString());
  };

  const openConversation = (conversationId: number) => {
    router.push(`/?conversation=${conversationId}`);
    setHistoryMenuId(null);
  };

  const renameConversation = async (conversationId: number) => {
    const title = renameValue.trim();
    setRenamingId(null);
    setRenameValue("");
    if (!title) {
      return;
    }
    const current = conversations.find((item) => item.id === conversationId);
    if (current?.title === title) {
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
      dispatchConversationRefreshEvent();
      await loadConversations();
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
      if (pathname === "/" && activeConversationId === conversationId) {
        router.replace("/");
      }
      dispatchConversationRefreshEvent();
      await loadConversations();
    } finally {
      setHistoryMenuId(null);
    }
  };

  return (
    <>
      <aside className={`sidebar ${sidebarPinned ? "" : "minimized"}`}>
        <div className="sidebar-shell">
          <div className="sidebar-top">
            <Link href="/" className="logo-home" aria-label="返回研究工作台">
              <div className="logo-badge">AI</div>
            </Link>
            <button className="theme-toggle" type="button" onClick={onThemeToggle}>
              {theme === "dark" ? "LIGHT" : "DARK"}
            </button>
            <button
              className="pin-toggle"
              type="button"
              onClick={onSidebarToggle}
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
            <div className="sidebar-quick-actions">
              {chatActions.map((item) => {
                const isActive =
                  item.href === "/"
                    ? pathname === "/" && activeConversationId === null
                    : pathname === item.href;

                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    className={`tool-link sidebar-quick-action ${isActive ? "active" : ""}`}
                  >
                    <ChatActionIcon kind={item.icon} />
                    <strong>{item.name}</strong>
                  </Link>
                );
              })}
            </div>

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
                {atomicTools.map((tool) =>
                  tool.href ? (
                    <Link
                      key={tool.name}
                      href={tool.href}
                      className={`tool-item tool-link ${pathname === tool.href ? "active" : ""}`}
                    >
                      <div>
                        <strong>{tool.name}</strong>
                        <p>{tool.desc}</p>
                      </div>
                      <span className="tool-status">{tool.status}</span>
                    </Link>
                  ) : (
                    <div key={tool.name} className="tool-item tool-item-disabled">
                      <div>
                        <strong>{tool.name}</strong>
                        <p>{tool.desc}</p>
                      </div>
                      <span className="tool-status muted">{tool.status}</span>
                    </div>
                  )
                )}
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
                    <div
                      key={item.id}
                      className={`history-item history-row ${
                        activeConversationId === item.id ? "active" : ""
                      }`}
                    >
                      {renamingId === item.id ? (
                        <div className="history-line">
                          <input
                            ref={renameInputRef}
                            className="history-rename-input"
                            value={renameValue}
                            onChange={(event) => setRenameValue(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onBlur={() => void renameConversation(item.id)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                void renameConversation(item.id);
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
                        <button
                          type="button"
                          className="history-link-button"
                          onClick={() => openConversation(item.id)}
                        >
                          <div className="history-line">
                            <strong>{item.title}</strong>
                          </div>
                        </button>
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
                                setDeleteTarget(item);
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
                          await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/logout`, {
                            method: "POST",
                            credentials: "include"
                          });
                        } finally {
                          setSettingsOpen(false);
                          await loadSession();
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
                <button type="button" className="ghost-button" onClick={goToLogin}>
                  登录
                </button>
                <button type="button" className="solid-button" onClick={goToLogin}>
                  注册
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      {deleteTarget ? (
        <div className="modal-backdrop" onClick={() => setDeleteTarget(null)} role="presentation">
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>确认删除该会话？</h3>
            <p>{deleteTarget.title}</p>
            <div className="modal-actions">
              <button type="button" className="ghost-button" onClick={() => setDeleteTarget(null)}>
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
    </>
  );
}
