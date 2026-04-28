"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { runtimeConfig } from "@/config/runtime";

type SearchMode = "quick" | "deep";

type HealthPayload = {
  status: string;
  available_sources?: string[];
};

type CriterionItem = {
  criterion_id: string;
  description: string;
  required: boolean;
  supported: boolean;
  score?: number | null;
  confidence?: number | null;
  evidence?: string[];
  reason?: string | null;
};

type PaperItem = {
  source: string;
  source_id?: string | null;
  title: string;
  abstract?: string | null;
  year?: number | null;
  doi?: string | null;
  url?: string | null;
  pdf_url?: string | null;
  is_oa?: boolean | null;
  authors?: string[];
  decision?: string | null;
  reason?: string | null;
  confidence?: number | null;
  score?: number | null;
};

type SearchPayload = {
  query: string;
  rewritten_query: string;
  mode: SearchMode;
  used_sources: string[];
  total_results: number;
  results: PaperItem[];
};

type ProgressEventPayload =
  | { type: "status"; stage?: string; message?: string }
  | {
      type: "intent";
      intent: {
        planner?: string;
        rewritten_query?: string;
        logic?: string;
        reasoning?: string | null;
        criteria?: { id: string; description: string; required: boolean; terms: string[] }[];
      };
    }
  | {
      type: "query_bundle";
      items: { label: string; query: string; purpose?: string | null }[];
    }
  | {
      type: "source_results";
      source: string;
      count: number;
      items: PaperItem[];
    }
  | {
      type: "ranked_results";
      mode: SearchMode;
      final: boolean;
      items: PaperItem[];
    }
  | {
      type: "judge_decision";
      source: string;
      paper: PaperItem;
      criteria: CriterionItem[];
      fallback: boolean;
    }
  | {
      type: "completed";
      result: SearchPayload;
    }
  | {
      type: "error";
      message?: string;
    };

type ProgressEntry = {
  id: string;
  text: string;
};

type JudgeEntry = {
  id: string;
  source: string;
  paper: PaperItem;
  criteria: CriterionItem[];
  fallback: boolean;
};

function paperKey(item: PaperItem) {
  return `${item.source}-${item.doi ?? item.source_id ?? item.title}`;
}

function orderPaperItems(items: PaperItem[]) {
  return [...items].sort((left, right) => {
    const leftScore = left.score ?? 0;
    const rightScore = right.score ?? 0;
    if (rightScore !== leftScore) {
      return rightScore - leftScore;
    }
    const leftYear = left.year ?? 0;
    const rightYear = right.year ?? 0;
    if (rightYear !== leftYear) {
      return rightYear - leftYear;
    }
    return left.title.localeCompare(right.title);
  });
}

function mergePaperLists(current: PaperItem[], incoming: PaperItem[]) {
  const next = new Map<string, PaperItem>();
  current.forEach((item) => {
    next.set(paperKey(item), item);
  });
  incoming.forEach((item) => {
    next.set(paperKey(item), { ...(next.get(paperKey(item)) ?? {}), ...item });
  });
  return orderPaperItems(Array.from(next.values()));
}

function markAsCandidate(items: PaperItem[]) {
  return items.map((item) => ({
    ...item,
    decision: item.decision || "candidate"
  }));
}

function upsertLivePaper(current: PaperItem[], incoming: PaperItem) {
  const key = paperKey(incoming);
  const next = new Map<string, PaperItem>();
  current.forEach((item) => {
    next.set(paperKey(item), item);
  });

  const existing = next.get(key);
  const merged = { ...(existing ?? {}), ...incoming };
  if ((merged.decision || "").toLowerCase() === "drop") {
    next.delete(key);
  } else {
    next.set(key, merged);
  }

  return orderPaperItems(Array.from(next.values()));
}

function buildProgressText(payload: ProgressEventPayload) {
  if (payload.type === "status") {
    return payload.message || "检索进度已更新。";
  }
  if (payload.type === "intent") {
    const logic = payload.intent.logic ? `，逻辑：${payload.intent.logic}` : "";
    return `已完成检索意图解析${logic}。`;
  }
  if (payload.type === "query_bundle") {
    return `已生成 ${payload.items.length} 条检索表达式。`;
  }
  if (payload.type === "source_results") {
    return `${payload.source} 返回 ${payload.count} 篇候选论文。`;
  }
  if (payload.type === "ranked_results") {
    return `当前已更新 ${payload.items.length} 篇排序结果。`;
  }
  if (payload.type === "judge_decision") {
    return `${payload.source} 完成一篇论文判断：${payload.paper.title}`;
  }
  if (payload.type === "completed") {
    return `检索完成，共得到 ${payload.result.total_results} 篇结果。`;
  }
  return payload.message || "论文检索暂时不可用，请稍后再试。";
}

