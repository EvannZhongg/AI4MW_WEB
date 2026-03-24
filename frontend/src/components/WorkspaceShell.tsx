"use client";

import { Suspense, useEffect, useState } from "react";
import { AppSidebar } from "@/components/AppSidebar";

type WorkspaceShellProps = {
  children: React.ReactNode;
};

export function WorkspaceShell({ children }: WorkspaceShellProps) {
  const [sidebarPinned, setSidebarPinned] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const storedTheme = window.localStorage.getItem("ai4mw_theme");
    const storedSidebarPinned = window.localStorage.getItem("ai4mw_sidebar_pinned");
    if (storedTheme === "dark" || storedTheme === "light") {
      setTheme(storedTheme);
    }
    if (storedSidebarPinned === "true" || storedSidebarPinned === "false") {
      setSidebarPinned(storedSidebarPinned === "true");
    }
  }, []);

  useEffect(() => {
    document.body.dataset.theme = theme;
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ai4mw_theme", theme);
    }
  }, [theme]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("ai4mw_sidebar_pinned", String(sidebarPinned));
  }, [sidebarPinned]);

  return (
    <div className={`workspace ${sidebarPinned ? "sidebar-pinned" : "sidebar-minimized"}`}>
      <Suspense fallback={<SidebarFallback sidebarPinned={sidebarPinned} theme={theme} />}>
        <AppSidebar
          sidebarPinned={sidebarPinned}
          theme={theme}
          onThemeToggle={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
          onSidebarToggle={() => setSidebarPinned((prev) => !prev)}
        />
      </Suspense>
      <main className="main">{children}</main>
    </div>
  );
}

function SidebarFallback({
  sidebarPinned,
  theme
}: {
  sidebarPinned: boolean;
  theme: "dark" | "light";
}) {
  return (
    <aside className={`sidebar ${sidebarPinned ? "" : "minimized"}`}>
      <div className="sidebar-shell">
        <div className="sidebar-top">
          <div className="logo-home" aria-hidden="true">
            <div className="logo-badge">AI</div>
          </div>
          <button className="theme-toggle" type="button" disabled>
            {theme === "dark" ? "LIGHT" : "DARK"}
          </button>
          <button className="pin-toggle" type="button" disabled aria-hidden="true">
            <img src="/assets/sidebar-toggle.png" alt="toggle" className="pin-icon pinned" />
          </button>
        </div>
        <div className="sidebar-body">
          <div className="nav-group">
            <div className="nav-header">
              <h4>Loading</h4>
            </div>
            <div className="nav-list">
              <div className="nav-item">
                <div>
                  <strong>正在加载侧栏...</strong>
                  <p>会话和工具入口将在客户端就绪后显示。</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
