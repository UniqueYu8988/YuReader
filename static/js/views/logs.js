import { selectLibraryShelf, setActiveView, setRouteHash } from "../core/router.js";
import { hideAllNoteFloats } from "../core/router.js";
import { $, state } from "../core/state.js";
import { stopReadingTimer } from "../core/timer.js";
import { escapeHtml, formatDuration, formatInteger, refreshIcons, renderMarkdown, showToast } from "../core/utils.js";
import { activityLevel, renderHome } from "./home.js";
import { closeNotePopover } from "./reader.js";
import { reviewDateLabel } from "./review.js";

export function setWeeklyNoteOpen(open) {
  state.weeklyNoteOpen = Boolean(open);
  $("logsNoteFloat")?.classList.toggle("note-is-open", state.weeklyNoteOpen);
  $("logsNotePopover")?.classList.toggle("is-open", state.weeklyNoteOpen);
  $("logsNotePopover")?.setAttribute("aria-hidden", String(!state.weeklyNoteOpen));
  $("toggleLogsNoteDock")?.setAttribute("aria-expanded", String(state.weeklyNoteOpen));
  if (state.weeklyNoteOpen) window.setTimeout(() => $("weeklySummary")?.focus(), 120);
}

export function renderWeeklyCard() {
  const weekly = state.weekly;
  if (!weekly) return;

  $("logsWeekEyebrow").textContent = `本周概览（${weekly.week} · ${weekly.start} 至 ${weekly.end}）`;
  $("logsWeekDuration").textContent = formatDuration(weekly.duration_seconds || 0, true);
  $("logsWeekDays").textContent = `${weekly.day_count || 0} 天`;
  $("logsWeekSummaries").textContent = `${weekly.summary_count || 0} 天`;

  const domainTotals = weekly.activity_by_domain || {};
  $("logsMedMetric").textContent = formatDuration(domainTotals.medicine || 0, true);
  $("logsPolMetric").textContent = formatDuration(domainTotals.politics || 0, true);
  $("logsEngMetric").textContent = formatDuration(domainTotals.english || 0, true);

  if ($("weeklySummary")) {
    $("weeklySummary").value = weekly.report || "";
  }
  if ($("weeklyDrawerObsidian")) {
    $("weeklyDrawerObsidian").href = weekly.obsidian_uri || "obsidian://open";
  }
  if ($("weeklySaved")) {
    $("weeklySaved").textContent = (weekly.report || "").trim() ? "已保存为独立周报" : "粘贴侧边栏周报，自动保存";
  }
  if ($("logsPopoverEyebrow")) {
    $("logsPopoverEyebrow").textContent = `${weekly.week} 周度复盘与 AI 知识织网`;
  }
}