function renderPaperCard(item: PaperItem, compact = false) {
  const decisionLabel =
    item.decision === "candidate"
      ? "候选"
      : item.decision === "keep"
        ? "保留"
        : item.decision === "maybe"
          ? "待定"
          : item.decision;
  const decisionClass =
    item.decision === "candidate"
      ? "info"
      : item.decision === "keep"
        ? "success"
        : item.decision === "maybe"
          ? "warning"
          : "";

  return (
    <article key={paperKey(item)} className={`paper-result-card ${compact ? "compact" : ""}`}>
      <div className="paper-result-top">
        <div className="paper-result-tags">
          <span className="tag accent">{item.source}</span>
          {item.year ? <span className="tag">{item.year}</span> : null}
          {decisionLabel ? <span className={`tag ${decisionClass}`.trim()}>{decisionLabel}</span> : null}
          {item.is_oa ? <span className="tag success">Open Access</span> : null}
        </div>
        <div className="paper-result-links">
          {item.url ? (
            <a href={item.url} target="_blank" rel="noreferrer" className="ghost-button">
              查看详情
            </a>
          ) : null}
          {item.pdf_url ? (
            <a href={item.pdf_url} target="_blank" rel="noreferrer" className="solid-button">
              PDF
            </a>
          ) : null}
        </div>
      </div>

      <h3>{item.title}</h3>
      {item.authors && item.authors.length > 0 ? (
        <p className="paper-result-authors">{item.authors.slice(0, 6).join(", ")}</p>
      ) : null}
      {item.abstract ? <p className="paper-result-abstract">{item.abstract}</p> : null}
      {item.reason ? <p className="paper-result-reason">{item.reason}</p> : null}
      {item.doi ? <p className="paper-result-doi">DOI: {item.doi}</p> : null}
    </article>
  );
}

