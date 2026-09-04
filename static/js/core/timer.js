import { loadStats } from "../views/logs.js";
import { $, READING_FLUSH_SECONDS, READING_IDLE_MS, state } from "./state.js";

export function collectReadingTime(now = Date.now()) {
  const startedAt = state.readingLastTick || now; state.readingLastTick = now;
  if (!state.readingActive || !state.readingSectionId || document.hidden) return;
  const activeUntil = Math.min(now, state.readingLastScroll + READING_IDLE_MS);
  if (activeUntil > startedAt) state.readingPendingSeconds += (activeUntil - startedAt) / 1000;
}

export function markWorkspaceActivity() {
  if (state.workspaceActive) {
    state.workspaceLastActive = Date.now();
    syncAuraIndicator();
  }
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
    window.fetchDailyGoals?.();
  } catch { state.workspacePendingSeconds += seconds; }
}

export function stopWorkspaceTimer() {
  collectWorkspaceTime(); state.workspaceActive = false; flushWorkspaceTime();
  syncAuraIndicator();
}

export function startWorkspaceTimer(activity) {
  stopWorkspaceTimer();
  if (!activity?.activity_type || !activity?.domain || !activity?.subject_id || !activity?.resource_id || !activity?.item_id) return;
  state.workspaceActivity = { ...activity, activity_id: activity.activity_id || `${activity.activity_type}-${Date.now()}-${Math.random().toString(36).slice(2)}` };
  state.workspaceActive = true; state.workspaceLastTick = Date.now(); state.workspaceLastActive = state.workspaceLastTick; state.workspacePendingSeconds = 0;
  syncAuraIndicator();
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
    window.fetchDailyGoals?.();
  } catch { state.readingPendingSeconds += seconds; }
}