export function renderTimelineCards() {
  const filter = state.logsFilter || "all";
  const entries = state.logs?.entries || [];
  const weeks = state.logs?.weekly_entries || [];

  $("logsFilterAllCount").textContent = `(${entries.length + weeks.length})`;
  $("logsFilterWeeklyCount").textContent = `(${weeks.length})`;
  $("logsFilterDailyCount").textContent = `(${entries.length})`;

  if (filter === "stats") {
    $("logsTimelineSection").classList.add("hidden");
    $("logsStatsSection").classList.remove("hidden");
    renderEmbeddedStats();
    return;
  }

  $("logsTimelineSection").classList.remove("hidden");
  $("logsStatsSection").classList.add("hidden");

  let html = "";

  if (filter === "all" || filter === "weekly") {
    if (weeks.length) {
      const weeklyCards = weeks.map((item) => `
        <div class="logs-card logs-card-weekly" data-card-week="${escapeHtml(item.week)}">
          <div class="logs-card-header">
            <div class="logs-card-title-group">
              <span class="logs-pill-badge weekly">
                <i data-lucide="calendar-range"></i>
                <span>阶段周报</span>
              </span>
              <h3 class="logs-card-date">${escapeHtml(item.week)} 阶段复习档案</h3>
            </div>
            <div class="logs-card-actions">
              <button type="button" class="logs-card-btn view-weekly-btn" data-view-week="${escapeHtml(item.week)}">
                <span>查看汇编</span>
                <i data-lucide="arrow-right"></i>
              </button>
            </div>
          </div>
          <div class="logs-card-body">
            <div class="logs-card-metric-row">
              <span class="logs-card-meta-item">已归档 ${formatInteger(item.character_count || 0)} 字</span>
              <span class="logs-stat-divider">·</span>
              <span class="logs-card-meta-item">${item.source === "learning_record" ? "本地学习记录" : "历史周报"}</span>
            </div>
          </div>
        </div>
      `).join("");
      html += `<div class="logs-timeline-group"><div class="logs-group-title"><span>周报归档</span><small>${weeks.length} 份</small></div>${weeklyCards}</div>`;
    }
  }

  if (filter === "all" || filter === "daily") {
    if (entries.length) {
      const dailyCards = entries.map((entry) => {
        const domains = entry.domain_totals || {};
        const domainPills = [];
        if ((domains.medicine || 0) > 0) {
          domainPills.push(`<span class="logs-domain-pill medicine"><i data-lucide="stethoscope"></i><span>医学 ${formatDuration(domains.medicine, true)}</span></span>`);
        }
        if ((domains.politics || 0) > 0) {
          domainPills.push(`<span class="logs-domain-pill politics"><i data-lucide="landmark"></i><span>政治 ${formatDuration(domains.politics, true)}</span></span>`);
        }
        if ((domains.english || 0) > 0) {
          domainPills.push(`<span class="logs-domain-pill english"><i data-lucide="languages"></i><span>英语 ${formatDuration(domains.english, true)}</span></span>`);
        }

        const quoteHtml = entry.summary_preview ? `
          <blockquote class="logs-summary-quote">
            <i data-lucide="quote"></i>
            <span>${escapeHtml(entry.summary_preview)}</span>
          </blockquote>
        ` : "";

        return `
          <div class="logs-card logs-card-daily" data-card-date="${escapeHtml(entry.date)}">
            <div class="logs-card-header">
              <div class="logs-card-title-group">
                <span class="logs-pill-badge ${entry.has_summary ? "summary-done" : "activity-only"}">
                  <i data-lucide="${entry.has_summary ? "check-circle-2" : "clock-3"}"></i>
                  <span>${entry.has_summary ? "已完成复盘" : "学习活动"}</span>
                </span>
                <h3 class="logs-card-date">${reviewDateLabel(entry.date)}</h3>
              </div>
              <div class="logs-card-actions">
                <button type="button" class="logs-card-btn view-daily-btn" data-view-date="${escapeHtml(entry.date)}">
                  <span>查看详情</span>
                  <i data-lucide="arrow-right"></i>
                </button>
              </div>
            </div>
            <div class="logs-card-body">
              <div class="logs-card-domain-pills">
                ${domainPills.length ? domainPills.join("") : `<span class="logs-domain-pill muted"><span>${entry.subject_count || 1} 个活动</span></span>`}
                <span class="logs-card-duration">${formatDuration(entry.duration_seconds || 0, true)}</span>
              </div>
              ${quoteHtml}
            </div>
          </div>
        `;
      }).join("");
      html += `<div class="logs-timeline-group"><div class="logs-group-title"><span>每日足迹</span><small>${entries.length} 个学习日</small></div>${dailyCards}</div>`;
    }
  }

  if (!html) {
    html = `<div class="review-empty"><i data-lucide="calendar-off"></i><strong>当前分类暂无记录</strong><span>完成学习或回顾后，档案将自动呈现在这里。</span></div>`;
  }

  $("logsTimelineContainer").innerHTML = html;

  $("logsTimelineContainer").querySelectorAll("[data-view-date]").forEach((btn) => {
    btn.addEventListener("click", () => openLogDetail(btn.dataset.viewDate));
  });
  $("logsTimelineContainer").querySelectorAll("[data-view-week]").forEach((btn) => {
    btn.addEventListener("click", () => openWeeklyReport(btn.dataset.viewWeek));
  });

  refreshIcons();
}

