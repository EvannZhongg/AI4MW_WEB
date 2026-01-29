import { runtimeConfig } from "@/config/runtime";

type QueryValue = string | number | boolean | null | undefined;

type RequestOptions = {
  method?: string;
  headers?: Record<string, string>;
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const base = runtimeConfig.apiBase.replace(/\/$/, "");
  const normalizedPath = path.startsWith("http") ? path : `${base}/${path.replace(/^\//, "")}`;
  if (!query || Object.keys(query).length === 0) {
    return normalizedPath;
  }
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    search.set(key, String(value));
  }
  return `${normalizedPath}?${search.toString()}`;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", headers, body, query, signal } = options;
  const url = buildUrl(path, query);
  const init: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(headers ?? {})
    },
    signal
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const response = await fetch(url, init);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`API ${response.status}: ${message}`);
  }
  return (await response.json()) as T;
}

export const apiClient = {
  get<T>(path: string, options?: Omit<RequestOptions, "method" | "body">) {
    return request<T>(path, { ...options, method: "GET" });
  },
  post<T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) {
    return request<T>(path, { ...options, method: "POST", body });
  },
  put<T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) {
    return request<T>(path, { ...options, method: "PUT", body });
  },
  delete<T>(path: string, options?: Omit<RequestOptions, "method" | "body">) {
    return request<T>(path, { ...options, method: "DELETE" });
  }
};