export function syncAuraIndicator() {
  const pulseEl = document.getElementById("brandTimerPulse");
  const barEl = document.getElementById("brandProgressBar");
  const brandBtn = document.getElementById("brandButton");
  if (!pulseEl || !barEl) return;

  const now = Date.now();
  const isReading = Boolean(state.readingActive && !document.hidden && (now - (state.readingLastScroll || now) <= READING_IDLE_MS));
  const isWorkspace = Boolean(state.workspaceActive && !document.hidden && (now - (state.workspaceLastActive || now) <= READING_IDLE_MS));
  const isTiming = isReading || isWorkspace;

  pulseEl.classList.toggle("is-timing", isTiming);

  // Compute current page task completion progress (0.0 to 1.0)
  let progress = 0;
  let tooltip = "YuReader · 本地阅读空间";
  const view = state.activeView || "home";

  const goals = state.dailyGoalsData?.goals || {};
  const prog = state.dailyGoalsData?.progress || {};
  const readingGoals = goals.reading || {};
  const readingProg = prog.reading || {};
  const practiceGoals = goals.practice || {};
  const practiceProg = prog.practice || {};

  if (view === "reader") {
    // Reading content: track domain reading time metric
    const book = state.books?.find((b) => b.id === state.current?.book_id || b.sections?.some((s) => s.id === state.current?.id));
    const domain = book?.domain || (state.current?.book_id?.startsWith("politics-") ? "politics" : state.current?.book_id?.startsWith("english-") ? "english" : "medicine");

    let domainLabel = "医学阅读";
    let targetHours = Number(readingGoals.medicine_hours ?? 2.0);
    let baseSeconds = Number(readingProg.medicine_seconds || 0);

    if (domain === "politics") {
      domainLabel = "政治阅读";
      targetHours = Number(readingGoals.politics_hours ?? 0.5);
      baseSeconds = Number(readingProg.politics_seconds || 0);
    } else if (domain === "english") {
      domainLabel = "英语阅读";
      targetHours = Number(readingGoals.english_hours ?? 0.5);
      baseSeconds = Number(readingProg.english_seconds || 0);
    }

    const pendingSeconds = Math.max(0, state.readingPendingSeconds || 0);
    const totalSeconds = baseSeconds + pendingSeconds;
    const targetSeconds = Math.max(1, targetHours * 3600);
    progress = Math.min(1, Math.max(0, totalSeconds / targetSeconds));

    const curHours = (totalSeconds / 3600).toFixed(1);
    const pct = Math.round(progress * 100);
    tooltip = `${domainLabel}目标：${curHours} / ${targetHours.toFixed(1)}小时 (${pct}%)${isTiming ? " · 计时中" : ""}`;
  } else if (view === "home") {
    // Today's page: track total study duration metric
    const targetHours = Number(goals.total_hours ?? 8.0);
    const baseSeconds = Number(prog.total_seconds || 0);
    const pendingSeconds = Math.max(0, (state.readingPendingSeconds || 0) + (state.workspacePendingSeconds || 0));
    const totalSeconds = baseSeconds + pendingSeconds;
    const targetSeconds = Math.max(1, targetHours * 3600);
    progress = Math.min(1, Math.max(0, totalSeconds / targetSeconds));

    const curHours = (totalSeconds / 3600).toFixed(1);
    const pct = Math.round(progress * 100);
    tooltip = `今日总时长目标：${curHours} / ${targetHours.toFixed(1)}小时 (${pct}%)${isTiming ? " · 计时中" : ""}`;
  } else if (view === "oralFocus") {
    // Oral recitation: in-chapter completion or daily goal
    const items = state.oralFocusChapter?.items || [];
    if (items.length > 0) {
      const done = items.filter((it) => it.progress?.mastery && it.progress.mastery !== "unseen").length;
      progress = Math.min(1, Math.max(0, done / items.length));
      const pct = Math.round(progress * 100);
      const title = state.oralFocusChapter.chapter?.title || state.oralFocusChapter.title || "口腔重点背诵";
      tooltip = `${title}：${done} / ${items.length}题 (${pct}%)${isTiming ? " · 计时中" : ""}`;
    } else {
      const medDefGoal = Number(practiceGoals.medicine_definition ?? 20);
      const medEssayGoal = Number(practiceGoals.medicine_essay ?? 20);
      const totalGoal = medDefGoal + medEssayGoal;
      const totalDone = Number(practiceProg.medicine_definition || 0) + Number(practiceProg.medicine_essay || 0);
      progress = totalGoal > 0 ? Math.min(1, Math.max(0, totalDone / totalGoal)) : 0;
      const pct = Math.round(progress * 100);
      tooltip = `今日背诵目标：${totalDone} / ${totalGoal}个 (${pct}%)${isTiming ? " · 计时中" : ""}`;
    }
  } else if (view === "practice") {
    // Practice: objective or subjective session completion
    if (state.practice?.questions?.length) {
      const questions = state.practice.questions;
      const total = questions.length;
      const answered = questions.filter((q) => q.answered).length;
      progress = Math.min(1, Math.max(0, answered / Math.max(1, total)));
      const pct = Math.round(progress * 100);
      const isMistakes = Boolean(state.practice.is_mistakes_session || state.practice.entry?.is_mistakes_session || state.practice.bank?.id === "mistakes-session");
      const label = isMistakes ? "错题攻坚" : "题组练习";
      tooltip = `${label}：${answered} / ${total}题 (${pct}%)${isTiming ? " · 计时中" : ""}`;
    } else if (state.subjectivePractice) {
      const ans = document.getElementById("subjectiveAnswer")?.value || state.subjectivePractice.response?.answer || "";
      const isDone = Boolean(ans.trim());
      progress = isDone ? 1.0 : 0.0;
      tooltip = `主观题作答：${isDone ? "已完成" : "作答中"}${isTiming ? " · 计时中" : ""}`;
    } else {
      progress = 0.2;
      tooltip = `专项练习${isTiming ? " · 计时中" : ""}`;
    }
  } else if (view === "review") {
    const summaryText = document.getElementById("reviewDailySummary")?.value || state.review?.daily_summary?.summary_markdown || "";
    const isDone = Boolean(summaryText.trim());
    progress = isDone ? 1.0 : 0.0;
    tooltip = `复盘回顾：${isDone ? "已保存总结 (100%)" : "待撰写总结"}${isTiming ? " · 计时中" : ""}`;
  } else if (view === "library") {
    if (state.libraryDomain === "politics") {
      const targetHours = Number(readingGoals.politics_hours ?? 0.5);
      const baseSec = Number(readingProg.politics_seconds || 0);
      progress = targetHours > 0 ? Math.min(1, baseSec / (targetHours * 3600)) : 0;
      tooltip = `政治阅读目标：${(baseSec / 3600).toFixed(1)} / ${targetHours.toFixed(1)}小时 (${Math.round(progress * 100)}%)`;
    } else if (state.libraryDomain === "english") {
      const targetHours = Number(readingGoals.english_hours ?? 0.5);
      const baseSec = Number(readingProg.english_seconds || 0);
      progress = targetHours > 0 ? Math.min(1, baseSec / (targetHours * 3600)) : 0;
      tooltip = `英语阅读目标：${(baseSec / 3600).toFixed(1)} / ${targetHours.toFixed(1)}小时 (${Math.round(progress * 100)}%)`;
    } else if (state.libraryDomain === "mistakes") {
      const mistakesRemaining = state.mistakesData?.pending ?? state.mistakesData?.total ?? 0;
      tooltip = mistakesRemaining > 0 ? `错题攻坚：剩余 ${mistakesRemaining} 道错题` : "错题攻坚：错题本已清零";
      progress = mistakesRemaining > 0 ? 0.3 : 1.0;
    } else {
      const targetHours = Number(readingGoals.medicine_hours ?? 2.0);
      const baseSec = Number(readingProg.medicine_seconds || 0);
      progress = targetHours > 0 ? Math.min(1, baseSec / (targetHours * 3600)) : 0;
      tooltip = `医学阅读目标：${(baseSec / 3600).toFixed(1)} / ${targetHours.toFixed(1)}小时 (${Math.round(progress * 100)}%)`;
    }
  } else {
    const targetHours = Number(goals.total_hours ?? 8.0);
    const totalSec = Number(prog.total_seconds || 0) + Math.max(0, (state.readingPendingSeconds || 0) + (state.workspacePendingSeconds || 0));
    progress = Math.min(1, Math.max(0, totalSec / Math.max(1, targetHours * 3600)));
    tooltip = `今日总时长目标：${(totalSec / 3600).toFixed(1)} / ${targetHours.toFixed(1)}小时 (${Math.round(progress * 100)}%)`;
  }

  if (brandBtn) brandBtn.title = tooltip;

  // Circumference for r=18: 2 * Math.PI * 18 = 113.1
  const circumference = 113.1;
  const offset = circumference * (1 - Math.min(1, Math.max(0, progress)));
  barEl.style.strokeDashoffset = offset.toFixed(2);
  barEl.classList.toggle("is-complete", progress >= 0.99);
}