function renderEmbeddedStats() {
  const container = $("logsStatsWrapper");
  if (!container) return;
  const statsDashboard = document.querySelector("#statsView .stats-workspace");
  if (statsDashboard) {
    container.innerHTML = statsDashboard.innerHTML;
    container.querySelectorAll("[data-shelf]").forEach((button) => {
      button.addEventListener("click", () => selectLibraryShelf(button.dataset.shelf));
    });
    refreshIcons();
  }
}

let logsEventsBound = false;
export function bindLogsEvents() {
  if (logsEventsBound) return;

  $("logsCopyWeeklyPromptBtn")?.addEventListener("click", async () => {
    const prompt = state.weekly?.ai_weekly_prompt || "";
    if (!prompt) {
      showToast("当前周暂无足够复盘数据生成摘要");
      return;
    }
    try {
      await navigator.clipboard.writeText(prompt);
      showToast("已复制本周知识织网摘要，可直接发给侧边栏 Gemini 提炼！");
    } catch {
      showToast("复制失败，请手动复制");
    }
  });

  $("logsOpenDrawerBtn")?.addEventListener("click", () => {
    setWeeklyNoteOpen(!state.weeklyNoteOpen);
  });

  $("toggleLogsNoteDock")?.addEventListener("click", () => {
    setWeeklyNoteOpen(!state.weeklyNoteOpen);
  });

  $("closeLogsNote")?.addEventListener("click", () => {
    setWeeklyNoteOpen(false);
  });

  $("weeklySummary")?.addEventListener("input", scheduleWeeklySave);

  $("logsTabs")?.querySelectorAll("[data-logs-filter]").forEach((tab) => {
    tab.addEventListener("click", () => {
      $("logsTabs").querySelectorAll("[data-logs-filter]").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      state.logsFilter = tab.dataset.logsFilter;
      renderTimelineCards();
    });
  });

  $("logsBack")?.addEventListener("click", () => {
    $("logsDetail").classList.add("hidden");
    $("logsTimelineSection").classList.remove("hidden");
    $("logsWeeklyCard").classList.remove("hidden");
    $("logsTabs").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "auto" });
  });

  $("weeklyBack")?.addEventListener("click", () => {
    $("weeklyReport").classList.add("hidden");
    $("logsTimelineSection").classList.remove("hidden");
    $("logsWeeklyCard").classList.remove("hidden");
    $("logsTabs").classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "auto" });
  });

  logsEventsBound = true;
}