export default function PaperSearchPage() {
  const [query, setQuery] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [lastMode, setLastMode] = useState<SearchMode>("quick");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SearchPayload | null>(null);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [progressEntries, setProgressEntries] = useState<ProgressEntry[]>([]);
  const [liveResults, setLiveResults] = useState<PaperItem[]>([]);
  const [judgeEntries, setJudgeEntries] = useState<JudgeEntry[]>([]);
  const [intentSummary, setIntentSummary] = useState<ProgressEventPayload | null>(null);
  const [queryBundle, setQueryBundle] = useState<
    { label: string; query: string; purpose?: string | null }[]
  >([]);
  const [progressExpanded, setProgressExpanded] = useState(true);
  const readerAbortRef = useRef<AbortController | null>(null);

  const hasSearchSession =
    isSearching ||
    result !== null ||
    progressEntries.length > 0 ||
    liveResults.length > 0 ||
    judgeEntries.length > 0;

  useEffect(() => {
    const loadHealth = async () => {
      try {
        const response = await fetch(`${runtimeConfig.apiBase.replace(/\/$/, "")}/api/paper-search/health`);
        if (!response.ok) {
          throw new Error("health_failed");
        }
        const payload = (await response.json()) as HealthPayload;
        setHealth(payload);
      } catch {
        setHealth({ status: "offline", available_sources: [] });
      }
    };

    void loadHealth();

    return () => {
      readerAbortRef.current?.abort();
    };
  }, []);

  const sourceSummary = useMemo(() => {
    const sourceCount = result?.used_sources.length ?? health?.available_sources?.length ?? 0;
    if (sourceCount <= 0) {
      return "暂无可用检索源";
    }
    return `当前接入 ${sourceCount} 个检索源`;
  }, [health?.available_sources?.length, result?.used_sources.length]);

  const pushProgress = (payload: ProgressEventPayload) => {
    setProgressEntries((prev) =>
      [
        ...prev,
        {
          id: `${Date.now()}-${prev.length}`,
          text: buildProgressText(payload)
        }
      ].slice(-80)
    );
  };

  const resetSearchState = () => {
    setError(null);
    setResult(null);
    setProgressEntries([]);
    setLiveResults([]);
    setJudgeEntries([]);
    setIntentSummary(null);
    setQueryBundle([]);
    setProgressExpanded(true);
  };

  const handleEvent = (payload: ProgressEventPayload) => {
    pushProgress(payload);

    if (payload.type === "intent") {
      setIntentSummary(payload);
      return;
    }

    if (payload.type === "query_bundle") {
      setQueryBundle(payload.items);
      return;
    }

    if (payload.type === "source_results") {
      setLiveResults((prev) => mergePaperLists(prev, markAsCandidate(payload.items)));
      return;
    }

    if (payload.type === "ranked_results") {
      setLiveResults(orderPaperItems(payload.items.filter((item) => item.decision !== "drop")));
      return;
    }

    if (payload.type === "judge_decision") {
      setJudgeEntries((prev) => [
        {
          id: `${paperKey(payload.paper)}-${Date.now()}`,
          source: payload.source,
          paper: payload.paper,
          criteria: payload.criteria,
          fallback: payload.fallback
        },
        ...prev
      ].slice(0, 40));
      setLiveResults((prev) => upsertLivePaper(prev, payload.paper));
      return;
    }

    if (payload.type === "completed") {
      setResult(payload.result);
      setLiveResults(orderPaperItems(payload.result.results));
      return;
    }

    if (payload.type === "error") {
      setError(payload.message || "论文检索暂时不可用，请稍后再试。");
    }
  };

  const handleSearch = async (mode: SearchMode) => {
    const trimmed = query.trim();
    if (!trimmed || isSearching) {
      return;
    }

    readerAbortRef.current?.abort();
    resetSearchState();
    setIsSearching(true);
    setLastMode(mode);

    const controller = new AbortController();
    readerAbortRef.current = controller;

    try {
      const response = await fetch(
        `${runtimeConfig.apiBase.replace(/\/$/, "")}/api/paper-search/${mode}/stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream"
          },
          body: JSON.stringify({ query: trimmed }),
          signal: controller.signal
        }
      );

      if (!response.ok || !response.body) {
        const payload = (await response.json().catch(() => null)) as { message?: string } | null;
        throw new Error(payload?.message || "论文检索暂时不可用，请稍后再试。");
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
          handleEvent(JSON.parse(payload) as ProgressEventPayload);
        } catch {
          setError("论文检索暂时不可用，请稍后再试。");
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
    } catch (searchError) {
      if (searchError instanceof DOMException && searchError.name === "AbortError") {
        return;
      }
      setError(
        searchError instanceof Error ? searchError.message : "论文检索暂时不可用，请稍后再试。"
      );
    } finally {
      setIsSearching(false);
      readerAbortRef.current = null;
    }
  };

  return (
    <section
      className={`feature-page paper-search-page ${hasSearchSession ? "search-active" : "search-idle"}`}
    >
      <header className="page-header page-header-wide">
        <div>
          <span className="page-kicker">Paper Search</span>
          <h1>论文检索</h1>
          <p>输入主题、方法或问题描述，选择快速检索或深度检索后即可开始查找相关论文。</p>
        </div>
        <div className="service-card">
          <span className={`service-dot ${health?.status === "ok" ? "online" : "offline"}`} />
          <div>
            <strong>论文检索引擎</strong>
            <p>{health?.status === "ok" ? sourceSummary : "当前暂不可用，请稍后再试。"}</p>
          </div>
        </div>
      </header>

      <div className="paper-search-shell panel-card">
        <div className="paper-search-box">
          <div className="paper-search-input-wrap">
            <input
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="例如：查找近三年关于 AI for Materials 的相关论文"
              aria-label="论文检索输入框"
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void handleSearch(lastMode);
                }
              }}
            />
          </div>
          <div className="paper-search-actions">
            <div className="paper-search-mode-pills">
              <button
                type="button"
                className={`paper-search-action ${lastMode === "quick" ? "active" : ""}`}
                disabled={isSearching}
                onClick={() => setLastMode("quick")}
              >
                <span className="paper-search-action-dot" aria-hidden="true" />
                <strong>Quick Search</strong>
              </button>
              <button
                type="button"
                className={`paper-search-action ${lastMode === "deep" ? "active" : ""}`}
                disabled={isSearching}
                onClick={() => setLastMode("deep")}
              >
                <span className="paper-search-action-dot accent" aria-hidden="true" />
                <strong>Deep Search</strong>
              </button>
              <span className="paper-search-helper-pill">{isSearching ? "检索中..." : sourceSummary}</span>
            </div>
            <button
              type="button"
              className="paper-search-submit"
              disabled={!query.trim() || isSearching}
              aria-label="开始论文检索"
              onClick={() => void handleSearch(lastMode)}
            >
              <span className="paper-search-submit-icon" aria-hidden="true" />
            </button>
          </div>
        </div>
        {error ? <div className="status-banner error">{error}</div> : null}
      </div>

      {hasSearchSession ? (
        <div className="paper-search-live">
          <div className="paper-search-live-grid">
            <section className="panel-card paper-search-progress-panel">
              <button
                type="button"
                className="paper-progress-toggle"
                onClick={() => setProgressExpanded((prev) => !prev)}
                aria-expanded={progressExpanded}
              >
                <div>
                  <span className="page-kicker">Progress</span>
                  <h2>检索进度</h2>
                </div>
                <span className={`paper-progress-toggle-icon ${progressExpanded ? "expanded" : ""}`}>
                  {progressExpanded ? "收起" : "展开"}
                </span>
              </button>

              {progressExpanded ? (
                <>
                  {intentSummary && intentSummary.type === "intent" ? (
                    <div className="paper-intent-card">
                      <strong>{intentSummary.intent.rewritten_query || query}</strong>
                      <p>
                        {intentSummary.intent.planner === "llm" ? "LLM 规划" : "Heuristic 规划"}
                        {intentSummary.intent.logic ? ` · ${intentSummary.intent.logic}` : ""}
                      </p>
                      {intentSummary.intent.reasoning ? (
                        <p className="paper-intent-reasoning">{intentSummary.intent.reasoning}</p>
                      ) : null}
                    </div>
                  ) : null}

                  {queryBundle.length > 0 ? (
                    <div className="paper-query-list">
                      {queryBundle.map((item) => (
                        <div key={item.label} className="paper-query-chip">
                          <strong>{item.label}</strong>
                          <span>{item.query}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  <div className="paper-progress-feed">
                    {progressEntries.length === 0 ? (
                      <p className="muted">等待检索启动。</p>
                    ) : (
                      progressEntries.map((item, index) => (
                        <div key={item.id} className="paper-progress-item">
                          <span className="paper-progress-index">{index + 1}</span>
                          <div>{item.text}</div>
                        </div>
                      ))
                    )}
                  </div>
                </>
              ) : null}
            </section>

            <section className="paper-search-results panel-card">
              <div className="paper-search-results-head">
                <div>
                  <span className="page-kicker">
                    {lastMode === "deep" ? "Deep Search" : "Quick Search"}
                  </span>
                  <h2>
                    {result ? `${result.total_results} 篇结果` : isSearching ? "动态结果更新中" : "检索结果"}
                  </h2>
                </div>
                <p>{intentSummary?.type === "intent" ? intentSummary.intent.rewritten_query || query : query}</p>
              </div>

              {liveResults.length === 0 ? (
                <p className="muted">{isSearching ? "正在等待候选论文返回..." : "暂无结果。"}</p>
              ) : (
                <div className="paper-result-list">
                  {liveResults.map((item) => renderPaperCard(item, false))}
                </div>
              )}
            </section>
          </div>

          {lastMode === "deep" ? (
            <section className="panel-card paper-judge-panel">
              <div className="panel-head">
                <div>
                  <span className="page-kicker">LLM Judge</span>
                  <h2>判断过程</h2>
                </div>
              </div>

              {judgeEntries.length === 0 ? (
                <p className="muted">{isSearching ? "正在等待判断结果..." : "暂无判断记录。"}</p>
              ) : (
                <div className="paper-judge-list">
                  {judgeEntries.map((entry) => (
                    <article key={entry.id} className="paper-judge-card">
                      <div className="paper-result-top">
                        <div className="paper-result-tags">
                          <span className="tag accent">{entry.source}</span>
                          {entry.paper.decision ? <span className="tag">{entry.paper.decision}</span> : null}
                          {entry.fallback ? <span className="tag warning">Fallback</span> : null}
                        </div>
                      </div>
                      <strong>{entry.paper.title}</strong>
                      {entry.paper.reason ? <p className="paper-result-reason">{entry.paper.reason}</p> : null}
                      <div className="paper-judge-criteria">
                        {entry.criteria.slice(0, 4).map((criterion) => (
                          <div key={`${entry.id}-${criterion.criterion_id}`} className="paper-judge-criterion">
                            <span>{criterion.description}</span>
                            <strong>{criterion.supported ? "支持" : "不足"}</strong>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