export function startReadingTimer(sectionId) {
  stopWorkspaceTimer();
  collectReadingTime(); flushReadingTime();
  state.readingSectionId = sectionId; state.readingActive = true; state.readingLastTick = Date.now(); state.readingLastScroll = state.readingLastTick;
  syncAuraIndicator();
}

export function stopReadingTimer() {
  collectReadingTime(); state.readingActive = false; flushReadingTime({ refresh: true }); stopWorkspaceTimer();
  syncAuraIndicator();
}

export function markReadingScroll() {
  if (!state.readingActive || !state.readingSectionId) return;
  collectReadingTime(); state.readingLastScroll = Date.now(); state.readingLastTick = state.readingLastScroll;
  syncAuraIndicator();
}

export function initializeReadingTimer() {
  window.addEventListener("scroll", markReadingScroll, { passive: true });
  window.addEventListener("scroll", markWorkspaceActivity, { passive: true });
  ["click", "input", "change", "keydown"].forEach((eventName) => document.addEventListener(eventName, markWorkspaceActivity, { passive: true }));
  document.addEventListener("visibilitychange", () => { collectReadingTime(); collectWorkspaceTime(); syncAuraIndicator(); if (document.hidden) { flushReadingTime(); flushWorkspaceTime(); } });
  window.addEventListener("pagehide", () => { flushReadingTime({ beacon: true }); flushWorkspaceTime({ beacon: true }); });
  window.setInterval(() => {
    collectReadingTime(); collectWorkspaceTime();
    if (state.readingPendingSeconds >= READING_FLUSH_SECONDS) flushReadingTime();
    if (state.workspacePendingSeconds >= READING_FLUSH_SECONDS) flushWorkspaceTime();
    syncAuraIndicator();
  }, 1000);
  syncAuraIndicator();
}

window.syncAuraIndicator = syncAuraIndicator;