export function renderStats() {
  const stats = state.stats || {};
  const totalActivitySeconds = Number(stats.total_activity_seconds ?? stats.total_learning_seconds ?? 0);

  // 1. 四维里程碑
  if ($("statsTotalDuration")) $("statsTotalDuration").textContent = formatDuration(totalActivitySeconds, true);
  if ($("statsTodaySub")) $("statsTodaySub").textContent = `今日专注 ${formatDuration(stats.today_activity_seconds || 0, true)}`;
  if ($("statsStreak")) $("statsStreak").textContent = `${formatInteger(stats.streak || 0)} 天`;
  if ($("statsActiveDaysSub")) $("statsActiveDaysSub").textContent = `累计活跃 ${formatInteger(stats.active_day_count || 0)} 天`;
  if ($("statsPracticeTotal")) $("statsPracticeTotal").textContent = `${formatInteger(stats.subject_assets?.politics?.answered_count || (stats.effort_summary?.practice?.answered_count || 0))} 题`;
  if ($("statsAccuracySub")) $("statsAccuracySub").textContent = `综合正确率 ${stats.subject_assets?.politics?.accuracy || 0}%`;
  if ($("statsNoteTotal")) $("statsNoteTotal").textContent = `${formatInteger(stats.note_character_count || 0)} 字`;
  if ($("statsReviewDaysSub")) $("statsReviewDaysSub").textContent = `已完成 ${formatInteger(stats.review_day_count || 0)} 天复盘`;

  // 2. 黄金时段摘要
  if ($("circadianInsightText")) {
    if (stats.golden_slot && stats.golden_slot.percent > 0) {
      $("circadianInsightText").textContent = `恭喜！您的黄金专注期在【${stats.golden_slot.label}】，贡献了全天 ${stats.golden_slot.percent}% 的高强度学时。`;
    } else {
      $("circadianInsightText").textContent = "开启沉浸研习，系统将自动测算您的晨/午/暮黄金精力时段。";
    }
  }

  // 3. 三时段微胶囊作息热力图
  const days = stats.days || [];
  const weeks = Math.max(1, stats.weeks || 12);
  if ($("activityGrid")) {
    $("activityGrid").style.setProperty("--reader-activity-weeks", weeks);
    $("activityMonths").style.setProperty("--reader-activity-weeks", weeks);

    $("activityGrid").innerHTML = days.map((day) => {
      const circadian = day.circadian || { morning_seconds: 0, afternoon_seconds: 0, evening_seconds: 0 };
      const mLevel = activityLevel(circadian.morning_seconds, 7200);
      const aLevel = activityLevel(circadian.afternoon_seconds, 7200);
      const eLevel = activityLevel(circadian.evening_seconds, 7200);
      const label = new Date(`${day.date}T00:00:00`).toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
      const details = `晨间 ${formatDuration(circadian.morning_seconds)} · 午后 ${formatDuration(circadian.afternoon_seconds)} · 晚间 ${formatDuration(circadian.evening_seconds)}（全天 ${formatDuration(day.activity_seconds || 0)}）`;
      return `<div class="reader-circadian-cell${day.active ? " active-day" : ""}${day.future ? " future" : ""}${day.date === stats.today ? " today" : ""}" title="${escapeHtml(`${label}：${details}`)}" aria-label="${escapeHtml(`${label}，${details}`)}">
        <i class="slot-morning level-${mLevel}"></i>
        <i class="slot-afternoon level-${aLevel}"></i>
        <i class="slot-evening level-${eLevel}"></i>
      </div>`;
    }).join("");

    const monthLabels = [];
    for (let week = 0; week < weeks; week += 1) {
      const day = days[week * 7];
      const month = day ? new Date(`${day.date}T00:00:00`).getMonth() : -1;
      const previous = week && days[(week - 1) * 7] ? new Date(`${days[(week - 1) * 7].date}T00:00:00`).getMonth() : -1;
      monthLabels.push(`<span>${week === 0 || month !== previous ? `${month + 1}月` : ""}</span>`);
    }
    $("activityMonths").innerHTML = monthLabels.join("");
  }

  // 4. 三大学科深度资产看板
  const subAssets = stats.subject_assets || {};
  if ($("medTotalHours")) $("medTotalHours").textContent = formatDuration(subAssets.medicine?.duration_seconds || 0, true);
  if ($("medBooksCount")) $("medBooksCount").textContent = `${subAssets.medicine?.book_count || 0} 本`;
  if ($("medNotesCount")) $("medNotesCount").textContent = `${subAssets.medicine?.note_count || 0} 篇`;
  if ($("medOralCount")) $("medOralCount").textContent = `${subAssets.medicine?.oral_studied || 0} 条`;

  if ($("polTotalHours")) $("polTotalHours").textContent = formatDuration(subAssets.politics?.duration_seconds || 0, true);
  if ($("polQuestionsCount")) $("polQuestionsCount").textContent = `${subAssets.politics?.answered_count || 0} 题`;
  if ($("polCorrectCount")) $("polCorrectCount").textContent = `${subAssets.politics?.correct_count || 0} 题`;
  if ($("polAccuracy")) $("polAccuracy").textContent = `${subAssets.politics?.accuracy || 0}%`;

  if ($("engTotalHours")) $("engTotalHours").textContent = formatDuration(subAssets.english?.duration_seconds || 0, true);
  if ($("engAttemptsCount")) $("engAttemptsCount").textContent = `${(stats.activity_counts || {})["objective_practice"] || 0} 题`;
  if ($("engVocabWords")) $("engVocabWords").textContent = `${formatInteger(subAssets.english?.vocab_words || 0)} 词`;
  if ($("engNotebookChars")) $("engNotebookChars").textContent = `${formatInteger(subAssets.english?.notebook_characters || 0)} 字`;
  if ($("engNotebookWeeks")) $("engNotebookWeeks").textContent = `${subAssets.english?.notebook_weeks || 0} 周`;

  document.querySelectorAll("#statsSubjectCards [data-shelf]").forEach((button) => {
    button.addEventListener("click", () => selectLibraryShelf(button.dataset.shelf));
  });

  // 5. 输入 vs 输出配比
  const inOut = stats.input_output_ratio || { input_ratio: 50, output_ratio: 50, input_seconds: 0, output_seconds: 0 };
  if ($("ratioInputFill")) $("ratioInputFill").style.width = `${inOut.input_ratio}%`;
  if ($("ratioOutputFill")) $("ratioOutputFill").style.width = `${inOut.output_ratio}%`;
  if ($("ratioInputText")) $("ratioInputText").textContent = `${inOut.input_ratio}% (${formatDuration(inOut.input_seconds, true)})`;
  if ($("ratioOutputText")) $("ratioOutputText").textContent = `${inOut.output_ratio}% (${formatDuration(inOut.output_seconds, true)})`;

  // 6. 活动类型清单
  const activityLabels = { read: "阅读精读", objective_practice: "客观题练习", subjective_practice: "主观题/背诵", notebook: "词汇与句式笔记", review: "每日复盘总结" };
  const activityIcons = { read: "book-open", objective_practice: "circle-check-big", subjective_practice: "pen-line", notebook: "notebook-pen", review: "history" };
  if ($("activityTypeList")) {
    $("activityTypeList").innerHTML = Object.keys(activityLabels).map((key) => {
      const cnt = (stats.activity_counts || {})[key] || 0;
      const dur = (stats.activity_totals || {})[key] || 0;
      return `<div class="activity-type-row">
        <div class="atr-left">
          <i data-lucide="${activityIcons[key]}"></i>
          <span>${activityLabels[key]}</span>
          <small>${formatInteger(cnt)} 次</small>
        </div>
        <strong class="atr-val">${formatDuration(dur, true)}</strong>
      </div>`;
    }).join("");
  }

  refreshIcons();
}

