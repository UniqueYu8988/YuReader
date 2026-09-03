import { selectLibraryShelf, setActiveView, setRouteHash } from "../core/router.js";
import { hideAllNoteFloats } from "../core/router.js";
import { $, state } from "../core/state.js";
import { stopReadingTimer } from "../core/timer.js";
import { escapeHtml, formatDuration, formatInteger, refreshIcons, renderMarkdown } from "../core/utils.js";
import { activityLevel, renderHome } from "./home.js";
import { closeNotePopover } from "./reader.js";
import { reviewDateLabel } from "./review.js";

export function renderStats() {
  const stats = state.stats || {};
  const totalActivitySeconds = Number(stats.total_activity_seconds ?? stats.total_learning_seconds ?? 0);
  $("statsTodayDuration").textContent = formatDuration(stats.today_activity_seconds, true);
  $("statsTotalDuration").textContent = formatDuration(totalActivitySeconds, true);
  $("statsTotalReading").textContent = formatDuration(totalActivitySeconds, true);
  $("statsActiveDays").textContent = formatInteger(stats.active_day_count);
  $("statsStreak").textContent = `${formatInteger(stats.streak)} 天`;
  $("activitySummary").textContent = `近 ${stats.weeks || 12} 周 · ${formatDuration(stats.heatmap_total_seconds)}`;
  const legacySeconds = Number(stats.legacy_unmapped_reading_seconds || 0);
  const legacyNote = $("statsLegacyNote");
  legacyNote.classList.toggle("hidden", legacySeconds <= 0);
  legacyNote.textContent = legacySeconds > 0 ? `另有 ${formatDuration(legacySeconds)} 历史阅读尚未安全映射，已保留兼容口径，未计入统一时长。` : "";

  const days = stats.days || [];
  const weeks = Math.max(1, stats.weeks || 12);
  $("activityGrid").style.setProperty("--reader-activity-weeks", weeks);
  $("activityMonths").style.setProperty("--reader-activity-weeks", weeks);
  $("activityGrid").innerHTML = days.map((day) => {
    const intensity = Number(day.activity_seconds || 0) || (day.active ? 1 : 0);
    const level = activityLevel(intensity, stats.max || intensity);
    const label = new Date(`${day.date}T00:00:00`).toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
    const legacy = Number(day.legacy_unmapped_reading_seconds || 0);
    const details = `${formatDuration(day.activity_seconds)} · ${formatInteger(day.activity_count || 0)} 个活动${legacy > 0 ? ` · 兼容阅读 ${formatDuration(legacy)}` : ""}`;
    return `<span class="reader-activity-cell level-${level}${day.active ? " active-day" : ""}${day.future ? " future" : ""}${day.date === stats.today ? " today" : ""}" title="${escapeHtml(`${label}：${details}`)}" aria-label="${escapeHtml(`${label}，${details}`)}"></span>`;
  }).join("");
  const monthLabels = [];
  for (let week = 0; week < weeks; week += 1) {
    const day = days[week * 7];
    const month = day ? new Date(`${day.date}T00:00:00`).getMonth() : -1;
    const previous = week && days[(week - 1) * 7] ? new Date(`${days[(week - 1) * 7].date}T00:00:00`).getMonth() : -1;
    monthLabels.push(`<span>${week === 0 || month !== previous ? `${month + 1}月` : ""}</span>`);
  }
  $("activityMonths").innerHTML = monthLabels.join("");

  const domainLabels = { medicine: "医学", politics: "政治", english: "英语", other: "其他兼容项" };
  const domainIcons = { medicine: "stethoscope", politics: "landmark", english: "languages", other: "layers-2" };
  const activityLabels = { read: "阅读", objective_practice: "客观题", subjective_practice: "主观题", notebook: "笔记", review: "回顾" };
  const activityIcons = { read: "book-open", objective_practice: "circle-check-big", subjective_practice: "pen-line", notebook: "notebook-pen", review: "history" };
  const domainTotals = stats.activity_domain_totals || {};
  const domainCounts = stats.activity_domain_counts || {};
  const domains = ["medicine", "politics", "english", "other"].filter((key) => Number(domainTotals[key] || 0) > 0 || Number(domainCounts[key] || 0) > 0);
  const domainRows = domains.map((key) => {
    const row = `<span class="reader-effort-icon"><i data-lucide="${domainIcons[key]}"></i></span><span class="reader-effort-name"><strong>${domainLabels[key]}</strong><small>${formatInteger(domainCounts[key] || 0)} 个活动</small></span><span class="reader-effort-value">${formatDuration(domainTotals[key], true)}</span><i data-lucide="${key === "other" ? "layers-2" : "arrow-up-right"}"></i>`;
    return key === "other" ? `<div class="reader-effort-row">${row}</div>` : `<button type="button" class="reader-effort-row" data-stats-shelf="${key}">${row}</button>`;
  }).join("");
  const activityRows = Object.keys(activityLabels).map((key) => `<div class="reader-effort-row"><span class="reader-effort-icon"><i data-lucide="${activityIcons[key]}"></i></span><span class="reader-effort-name"><strong>${activityLabels[key]}</strong><small>${formatInteger((stats.activity_counts || {})[key] || 0)} 次活动</small></span><span class="reader-effort-value">${formatDuration((stats.activity_totals || {})[key], true)}</span><i data-lucide="minus"></i></div>`).join("");
  $("effortDistribution").innerHTML = `<div class="reader-stats-group"><p class="eyebrow">按学科</p>${domainRows || `<span class="reader-stats-empty">完成一次学习后，这里会显示学科时长。</span>`}</div><div class="reader-stats-group"><p class="eyebrow">按活动类型</p>${activityRows}</div>`;
  $("effortDistribution").querySelectorAll("[data-stats-shelf]").forEach((button) => button.addEventListener("click", () => selectLibraryShelf(button.dataset.statsShelf)));
  refreshIcons();
}

