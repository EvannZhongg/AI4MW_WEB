export const CONVERSATIONS_REFRESH_EVENT = "ai4mw:conversations-refresh";

export function dispatchConversationRefreshEvent() {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(CONVERSATIONS_REFRESH_EVENT));
}
