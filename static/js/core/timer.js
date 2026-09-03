import { loadStats } from "../views/logs.js";
import { $, READING_FLUSH_SECONDS, READING_IDLE_MS, state } from "./state.js";

export function collectReadingTime(now = Date.now()) {
  const startedAt = state.readingLastTick || now; state.readingLastTick = now;
  if (!state.readingActive || !state.readingSectionId || document.hidden) return;
  const activeUntil = Math.min(now, state.readingLastScroll + READING_IDLE_MS);
  if (activeUntil > startedAt) state.readingPendingSeconds += (activeUntil - startedAt) / 1000;
}

export function markWorkspaceActivity() {
  if (state.workspaceActive) state.workspaceLastActive = Date.now();
}

export function collectWorkspaceTime(now = Date.now()) {
  const startedAt = state.workspaceLastTick || now; state.workspaceLastTick = now;
  if (!state.workspaceActive || document.hidden) return;
  const activeUntil = Math.min(now, state.workspaceLastActive + READING_IDLE_MS);
  if (activeUntil > startedAt) state.workspacePendingSeconds += (activeUntil - startedAt) / 1000;
}

export async function flushWorkspaceTime({ beacon = false } = {}) {
  collectWorkspaceTime();
  const seconds = Math.min(600, Math.floor(state.workspacePendingSeconds));
  const activity = state.workspaceActivity;
  if (seconds < 1 || !activity) return;
  state.workspacePendingSeconds -= seconds;
  const idempotencyKey = state.workspaceFlushKey || `${activity.activity_id}-${++state.workspaceFlushSequence}`;
  state.workspaceFlushKey = idempotencyKey;
  const body = JSON.stringify({ ...activity, seconds, idempotency_key: idempotencyKey });
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon("/api/activity/heartbeat", new Blob([body], { type: "application/json" })); state.workspaceFlushKey = ""; return;
  }
  try {
    const response = await fetch("/api/activity/heartbeat", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
    if (!response.ok) throw new Error("activity timer save failed");
    state.workspaceFlushKey = "";
  } catch { state.workspacePendingSeconds += seconds; }
}

export function stopWorkspaceTimer() {
  collectWorkspaceTime(); state.workspaceActive = false; flushWorkspaceTime();
}

export function startWorkspaceTimer(activity) {
  stopWorkspaceTimer();
  if (!activity?.activity_type || !activity?.domain || !activity?.subject_id || !activity?.resource_id || !activity?.item_id) return;
  state.workspaceActivity = { ...activity, activity_id: activity.activity_id || `${activity.activity_type}-${Date.now()}-${Math.random().toString(36).slice(2)}` };
  state.workspaceActive = true; state.workspaceLastTick = Date.now(); state.workspaceLastActive = state.workspaceLastTick; state.workspacePendingSeconds = 0;
}

export async function flushReadingTime({ beacon = false, refresh = false } = {}) {
  collectReadingTime();
  const seconds = Math.min(600, Math.floor(state.readingPendingSeconds));
  if (seconds < 1 || !state.readingSectionId) return;
  const sectionId = state.readingSectionId; state.readingPendingSeconds -= seconds;
  const idempotencyKey = state.readingFlushKey || `${sectionId}-${Date.now()}-${seconds}`;
  state.readingFlushKey = idempotencyKey;
  const body = JSON.stringify({ section_id: sectionId, seconds, idempotency_key: idempotencyKey });
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon("/api/reading-time", new Blob([body], { type: "application/json" })); state.readingFlushKey = ""; return;
  }
  try {
    const response = await fetch("/api/reading-time", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
    if (!response.ok) throw new Error("timer save failed");
    state.readingFlushKey = "";
    if (refresh) loadStats();
  } catch { state.readingPendingSeconds += seconds; }
}

export function startReadingTimer(sectionId) {
  stopWorkspaceTimer();
  collectReadingTime(); flushReadingTime();
  state.readingSectionId = sectionId; state.readingActive = true; state.readingLastTick = Date.now(); state.readingLastScroll = state.readingLastTick;
}

export function stopReadingTimer() {
  collectReadingTime(); state.readingActive = false; flushReadingTime({ refresh: true }); stopWorkspaceTimer();
}

export function markReadingScroll() {
  if (!state.readingActive || !state.readingSectionId) return;
  collectReadingTime(); state.readingLastScroll = Date.now(); state.readingLastTick = state.readingLastScroll;
}

export function initializeReadingTimer() {
  window.addEventListener("scroll", markReadingScroll, { passive: true });
  window.addEventListener("scroll", markWorkspaceActivity, { passive: true });
  ["click", "input", "change", "keydown"].forEach((eventName) => document.addEventListener(eventName, markWorkspaceActivity, { passive: true }));
  document.addEventListener("visibilitychange", () => { collectReadingTime(); collectWorkspaceTime(); if (document.hidden) { flushReadingTime(); flushWorkspaceTime(); } });
  window.addEventListener("pagehide", () => { flushReadingTime({ beacon: true }); flushWorkspaceTime({ beacon: true }); });
  window.setInterval(() => { collectReadingTime(); collectWorkspaceTime(); if (state.readingPendingSeconds >= READING_FLUSH_SECONDS) flushReadingTime(); if (state.workspacePendingSeconds >= READING_FLUSH_SECONDS) flushWorkspaceTime(); }, 5000);
}