export async function loadStats() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) throw new Error("stats unavailable");
    state.stats = await response.json(); renderHome(); renderStats();
  } catch { renderHome(); renderStats(); }
}

export async function openStats() {
  setRouteHash("records/stats");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); hideAllNoteFloats(); setActiveView("stats"); window.scrollTo({ top: 0, behavior: "auto" });
  await loadStats();
}

export function renderLogsList() {
  $("logsDetail").classList.add("hidden"); $("weeklyReport").classList.add("hidden"); $("logsList").classList.remove("hidden"); const entries = state.logs?.entries || []; const weeks = state.logs?.weekly_entries || [];
  const dailyRows = entries.length ? entries.map((entry) => `<button class="log-mail-row" type="button" data-log-date="${entry.date}"><span><strong>${reviewDateLabel(entry.date)}</strong><small>${entry.has_summary ? "已有回顾总述" : "学习活动归档"}</small></span><span>${entry.unarchived ? "来源待归档" : `${entry.subject_count} 个学科`}</span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="review-empty"><i data-lucide="mail-open"></i><strong>还没有学习记录</strong><span>完成一次学习或回顾后，记录会出现在这里。</span></div>`;
  const weeklyRows = weeks.length ? `<div class="log-section-label"><span>周报归档</span><small>${weeks.length} 份</small></div>${weeks.map((entry) => `<button class="log-mail-row weekly" type="button" data-log-week="${entry.week}"><span><strong>${entry.week} 周报</strong><small>阶段性复习档案</small></span><span></span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("")}` : "";
  $("logsList").innerHTML = `${dailyRows}${weeklyRows}`;
  $("logsList").querySelectorAll("[data-log-date]").forEach((button) => button.addEventListener("click", () => openLogDetail(button.dataset.logDate)));
  $("logsList").querySelectorAll("[data-log-week]").forEach((button) => button.addEventListener("click", () => openWeeklyReport(button.dataset.logWeek))); refreshIcons();
}

export async function openLogDetail(day) {
  const response = await fetch(`/api/logs?date=${encodeURIComponent(day)}`, { cache: "no-store" }); if (!response.ok) return; const payload = await response.json(); const detail = payload.detail; if (!detail) return;
  const legacy = detail.legacy_content?.trim() ? `<hr><p class="eyebrow">旧日志历史（只读）</p>${renderMarkdown(detail.legacy_content)}` : "";
  $("logsList").classList.add("hidden"); $("logsDetail").classList.remove("hidden"); $("logsArticle").innerHTML = `${renderMarkdown(detail.content)}${legacy}`; $("logsObsidianLink").href = detail.obsidian_uri || "obsidian://open"; refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

export async function openWeeklyReport(week = "") {
  const suffix = typeof week === "string" && week ? `?week=${encodeURIComponent(week)}` : ""; const response = await fetch(`/api/weekly-report${suffix}`, { cache: "no-store" }); if (!response.ok) return; state.weekly = await response.json(); $("logsList").classList.add("hidden"); $("logsDetail").classList.add("hidden"); $("weeklyReport").classList.remove("hidden"); $("weeklyTitle").textContent = `${state.weekly.week} 周报`; const recordCount = state.weekly.record_count ?? state.weekly.day_count ?? 0; $("weeklyMeta").textContent = `${state.weekly.start} 至 ${state.weekly.end} · ${recordCount} 个学习日 · ${formatDuration(state.weekly.duration_seconds || 0)}`; const legacyReport = state.weekly.legacy_report?.trim() ? `<hr><p class="eyebrow">旧周报历史（只读）</p>${renderMarkdown(state.weekly.legacy_report)}` : ""; $("weeklySource").innerHTML = `${renderMarkdown(state.weekly.source_markdown)}${legacyReport}`; $("weeklySummary").value = state.weekly.report || ""; $("weeklyObsidianLink").href = state.weekly.obsidian_uri || "obsidian://open"; refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

export function scheduleWeeklySave() {
  if (!state.weekly) return; const content = $("weeklySummary").value; $("weeklySaved").textContent = "保存中…"; window.clearTimeout(state.weeklySaveTimer); state.weeklySaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/weekly-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ week: state.weekly.week, content }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); $("weeklySaved").textContent = content.trim() ? "已保存为独立周报" : "周报已清空"; $("weeklyObsidianLink").href = result.obsidian_uri || "obsidian://open"; const logsResponse = await fetch("/api/logs", { cache: "no-store" }); if (logsResponse.ok) state.logs = await logsResponse.json(); } catch { $("weeklySaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

export async function openLogs() {
  setRouteHash("records");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); hideAllNoteFloats(); setActiveView("logs"); window.scrollTo({ top: 0, behavior: "auto" });
  try { const response = await fetch("/api/logs", { cache: "no-store" }); if (!response.ok) throw new Error("logs unavailable"); state.logs = await response.json(); renderLogsList(); } catch { $("logsList").innerHTML = `<div class="review-empty"><strong>暂时无法读取学习记录</strong></div>`; }
}