export async function loadStats() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) throw new Error("stats unavailable");
    state.stats = await response.json();
    renderHome();
    renderStats();
  } catch {
    renderHome();
    renderStats();
  }
}

export async function openStats() {
  setRouteHash("records/stats");
  state.openRequest += 1;
  stopReadingTimer();
  closeNotePopover();
  hideAllNoteFloats();
  setActiveView("stats");
  window.scrollTo({ top: 0, behavior: "auto" });
  await loadStats();
}

export async function openLogDetail(day) {
  const response = await fetch(`/api/logs?date=${encodeURIComponent(day)}`, { cache: "no-store" });
  if (!response.ok) return;
  const payload = await response.json();
  const detail = payload.detail;
  if (!detail) return;
  const legacy = detail.legacy_content?.trim() ? `<hr><p class="eyebrow">旧日志历史（只读）</p>${renderMarkdown(detail.legacy_content)}` : "";
  $("logsTimelineSection").classList.add("hidden");
  $("logsWeeklyCard").classList.add("hidden");
  $("logsTabs").classList.add("hidden");
  $("logsDetail").classList.remove("hidden");
  $("logsArticle").innerHTML = `${renderMarkdown(detail.content)}${legacy}`;
  $("logsObsidianLink").href = detail.obsidian_uri || "obsidian://open";
  refreshIcons();
  window.scrollTo({ top: 0, behavior: "auto" });
}

