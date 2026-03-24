"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { runtimeConfig } from "@/config/runtime";

type SearchResult = {
  message_id: number;
  conversation_id: number;
  conversation_title: string;
  role: "user" | "assistant";
  snippet: string;
  created_at: string;
};

type SessionInfo = {
  authenticated: boolean;
  username?: string;
};

export default function ChatSearchPage() {
  return (
    <Suspense fallback={<ChatSearchLoadingState />}>
      <ChatSearchClient />
    </Suspense>
  );
}

function ChatSearchClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const [query, setQuery] = useState(initialQuery);
  const [searchedQuery, setSearchedQuery] = useState(initialQuery);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [user, setUser] = useState<SessionInfo>({ authenticated: false });

  const searchUrl = useMemo(() => {
    const trimmed = searchedQuery.trim();
    if (!trimmed) {
      return "";
    }
    const params = new URLSearchParams({ q: trimmed });
    return `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/chat-search?${params.toString()}`;
  }, [searchedQuery]);

  useEffect(() => {
    setQuery(initialQuery);
    setSearchedQuery(initialQuery);
  }, [initialQuery]);

  useEffect(() => {
    const loadSession = async () => {
      try {
        const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/session`, {
          credentials: "include",
        });
        if (!response.ok) {
          throw new Error(`session_${response.status}`);
        }
        const data = (await response.json()) as SessionInfo;
        setUser(data);
      } catch {
        setUser({ authenticated: false });
      }
    };

    void loadSession();
  }, []);

  useEffect(() => {
    if (!searchedQuery.trim()) {
      setResults([]);
      setError("");
      return;
    }

    let cancelled = false;

    const runSearch = async () => {
      setLoading(true);
      setError("");
      try {
        const response = await fetch(searchUrl, {
          credentials: "include",
        });
        if (response.status === 401) {
          throw new Error("请先登录后再搜索聊天记录。");
        }
        if (!response.ok) {
          throw new Error(`search_${response.status}`);
        }
        const data = (await response.json()) as { items?: SearchResult[] };
        if (!cancelled) {
          setResults(data.items ?? []);
        }
      } catch (searchError) {
        if (!cancelled) {
          setResults([]);
          setError(
            searchError instanceof Error && searchError.message
              ? searchError.message
              : "搜索失败，请稍后再试。"
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void runSearch();
    return () => {
      cancelled = true;
    };
  }, [searchUrl, searchedQuery]);

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      router.replace("/chat-search");
      return;
    }
    router.replace(`/chat-search?q=${encodeURIComponent(trimmed)}`);
  };

  return (
    <section className="feature-page chat-search-page">
      <div className="chat-search-bar-wrap">
        <form className="chat-search-bar" onSubmit={submitSearch}>
          <input
            type="search"
            value={query}
            placeholder="搜索用户提问或模型回答..."
            aria-label="搜索聊天内容"
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" className="solid-button">
            搜索
          </button>
        </form>
        <p className="chat-search-hint">
          仅使用数据库纯文本匹配，不使用向量检索或额外模型推理。
        </p>
      </div>

      {!user.authenticated ? (
        <div className="empty-state-card compact">
          <p className="empty-state-title">请先登录</p>
          <p>登录后即可搜索自己的聊天记录。</p>
        </div>
      ) : searchedQuery.trim() === "" ? (
        <div className="empty-state-card compact">
          <p className="empty-state-title">搜索聊天</p>
          <p>输入关键词后，将在用户消息与模型回复中做普通文本匹配。</p>
        </div>
      ) : loading ? (
        <div className="empty-state-card compact">
          <p className="empty-state-title">正在搜索</p>
          <p>正在检索包含 “{searchedQuery.trim()}” 的聊天记录。</p>
        </div>
      ) : error ? (
        <div className="empty-state-card compact">
          <p className="empty-state-title">搜索失败</p>
          <p>{error}</p>
        </div>
      ) : results.length === 0 ? (
        <div className="empty-state-card compact">
          <p className="empty-state-title">没有找到结果</p>
          <p>没有检索到包含 “{searchedQuery.trim()}” 的用户消息或模型回答。</p>
        </div>
      ) : (
        <div className="chat-search-results">
          {results.map((item) => (
            <button
              key={`${item.message_id}-${item.created_at}`}
              type="button"
              className="chat-search-result"
              onClick={() => router.push(`/?conversation=${item.conversation_id}`)}
            >
              <div className="chat-search-result-head">
                <strong>{item.conversation_title || `会话 ${item.conversation_id}`}</strong>
                <span className={`chat-search-role ${item.role}`}>{item.role}</span>
              </div>
              <p className="chat-search-snippet">{item.snippet}</p>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function ChatSearchLoadingState() {
  return (
    <section className="feature-page chat-search-page">
      <div className="chat-search-bar-wrap">
        <div className="chat-search-bar">
          <input type="search" placeholder="搜索聊天内容..." aria-label="搜索聊天内容" disabled />
          <button type="button" className="solid-button" disabled>
            搜索
          </button>
        </div>
      </div>
      <div className="empty-state-card compact">
        <p className="empty-state-title">页面加载中</p>
        <p>搜索框和结果列表将在客户端准备完成后显示。</p>
      </div>
    </section>
  );
}