export async function openWeeklyReport(week = "") {
  const suffix = typeof week === "string" && week ? `?week=${encodeURIComponent(week)}` : "";
  const response = await fetch(`/api/weekly-report${suffix}`, { cache: "no-store" });
  if (!response.ok) return;
  state.weekly = await response.json();
  $("logsTimelineSection").classList.add("hidden");
  $("logsWeeklyCard").classList.add("hidden");
  $("logsTabs").classList.add("hidden");
  $("weeklyReport").classList.remove("hidden");
  $("weeklyTitle").textContent = `${state.weekly.week} 周报汇编`;
  const recordCount = state.weekly.record_count ?? state.weekly.day_count ?? 0;
  $("weeklyMeta").textContent = `${state.weekly.start} 至 ${state.weekly.end} · ${recordCount} 个学习日 · ${formatDuration(state.weekly.duration_seconds || 0)}`;
  const legacyReport = state.weekly.legacy_report?.trim() ? `<hr><p class="eyebrow">旧周报历史（只读）</p>${renderMarkdown(state.weekly.legacy_report)}` : "";
  $("weeklySource").innerHTML = `${renderMarkdown(state.weekly.source_markdown)}${legacyReport}`;
  $("weeklySummary").value = state.weekly.report || "";
  $("weeklyObsidianLink").href = state.weekly.obsidian_uri || "obsidian://open";
  if ($("weeklyDrawerObsidian")) {
    $("weeklyDrawerObsidian").href = state.weekly.obsidian_uri || "obsidian://open";
  }
  refreshIcons();
  window.scrollTo({ top: 0, behavior: "auto" });
}

export function scheduleWeeklySave() {
  if (!state.weekly) return;
  const content = $("weeklySummary").value;
  $("weeklySaved").textContent = "保存中…";
  window.clearTimeout(state.weeklySaveTimer);
  state.weeklySaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/weekly-summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ week: state.weekly.week, content })
      });
      if (!response.ok) throw new Error("save failed");
      const result = await response.json();
      $("weeklySaved").textContent = content.trim() ? "已保存为独立周报" : "周报已清空";
      $("weeklyObsidianLink").href = result.obsidian_uri || "obsidian://open";
      if ($("weeklyDrawerObsidian")) {
        $("weeklyDrawerObsidian").href = result.obsidian_uri || "obsidian://open";
      }
      const logsResponse = await fetch("/api/logs", { cache: "no-store" });
      if (logsResponse.ok) state.logs = await logsResponse.json();
    } catch {
      $("weeklySaved").textContent = "保存失败，请稍后重试";
    }
  }, 420);
}

export async function openLogs() {
  setRouteHash("records");
  state.openRequest += 1;
  stopReadingTimer();
  closeNotePopover();
  hideAllNoteFloats();
  $("logsNoteFloat")?.classList.remove("hidden");
  setWeeklyNoteOpen(false);
  setActiveView("logs");
  window.scrollTo({ top: 0, behavior: "auto" });

  bindLogsEvents();

  $("logsDetail")?.classList.add("hidden");
  $("weeklyReport")?.classList.add("hidden");
  $("logsTimelineSection")?.classList.remove("hidden");
  $("logsWeeklyCard")?.classList.remove("hidden");
  $("logsTabs")?.classList.remove("hidden");

  try {
    const [logsRes, weeklyRes, statsRes] = await Promise.all([
      fetch("/api/logs", { cache: "no-store" }),
      fetch("/api/weekly-report", { cache: "no-store" }),
      fetch("/api/stats", { cache: "no-store" })
    ]);
    if (logsRes.ok) state.logs = await logsRes.json();
    if (weeklyRes.ok) state.weekly = await weeklyRes.json();
    if (statsRes.ok) {
      state.stats = await statsRes.json();
      renderStats();
    }
    renderWeeklyCard();
    renderTimelineCards();
  } catch {
    showToast("读取学习档案失败，请刷新重试");
  }
}