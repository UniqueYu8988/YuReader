const DOMAIN_LABELS = { medicine: "医学", politics: "政治", english: "英语" };
const SHELF_ORDER = ["medicine", "politics", "english"];
const BOOK_COVER_LABELS = {
  "dental-pulp-5e": "牙体",
  "implantology-5e": "种植",
  "oral-anatomy-8e": "口解",
  "oral-maxillofacial-imaging-7e": "影像",
  "oral-maxillofacial-surgery-8e": "口外",
  "oral-mucosa-diseases-5e": "黏膜",
  "oral-pathology-8e": "口组",
  "orthodontics-7e": "正畸",
  "pediatric-dentistry-5e": "儿牙",
  "periodontology-5e": "牙周",
  "prosthodontics-8e": "修复",
  "politics-core-marxism": "马原",
  "politics-ethics-law": "思修",
  "politics-mao": "毛概",
  "politics-modern-history": "史纲",
  "politics-xi": "习中特",
};
const state = { books: [], questionBanks: [], sections: new Map(), current: null, libraryBookId: null, libraryDomain: "medicine", resource: null, resourceBookId: null, resourceCache: new Map(), resourceLoads: new Map(), libraryRailPages: {}, englishCenterTrack: 1, englishCenterYear: "", englishCenterType: "reading", englishCenterOverviewCache: new Map(), englishExamOverview: null, englishExamOverviewBankId: "", readerOriginBookId: null, material: "cleaned", saveTimer: null, noteOpen: false, noteTrigger: null, openRequest: 0, review: null, reviewSummarySaveTimer: null, logs: null, weekly: null, weeklySaveTimer: null, stats: null, homeContinueTarget: null, homeResumeTargets: new Map(), readingActive: false, readingSectionId: "", readingLastTick: Date.now(), readingLastScroll: 0, readingPendingSeconds: 0, readingFlushKey: "", workspaceActivity: null, workspaceActive: false, workspaceLastTick: Date.now(), workspaceLastActive: 0, workspacePendingSeconds: 0, workspaceFlushSequence: 0, workspaceFlushKey: "", homeResizeTimer: null, practice: null, practiceIndex: 0, practiceReturn: "reader", practiceOverviewBankId: "", practiceAnalysisSaveTimer: null, practiceReadingItems: [], practiceReadingToken: 0, subjectivePractice: null, subjectiveReturn: "exam-overview", subjectiveSaveTimer: null, oralFocus: null, oralFocusSubjectId: "", oralFocusTypeFilter: "", oralFocusItem: null, oralFocusFlatItems: [], oralFocusSaveTimer: null };
const $ = (id) => document.getElementById(id);
const READING_IDLE_MS = 10 * 60 * 1000;
const READING_FLUSH_SECONDS = 15;
const THEME_STORAGE_KEY = "yureader-theme";
const ROUTE_ALIASES = {
  today: "home", home: "home", dashboard: "home",
  library: "library", books: "library", bookshelf: "library", shelf: "library",
  "oral-focus": "oralFocus", "library/oral-focus": "oralFocus",
  review: "review", reviews: "review", "yesterday-review": "review",
  records: "logs", record: "logs", logs: "logs", log: "logs",
  "records/stats": "stats", stats: "stats", statistics: "stats",
};

function setRouteHash(route) {
  const next = `#${route}`;
  if (window.location.hash !== next) window.history.replaceState(null, "", next);
}

function hashRoute() {
  const raw = decodeURIComponent(window.location.hash.replace(/^#\/?/, "")).trim().toLowerCase();
  const queryRoute = new URLSearchParams(window.location.search).get("view")?.trim().toLowerCase() || "";
  return ROUTE_ALIASES[raw || queryRoute] || "";
}

function applyTheme(theme, { persist = true } = {}) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next;
  $("themeColor")?.setAttribute("content", next === "dark" ? "#1b1b19" : "#f5f4ed");
  if (persist) {
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch {}
  }
  const button = $("themeToggle");
  if (button) {
    const dark = next === "dark";
    button.innerHTML = `<i data-lucide="${dark ? "sun" : "moon"}"></i>`;
    button.setAttribute("aria-label", dark ? "切换到日间模式" : "切换到夜间模式");
    button.setAttribute("title", dark ? "切换到日间模式" : "切换到夜间模式");
    button.setAttribute("aria-pressed", String(dark));
  }
  refreshIcons();
}

function toggleTheme() {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
}

function refreshIcons() {
  window.lucide?.createIcons?.({ attrs: { "stroke-width": 1.7 } });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

const { inlineMarkdown, renderMarkdown } = window.YuReaderMarkdown.create(escapeHtml);

function normalizeSectionHeading(value) {
  return String(value || "").normalize("NFKC").replace(/[*_`~#]/g, "").replace(/[\s·•:：,，。.!！?？()（）\[\]【】]/g, "").toLowerCase();
}

function displayGuideTitle(value) {
  return String(value || "").replace(/^\s*[、．.]\s*/, "").trim();
}

function prepareSectionMarkdown(markdown, sectionTitle) {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const sectionKey = normalizeSectionHeading(sectionTitle);
  let contentStart = 0;
  let removedDuplicate = false;
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (!match || normalizeSectionHeading(match[2]) !== sectionKey) continue;
    lines.splice(index, 1);
    contentStart = index;
    removedDuplicate = true;
    break;
  }

  const headings = [];
  for (const line of lines.slice(contentStart)) {
    const match = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (!match) continue;
    const title = match[2].trim();
    if (!title || normalizeSectionHeading(title) === sectionKey) continue;
    if (/^第[一二三四五六七八九十百零〇\d]+章/.test(title) || /^>{0,2}\s*导言$/.test(title)) continue;
    headings.push({ level: match[1].length, title });
  }

  const points = headings.filter((item) => /^考点\s*\d+/i.test(item.title));
  const major = headings.filter((item) => /^[一二三四五六七八九十百]+[、.．]\s*/.test(item.title));
  let selected = [];
  let kind = "内容";
  if (points.length >= 2) {
    selected = points;
    kind = "考点";
  } else if (major.length >= 2) {
    selected = major;
  } else if (headings.length >= 2) {
    const shallowest = Math.min(...headings.map((item) => item.level));
    selected = headings.filter((item) => item.level === shallowest);
  }

  const seen = new Set();
  selected = selected.filter((item) => {
    const key = normalizeSectionHeading(item.title);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return { markdown: lines.join("\n"), guide: selected, kind, removedDuplicate };
}

function renderSectionGuide(article, guideElement, guideItems, kind) {
  guideElement.classList.add("hidden");
  guideElement.innerHTML = "";
  if (!guideItems.length) return;

  const renderedHeadings = [...article.querySelectorAll("h1, h2, h3, h4, h5, h6")];
  const links = [];
  let searchFrom = 0;
  guideItems.forEach((item, index) => {
    const expected = normalizeSectionHeading(item.title);
    const offset = renderedHeadings.slice(searchFrom).findIndex((heading) => normalizeSectionHeading(heading.textContent) === expected);
    if (offset < 0) return;
    const headingIndex = searchFrom + offset;
    const heading = renderedHeadings[headingIndex];
    const id = `section-guide-${links.length + 1}`;
    heading.id = id;
    searchFrom = headingIndex + 1;
    links.push(`<a href="#${id}"><span>${String(links.length + 1).padStart(2, "0")}</span><strong>${inlineMarkdown(displayGuideTitle(item.title))}</strong></a>`);
  });
  if (!links.length) return;

  guideElement.innerHTML = `<details open><summary><span><small>本节导航</small><strong>${links.length} 个${kind}</strong></span><i data-lucide="chevron-down"></i></summary><div class="section-guide-grid">${links.join("")}</div></details>`;
  guideElement.classList.remove("hidden");
  guideElement.querySelectorAll("a").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById(link.getAttribute("href").slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

function showToast(message) {
  const toast = $("toast"); toast.textContent = message; toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 2200);
}

function bookToc(book) {
  if (book.toc?.length) return book.toc;
  return [{ id: `${book.id}-contents`, order: 1, title: "目录", sections: book.sections || [] }];
}

function formatCharacters(value) {
  const count = Number(value || 0);
  if (!count) return "";
  return count >= 10000 ? `${(count / 10000).toFixed(1)} 万字` : `${(count / 1000).toFixed(1)} 千字`;
}

function bookCoverTitle(book) {
  const shortTitle = BOOK_COVER_LABELS[book?.id];
  if (shortTitle) return escapeHtml(shortTitle);
  const text = String(book?.title || "本地书籍").trim();
  const splitAt = text.startsWith("口腔") && text.length > 2 ? 2 : Math.ceil(text.length / 2);
  return `${escapeHtml(text.slice(0, splitAt))}<br>${escapeHtml(text.slice(splitAt))}`;
}

function setActiveView(mode) {
  const viewMode = mode === "reader" ? "library" : mode;
  ["home", "library", "oralFocus", "practice", "review", "logs", "stats"].forEach((view) => $(`${view}View`).classList.toggle("active", view === viewMode));
  const primaryMode = mode === "home" ? "home" : ["library", "reader", "oralFocus", "practice"].includes(mode) ? "library" : mode === "review" ? "review" : "logs";
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.classList.toggle("active", primaryMode === "home"));
  $("libraryNav").classList.toggle("active", primaryMode === "library"); $("mobileLibrary").classList.toggle("active", primaryMode === "library");
  $("reviewNav").classList.toggle("active", primaryMode === "review"); $("mobileReview").classList.toggle("active", primaryMode === "review");
  $("logsNav").classList.toggle("active", primaryMode === "logs"); $("mobileLogs").classList.toggle("active", primaryMode === "logs");
  $("pageTitle").textContent = mode === "home" ? "今日" : mode === "reader" ? "阅读" : mode === "oralFocus" ? "口腔重点" : mode === "library" ? "学习库" : mode === "practice" ? "练习" : mode === "review" ? "回顾" : mode === "logs" ? "记录" : "统计";
}

function setHomeMode() {
  setRouteHash("today");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("home"); renderHome(); window.scrollTo({ top: 0, behavior: "auto" });
}

function setLibraryMode() {
  setRouteHash("library");
  state.openRequest += 1; stopReadingTimer();
  state.resourceBookId = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden"); $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library"); closeNotePopover();
  renderBooks(); window.scrollTo({ top: 0, behavior: "auto" });
}

function selectLibraryShelf(shelf) {
  if (!SHELF_ORDER.includes(shelf)) return;
  state.openRequest += 1; stopReadingTimer(); closeNotePopover();
  state.libraryDomain = shelf;
  state.resourceBookId = null; state.resource = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden"); $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library");
  renderBooks(); window.scrollTo({ top: 0, behavior: "auto" });
}

function setReaderMode() {
  $("libraryWorkspace").classList.remove("resource-open");
  $("libraryWorkspace").classList.add("reader-open"); $("readerContent").classList.remove("hidden"); $("sectionNoteFloat").classList.remove("hidden");
  setActiveView("reader"); if (state.current?.id) startReadingTimer(state.current.id);
}

function formatInteger(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

function formatDuration(seconds, compact = false) {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  if (!total) return compact ? "0分" : "0分钟";
  if (total < 60) return compact ? "<1分" : "不足1分钟";
  if (compact && total >= 3600) {
    const hours = total / 3600; return `${hours.toFixed(hours < 10 ? 1 : 0).replace(/\.0$/, "")}小时`;
  }
  const minutes = Math.floor(total / 60);
  const hours = Math.floor(minutes / 60); const remainder = minutes % 60;
  if (!hours) return `${minutes}分`;
  return remainder ? `${hours}小时${remainder}分` : `${hours}小时`;
}

function collectReadingTime(now = Date.now()) {
  const startedAt = state.readingLastTick || now; state.readingLastTick = now;
  if (!state.readingActive || !state.readingSectionId || document.hidden) return;
  const activeUntil = Math.min(now, state.readingLastScroll + READING_IDLE_MS);
  if (activeUntil > startedAt) state.readingPendingSeconds += (activeUntil - startedAt) / 1000;
}

function markWorkspaceActivity() {
  if (state.workspaceActive) state.workspaceLastActive = Date.now();
}

function collectWorkspaceTime(now = Date.now()) {
  const startedAt = state.workspaceLastTick || now; state.workspaceLastTick = now;
  if (!state.workspaceActive || document.hidden) return;
  const activeUntil = Math.min(now, state.workspaceLastActive + READING_IDLE_MS);
  if (activeUntil > startedAt) state.workspacePendingSeconds += (activeUntil - startedAt) / 1000;
}

async function flushWorkspaceTime({ beacon = false } = {}) {
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

function stopWorkspaceTimer() {
  collectWorkspaceTime(); state.workspaceActive = false; flushWorkspaceTime();
}

function startWorkspaceTimer(activity) {
  stopWorkspaceTimer();
  if (!activity?.activity_type || !activity?.domain || !activity?.subject_id || !activity?.resource_id || !activity?.item_id) return;
  state.workspaceActivity = { ...activity, activity_id: activity.activity_id || `${activity.activity_type}-${Date.now()}-${Math.random().toString(36).slice(2)}` };
  state.workspaceActive = true; state.workspaceLastTick = Date.now(); state.workspaceLastActive = state.workspaceLastTick; state.workspacePendingSeconds = 0;
}

async function flushReadingTime({ beacon = false, refresh = false } = {}) {
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

function startReadingTimer(sectionId) {
  stopWorkspaceTimer();
  collectReadingTime(); flushReadingTime();
  state.readingSectionId = sectionId; state.readingActive = true; state.readingLastTick = Date.now(); state.readingLastScroll = state.readingLastTick;
}

function stopReadingTimer() {
  collectReadingTime(); state.readingActive = false; flushReadingTime({ refresh: true }); stopWorkspaceTimer();
}

function markReadingScroll() {
  if (!state.readingActive || !state.readingSectionId) return;
  collectReadingTime(); state.readingLastScroll = Date.now(); state.readingLastTick = state.readingLastScroll;
}

function activityTypeLabel(type) {
  return ({ read: "阅读", objective_practice: "客观题", subjective_practice: "主观题", notebook: "笔记", review: "回顾" })[type] || "学习";
}

function homeActivityTargetKey(prefix, index) {
  return `${prefix}-${index}`;
}

async function resumeActivityTarget(target) {
  if (!target?.view || !target.item_id) { setLibraryMode(); return; }
  if (target.view === "reader") { state.readerOriginBookId = null; openSection(target.item_id); return; }
  if (target.view === "english_notebook") { selectLibraryShelf("english"); return; }
  if (target.view === "subjective_practice") { openSubjectivePractice(target.resource_id, target.item_id); return; }
  if (target.view === "oral_focus") { openOralFocusItem(target.item_id); return; }
  if (target.view === "review") { openReview(target.item_id); return; }
  if (target.view === "practice") {
    if (target.knowledge_id && target.match_level) {
      openPractice({ bank_id: target.resource_id, knowledge_id: target.knowledge_id, match_level: target.match_level }, "home", target.start_index || 0);
      return;
    }
    try {
      const response = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(target.resource_id || "")}`, { cache: "no-store" });
      const payload = response.ok ? await response.json() : {};
      const entry = (payload.groups || []).find((group) => group.kind === "objective") || payload.groups?.[0];
      if (entry) openPractice({ bank_id: target.resource_id, knowledge_id: entry.knowledge_id, match_level: entry.match_level || "comprehensive" }, "home", 0);
      else showToast("暂时无法恢复这组题目");
    } catch { showToast("暂时无法恢复这组题目"); }
    return;
  }
  setLibraryMode();
}

function renderHome() {
  const stats = state.stats || {};
  const today = stats.today ? new Date(`${stats.today}T00:00:00`) : new Date();
  $("homeDate").textContent = today.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("homeGreeting").textContent = "今天继续学一点";
  const continuation = stats.continue_activity;
  const continueTarget = stats.continue_target || null;
  state.homeContinueTarget = continueTarget;
  $("homeLeadText").textContent = continuation ? `上次停在“${continuation.title}”` : "选择一本书，开始今天的学习";
  $("homeContinueLabel").textContent = continuation?.activity_label ? `继续${continuation.activity_label}` : "继续学习";
  $("homeContinueTitle").textContent = continuation?.title || "进入学习库选择内容";
  const pending = stats.review_pending;
  $("homeTodayMinutes").textContent = formatInteger(Math.floor((stats.today_activity_seconds || 0) / 60));
  $("homeTodayActivities").textContent = `${formatInteger(stats.today_activity_count || 0)} 项活动`;
  $("homeTodayNotes").textContent = `${formatInteger(stats.today_note_count || 0)} 条笔记`;
  $("homeReviewMeta").textContent = pending ? `${reviewDateLabel(pending.date)} · ${formatInteger(pending.activity_count)} 条待整理` : "整理最近学习";

  state.homeResumeTargets.clear();
  const todayActivities = stats.today_activities || [];
  $("homeTracePanel").classList.toggle("hidden", !todayActivities.length);
  $("homeTraceList").innerHTML = todayActivities.map((item, index) => {
    const key = homeActivityTargetKey("activity", index); state.homeResumeTargets.set(key, item.resume_target);
    return `<button class="reader-home-trace-row" type="button" data-home-resume="${key}"><span><strong>${escapeHtml(item.activity_label || activityTypeLabel(item.activity_type))}</strong><small>${escapeHtml(item.title || item.item_id || "学习条目")} · ${escapeHtml(item.subject_id || item.domain || "")}</small></span><span>${formatDuration(item.duration_seconds, true)}</span><i data-lucide="arrow-up-right"></i></button>`;
  }).join("");
  $("homeTraceList").querySelectorAll("[data-home-resume]").forEach((button) => button.addEventListener("click", () => resumeActivityTarget(state.homeResumeTargets.get(button.dataset.homeResume))));
  refreshIcons();
}

function activityLevel(count, maximum) {
  if (!count || !maximum) return 0;
  return Math.min(4, Math.max(1, Math.ceil((Math.log(count + 1) / Math.log(maximum + 1)) * 4)));
}

function renderStats() {
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

async function loadStats() {
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) throw new Error("stats unavailable");
    state.stats = await response.json(); renderHome(); renderStats();
  } catch { renderHome(); renderStats(); }
}

async function openStats() {
  setRouteHash("records/stats");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("stats"); window.scrollTo({ top: 0, behavior: "auto" });
  await loadStats();
}

function reviewDateLabel(value) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}

function setReviewPanel() {
  document.querySelector(".review-heading").classList.remove("hidden");
  $("reviewEmpty").classList.add("hidden");
  $("reviewReportPanel").classList.remove("hidden");
}

function renderReviewUnified() {
  const review = state.review;
  const sourceCount = review?.source_count || 0;
  $("reviewTitle").textContent = review ? `${reviewDateLabel(review.review_date)}的回顾` : "回顾";
  $("reviewSummary").textContent = review ? `${sourceCount} 条真实学习来源 · 一次性回顾` : "正在整理最近的学习活动…";
  $("reviewProgressText").textContent = review?.review_done ? "已完成" : "待回顾";
  $("reviewCombinedDocument").innerHTML = renderMarkdown(review?.combined_markdown || "暂无可归档的学习产出；原始活动记录仍可从记录页查看。");
  $("reviewDailySummary").value = review?.review_result || "";
  $("reviewSummarySaved").textContent = review?.review_done ? (review.review_no_text ? "已标记为无文本回顾" : "已保存为独立学习记录") : `${sourceCount} 条来源 · 粘贴后保存为独立学习记录`;
  $("reviewLogObsidian").href = review?.learning_record_uri || review?.log_uri || "obsidian://open";
  setReviewPanel(); refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

async function openReview(reviewDate = "") {
  if (typeof reviewDate !== "string") reviewDate = "";
  setRouteHash("review");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("review"); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const suffix = reviewDate ? `?date=${encodeURIComponent(reviewDate)}` : "";
    const response = await fetch(`/api/reviews${suffix}`, { cache: "no-store" });
    if (!response.ok) throw new Error("review unavailable");
    state.review = await response.json();
    const subject = state.review.subjects?.[0];
    const resourceId = subject?.book_id || subject?.subject_key || "daily-review";
    startWorkspaceTimer({ activity_type: "review", domain: subject?.domain || "medicine", subject_id: "daily-review", resource_id: resourceId, item_id: state.review.review_date, resume_target: { view: "review", resource_id: resourceId, item_id: state.review.review_date } });
    renderReviewUnified();
  } catch {
    $("reviewSummary").textContent = "暂时无法读取本地复习内容"; $("reviewEmpty").classList.remove("hidden");
  }
}

function scheduleDailySummarySave() {
  if (!state.review) return; const content = $("reviewDailySummary").value; $("reviewSummarySaved").textContent = "保存中…"; window.clearTimeout(state.reviewSummarySaveTimer);
  state.reviewSummarySaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/review-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: state.review.review_date, content, no_text: false }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); state.review = result.review; renderReviewUnified(); loadStats(); } catch { $("reviewSummarySaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

async function markReviewNoText() {
  if (!state.review) return;
  $("reviewSummarySaved").textContent = "保存中…";
  try {
    const response = await fetch("/api/review-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: state.review.review_date, content: "", no_text: true }) });
    if (!response.ok) throw new Error("save failed");
    const result = await response.json(); state.review = result.review; renderReviewUnified();
  } catch { $("reviewSummarySaved").textContent = "保存失败，请稍后重试"; }
}

async function openLogs() {
  setRouteHash("records");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("logs"); window.scrollTo({ top: 0, behavior: "auto" });
  try { const response = await fetch("/api/logs", { cache: "no-store" }); if (!response.ok) throw new Error("logs unavailable"); state.logs = await response.json(); renderLogsList(); } catch { $("logsList").innerHTML = `<div class="review-empty"><strong>暂时无法读取学习记录</strong></div>`; }
}

function applyRouteHash() {
  const route = hashRoute();
  if (route === "home") setHomeMode();
  else if (route === "library") setLibraryMode();
  else if (route === "oralFocus") openOralFocusIndex();
  else if (route === "review") openReview();
  else if (route === "logs") openLogs();
  else if (route === "stats") openStats();
}

function renderLogsList() {
  $("logsDetail").classList.add("hidden"); $("weeklyReport").classList.add("hidden"); $("logsList").classList.remove("hidden"); const entries = state.logs?.entries || []; const weeks = state.logs?.weekly_entries || [];
  const dailyRows = entries.length ? entries.map((entry) => `<button class="log-mail-row" type="button" data-log-date="${entry.date}"><span><strong>${reviewDateLabel(entry.date)}</strong><small>${entry.has_summary ? "已有回顾总述" : "学习活动归档"}</small></span><span>${entry.unarchived ? "来源待归档" : `${entry.subject_count} 个学科`}</span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="review-empty"><i data-lucide="mail-open"></i><strong>还没有学习记录</strong><span>完成一次学习或回顾后，记录会出现在这里。</span></div>`;
  const weeklyRows = weeks.length ? `<div class="log-section-label"><span>周报归档</span><small>${weeks.length} 份</small></div>${weeks.map((entry) => `<button class="log-mail-row weekly" type="button" data-log-week="${entry.week}"><span><strong>${entry.week} 周报</strong><small>阶段性复习档案</small></span><span></span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("")}` : "";
  $("logsList").innerHTML = `${dailyRows}${weeklyRows}`;
  $("logsList").querySelectorAll("[data-log-date]").forEach((button) => button.addEventListener("click", () => openLogDetail(button.dataset.logDate)));
  $("logsList").querySelectorAll("[data-log-week]").forEach((button) => button.addEventListener("click", () => openWeeklyReport(button.dataset.logWeek))); refreshIcons();
}

async function openLogDetail(day) {
  const response = await fetch(`/api/logs?date=${encodeURIComponent(day)}`, { cache: "no-store" }); if (!response.ok) return; const payload = await response.json(); const detail = payload.detail; if (!detail) return;
  const legacy = detail.legacy_content?.trim() ? `<hr><p class="eyebrow">旧日志历史（只读）</p>${renderMarkdown(detail.legacy_content)}` : "";
  $("logsList").classList.add("hidden"); $("logsDetail").classList.remove("hidden"); $("logsArticle").innerHTML = `${renderMarkdown(detail.content)}${legacy}`; $("logsObsidianLink").href = detail.obsidian_uri || "obsidian://open"; refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

async function openWeeklyReport(week = "") {
  const suffix = typeof week === "string" && week ? `?week=${encodeURIComponent(week)}` : ""; const response = await fetch(`/api/weekly-report${suffix}`, { cache: "no-store" }); if (!response.ok) return; state.weekly = await response.json(); $("logsList").classList.add("hidden"); $("logsDetail").classList.add("hidden"); $("weeklyReport").classList.remove("hidden"); $("weeklyTitle").textContent = `${state.weekly.week} 周报`; const recordCount = state.weekly.record_count ?? state.weekly.day_count ?? 0; $("weeklyMeta").textContent = `${state.weekly.start} 至 ${state.weekly.end} · ${recordCount} 个学习日 · ${formatDuration(state.weekly.duration_seconds || 0)}`; const legacyReport = state.weekly.legacy_report?.trim() ? `<hr><p class="eyebrow">旧周报历史（只读）</p>${renderMarkdown(state.weekly.legacy_report)}` : ""; $("weeklySource").innerHTML = `${renderMarkdown(state.weekly.source_markdown)}${legacyReport}`; $("weeklySummary").value = state.weekly.report || ""; $("weeklyObsidianLink").href = state.weekly.obsidian_uri || "obsidian://open"; refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

function scheduleWeeklySave() {
  if (!state.weekly) return; const content = $("weeklySummary").value; $("weeklySaved").textContent = "保存中…"; window.clearTimeout(state.weeklySaveTimer); state.weeklySaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/weekly-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ week: state.weekly.week, content }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); $("weeklySaved").textContent = content.trim() ? "已保存为独立周报" : "周报已清空"; $("weeklyObsidianLink").href = result.obsidian_uri || "obsidian://open"; const logsResponse = await fetch("/api/logs", { cache: "no-store" }); if (logsResponse.ok) state.logs = await logsResponse.json(); } catch { $("weeklySaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

function oralFocusMasteryLabel(value) {
  return ({ unseen: "未学", learning: "不会", fuzzy: "模糊", mastered: "已掌握" })[value] || "未学";
}

function selectedOralFocusSubject() {
  const subjects = state.oralFocus?.subjects || [];
  return subjects.find((item) => item.id === state.oralFocusSubjectId) || subjects[0] || null;
}

function renderOralFocusDirectory() {
  const subjects = state.oralFocus?.subjects || [];
  const subject = selectedOralFocusSubject();
  if (!subject) {
    $("oralFocusSubjectTabs").innerHTML = "";
    $("oralFocusChapters").innerHTML = `<div class="knowledge-index-empty"><strong>口腔重点资料尚未导入</strong><span>运行本地 DOCX 导入后，这里会显示五科目录。</span></div>`;
    return;
  }
  state.oralFocusSubjectId = subject.id;
  const type = state.oralFocusTypeFilter;
  const typeLabel = type === "definition" ? "名词解释" : type === "essay" ? "论述题" : "重点题";
  const filteredChapters = (subject.chapters || []).map((chapter) => ({ ...chapter, items: (chapter.items || []).filter((item) => !type || item.type === type) })).filter((chapter) => chapter.items.length);
  const filteredItems = filteredChapters.flatMap((chapter) => chapter.items);
  const studiedCount = filteredItems.filter((item) => item.mastery && item.mastery !== "unseen").length;
  $("oralFocusSummary").textContent = `${typeLabel} · ${formatInteger(filteredItems.length)} 道 · ${formatInteger(studiedCount)} 道已有学习记录`;
  $("oralFocusSubjectTabs").innerHTML = subjects.map((entry) => {
    const count = (entry.chapters || []).flatMap((chapter) => chapter.items || []).filter((item) => !type || item.type === type).length;
    return `<button type="button" class="${entry.id === subject.id ? "active" : ""}" data-oral-subject="${escapeHtml(entry.id)}" aria-pressed="${entry.id === subject.id ? "true" : "false"}"><strong>${escapeHtml(entry.short_title)}</strong><small>${formatInteger(count)} 题</small></button>`;
  }).join("");
  $("oralFocusChapters").innerHTML = filteredChapters.length ? filteredChapters.map((chapter, index) => `<details class="oral-focus-chapter" ${index === 0 ? "open" : ""}><summary><span>${String(chapter.order || index + 1).padStart(2, "0")}</span><strong>${escapeHtml(chapter.title)}</strong><em>${formatInteger(chapter.items.length)} 题</em><i data-lucide="chevron-right"></i></summary><div class="oral-focus-item-list">${chapter.items.map((item) => `<button class="oral-focus-item-row" type="button" data-oral-item="${escapeHtml(item.id)}" data-mastery="${escapeHtml(item.mastery || "unseen")}"><span>${escapeHtml(item.type_label)}${item.star_level ? ` · ${"★".repeat(item.star_level)}` : ""}</span><strong>${escapeHtml(item.title)}</strong><em>${oralFocusMasteryLabel(item.mastery)}</em><i data-lucide="arrow-right"></i></button>`).join("")}</div></details>`).join("") : `<div class="knowledge-index-empty"><strong>本科暂无${typeLabel}</strong><span>切换其他学科，或返回医学学习库选择另一类资料。</span></div>`;
  $("oralFocusSubjectTabs").querySelectorAll("[data-oral-subject]").forEach((button) => button.addEventListener("click", () => { state.oralFocusSubjectId = button.dataset.oralSubject; renderOralFocusDirectory(); window.scrollTo({ top: 0, behavior: "auto" }); }));
  $("oralFocusChapters").querySelectorAll("[data-oral-item]").forEach((button) => button.addEventListener("click", () => openOralFocusItem(button.dataset.oralItem)));
  refreshIcons();
}

async function loadOralFocus() {
  const response = await fetch("/api/oral-focus", { cache: "no-store" });
  if (!response.ok) throw new Error("oral focus unavailable");
  state.oralFocus = await response.json();
  if (!state.oralFocusSubjectId) state.oralFocusSubjectId = state.oralFocus.subjects?.[0]?.id || "";
  return state.oralFocus;
}

async function openOralFocusIndex(subjectId = "", type = "") {
  setRouteHash("library/oral-focus"); stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("oralFocus");
  $("oralFocusQuestion").classList.add("hidden"); $("oralFocusDirectory").classList.remove("hidden");
  try {
    if (!state.oralFocus?.available) await loadOralFocus();
    if (subjectId) state.oralFocusSubjectId = subjectId;
    state.oralFocusTypeFilter = type;
    renderOralFocusDirectory();
  } catch {
    state.oralFocus = { available: false, subjects: [] }; renderOralFocusDirectory();
  }
  window.scrollTo({ top: 0, behavior: "auto" });
}

function oralFocusPrompt(kind) {
  const item = state.oralFocusItem;
  if (!item) return "";
  if (kind === "understand") return "只依据当前页面帮助我理解这道口腔考试题。先说明它真正考什么、答案应按什么逻辑组织、哪些概念容易混淆。当前页尚未展示参考答案时，不要替我直接作答，也不要补充页面以外的医学知识；发现疑似 OCR 问题时只标记。";
  if (kind === "recall") return `请考我当前这道${item.type_label}。只念题，不提示答案；等待我完整口述后再追问一次。参考答案尚未在页面展示时，不要自行编造评分点。`;
  return "当前页面已经展示了我的作答与来源参考答案。请以页面参考答案为唯一评分基准，逐项输出：已覆盖评分点、遗漏评分点、错误或混淆、推荐答题顺序、20秒口述版。不要生成一篇替代我思考的长答案；疑似 OCR 问题单独标记。";
}

async function copyOralFocusPrompt(kind) {
  const prompt = oralFocusPrompt(kind); if (!prompt) return;
  try { await navigator.clipboard.writeText(prompt); showToast("提示词已复制，可粘贴到 Gemini 侧边栏"); }
  catch { showToast("复制失败，请允许剪贴板访问"); }
}

function updateOralFocusMastery(value) {
  if (!state.oralFocusItem) return;
  state.oralFocusItem.progress.mastery = value;
  renderOralFocusMastery(); scheduleOralFocusSave();
}

function renderOralFocusMastery() {
  const mastery = state.oralFocusItem?.progress?.mastery || "unseen";
  $("oralFocusMastery").querySelectorAll("[data-mastery]").forEach((button) => {
    const active = button.dataset.mastery === mastery;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function renderOralFocusQuestion() {
  const item = state.oralFocusItem; if (!item) return;
  const subject = item.subject || {}; const chapter = item.chapter || {};
  state.oralFocusSubjectId = subject.id || state.oralFocusSubjectId;
  const selected = selectedOralFocusSubject();
  state.oralFocusFlatItems = (selected?.chapters || []).flatMap((entry) => entry.items || []).filter((entry) => !state.oralFocusTypeFilter || entry.type === state.oralFocusTypeFilter);
  const position = Math.max(0, state.oralFocusFlatItems.findIndex((entry) => entry.id === item.id));
  $("oralFocusQuestionType").textContent = item.type_label || "重点题";
  $("oralFocusQuestionStars").textContent = item.star_level ? "★".repeat(item.star_level) : "";
  $("oralFocusQuestionLocation").textContent = `${subject.short_title || subject.title || "口腔"} · ${chapter.title || "未分章"}`;
  $("oralFocusQuestionTitle").textContent = item.title || "口腔重点题";
  $("oralFocusSourceNote").textContent = `${(item.source_files || []).join("、")}${item.has_table ? " · 含表格" : ""}${item.has_unreviewed_image ? " · 有待复核图片" : ""}`;
  $("oralFocusAnswer").value = item.progress?.answer || "";
  $("oralFocusMemory").value = item.progress?.memory_note || "";
  $("oralFocusSaved").textContent = item.progress?.updated_at ? "已载入上次保存" : "输入后自动保存";
  $("oralFocusReference").classList.toggle("hidden", !item.reference_revealed);
  $("oralFocusGradePrompt").classList.toggle("hidden", !item.reference_revealed);
  $("oralFocusReveal").classList.toggle("hidden", item.reference_revealed);
  $("oralFocusReferenceBody").innerHTML = item.reference_revealed ? renderMarkdown(item.answer_markdown || "暂无可识别的参考答案。") : "";
  $("oralFocusPosition").textContent = `${position + 1} / ${state.oralFocusFlatItems.length}`;
  $("oralFocusPrevious").disabled = position <= 0; $("oralFocusNext").disabled = position >= state.oralFocusFlatItems.length - 1;
  renderOralFocusMastery(); refreshIcons();
}

async function openOralFocusItem(itemId) {
  if (!itemId) return;
  setRouteHash("library/oral-focus"); stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("oralFocus");
  $("oralFocusDirectory").classList.add("hidden"); $("oralFocusQuestion").classList.remove("hidden");
  $("oralFocusQuestionTitle").textContent = "正在读取题目…"; $("oralFocusReferenceBody").innerHTML = ""; $("oralFocusReference").classList.add("hidden");
  try {
    if (!state.oralFocus?.available) await loadOralFocus();
    const response = await fetch(`/api/oral-focus/item?item_id=${encodeURIComponent(itemId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("item unavailable");
    state.oralFocusItem = await response.json();
    if (!state.oralFocusTypeFilter) state.oralFocusTypeFilter = state.oralFocusItem.type || "";
    renderOralFocusQuestion();
    const subject = state.oralFocusItem.subject || {};
    startWorkspaceTimer({ activity_type: "subjective_practice", domain: "medicine", subject_id: subject.title || subject.id, resource_id: `oral-focus:${subject.id}`, item_id: itemId, resume_target: { view: "oral_focus", resource_id: `oral-focus:${subject.id}`, item_id: itemId } });
  } catch { $("oralFocusQuestionTitle").textContent = "暂时无法读取这道题"; }
  window.scrollTo({ top: 0, behavior: "auto" });
}

async function revealOralFocusReference() {
  const item = state.oralFocusItem; if (!item || item.reference_revealed) return;
  const response = await fetch(`/api/oral-focus/item?item_id=${encodeURIComponent(item.id)}&reveal=1`, { cache: "no-store" });
  if (!response.ok) { showToast("暂时无法读取参考答案"); return; }
  const revealed = await response.json();
  state.oralFocusItem = { ...revealed, progress: { ...revealed.progress, answer: $("oralFocusAnswer").value, memory_note: $("oralFocusMemory").value } };
  renderOralFocusQuestion(); $("oralFocusReference").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function saveOralFocusProgress() {
  const item = state.oralFocusItem; if (!item) return;
  window.clearTimeout(state.oralFocusSaveTimer); state.oralFocusSaveTimer = null;
  const answer = $("oralFocusAnswer").value; const memoryNote = $("oralFocusMemory").value; const mastery = item.progress?.mastery || "unseen";
  $("oralFocusSaved").textContent = "保存中…";
  try {
    const response = await fetch("/api/oral-focus/progress", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item_id: item.id, answer, memory_note: memoryNote, mastery }) });
    if (!response.ok) throw new Error("save failed");
    const result = await response.json(); item.progress = result.progress;
    const directoryItem = (state.oralFocus?.subjects || []).flatMap((subject) => subject.chapters || []).flatMap((chapter) => chapter.items || []).find((entry) => entry.id === item.id);
    if (directoryItem) directoryItem.mastery = mastery;
    $("oralFocusSaved").textContent = result.saved ? "已自动保存" : "输入后自动保存";
  } catch { $("oralFocusSaved").textContent = "保存失败，请稍后重试"; }
}

function scheduleOralFocusSave() {
  if (!state.oralFocusItem) return;
  state.oralFocusItem.progress.answer = $("oralFocusAnswer").value;
  state.oralFocusItem.progress.memory_note = $("oralFocusMemory").value;
  $("oralFocusSaved").textContent = "保存中…"; window.clearTimeout(state.oralFocusSaveTimer);
  state.oralFocusSaveTimer = window.setTimeout(saveOralFocusProgress, 420);
}

async function navigateOralFocus(step) {
  const index = state.oralFocusFlatItems.findIndex((entry) => entry.id === state.oralFocusItem?.id);
  const target = state.oralFocusFlatItems[index + step]; if (!target) return;
  await saveOralFocusProgress(); openOralFocusItem(target.id);
}

function searchableBook(book) {
  return `${book.title} ${book.id} ${bookToc(book).map((chapter) => `${chapter.title} ${chapter.sections.map((section) => section.title).join(" ")}`).join(" ")}`.toLowerCase();
}

function englishShelfBooks() {
  return state.books.filter((book) => {
    if ((book.domain || "medicine") !== "english") return false;
    // Translation/writing reference pages belong to the year-specific true-paper
    // companion, not to the method-and-vocabulary shelf.
    return !/subjective|翻译与写作/i.test(`${book.id} ${book.title} ${book.resource_type || ""}`);
  });
}

function domainBooks() {
  if (state.libraryDomain === "english") return englishShelfBooks();
  return state.books.filter((book) => (book.domain || "medicine") === state.libraryDomain);
}

function renderDomainTabs() {
  document.querySelectorAll("[data-shelf]").forEach((button) => {
    const shelf = button.dataset.shelf;
    const active = shelf === state.libraryDomain;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function englishPanel(mode = "") {
  const isExams = mode === "exams"; const isExamOverview = mode === "exam-overview";
  $("englishExams")?.classList.toggle("hidden", !isExams);
  $("englishExamOverview")?.classList.toggle("hidden", !isExamOverview);
  $("bookTree")?.classList.toggle("hidden", isExams || isExamOverview);
  document.querySelector(".learning-center-header")?.classList.toggle("hidden", isExams || isExamOverview);
}

function renderEnglishExams() {
  englishPanel("exams");
  const banks = state.questionBanks.filter((bank) => bank.domain === "english").sort((a, b) => b.title.localeCompare(a.title, "zh-CN"));
  const bankRows = banks.map((bank) => {
    const knowledgeId = bank.knowledge_ids?.find((id) => /^english\.exam\.\d{4}\.e\d+$/.test(id)) || "";
    const track = /(?:英语\s*[（(]?二|e2(?:-|$)|英语二)/i.test(`${bank.subject || ""} ${bank.id}`) ? "考研英语二" : "考研英语一";
    return `<button class="english-exam-row" type="button" data-bank="${escapeHtml(bank.id)}" data-knowledge="${escapeHtml(knowledgeId)}" data-count="${bank.question_count}"><span><small>${track}</small><strong>${escapeHtml(bank.title)}</strong></span><span><small>客观题</small><strong>${bank.question_count} 题</strong></span><i data-lucide="arrow-right"></i></button>`;
  }).join("");
  $("englishExamList").innerHTML = bankRows || `<div class="english-archive-empty">还没有通过验证的真题包。</div>`;
  $("englishExamList").querySelectorAll("[data-bank]").forEach((button) => button.addEventListener("click", () => openEnglishExamOverview(button.dataset.bank)));
  refreshIcons();
}

function englishPaperSubjectiveRows(subjective) {
  if (!subjective?.available) return `<div class="english-paper-row unavailable"><span class="english-paper-row-index">—</span><span class="english-paper-row-copy"><small>SECTION III / IV</small><strong>翻译与写作</strong><em>原卷包含主观题，但对应资料尚未发布</em></span><span class="english-paper-row-status"><strong>待补充</strong></span><i data-lucide="clock-3"></i></div>`;
  return (subjective.sections || []).map((item, index) => `<button class="english-paper-row" type="button" data-paper-resource="${escapeHtml(item.book_id)}" data-paper-resource-section="${escapeHtml(item.section_id)}"><span class="english-paper-row-index">${String(index + 7).padStart(2, "0")}</span><span class="english-paper-row-copy"><small>SECTION III / IV</small><strong>${escapeHtml(item.title)}</strong><em>${escapeHtml(item.range)} · 独立作答，支持侧边栏批改</em></span><span class="english-paper-row-status"><strong>进入练习</strong></span><i data-lucide="arrow-up-right"></i></button>`).join("");
}

function renderEnglishExamOverview() {
  englishPanel("exam-overview");
  const payload = state.englishExamOverview;
  const bank = payload?.bank || state.questionBanks.find((item) => item.id === state.englishExamOverviewBankId);
  if (!payload || !bank) {
    $("englishExamOverviewTitle").textContent = "正在读取试卷…";
    $("englishExamOverviewMeta").textContent = "正在整理题型与文章顺序。";
    $("englishExamOverviewFacts").innerHTML = "";
    $("englishExamOverviewSections").innerHTML = `<div class="english-archive-empty">正在读取这套真题的结构…</div>`;
    $("englishExamOverviewCompanion").innerHTML = "";
    $("englishExamOverviewCompanion").classList.add("hidden");
    refreshIcons();
    return;
  }
  const groups = payload.groups || [];
  const catalogBank = state.questionBanks.find((item) => item.id === bank.id) || bank;
  const subjective = payload.subjective || { available: false, sections: [], question_count: 0, range: "" };
  const coverage = bank.coverage || catalogBank.coverage || {};
  const subjectiveLabel = String(subjective.range || coverage.subjective_questions || "46–52").replace(/retained outside objective bank/i, "").trim() || "46–52";
  const track = /(?:英语\s*[（(]?二|e2(?:-|$)|英语二)/i.test(`${bank.subject || ""} ${bank.id}`) ? "考研英语二" : "考研英语一";
  const trackCode = track.endsWith("二") ? "ENGLISH II" : "ENGLISH I";
  $("englishExamOverviewEyebrow").textContent = `${String(bank.title || "").match(/\d{4}/)?.[0] || "PAST PAPER"} · ${trackCode}`;
  $("englishExamOverviewTitle").textContent = bank.title || `${track}真题`;
  $("englishExamOverviewMeta").textContent = `按原试卷顺序组织：客观题逐题作答。${subjective.available ? "翻译与写作进入独立主观题练习。" : "主观题资料尚未发布。"}`;
  $("englishExamOverviewFacts").innerHTML = `<div><span>客观题</span><strong>${formatInteger(payload.question_count)} 题</strong><em>第 1–45 题</em></div><div><span>主观题</span><strong>${formatInteger(subjective.question_count || 0)} 题</strong><em>第 ${escapeHtml(subjectiveLabel.replace(/.*?(\d+[-–]\d+).*/, "$1"))} 题</em></div><div><span>客观题型</span><strong>${groups.length} 组</strong><em>完形、阅读与新题型</em></div><div><span>完成进度</span><strong>${formatInteger(payload.answered_count)} / ${formatInteger(payload.question_count)}</strong><em>按已提交题目计算</em></div>`;
  const objectiveRows = groups.map((group, index) => {
    const range = group.start_number === group.end_number ? `第 ${group.start_number} 题` : `第 ${group.start_number}–${group.end_number} 题`;
    const passage = group.paragraph_count ? ` · 原文 ${group.paragraph_count} 段` : "";
    const completed = `${group.answered_count}/${group.question_count} 已答`;
    const knowledgeId = group.knowledge_id || catalogBank.knowledge_ids?.find((id) => /^english\.exam\.\d{4}\.e\d+$/.test(id)) || "";
    return `<button class="english-paper-row" type="button" data-paper-start="${group.start_index}" data-paper-bank="${escapeHtml(bank.id)}" data-paper-knowledge="${escapeHtml(knowledgeId)}"><span class="english-paper-row-index">${String(index + 1).padStart(2, "0")}</span><span class="english-paper-row-copy"><small>${escapeHtml(group.part)}</small><strong>${escapeHtml(group.label)}</strong><em>${range} · ${formatInteger(group.question_count)} 题${passage}</em></span><span class="english-paper-row-status"><small>${completed}</small><strong>进入答题</strong></span><i data-lucide="arrow-right"></i></button>`;
  }).join("");
  $("englishExamOverviewProgress").textContent = `${formatInteger(payload.answered_count)} / ${formatInteger(payload.question_count)} 题已答`;
  $("englishExamOverviewSections").innerHTML = objectiveRows || `<div class="english-archive-empty">暂无可用的客观题分组。</div>`;
  $("englishExamOverviewCompanion").classList.remove("hidden");
  $("englishExamOverviewCompanion").innerHTML = `<header><div><p class="eyebrow">SECTION III / IV</p><h4>翻译与写作</h4></div><span>${subjective.available ? "主观题练习" : "原卷题型"}</span></header><div class="english-paper-companion-list">${englishPaperSubjectiveRows(subjective)}</div>`;
  $("englishExamOverviewSections").querySelectorAll("[data-paper-start]").forEach((button) => button.addEventListener("click", () => {
    const startIndex = Number(button.dataset.paperStart || 0); const group = groups.find((item) => Number(item.start_index) === startIndex);
    openPractice({ bank_id: button.dataset.paperBank, knowledge_id: button.dataset.paperKnowledge, match_level: "comprehensive", question_count: Number(group?.question_count || 0), label: group?.label || "" }, "english-exam-overview", startIndex);
  }));
  $("englishExamOverviewCompanion").querySelectorAll("[data-paper-resource]").forEach((button) => button.addEventListener("click", () => { state.subjectiveReturn = "exam-overview"; openSubjectivePractice(button.dataset.paperResource, button.dataset.paperResourceSection); }));
  refreshIcons();
}

async function openEnglishExamOverview(bankId) {
  if (!bankId) return;
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden");
  state.englishExamOverview = null; state.englishExamOverviewBankId = bankId; state.resourceBookId = null; state.resource = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden");
  setActiveView("library"); renderEnglishExamOverview(); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const response = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(bankId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("overview unavailable");
    const payload = await response.json();
    if (state.englishExamOverviewBankId !== bankId) return;
    state.englishExamOverview = payload; renderEnglishExamOverview();
  } catch {
    if (state.englishExamOverviewBankId !== bankId) return;
    $("englishExamOverviewTitle").textContent = "暂时无法读取试卷";
    $("englishExamOverviewMeta").textContent = "请确认题库通过验证且本地服务正在运行。";
    $("englishExamOverviewSections").innerHTML = `<div class="english-archive-empty">这套真题暂时不可用。</div>`;
    refreshIcons();
  }
}

function sectionEntryHtml(section) {
  return `<button class="reader-section-entry ${section.id === state.current?.id ? "active" : ""}" type="button" data-section-id="${escapeHtml(section.id)}"><span>${String(section.section_order || 1).padStart(2, "0")}</span><span><strong>${escapeHtml(section.title)}</strong><small>${formatCharacters(section.character_count) || "阅读小节"}</small></span><i data-lucide="arrow-up-right"></i></button>`;
}

function chapterListHtml(book, chapters, { openAll = false } = {}) {
  return `<div class="reader-chapter-list">${chapters.map((chapter) => {
    const chapterOpen = openAll ? true : (chapter.id === state.current?.chapter_id || chapter.order === 1);
    return `<details class="reader-chapter-group" data-chapter-id="${escapeHtml(chapter.id)}" ${chapterOpen ? "open" : ""}>
      <summary><span>${String(chapter.order).padStart(2, "0")}</span><strong>${escapeHtml(chapter.title)}</strong><em>${chapter.sections.length} 节</em><i data-lucide="chevron-right"></i></summary>
      <div class="reader-section-list">${chapter.sections.map((section) => sectionEntryHtml(section)).join("")}</div>
    </details>`;
  }).join("")}</div>`;
}

const LEARNING_CENTER_COPY = {
  medicine: ["医学", "教材、名词解释与论述。"],
  politics: ["政治", "五科讲义、基础训练与拔高训练。"],
  english: ["英语", "方法资料、历年真题与翻译写作。"],
};

const POLITICS_SUBJECTS = [
  ["marxism", "马原"], ["mao", "毛中特"], ["xi", "习思想"], ["modern-history", "史纲"], ["ethics-law", "思法"],
];

function learningRailSize() {
  if (window.innerWidth <= 680) return 2;
  if (window.innerWidth <= 960) return 3;
  return 5;
}

function recentFirstBooks(books, domain) {
  const recent = (state.stats?.recent_resources || []).filter((entry) => entry.domain === domain).map((entry) => entry.resource_id);
  const rank = new Map(recent.map((id, index) => [id, index]));
  return [...books].sort((a, b) => {
    const aRank = rank.has(a.id) ? rank.get(a.id) : Number.MAX_SAFE_INTEGER;
    const bRank = rank.has(b.id) ? rank.get(b.id) : Number.MAX_SAFE_INTEGER;
    return aRank - bRank;
  });
}

function learningSectionHeader(index, title, meta, railId = "") {
  return `<header class="learning-section-heading"><div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(meta)}</p></div>${railId ? `<nav aria-label="${escapeHtml(title)}翻页"><small data-rail-position="${escapeHtml(railId)}"></small><button type="button" data-rail-move="${escapeHtml(railId)}:-1" aria-label="上一组"><i data-lucide="arrow-left"></i></button><button type="button" data-rail-move="${escapeHtml(railId)}:1" aria-label="下一组"><i data-lucide="arrow-right"></i></button></nav>` : ""}</header>`;
}

function learningBookCard(book, recentId = "") {
  return `<button class="learning-book-card${book.id === recentId ? " recent" : ""}" type="button" data-library-book="${escapeHtml(book.id)}" aria-label="打开《${escapeHtml(book.title)}》"><span class="reader-book-cover" aria-hidden="true"><strong>${bookCoverTitle(book)}</strong></span><span><strong>${escapeHtml(book.title)}</strong><small>${escapeHtml(book.subject || book.resource_type_label || "学习资料")}</small></span></button>`;
}

function learningRailHtml(railId, items, renderItem) {
  const size = learningRailSize(); const pageCount = Math.max(1, Math.ceil(items.length / size));
  const page = Math.min(pageCount - 1, Math.max(0, Number(state.libraryRailPages[railId] || 0)));
  state.libraryRailPages[railId] = page;
  const visible = items.slice(page * size, page * size + size);
  return `<div class="learning-rail" data-learning-rail="${escapeHtml(railId)}" style="--learning-rail-count:${Math.max(1, Math.min(size, visible.length))}">${visible.map(renderItem).join("") || `<div class="learning-empty"><strong>资料尚未导入</strong><span>板块会保留在这里，导入后自动出现。</span></div>`}</div><span class="hidden" data-rail-pages="${escapeHtml(railId)}" data-page="${page}" data-page-count="${pageCount}"></span>`;
}

function oralFocusSubjectCards(type) {
  return (state.oralFocus?.subjects || []).map((subject) => {
    const count = (subject.chapters || []).flatMap((chapter) => chapter.items || []).filter((item) => item.type === type).length;
    return { ...subject, focus_type: type, focus_count: count };
  }).filter((subject) => subject.focus_count);
}

function oralFocusCard(subject) {
  const label = subject.focus_type === "definition" ? "名解" : "论述";
  return `<button class="learning-book-card learning-focus-card" type="button" data-oral-subject="${escapeHtml(subject.id)}" data-oral-type="${escapeHtml(subject.focus_type)}" aria-label="打开${escapeHtml(subject.short_title)}${label}"><span class="reader-book-cover" aria-hidden="true"><small>${escapeHtml(subject.short_title)}</small><strong>${label}</strong></span><span><strong>${escapeHtml(subject.short_title)}${subject.focus_type === "definition" ? "名词解释" : "论述题"}</strong><small>${formatInteger(subject.focus_count)} 题 · 一页一道题</small></span></button>`;
}

function renderMedicineCenter() {
  const books = recentFirstBooks(domainBooks(), "medicine"); const recentId = books[0]?.id || "";
  const definitions = oralFocusSubjectCards("definition"); const essays = oralFocusSubjectCards("essay");
  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", `${books.length} 本口腔教材 · 最近阅读自动置前`, "medicine-books")}${learningRailHtml("medicine-books", books, (book) => learningBookCard(book, recentId))}</section>
    <section class="learning-center-section">${learningSectionHeader(2, "名词解释", state.oralFocus?.available ? "按原始资料分为五本，进入后逐题闭卷背诵" : "资料入口已保留，等待本地重点资料", "medicine-definitions")}${learningRailHtml("medicine-definitions", definitions, oralFocusCard)}</section>
    <section class="learning-center-section">${learningSectionHeader(3, "论述", state.oralFocus?.available ? "保留口外、口组、牙体、牙周与修复的来源边界" : "资料入口已保留，等待本地重点资料", "medicine-essays")}${learningRailHtml("medicine-essays", essays, oralFocusCard)}</section>`;
}

function politicsPracticeSection(index, bankId, title, description, tone) {
  const bank = state.questionBanks.find((entry) => entry.id === bankId);
  if (!bank) return `<section class="learning-center-section">${learningSectionHeader(index, title, description)}<div class="learning-empty"><strong>题库尚未导入</strong><span>通过验证后会在这里显示，不会静默消失。</span></div></section>`;
  const subjectButtons = POLITICS_SUBJECTS.map(([key, label]) => {
    const prefix = `politics.${key}.`;
    const matcher = tone === "advanced" ? ".test-" : ".ch";
    const knowledgeId = (bank.knowledge_ids || []).find((id) => id.startsWith(prefix) && id.includes(matcher)) || "";
    const units = (bank.knowledge_ids || []).filter((id) => id.startsWith(prefix) && id.includes(matcher)).length;
    return `<button type="button" ${knowledgeId ? `data-politics-bank="${escapeHtml(bank.id)}" data-politics-knowledge="${escapeHtml(knowledgeId)}" data-politics-level="${tone === "advanced" ? "comprehensive" : "chapter"}"` : "disabled"}><span><strong>${label}</strong><small>${units ? `${units} 个训练单元` : "暂无匹配题组"}</small></span><i data-lucide="arrow-up-right"></i></button>`;
  }).join("");
  return `<section class="learning-center-section learning-practice-section ${tone}">${learningSectionHeader(index, title, `${formatInteger(bank.question_count)} 道正式题 · ${description}${tone === "advanced" ? ` · ${formatInteger(bank.test_count || 0)} 组综合测试` : ""}`)}<div class="learning-subject-actions">${subjectButtons}</div></section>`;
}

function renderPoliticsCenter() {
  const books = recentFirstBooks(domainBooks(), "politics"); const recentId = books[0]?.id || "";
  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", "五科基础讲义 · 最近阅读自动置前", "politics-books")}${learningRailHtml("politics-books", books, (book) => learningBookCard(book, recentId))}</section>
    ${politicsPracticeSection(2, "politics-basic-bank", "优题库基础篇", "建立章节级选择题基础", "basic")}
    ${politicsPracticeSection(3, "politics-advanced-bank", "优题库拔高篇", "按真实综合测试分组训练", "advanced")}`;
}

function englishBankInfo(bank) {
  const year = Number(String(`${bank.id} ${bank.title}`).match(/20\d{2}/)?.[0] || 0);
  const paper = /(?:英语\s*[（(]?二|e2(?:-|$)|英语二)/i.test(`${bank.subject || ""} ${bank.id}`) ? 2 : 1;
  return { bank, year, paper };
}

function selectedEnglishBank() {
  const candidates = state.questionBanks.map(englishBankInfo).filter((entry) => entry.bank.domain === "english" && entry.paper === state.englishCenterTrack).sort((a, b) => b.year - a.year);
  if (!candidates.length) return null;
  if (!candidates.some((entry) => entry.year === Number(state.englishCenterYear))) state.englishCenterYear = String(candidates[0].year);
  return candidates.find((entry) => entry.year === Number(state.englishCenterYear)) || candidates[0];
}

function englishSelectionHtml(selected) {
  const years = state.questionBanks.map(englishBankInfo).filter((entry) => entry.bank.domain === "english" && entry.paper === state.englishCenterTrack && entry.year).sort((a, b) => b.year - a.year);
  return `<div class="english-center-filters"><div role="group" aria-label="英语试卷类型"><button type="button" data-english-track="1" class="${state.englishCenterTrack === 1 ? "active" : ""}">英语一</button><button type="button" data-english-track="2" class="${state.englishCenterTrack === 2 ? "active" : ""}">英语二</button></div><label><span>年份</span><select id="englishCenterYear" aria-label="选择真题年份">${years.map((entry) => `<option value="${entry.year}" ${entry.year === selected?.year ? "selected" : ""}>${entry.year}</option>`).join("")}</select></label></div>`;
}

function renderEnglishCenter() {
  const books = recentFirstBooks(englishShelfBooks(), "english"); const recentId = books[0]?.id || ""; const selected = selectedEnglishBank();
  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", `${books.length} 本方法、阅读与词汇资料 · 最近阅读自动置前`, "english-books")}${learningRailHtml("english-books", books, (book) => learningBookCard(book, recentId))}</section>
    <section class="learning-center-section english-training-section">${learningSectionHeader(2, "真题训练", "完形、阅读与新题型统一按年份快速进入")}${englishSelectionHtml(selected)}<div class="english-type-tabs" role="group" aria-label="客观题型"><button type="button" data-english-type="cloze" class="${state.englishCenterType === "cloze" ? "active" : ""}">完形填空</button><button type="button" data-english-type="reading" class="${state.englishCenterType === "reading" ? "active" : ""}">阅读理解</button><button type="button" data-english-type="new" class="${state.englishCenterType === "new" ? "active" : ""}">新题型</button></div><div class="english-center-groups" id="englishCenterObjectiveGroups"><div class="learning-loading">正在读取${selected?.year || ""}年题型…</div></div></section>
    <section class="learning-center-section english-writing-section">${learningSectionHeader(3, "翻译与写作", "与客观题拆分，独立作答后再查看参考解析")}<div class="english-center-groups subjective" id="englishCenterSubjectiveGroups"><div class="learning-loading">正在读取翻译与写作资料…</div></div></section>`;
}

function renderLearningCenterOverview(payload, bankInfo) {
  const objective = $("englishCenterObjectiveGroups"); const subjective = $("englishCenterSubjectiveGroups");
  if (!objective || !subjective || state.libraryDomain !== "english" || selectedEnglishBank()?.bank.id !== bankInfo.bank.id) return;
  const groups = (payload.groups || []).filter((group) => {
    const start = Number(group.start_number || 0);
    return state.englishCenterType === "cloze" ? start <= 20 : state.englishCenterType === "reading" ? start >= 21 && start <= 40 : start >= 41;
  });
  objective.innerHTML = groups.length ? groups.map((group) => `<button type="button" data-english-objective-bank="${escapeHtml(bankInfo.bank.id)}" data-english-objective-knowledge="${escapeHtml(group.knowledge_id || "")}" data-english-objective-start="${Number(group.start_index || 0)}"><span><small>${escapeHtml(group.part || "真题训练")}</small><strong>${escapeHtml(group.label)}</strong><em>第 ${group.start_number}–${group.end_number} 题 · ${group.answered_count || 0}/${group.question_count} 已答</em></span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="learning-empty"><strong>该题型暂无可用分组</strong><span>原始试卷结构仍保留，不会使用其他题型替代。</span></div>`;
  const subjectiveItems = payload.subjective?.sections || [];
  subjective.innerHTML = subjectiveItems.length ? subjectiveItems.map((item) => `<button type="button" data-english-subjective-book="${escapeHtml(item.book_id)}" data-english-subjective-section="${escapeHtml(item.section_id)}" data-english-subjective-bank="${escapeHtml(bankInfo.bank.id)}"><span><small>${bankInfo.year} · ENGLISH ${bankInfo.paper === 2 ? "II" : "I"}</small><strong>${escapeHtml(item.title)}</strong><em>${escapeHtml(item.range || "独立作答")}</em></span><i data-lucide="arrow-up-right"></i></button>`).join("") : `<div class="learning-empty"><strong>这个年份暂无独立主观题资料</strong><span>不会把整套试卷参考页误当作翻译或作文解析。</span></div>`;
  bindEnglishCenterGroups(); refreshIcons();
}

async function loadEnglishCenterOverview() {
  const selected = selectedEnglishBank(); if (!selected) return;
  try {
    let payload = state.englishCenterOverviewCache.get(selected.bank.id);
    if (!payload) {
      const response = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(selected.bank.id)}`, { cache: "no-store" });
      if (!response.ok) throw new Error("overview unavailable");
      payload = await response.json(); state.englishCenterOverviewCache.set(selected.bank.id, payload);
    }
    renderLearningCenterOverview(payload, selected);
  } catch {
    const objective = $("englishCenterObjectiveGroups"); const subjective = $("englishCenterSubjectiveGroups");
    if (objective) objective.innerHTML = `<div class="learning-empty"><strong>暂时无法读取真题结构</strong><span>请确认本地题库可用后重试。</span></div>`;
    if (subjective) subjective.innerHTML = `<div class="learning-empty"><strong>暂时无法读取主观题资料</strong><span>已有作答和历史资料不会受到影响。</span></div>`;
  }
}

function bindEnglishCenterGroups() {
  $("bookTree").querySelectorAll("[data-english-objective-bank]").forEach((button) => button.addEventListener("click", () => openPractice({ bank_id: button.dataset.englishObjectiveBank, knowledge_id: button.dataset.englishObjectiveKnowledge, match_level: "comprehensive" }, "learning-center", Number(button.dataset.englishObjectiveStart || 0))));
  $("bookTree").querySelectorAll("[data-english-subjective-section]").forEach((button) => button.addEventListener("click", () => { state.subjectiveReturn = "learning-center"; state.englishExamOverviewBankId = button.dataset.englishSubjectiveBank; openSubjectivePractice(button.dataset.englishSubjectiveBook, button.dataset.englishSubjectiveSection); }));
}

function bindLearningCenter() {
  const tree = $("bookTree");
  tree.querySelectorAll("[data-library-book]").forEach((button) => {
    button.addEventListener("click", () => openResource(button.dataset.libraryBook));
    button.addEventListener("pointerenter", () => prefetchResource(button.dataset.libraryBook), { once: true });
    button.addEventListener("focus", () => prefetchResource(button.dataset.libraryBook), { once: true });
  });
  tree.querySelectorAll("[data-oral-subject]").forEach((button) => button.addEventListener("click", () => openOralFocusIndex(button.dataset.oralSubject, button.dataset.oralType)));
  tree.querySelectorAll("[data-rail-move]").forEach((button) => button.addEventListener("click", () => {
    const [railId, step] = button.dataset.railMove.split(":"); const marker = tree.querySelector(`[data-rail-pages="${railId}"]`);
    const pageCount = Number(marker?.dataset.pageCount || 1); const page = Number(marker?.dataset.page || 0);
    state.libraryRailPages[railId] = (page + Number(step) + pageCount) % pageCount; renderBooks();
  }));
  tree.querySelectorAll("[data-rail-pages]").forEach((marker) => {
    const label = tree.querySelector(`[data-rail-position="${marker.dataset.railPages}"]`);
    if (label) {
      const pageCount = Number(marker.dataset.pageCount || 1);
      label.textContent = `${Number(marker.dataset.page || 0) + 1} / ${pageCount}`;
      label.closest("nav")?.classList.toggle("single-page", pageCount <= 1);
    }
  });
  tree.querySelectorAll("[data-politics-bank]").forEach((button) => button.addEventListener("click", () => openPractice({ bank_id: button.dataset.politicsBank, knowledge_id: button.dataset.politicsKnowledge, match_level: button.dataset.politicsLevel }, "learning-center")));
  tree.querySelectorAll("[data-english-track]").forEach((button) => button.addEventListener("click", () => { state.englishCenterTrack = Number(button.dataset.englishTrack); state.englishCenterYear = ""; renderBooks(); }));
  $("englishCenterYear")?.addEventListener("change", (event) => { state.englishCenterYear = event.target.value; renderBooks(); });
  tree.querySelectorAll("[data-english-type]").forEach((button) => button.addEventListener("click", () => { state.englishCenterType = button.dataset.englishType; renderBooks(); }));
  bindEnglishCenterGroups();
}

function renderBooks() {
  renderDomainTabs(); englishPanel("");
  const copy = LEARNING_CENTER_COPY[state.libraryDomain] || LEARNING_CENTER_COPY.medicine;
  $("learningCenterTitle").textContent = copy[0]; $("learningCenterDescription").textContent = copy[1];
  const tree = $("bookTree"); tree.classList.remove("hidden");
  tree.innerHTML = state.libraryDomain === "politics" ? renderPoliticsCenter() : state.libraryDomain === "english" ? renderEnglishCenter() : renderMedicineCenter();
  bindLearningCenter(); refreshIcons();
  if (state.libraryDomain === "english") loadEnglishCenterOverview();
}

function renderResource() {
  const payload = state.resource; const book = payload?.book; const summary = payload?.summary || {};
  if (!book) return;
  $("resourcePanel").classList.remove("is-loading");
  $("resourceStatus").classList.add("hidden"); $("resourceStatus").textContent = "";
  $("resourceProgressTrack").classList.remove("is-loading");
  $("resourceDomainLabel").textContent = `${book.domain_label || DOMAIN_LABELS[book.domain] || "医学"} · ${book.resource_type_label || book.resource_type || "教材"}`;
  $("resourceTitle").textContent = book.title;
  $("resourceMeta").textContent = `${book.edition ? `${book.edition} · ` : ""}${book.subject}`;
  const lastSection = summary.last_section;
  const progress = Number(summary.progress || 0);
  const progressText = `${progress.toFixed(progress % 1 ? 1 : 0)}%`;
  $("resourceProgressBar").style.width = `${Math.min(100, Math.max(0, progress))}%`;
  $("resourceProgressTrack").title = `阅读进度 ${progressText}（已学习小节 / 全部小节）`;
  $("resourceContinueTitle").textContent = lastSection ? `${lastSection.title} · ${lastSection.chapter_title}` : `从 ${book.sections[0] ? book.sections[0].title : "第一章"} 开始阅读`;
  $("resourceContinue").dataset.sectionId = lastSection?.id || book.sections[0]?.id || "";
  const chapters = bookToc(book).filter((chapter) => chapter.sections.length);
  $("resourceDirectory").innerHTML = `<section class="reader-directory resource-directory-list">${chapterListHtml(book, chapters)}</section>`;
  $("resourceDirectory").querySelectorAll("[data-section-id]").forEach((button) => button.addEventListener("click", () => { state.readerOriginBookId = state.resourceBookId; openSection(button.dataset.sectionId); }));
  refreshIcons();
}

function renderResourceLoading(book) {
  state.resource = { book, summary: {} };
  renderResource();
  $("resourcePanel").classList.add("is-loading");
  $("resourceProgressTrack").classList.add("is-loading");
  $("resourceProgressTrack").title = "正在读取本地学习记录";
}

function fetchResource(bookId, force = false) {
  const cached = state.resourceCache.get(bookId);
  if (!force && cached && Date.now() - cached.fetchedAt < 15000) return Promise.resolve(cached.payload);
  if (state.resourceLoads.has(bookId)) return state.resourceLoads.get(bookId);
  const request = fetch(`/api/resource/${encodeURIComponent(bookId)}`, { cache: "no-store" })
    .then((response) => { if (!response.ok) throw new Error("resource unavailable"); return response.json(); })
    .then((payload) => { state.resourceCache.set(bookId, { payload, fetchedAt: Date.now() }); return payload; })
    .finally(() => state.resourceLoads.delete(bookId));
  state.resourceLoads.set(bookId, request);
  return request;
}

function prefetchResource(bookId) {
  if (!bookId || state.resourceCache.has(bookId)) return;
  fetchResource(bookId).catch(() => {});
}

async function openResource(bookId) {
  if (!bookId) return;
  state.openRequest += 1; stopReadingTimer(); closeNotePopover();
  const book = state.books.find((item) => item.id === bookId);
  if (!book) return;
  const cached = state.resourceCache.get(bookId);
  if (cached) { state.resource = cached.payload; renderResource(); }
  else renderResourceLoading(book);
  $("libraryWorkspace").classList.remove("reader-open");
  $("libraryWorkspace").classList.add("resource-open");
  $("readerContent").classList.add("hidden");
  $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library");
  state.resourceBookId = bookId;
  try {
    const payload = await fetchResource(bookId);
    if (state.resourceBookId !== bookId) return;
    state.resource = payload; renderResource(); loadResourcePractice(bookId);
  } catch {
    if (state.resourceBookId !== bookId) return;
    if (cached) { state.resource = cached.payload; renderResource(); }
    else {
      $("resourcePanel").classList.remove("is-loading"); $("resourceProgressTrack").classList.remove("is-loading");
      $("resourceStatus").classList.remove("hidden"); $("resourceStatus").textContent = "暂时无法读取这份资料，请确认本地服务正在运行。";
    }
  }
  renderBooks(); window.scrollTo({ top: 0, behavior: "auto" });
}

async function openResourceSection(bookId, sectionId) {
  if (!bookId || !sectionId) return;
  await openResource(bookId);
  if (state.resourceBookId !== bookId) return;
  const book = state.books.find((item) => item.id === bookId);
  if (!book?.sections?.some((section) => section.id === sectionId)) return;
  state.readerOriginBookId = bookId;
  await openSection(sectionId);
}

function subjectiveModeCopy(mode, prompt = "") {
  if (mode === "translation") return { label: "翻译练习", answerLabel: "我的译文", hint: "按题号完成目标句，再对照参考解析", placeholder: "按题号输入译文，例如：46. ……", icon: "languages" };
  if (mode === "writing-a") return { label: "应用文写作", answerLabel: "我的作文", hint: "先确认写作对象与任务，再完成一稿", placeholder: "在这里完成应用文（书信、通知或邮件）", icon: "mail-pen" };
  if (mode === "writing-b") return { label: "图画 / 图表写作", answerLabel: "我的作文", hint: "先描述材料，再解释寓意并给出评论", placeholder: "在这里完成图画或图表作文", icon: "chart-no-axes-combined" };
  return { label: "翻译与写作", answerLabel: "我的作答", hint: "按原卷顺序完成主观题，可在下方记录修改计划", placeholder: "在这里输入你的作答", icon: "pen-line" };
}

function subjectiveDisplayTitle(value) {
  return String(value || "").replace(/\s*(?:（候选）|\(候选\)|候选包|候选)\s*$/i, "").trim();
}

function subjectiveWordCount(value, mode) {
  const text = String(value || "").trim();
  if (!text) return 0;
  if (mode === "translation") return text.replace(/\s/g, "").length;
  return (text.match(/[A-Za-z]+(?:['’-][A-Za-z]+)*/g) || []).length;
}

function subjectiveWordTarget(payload) {
  const source = String(payload?.prompt_markdown || "");
  if (payload?.mode === "translation") {
    const count = (source.match(/\(\d+\)/g) || []).length;
    return count ? `${count} 个目标句` : "按原题要求完成";
  }
  const range = source.match(/(?:about|around|approximately)\s+(\d+(?:\s*[-–]\s*\d+)?)\s*words?/i) || source.match(/(\d+(?:\s*[-–]\s*\d+)?)\s*words?/i);
  return range ? `原题要求约 ${range[1].replace(/\s+/g, "")} 词` : "按原题字数完成";
}

function renderSubjectiveLoading() {
  $("subjectivePracticeEyebrow").textContent = "主观题练习";
  $("subjectivePracticeTitle").textContent = "正在读取题目…";
  $("subjectivePracticeMeta").textContent = "原题与解析保持独立，作答会自动保存。";
  $("subjectivePromptBody").innerHTML = `<p class="practice-reading-loading">正在读取题目与材料…</p>`;
  $("subjectiveReferencePanel").classList.add("hidden");
  $("subjectiveAnswer").value = ""; $("subjectiveReflection").value = "";
}

function renderSubjectivePractice(payload) {
  const copy = subjectiveModeCopy(payload.mode, payload.prompt_markdown);
  const response = payload.response || {};
  state.subjectivePractice = { ...payload, referenceVisible: false };
  $("subjectivePracticeEyebrow").textContent = `${copy.label} · 原卷主观题`;
  $("subjectivePracticeTitle").textContent = payload.title || copy.label;
  $("subjectivePracticeMeta").textContent = `${payload.subject || "考研英语"} · ${subjectiveDisplayTitle(payload.chapter_title || "主观题")} · ${payload.storage === "obsidian" ? "已连接 Obsidian" : "本机保存"}`;
  $("subjectivePromptMeta").textContent = payload.reference_available ? "原题保持原样 · 参考解析可稍后展开" : "原题保持原样 · 暂无独立参考解析";
  const imageBase = payload.book_id ? `/api/book-assets/${encodeURIComponent(payload.book_id)}/` : "";
  $("subjectivePromptBody").innerHTML = renderMarkdown(payload.prompt_markdown || "暂无题目内容", imageBase);
  $("subjectiveAnswerLabel").textContent = copy.answerLabel;
  $("subjectiveAnswerHint").textContent = copy.hint;
  $("subjectiveAnswer").placeholder = copy.placeholder;
  $("subjectiveAnswer").value = String(response.answer || "");
  $("subjectiveReflection").value = String(response.reflection || "");
  $("subjectiveWordTarget").textContent = subjectiveWordTarget(payload);
  $("subjectivePracticeStatus").textContent = response.answer || response.reflection ? "已载入上次保存" : "输入后自动保存";
  $("subjectivePracticeObsidian").href = payload.obsidian_uri || "obsidian://open";
  $("subjectiveReferenceBody").innerHTML = payload.reference_available ? renderMarkdown(payload.reference_markdown, imageBase) : `<p class="subjective-reference-empty">这个年份的本地资料没有独立的翻译 / 作文解析页。可以直接把题目交给侧边栏 Gemini 批改，结果会保存到本练习记录。</p>`;
  $("subjectiveReferencePanel").classList.add("hidden");
  const reveal = $("subjectiveRevealReference"); reveal.disabled = !payload.reference_available; reveal.innerHTML = `<span>${payload.reference_available ? "查看参考解析" : "暂无独立解析"}</span><i data-lucide="${payload.reference_available ? "arrow-down" : "minus"}"></i>`;
  updateSubjectiveWordCount(); refreshIcons();
}

function updateSubjectiveWordCount() {
  const payload = state.subjectivePractice; if (!payload) return;
  const count = subjectiveWordCount($("subjectiveAnswer").value, payload.mode);
  $("subjectiveWordCount").textContent = payload.mode === "translation" ? `${formatInteger(count)} 字符` : `${formatInteger(count)} 词`;
}

async function openSubjectivePractice(bookId, sectionId) {
  if (!bookId || !sectionId) return;
  const requestId = ++state.openRequest;
  stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden");
  state.practice = null; state.subjectivePractice = null; state.subjectiveSaveTimer = null;
  state.practiceOverviewBankId = state.englishExamOverviewBankId || "";
  $("practiceWorkspace").classList.add("hidden"); $("subjectivePracticeWorkspace").classList.remove("hidden");
  setActiveView("practice"); renderSubjectiveLoading(); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const query = new URLSearchParams({ section_id: sectionId });
    const response = await fetch(`/api/subjective/practice?${query}`, { cache: "no-store" });
    if (!response.ok) throw new Error("subjective unavailable");
    const payload = await response.json();
    if (requestId !== state.openRequest) return;
    startWorkspaceTimer({ activity_type: "subjective_practice", domain: "english", subject_id: payload.subject || payload.book_id, resource_id: payload.book_id, item_id: payload.section_id, resume_target: { view: "subjective_practice", resource_id: payload.book_id, item_id: payload.section_id } });
    renderSubjectivePractice(payload);
  } catch {
    if (requestId !== state.openRequest) return;
    $("subjectivePracticeTitle").textContent = "暂时无法读取主观题";
    $("subjectivePracticeMeta").textContent = "请返回试卷导览后重试。";
    $("subjectivePromptBody").innerHTML = `<p class="practice-reading-empty">这份主观题资料暂时不可用。</p>`;
    showToast("主观题资料读取失败");
  }
}

function returnFromSubjectivePractice() {
  window.clearTimeout(state.subjectiveSaveTimer); state.subjectiveSaveTimer = null;
  state.subjectivePractice = null; $("subjectivePracticeWorkspace").classList.add("hidden"); $("practiceWorkspace").classList.remove("hidden");
  if (state.subjectiveReturn === "learning-center") { state.subjectiveReturn = "exam-overview"; selectLibraryShelf("english"); }
  else if (state.practiceOverviewBankId) openEnglishExamOverview(state.practiceOverviewBankId);
  else setLibraryMode();
}

function toggleSubjectiveReference() {
  const payload = state.subjectivePractice; if (!payload?.reference_available) return;
  payload.referenceVisible = !payload.referenceVisible;
  const panel = $("subjectiveReferencePanel"); panel.classList.toggle("hidden", !payload.referenceVisible);
  const button = $("subjectiveRevealReference"); button.innerHTML = `<span>${payload.referenceVisible ? "收起参考解析" : "查看参考解析"}</span><i data-lucide="${payload.referenceVisible ? "arrow-up" : "arrow-down"}"></i>`;
  if (payload.referenceVisible) window.setTimeout(() => panel.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
  refreshIcons();
}

function scheduleSubjectiveSave() {
  const payload = state.subjectivePractice; if (!payload) return;
  updateSubjectiveWordCount();
  const answer = $("subjectiveAnswer").value; const reflection = $("subjectiveReflection").value;
  $("subjectivePracticeStatus").textContent = "保存中…"; window.clearTimeout(state.subjectiveSaveTimer);
  state.subjectiveSaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/subjective/response", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section_id: payload.section_id, answer, reflection }) });
      if (!response.ok) throw new Error("subjective save failed");
      const result = await response.json(); payload.response = result.response || {}; payload.obsidian_uri = result.obsidian_uri || payload.obsidian_uri;
      $("subjectivePracticeObsidian").href = payload.obsidian_uri || "obsidian://open";
      $("subjectivePracticeStatus").textContent = answer.trim() || reflection.trim() ? (result.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
    } catch { $("subjectivePracticeStatus").textContent = "保存失败，请稍后重试"; }
  }, 420);
}

function returnFromResource() {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover();
  state.resourceBookId = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open");
  $("readerContent").classList.add("hidden");
  $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library"); window.scrollTo({ top: 0, behavior: "auto" });
  renderBooks();
}

function returnFromReader() {
  if (state.readerOriginBookId) openResource(state.readerOriginBookId);
  else setLibraryMode();
}

function renderSectionMenu() {
  const menu = $("readerCrumbMenu"); const book = state.books.find((item) => item.id === state.current?.book_id);
  if (!book) { menu.innerHTML = ""; return; }
  menu.innerHTML = bookToc(book).map((chapter) => `<section><header><span>${String(chapter.order).padStart(2, "0")}</span><strong>${escapeHtml(chapter.title)}</strong></header>${chapter.sections.map((section) => `<button type="button" class="${section.id === state.current.id ? "active" : ""}" data-menu-section="${escapeHtml(section.id)}"><span>${String(section.section_order || 1).padStart(2, "0")} · ${escapeHtml(section.title)}</span><small>${formatCharacters(section.character_count)}</small></button>`).join("")}</section>`).join("");
  menu.querySelectorAll("[data-menu-section]").forEach((button) => button.addEventListener("click", () => { closeSectionMenu(); openSection(button.dataset.menuSection); })); refreshIcons();
}

function setNavigationState() {
  const book = state.books.find((item) => item.id === state.current?.book_id); const index = book?.sections.findIndex((section) => section.id === state.current.id) ?? -1;
  const previous = index > 0; const next = index >= 0 && index < book.sections.length - 1;
  [$("readerPreviousSection"), $("previousSection")].forEach((button) => { if (button) button.disabled = !previous; });
  [$("readerNextSection"), $("nextSectionLink")].forEach((button) => { if (button) button.disabled = !next; });
}

async function openSection(sectionId) {
  const requestId = ++state.openRequest;
  const response = await fetch(`/api/sections/${encodeURIComponent(sectionId)}`, { cache: "no-store" });
  if (requestId !== state.openRequest) return;
  if (!response.ok) { showToast("暂时无法打开这一节"); return; }
  const section = await response.json(); const book = state.books.find((item) => item.sections.some((entry) => entry.id === section.id));
  if (requestId !== state.openRequest) return;
  state.current = { ...section, book_id: book?.id }; state.libraryBookId = book?.id || null; state.sections.set(section.id, state.current); setReaderMode();
  fetch("/api/activity", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section_id: section.id }) }).then(() => loadStats()).catch(() => {});
  const index = book?.sections.findIndex((entry) => entry.id === section.id) ?? 0;
  const chapter = bookToc(book).find((item) => item.id === section.chapter_id); const chapterSectionCount = chapter?.sections.length || 1;
  $("readerBook").textContent = section.book_title; $("readerChapter").textContent = section.chapter_title || "目录"; $("readerTitle").textContent = section.title; $("readerLocation").textContent = section.title; $("readerSectionNumber").textContent = `${String(section.chapter_order || 1).padStart(2, "0")} 章 · ${section.section_order || 1} / ${chapterSectionCount} 节`;
  const materialLabel = section.material_kind === "cleaned" ? "清洗正文" : "原始 Markdown";
  const lengthLabel = formatCharacters(section.character_count); $("readerBookMeta").textContent = `${materialLabel}${lengthLabel ? ` · ${lengthLabel}` : ""}`; $("readerBookMeta").title = section.path || materialLabel; $("readerNoteMeta").textContent = section.note?.trim() ? "已有笔记" : "暂无笔记";
  $("sectionNote").value = section.note || ""; $("noteSavedText").textContent = section.note?.trim() ? "已保存到本节" : "输入后自动保存"; $("openObsidian").href = section.obsidian_uri || "obsidian://open";
  state.material = "cleaned"; closeSectionMenu(); closeNotePopover(); renderSectionMenu(); renderMaterial(); setNavigationState(); renderBooks(); loadSectionPractice(); window.scrollTo({ top: 0, behavior: "smooth" });
}

function practiceEntryLabel(entry) {
  return entry.match_level === "comprehensive" ? "综合测试" : entry.match_level === "chapter" ? "本章练习" : "本节练习";
}

function concisePracticeBankTitle(title) {
  const value = String(title || "").trim();
  if (value.includes("拔高")) return "拔高题库";
  if (value.includes("基础")) return "基础题库";
  return value.replace(/(?:综合测试)?题库$/, "") || "真实题库";
}

async function loadSectionPractice() {
  const button = $("readerPractice"); button.classList.add("hidden"); button.replaceWith(button.cloneNode(true));
  const fresh = $("readerPractice");
  if (!state.current?.book_id || !state.current?.id) return;
  const sectionId = state.current.id;
  try {
    const response = await fetch(`/api/practice/availability?book_id=${encodeURIComponent(state.current.book_id)}&section_id=${encodeURIComponent(state.current.id)}`, { cache: "no-store" });
    if (!response.ok || state.current?.id !== sectionId) return;
    const payload = await response.json(); const entry = payload.entries?.[0];
    if (!entry) return;
    const label = `${practiceEntryLabel(entry)}，${entry.question_count}题`;
    fresh.classList.remove("hidden"); fresh.title = label; fresh.setAttribute("aria-label", label);
    fresh.addEventListener("click", () => openPractice(entry, "reader")); refreshIcons();
  } catch { /* A missing practice package must not disturb reading. */ }
}

async function loadResourcePractice(bookId) {
  const container = $("resourcePractice"); container.classList.add("hidden"); container.innerHTML = "";
  try {
    const response = await fetch(`/api/practice/availability?book_id=${encodeURIComponent(bookId)}`, { cache: "no-store" });
    if (!response.ok || state.resourceBookId !== bookId) return;
    const payload = await response.json(); const entry = payload.entries?.[0];
    if (!entry) return;
    let groups = [];
    if (entry.match_level === "comprehensive") {
      try {
        const overviewResponse = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(entry.bank_id)}`, { cache: "no-store" });
        const overview = overviewResponse.ok ? await overviewResponse.json() : {};
        const subject = state.resource?.book?.subject || state.resource?.book?.title || "";
        groups = (overview.groups || []).filter((group) => group.kind === "objective" && (!subject || String(group.label || "").includes(subject)));
      } catch { groups = []; }
    }
    container.classList.remove("hidden");
    if (groups.length > 1) {
      container.innerHTML = `<div class="resource-practice-list">${groups.map((group, index) => `<button type="button" data-practice-group="${index}"><i data-lucide="circle-dot-dashed"></i><span><strong>${escapeHtml(group.label)}</strong><small>${group.answered_count || 0} / ${group.question_count} 已答</small></span><i data-lucide="arrow-right"></i></button>`).join("")}</div>`;
      container.querySelectorAll("[data-practice-group]").forEach((button) => button.addEventListener("click", () => { const group = groups[Number(button.dataset.practiceGroup)]; openPractice({ ...entry, unit_label: group.label, unit_key: group.key }, "resource"); }));
    } else {
      container.innerHTML = `<button class="resource-continue" type="button"><span><small>真实题库</small><strong>${practiceEntryLabel(entry)} · ${entry.question_count} 题</strong></span><i data-lucide="arrow-right"></i></button>`;
      container.querySelector("button").addEventListener("click", () => openPractice(entry, "resource"));
    }
    refreshIcons();
  } catch { /* The resource page remains usable without a bank. */ }
}

async function openPractice(entry, returnTo, startIndex = 0) {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); state.practiceReturn = returnTo; state.practiceOverviewBankId = returnTo === "english-exam-overview" ? entry.bank_id : ""; state.practiceIndex = Math.max(0, Number(startIndex) || 0);
  state.subjectivePractice = null; $("subjectivePracticeWorkspace")?.classList.add("hidden"); $("practiceWorkspace")?.classList.remove("hidden");
  try {
    const query = new URLSearchParams({ bank_id: entry.bank_id, knowledge_id: entry.knowledge_id, match_level: entry.match_level });
    const response = await fetch(`/api/practice/session?${query}`, { cache: "no-store" }); if (!response.ok) throw new Error("practice unavailable");
    const session = await response.json();
    if (entry.unit_label) {
      const scoped = (session.questions || []).filter((question) => (question.unit_label || question.unit) === entry.unit_label);
      if (scoped.length) { session.questions = scoped; session.question_count = scoped.length; session.answered_count = scoped.filter((question) => question.answered).length; state.practiceIndex = 0; }
    }
    state.practice = { ...session, entry }; setActiveView("practice"); renderPracticeSessionMap(); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
  } catch { showToast("暂时无法读取这组题目"); }
}

function practiceSessionStats() {
  const questions = state.practice?.questions || [];
  const answered = questions.filter((item) => item.answered).length;
  const correct = questions.filter((item) => item.answered && item.correct === true).length;
  const wrong = questions.filter((item) => item.answered && item.correct === false).length;
  return { total: questions.length, answered, correct, wrong, unanswered: Math.max(0, questions.length - answered) };
}

function practiceUnitGroups() {
  const groups = [];
  (state.practice?.questions || []).forEach((question, index) => {
    const label = question.unit_label || question.unit || "本组题目";
    let group = groups[groups.length - 1];
    if (!group || group.label !== label) { group = { label, items: [] }; groups.push(group); }
    group.items.push({ ...question, index });
  });
  return groups;
}

function renderPracticeSessionMap() {
  const map = $("practiceUnitMap"); if (!map || !state.practice) return;
  const stats = practiceSessionStats(); $("practiceSessionState").textContent = `${stats.answered} / ${stats.total} 已答${stats.wrong ? ` · ${stats.wrong} 题待梳理` : ""}`;
  map.innerHTML = practiceUnitGroups().map((group, groupIndex) => {
    const current = group.items.some((item) => item.index === state.practiceIndex);
    const answered = group.items.filter((item) => item.answered).length;
    return `<details class="practice-map-unit" ${current || groupIndex === 0 ? "open" : ""}><summary><span><strong>${escapeHtml(group.label)}</strong><small>${answered} / ${group.items.length} 已答</small></span><i data-lucide="chevron-right"></i></summary><nav>${group.items.map((item) => `<button class="practice-map-number${item.index === state.practiceIndex ? " current" : ""}${item.answered ? (item.correct ? " correct" : " wrong") : ""}" type="button" data-practice-index="${item.index}" aria-label="第 ${escapeHtml(item.local_number || item.index + 1)} 题${item.answered ? (item.correct ? "，已答对" : "，已答错") : "，未作答"}">${escapeHtml(item.local_number || item.index + 1)}</button>`).join("")}</nav></details>`;
  }).join("");
  map.querySelectorAll("[data-practice-index]").forEach((button) => button.addEventListener("click", () => {
    state.practiceIndex = Number(button.dataset.practiceIndex); $("practiceSessionMap").classList.add("hidden"); $("practiceMapToggle").setAttribute("aria-expanded", "false"); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
  }));
  refreshIcons();
}

function togglePracticeSessionMap() {
  const panel = $("practiceSessionMap"); const nextOpen = panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !nextOpen); $("practiceMapToggle").setAttribute("aria-expanded", String(nextOpen));
  $("practiceMapToggle").setAttribute("title", nextOpen ? "收起题组导航" : "打开题组导航");
  if (nextOpen) renderPracticeSessionMap();
}

function finishPracticeSession() {
  if (!state.practice) return;
  const stats = practiceSessionStats(); stopWorkspaceTimer();
  $("practiceSessionMap").classList.add("hidden"); $("practiceMapToggle").setAttribute("aria-expanded", "false");
  $("practiceQuestionSurface").classList.add("hidden"); $("practiceResult").classList.add("hidden"); $("practicePagination").classList.add("hidden"); $("practiceSessionSummary").classList.remove("hidden");
  $("practiceSummaryFacts").innerHTML = `<div><span>已完成</span><strong>${stats.answered}</strong><small>共 ${stats.total} 题</small></div><div><span>回答正确</span><strong>${stats.correct}</strong><small>${stats.answered ? `${Math.round((stats.correct / stats.answered) * 100)}% 正确率` : "尚未作答"}</small></div><div><span>需要梳理</span><strong>${stats.wrong}</strong><small>可直接回到错题</small></div><div><span>未作答</span><strong>${stats.unanswered}</strong><small>下次继续完成</small></div>`;
  $("practiceReviewWrong").classList.toggle("hidden", !stats.wrong); loadStats(); refreshIcons(); window.scrollTo({ top: 0, behavior: "smooth" });
}

function reviewFirstWrongPracticeQuestion() {
  const index = (state.practice?.questions || []).findIndex((item) => item.answered && item.correct === false);
  if (index < 0) return;
  state.practiceIndex = index; $("practiceSessionSummary").classList.add("hidden"); $("practiceQuestionSurface").classList.remove("hidden"); $("practicePagination").classList.remove("hidden"); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
}

function isClozeQuestion(question) {
  return /完形填空/.test(String(question?.unit_label || question?.unit || ""));
}

function practiceWorkflowHint(question) {
  const unit = String(question?.unit_label || question?.unit || "");
  if (/完形填空/.test(unit)) return "点击文章中的空格选择答案";
  if (/Part B/.test(unit)) return "为缺口选择合适段落";
  if (/阅读理解/.test(unit)) return "先读完整文章，再判断题干";
  return "先阅读材料，再作答";
}

function prepareClozeMarkdown(markdown, count = 20) {
  const source = String(markdown || ""); let cursor = 0; let output = "";
  for (let number = 1; number <= count; number += 1) {
    const pattern = new RegExp(`(?<![\\d])${number}(?![\\d])`);
    let match = pattern.exec(source.slice(cursor));
    // A comma is valid punctuation after a blank ("4, you're"), but a
    // thousands separator is not a blank marker ("1,000").
    while (match) {
      const absoluteEnd = cursor + match.index + match[0].length;
      if (!(source[absoluteEnd] === "," && /^\d{3}(?!\d)/.test(source.slice(absoluteEnd + 1)))) break;
      const next = pattern.exec(source.slice(absoluteEnd));
      if (!next) { match = null; break; }
      match = { ...next, index: next.index + absoluteEnd - cursor };
    }
    if (!match) continue;
    const start = cursor + match.index; const end = start + match[0].length;
    output += source.slice(cursor, start) + `YUREADERCLOZE${number}TOKEN`; cursor = end;
  }
  return output + source.slice(cursor);
}

function renderClozeContext(markdown, activeNumber) {
  const html = renderMarkdown(prepareClozeMarkdown(markdown));
  return html.replace(/YUREADERCLOZE(\d+)TOKEN/g, (_, value) => {
    const number = Number(value); const active = number === Number(activeNumber);
    return `<button class="cloze-blank${active ? " active" : ""}" type="button" data-cloze-index="${number}" aria-label="第 ${number} 空">${number}</button>`;
  });
}

function renderClozeChoices(question, attempt = null) {
  const tray = $("practiceClozeChoices"); const cloze = isClozeQuestion(question);
  tray.classList.toggle("hidden", !cloze);
  if (!cloze) { tray.innerHTML = ""; return; }
  const selected = new Set(attempt?.selected_answers || [...$("practiceOptions").querySelectorAll("input:checked")].map((input) => input.value));
  const revealed = Boolean(attempt && Object.keys(attempt).length);
  const correct = new Set(question.correct_answers || []);
  const options = (question.options || []).map((option) => {
    const label = String(option.label || ""); const classes = ["cloze-choice"];
    if (selected.has(label)) classes.push("selected");
    if (revealed && correct.has(label)) classes.push("correct");
    if (revealed && selected.has(label) && !correct.has(label)) classes.push("incorrect");
    return `<button class="${classes.join(" ")}" type="button" data-cloze-answer="${escapeHtml(label)}"${revealed ? " disabled" : ""}><strong>${escapeHtml(label)}</strong><span>${renderMarkdown(option.text_md || "")}</span></button>`;
  }).join("");
  const number = question.local_number || state.practiceIndex + 1;
  tray.innerHTML = `<div class="cloze-choice-head"><strong>第 ${number} 空</strong><span>${revealed ? "已提交，可在下方查看解析" : "点击选项填入这个空"}</span></div><div class="cloze-choice-list">${options}</div>`;
  tray.querySelectorAll("[data-cloze-answer]").forEach((button) => button.addEventListener("click", () => {
    const input = $("practiceOptions").querySelector(`input[value="${button.dataset.clozeAnswer}"]`); if (!input || input.disabled) return;
    input.checked = true; updatePracticeOptionState(); renderClozeChoices(question, null);
  }));
}

function focusClozeBlank(number) {
  const target = state.practice?.questions?.findIndex((item) => Number(item.local_number) === Number(number));
  if (target == null || target < 0) return;
  const focus = () => document.querySelector(`[data-cloze-index="${Number(number)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  if (target === state.practiceIndex) { focus(); return; }
  state.practiceIndex = target; renderPracticeQuestion().then(focus).catch(() => {});
}

function isReadingComprehensionPractice(practice) {
  const entryLabel = String(practice?.entry?.label || practice?.entry?.unit_label || "");
  const first = practice?.questions?.[0] || {};
  const unit = String(first.unit_label || first.unit || "");
  return /阅读理解/.test(`${entryLabel} ${unit}`) && !/完形填空/.test(`${entryLabel} ${unit}`);
}

function readingQuestionType(question) {
  return question?.question_type === "multiple_choice" ? "多项选择" : "单项选择";
}

function readingAnswerStatus(payload) {
  if (!payload?.attempt) return "未作答";
  return payload.attempt.correct ? "已答 · 正确" : "已答 · 待梳理";
}

function updateReadingProgress() {
  const practice = state.practice; if (!practice) return;
  const items = state.practiceReadingItems || [];
  const answered = items.filter((item) => item?.attempt).length;
  const total = items.length || practice.question_count || 0;
  $("practiceProgressText").textContent = `${answered} / ${total} 已答`;
  $("practiceReadingProgress").textContent = `${answered} / ${total} 已答`;
  $("practiceProgressBar").style.setProperty("--practice-progress", `${total ? (answered / total) * 100 : 0}%`);
}

function readingQuestionHtml(payload, index) {
  const question = payload?.question || {};
  const attempt = payload?.attempt;
  const prior = attempt?.selected_answers || [];
  const revealed = Boolean(attempt);
  const inputType = question.question_type === "multiple_choice" ? "checkbox" : "radio";
  const options = (question.options || []).map((option) => {
    const label = String(option.label || "");
    const selected = prior.includes(label);
    const correct = revealed && (question.correct_answers || []).includes(label);
    const incorrect = revealed && selected && !correct;
    return `<label class="practice-option${selected ? " selected" : ""}${correct ? " correct" : ""}${incorrect ? " incorrect" : ""}"><input type="${inputType}" name="reading-answer-${index}" value="${escapeHtml(label)}" ${selected ? "checked" : ""}${revealed ? " disabled" : ""}><strong class="practice-option-label">${escapeHtml(label)}</strong><span class="practice-option-text">${renderMarkdown(option.text_md || "")}</span><span class="practice-option-state" aria-hidden="true">${correct ? '<i data-lucide="check"></i>' : (incorrect ? '<i data-lucide="x"></i>' : "")}</span></label>`;
  }).join("");
  const feedback = revealed ? `<section class="reading-question-feedback" aria-live="polite"><header><span class="practice-result-icon${attempt.correct ? "" : " wrong"}"><i data-lucide="${attempt.correct ? "check" : "x"}"></i></span><div><strong>${attempt.correct ? "回答正确" : "继续梳理这个知识点"}</strong><small>正确答案：${escapeHtml((question.correct_answers || []).join("、"))}</small></div></header><section class="reading-question-analysis"><h4>原书解析</h4><article class="knowledge-article">${renderMarkdown(question.source_analysis_md || "暂无原书解析")}</article></section><section class="reading-personal-analysis"><header><div><strong>个人解析</strong><small data-reading-analysis-status>${payload.personal_analysis?.trim() ? "已保存到练习笔记" : "粘贴侧边栏的分析，自动保存"}</small></div><a class="note-icon-button" href="obsidian://open" data-reading-obsidian aria-label="在 Obsidian 中打开练习笔记"><img src="/assets/obsidian.svg" alt=""></a></header><textarea rows="6" data-reading-analysis placeholder="粘贴侧边栏 AI 的解析，或写下自己的判断过程">${escapeHtml(payload.personal_analysis || "")}</textarea></section></section>` : "";
  return `<article class="reading-question-block" data-reading-index="${index}"><header class="reading-question-heading"><div><span>第 ${escapeHtml(question.local_number || index + 1)} 题</span><small>${escapeHtml(readingQuestionType(question))}</small></div><em data-reading-status>${readingAnswerStatus(payload)}</em></header><div class="knowledge-article reading-question-stem">${renderMarkdown(question.stem_md || "")}</div><div class="reading-question-options${revealed ? " is-revealed" : ""}">${options}</div><div class="reading-question-actions">${revealed ? "" : `<button class="secondary-button reading-question-submit" type="button" data-reading-submit="${index}"${prior.length ? "" : " disabled"}>提交答案</button>`}</div>${feedback}</article>`;
}

function bindReadingQuestion(index) {
  const block = document.querySelector(`[data-reading-index="${index}"]`); const item = state.practiceReadingItems[index]; if (!block || !item) return;
  block.querySelectorAll(".practice-option input").forEach((input) => input.addEventListener("change", () => {
    block.querySelectorAll(".practice-option").forEach((option) => option.classList.toggle("selected", option.querySelector("input")?.checked));
    const submit = block.querySelector("[data-reading-submit]"); if (submit) submit.disabled = !block.querySelector("input:checked");
  }));
  block.querySelector("[data-reading-submit]")?.addEventListener("click", () => submitReadingAnswer(index));
  block.querySelector("[data-reading-analysis]")?.addEventListener("input", () => scheduleReadingAnalysisSave(index));
}

function renderReadingQuestionBlock(index) {
  const block = document.querySelector(`[data-reading-index="${index}"]`); if (!block) return;
  block.outerHTML = readingQuestionHtml(state.practiceReadingItems[index], index);
  bindReadingQuestion(index); refreshIcons();
}

async function submitReadingAnswer(index) {
  const item = state.practiceReadingItems[index]; const question = item?.question; const block = document.querySelector(`[data-reading-index="${index}"]`); if (!question || !block) return;
  const selected = [...block.querySelectorAll("input:checked")].map((input) => input.value); if (!selected.length) { showToast("请先选择答案"); return; }
  const submit = block.querySelector("[data-reading-submit]"); if (submit) { submit.disabled = true; submit.textContent = "提交中…"; }
  try {
    const response = await fetch("/api/practice/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, selected_answers: selected }) });
    if (!response.ok) throw new Error("answer failed");
    const result = await response.json(); state.practiceReadingItems[index] = { ...item, question: result.question, attempt: result.attempt };
    state.practice.questions[index] = { ...state.practice.questions[index], answered: true, correct: result.attempt.correct }; renderReadingQuestionBlock(index); updateReadingProgress();
  } catch { if (submit) { submit.disabled = false; submit.textContent = "提交答案"; } showToast("提交失败，请稍后重试"); }
}

function scheduleReadingAnalysisSave(index) {
  const item = state.practiceReadingItems[index]; const question = item?.question; const block = document.querySelector(`[data-reading-index="${index}"]`); const textarea = block?.querySelector("[data-reading-analysis]"); if (!question || !item?.attempt || !textarea) return;
  const status = block.querySelector("[data-reading-analysis-status]"); const content = textarea.value; if (status) status.textContent = "保存中…"; window.clearTimeout(item.analysisSaveTimer);
  item.analysisSaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/practice/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, content }) }); if (!response.ok) throw new Error("analysis failed");
      const result = await response.json(); item.personal_analysis = content; if (status) status.textContent = content.trim() ? "已保存到练习笔记" : "个人解析已清空"; const link = block.querySelector("[data-reading-obsidian]"); if (link) link.href = result.obsidian_uri || "obsidian://open";
    } catch { if (status) status.textContent = "保存失败，请稍后重试"; }
  }, 420);
}

async function renderReadingComprehension() {
  const practice = state.practice; const requestId = state.openRequest; const layout = $("practiceReadingLayout"); const body = $("practiceReadingBody"); const questions = $("practiceReadingQuestions");
  state.practiceReadingToken += 1; const token = state.practiceReadingToken; state.practiceReadingItems = [];
  $("practiceWorkspace")?.classList.add("reading-comprehension-active"); $("practiceQuestionSurface").classList.add("is-reading-comprehension"); layout.classList.remove("hidden"); $("practiceResult").classList.add("hidden"); $("practicePagination").classList.add("hidden");
  $("practiceEyebrow").textContent = `${practice.entry?.label || "阅读理解"} · 真实题库`; $("practiceTitle").textContent = concisePracticeBankTitle(practice.bank.title); $("practiceTitle").title = practice.bank.title;
  $("practiceQuestionType").textContent = "阅读理解"; $("practiceQuestionNumber").textContent = "整篇阅读"; $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题 · 先读完整文章，再自由选择题目作答`;
  $("practiceReadingMeta").textContent = `${practice.entry?.label || "阅读理解"} · ${practice.questions.length} 题`;
  body.innerHTML = `<p class="practice-reading-loading">正在读取整篇文章…</p>`; questions.innerHTML = `<p class="practice-reading-loading">正在读取全部题目…</p>`; updateReadingProgress();
  let results;
  try {
    results = await Promise.all(practice.questions.map(async (item) => { const query = new URLSearchParams({ bank_id: practice.bank.id, question_id: item.question_id }); const response = await fetch(`/api/practice/question?${query}`, { cache: "no-store" }); if (!response.ok) throw new Error("question unavailable"); return response.json(); }));
  } catch {
    if (requestId === state.openRequest && token === state.practiceReadingToken) { body.innerHTML = `<p class="practice-reading-empty">阅读原文暂时无法读取。</p>`; questions.innerHTML = `<p class="practice-reading-empty">题目暂时无法读取，请返回试卷导览后重试。</p>`; showToast("阅读理解题目读取失败"); }
    return;
  }
  if (requestId !== state.openRequest || token !== state.practiceReadingToken || state.practice !== practice) return;
  state.practiceReadingItems = results;
  const firstQuestion = results[0]?.question;
  if (firstQuestion) startWorkspaceTimer({ activity_type: "objective_practice", domain: practice.bank.domain || "english", subject_id: firstQuestion.subject_label || practice.bank.subject || practice.bank.id, resource_id: practice.bank.id, item_id: firstQuestion.question_id, resume_target: { view: "practice", resource_id: practice.bank.id, item_id: firstQuestion.question_id, question_id: firstQuestion.question_id } });
  const firstContext = results.map((item) => String(item.question?.context_md || "").trim()).find(Boolean) || ""; const paragraphCount = firstContext ? firstContext.split(/\n\s*\n/).filter((item) => item.trim()).length : 0;
  $("practiceReadingMeta").textContent = `${practice.entry?.label || "阅读理解"}${paragraphCount ? ` · ${paragraphCount} 段` : ""}`; body.innerHTML = firstContext ? renderMarkdown(firstContext) : `<p class="practice-reading-empty">这组题目没有附带可显示的阅读原文。</p>`; questions.innerHTML = results.map((item, index) => readingQuestionHtml(item, index)).join(""); results.forEach((_, index) => bindReadingQuestion(index)); updateReadingProgress(); refreshIcons();
}

async function renderPracticeQuestion() {
  $("subjectivePracticeWorkspace")?.classList.add("hidden"); $("practiceWorkspace")?.classList.remove("hidden");
  $("practiceSessionSummary")?.classList.add("hidden"); $("practiceQuestionSurface")?.classList.remove("hidden");
  const practice = state.practice; const reading = isReadingComprehensionPractice(practice); $("practiceQuestionSurface").classList.toggle("is-reading-comprehension", reading); $("practiceReadingLayout").classList.toggle("hidden", !reading); $("practicePagination").classList.toggle("hidden", reading); $("practiceWorkspace")?.classList.toggle("reading-comprehension-active", reading);
  $("practiceMapToggle")?.classList.toggle("hidden", reading); $("practiceSessionMap")?.classList.add("hidden"); $("practiceMapToggle")?.setAttribute("aria-expanded", "false");
  if (reading) { await renderReadingComprehension(); return; }
  state.practiceReadingItems = [];
  await renderSinglePracticeQuestion();
}

async function renderSinglePracticeQuestion() {
  const practice = state.practice; const item = practice?.questions?.[state.practiceIndex]; if (!item) return;
  $("practiceEyebrow").textContent = practice.entry.match_level === "comprehensive" ? "综合测试 · 真实题库" : `${practiceEntryLabel(practice.entry)} · 真实题库`;
  $("practiceTitle").textContent = concisePracticeBankTitle(practice.bank.title); $("practiceTitle").title = practice.bank.title; $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题 · ${practiceWorkflowHint(item)}`;
  $("practiceProgressText").textContent = `${state.practiceIndex + 1} / ${practice.question_count}`; $("practiceProgressBar").style.setProperty("--practice-progress", `${((state.practiceIndex + 1) / practice.question_count) * 100}%`);
  $("practiceResult").classList.add("hidden"); $("practiceSubmit").classList.remove("hidden"); $("practiceSubmit").disabled = true;
  const query = new URLSearchParams({ bank_id: practice.bank.id, question_id: item.question_id }); const response = await fetch(`/api/practice/question?${query}`, { cache: "no-store" }); if (!response.ok) { showToast("题目读取失败"); return; }
  const payload = await response.json(); const question = payload.question; state.practice.question = payload;
  startWorkspaceTimer({ activity_type: "objective_practice", domain: question.domain || practice.bank.domain || "english", subject_id: question.subject_label || practice.bank.subject || practice.bank.id, resource_id: practice.bank.id, item_id: question.question_id, resume_target: { view: "practice", resource_id: practice.bank.id, item_id: question.question_id, question_id: question.question_id } });
  const unitLabel = question.unit_label || question.unit || "题目"; const answerType = question.question_type === "multiple_choice" ? "多项选择" : "单项选择";
  $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题 · ${practiceWorkflowHint(question)}`;
  $("practiceQuestionType").textContent = `${unitLabel} · ${answerType}`; $("practiceQuestionNumber").textContent = `第 ${question.local_number || state.practiceIndex + 1} 题`;
  const context = String(question.context_md || "").trim(); const paragraphCount = context ? context.split(/\n\s*\n/).filter((item) => item.trim()).length : 0; const cloze = isClozeQuestion(question); $("practiceContext").classList.toggle("hidden", !context); $("practiceContext").open = Boolean(context); $("practiceContextLabel").textContent = context ? `${cloze ? "完形填空全文" : "阅读原文"} · ${unitLabel}${paragraphCount ? `（${paragraphCount}段）` : ""}` : "阅读原文"; $("practiceContextBody").innerHTML = context ? (cloze ? renderClozeContext(context, question.local_number) : renderMarkdown(context)) : "";
  $("practiceContextBody").querySelectorAll("[data-cloze-index]").forEach((button) => button.addEventListener("click", () => focusClozeBlank(Number(button.dataset.clozeIndex))));
  $("practiceStem").innerHTML = cloze ? `<p class="cloze-instruction">点击正文中的任意空格，选项会在正文下方出现。</p>` : renderMarkdown(question.stem_md || ""); const prior = payload.attempt?.selected_answers || [];
  $("practiceOptions").innerHTML = (question.options || []).map((option) => `<label class="practice-option${prior.includes(option.label) ? " selected" : ""}"><input type="${question.question_type === "multiple_choice" ? "checkbox" : "radio"}" name="practice-answer" value="${escapeHtml(option.label)}" ${prior.includes(option.label) ? "checked" : ""}><strong class="practice-option-label">${escapeHtml(option.label)}</strong><span class="practice-option-text">${renderMarkdown(option.text_md || "")}</span><span class="practice-option-state" aria-hidden="true"></span></label>`).join("");
  $("practiceOptions").classList.toggle("hidden", cloze); renderClozeChoices(question, payload.attempt);
  $("practiceOptions").querySelectorAll("input").forEach((input) => input.addEventListener("change", updatePracticeOptionState));
  updatePracticeOptionState();
  $("practicePrevious").disabled = state.practiceIndex === 0; const last = state.practiceIndex >= practice.question_count - 1; $("practiceNext").disabled = false; $("practiceNext").querySelector("span").textContent = last ? "完成本组" : "下一题";
  if (payload.attempt) showPracticeResult(payload); renderPracticeSessionMap(); refreshIcons();
}

function showPracticeResult(payload) {
  const question = payload.question; const attempt = payload.attempt || {}; $("practiceSubmit").classList.add("hidden"); $("practiceResult").classList.remove("hidden");
  $("practiceResultTitle").textContent = attempt.correct ? "回答正确" : "继续梳理这个知识点"; $("practiceCorrectAnswer").textContent = `正确答案：${(question.correct_answers || []).join("、")}`;
  $("practiceResultIcon").classList.toggle("wrong", !attempt.correct); $("practiceResultIcon").innerHTML = `<i data-lucide="${attempt.correct ? "check" : "x"}"></i>`;
  const correct = new Set(question.correct_answers || []); const selected = new Set(attempt.selected_answers || []);
  $("practiceOptions").querySelectorAll(".practice-option").forEach((option) => {
    const input = option.querySelector("input"); const label = input.value; input.disabled = true;
    option.classList.toggle("correct", correct.has(label)); option.classList.toggle("incorrect", selected.has(label) && !correct.has(label));
    option.querySelector(".practice-option-state").innerHTML = correct.has(label) ? '<i data-lucide="check"></i>' : (selected.has(label) ? '<i data-lucide="x"></i>' : "");
  });
  renderClozeChoices(question, attempt); $("practiceSourceAnalysis").innerHTML = renderMarkdown(question.source_analysis_md || "暂无原书解析"); $("practicePersonalAnalysis").value = payload.personal_analysis || ""; $("practiceAnalysisSaved").textContent = payload.personal_analysis?.trim() ? "已保存到练习笔记" : "粘贴侧边栏的分析，自动保存"; refreshIcons();
}

function updatePracticeOptionState() {
  const options = $("practiceOptions").querySelectorAll(".practice-option");
  options.forEach((option) => option.classList.toggle("selected", option.querySelector("input").checked));
  $("practiceSubmit").disabled = !$("practiceOptions").querySelector("input:checked");
}

async function submitPracticeAnswer() {
  const question = state.practice?.question?.question; if (!question) return; const selected = [...document.querySelectorAll('#practiceOptions input:checked')].map((input) => input.value);
  if (!selected.length) { showToast("请先选择答案"); return; }
  $("practiceSubmit").disabled = true;
  try { const response = await fetch("/api/practice/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, selected_answers: selected }) }); if (!response.ok) throw new Error("answer failed"); const result = await response.json(); state.practice.question = { ...state.practice.question, question: result.question, attempt: result.attempt }; showPracticeResult(state.practice.question); state.practice.questions[state.practiceIndex] = { ...state.practice.questions[state.practiceIndex], answered: true, correct: result.attempt.correct }; renderPracticeSessionMap(); } catch { $("practiceSubmit").disabled = false; showToast("提交失败，请稍后重试"); }
}

function schedulePracticeAnalysisSave() {
  const question = state.practice?.question?.question; if (!question || !state.practice?.question?.attempt) return; const content = $("practicePersonalAnalysis").value; $("practiceAnalysisSaved").textContent = "保存中…"; window.clearTimeout(state.practiceAnalysisSaveTimer);
  state.practiceAnalysisSaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/practice/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, content }) }); if (!response.ok) throw new Error("analysis failed"); const result = await response.json(); $("practiceAnalysisSaved").textContent = content.trim() ? "已保存到练习笔记" : "个人解析已清空"; $("practiceObsidian").href = result.obsidian_uri || "obsidian://open"; } catch { $("practiceAnalysisSaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

function returnFromPractice() { if (state.practiceReturn === "home") setHomeMode(); else if (state.practiceReturn === "learning-center") setLibraryMode(); else if (state.practiceReturn === "english-exams") { setActiveView("library"); renderEnglishExams(); } else if (state.practiceReturn === "english-exam-overview" && state.practiceOverviewBankId) openEnglishExamOverview(state.practiceOverviewBankId); else if (state.practiceReturn === "resource" && state.resourceBookId) openResource(state.resourceBookId); else if (state.current?.id) setReaderMode(); else setLibraryMode(); }

function finishReaderSession() {
  const bookId = state.current?.book_id;
  if (bookId) openResource(bookId);
  else setLibraryMode();
}

function renderMaterial() {
  const article = $("knowledgeArticle"); const source = state.material === "note" ? state.current?.note : state.current?.markdown;
  const guide = $("sectionGuide");
  const imageBase = state.current?.book_id ? `/api/book-assets/${encodeURIComponent(state.current.book_id)}/` : "";
  article.classList.toggle("note-stream", state.material === "note");
  if (state.material === "note") {
    guide.classList.add("hidden"); guide.innerHTML = "";
    article.innerHTML = !state.current?.note?.trim() ? `<div class="section-material-empty"><i data-lucide="notebook-pen"></i><strong>这一节还没有笔记</strong><span>打开右下角笔记入口，粘贴 AI 整理结果即可。</span></div>` : renderMarkdown(source || "暂无内容", imageBase);
  } else {
    const prepared = prepareSectionMarkdown(source || "暂无内容", state.current?.title || "");
    article.innerHTML = renderMarkdown(prepared.markdown, imageBase);
    renderSectionGuide(article, guide, prepared.guide, prepared.kind);
  }
  document.querySelectorAll("[data-section-material]").forEach((button) => { const active = button.dataset.sectionMaterial === state.material; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); refreshIcons();
}

function navigateSection(step) {
  const book = state.books.find((item) => item.id === state.current?.book_id); const index = book?.sections.findIndex((section) => section.id === state.current.id) ?? -1; const target = book?.sections[index + step]; if (target) openSection(target.id);
}

function setNoteControlsExpanded(expanded) {
  document.querySelectorAll('[aria-controls="sectionNotePopover"]').forEach((button) => {
    button.setAttribute("aria-expanded", String(expanded));
    button.classList.toggle("active", expanded);
  });
}

function openNotePopover(trigger = null) {
  state.noteOpen = true; state.noteTrigger = trigger;
  $("sectionNoteFloat").classList.add("note-is-open"); $("sectionNotePopover").classList.add("is-open"); $("sectionNotePopover").setAttribute("aria-hidden", "false"); setNoteControlsExpanded(true); window.setTimeout(() => $("sectionNote").focus(), 120);
}

function closeNotePopover({ restoreFocus = false } = {}) {
  const trigger = state.noteTrigger; state.noteOpen = false; state.noteTrigger = null;
  $("sectionNoteFloat")?.classList.remove("note-is-open"); $("sectionNotePopover")?.classList.remove("is-open"); $("sectionNotePopover")?.setAttribute("aria-hidden", "true"); setNoteControlsExpanded(false);
  if (restoreFocus && trigger?.isConnected) trigger.focus();
}

function closeSectionMenu() { $("readerCrumbMenu")?.classList.add("hidden"); $("readerSectionPicker")?.classList.remove("active"); $("readerSectionPicker")?.setAttribute("aria-expanded", "false"); }

function scheduleNoteSave() {
  if (!state.current) return;
  const sectionId = state.current.id; const content = $("sectionNote").value;
  $("noteSavedText").textContent = "保存中…"; window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section_id: sectionId, content }) });
      if (!response.ok) throw new Error("save failed"); const result = await response.json();
      const cached = state.sections.get(sectionId); if (cached) state.sections.set(sectionId, { ...cached, note: content });
      if (state.current?.id !== sectionId) return;
      state.current.note = content; $("openObsidian").href = result.obsidian_uri || "obsidian://open"; $("noteSavedText").textContent = content.trim() ? (result.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存"; $("readerNoteMeta").textContent = content.trim() ? "已有笔记" : "暂无笔记"; if (state.material === "note") renderMaterial(); loadStats();
    } catch { if (state.current?.id === sectionId) $("noteSavedText").textContent = "保存失败，请稍后重试"; }
  }, 420);
}

function bindNavigation() {
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.addEventListener("click", setHomeMode));
  $("themeToggle")?.addEventListener("click", toggleTheme);
  applyTheme(document.documentElement.dataset.theme || "light", { persist: false });
  $("libraryNav").addEventListener("click", setLibraryMode); $("mobileLibrary").addEventListener("click", setLibraryMode);
  document.querySelectorAll("[data-shelf]").forEach((button) => button.addEventListener("click", () => selectLibraryShelf(button.dataset.shelf)));
  $("resourceBack").addEventListener("click", returnFromResource);
  $("resourceContinue").addEventListener("click", () => { const sectionId = $("resourceContinue").dataset.sectionId; if (sectionId) { state.readerOriginBookId = state.resourceBookId; openSection(sectionId); } });
  $("oralFocusBackToLibrary").addEventListener("click", () => { state.libraryDomain = "medicine"; setLibraryMode(); });
  $("oralFocusBackToDirectory").addEventListener("click", () => openOralFocusIndex(state.oralFocusSubjectId, state.oralFocusTypeFilter));
  $("oralFocusReveal").addEventListener("click", revealOralFocusReference);
  $("oralFocusAnswer").addEventListener("input", scheduleOralFocusSave); $("oralFocusMemory").addEventListener("input", scheduleOralFocusSave);
  $("oralFocusMastery").querySelectorAll("[data-mastery]").forEach((button) => button.addEventListener("click", () => updateOralFocusMastery(button.dataset.mastery)));
  document.querySelectorAll("[data-oral-prompt]").forEach((button) => button.addEventListener("click", () => copyOralFocusPrompt(button.dataset.oralPrompt)));
  $("oralFocusPrevious").addEventListener("click", () => navigateOralFocus(-1)); $("oralFocusNext").addEventListener("click", () => navigateOralFocus(1));
  $("practiceBack").addEventListener("click", returnFromPractice); $("subjectivePracticeBack").addEventListener("click", returnFromSubjectivePractice); $("subjectiveFinishSession").addEventListener("click", returnFromSubjectivePractice); $("subjectiveRevealReference").addEventListener("click", toggleSubjectiveReference); $("subjectiveAnswer").addEventListener("input", scheduleSubjectiveSave); $("subjectiveReflection").addEventListener("input", scheduleSubjectiveSave); $("practiceSubmit").addEventListener("click", submitPracticeAnswer); $("practiceMapToggle").addEventListener("click", togglePracticeSessionMap); $("practiceFinishSession").addEventListener("click", finishPracticeSession); $("practiceReadingFinish").addEventListener("click", finishPracticeSession); $("practiceReviewWrong").addEventListener("click", reviewFirstWrongPracticeQuestion); $("practiceLeaveSession").addEventListener("click", returnFromPractice); $("practicePrevious").addEventListener("click", () => { if (state.practiceIndex > 0) { state.practiceIndex -= 1; renderPracticeQuestion(); } }); $("practiceNext").addEventListener("click", () => { if (state.practiceIndex < (state.practice?.question_count || 1) - 1) { state.practiceIndex += 1; renderPracticeQuestion(); } else finishPracticeSession(); }); $("practicePersonalAnalysis").addEventListener("input", schedulePracticeAnalysisSave);
  $("reviewNav").addEventListener("click", openReview); $("mobileReview").addEventListener("click", openReview);
  $("logsNav").addEventListener("click", openLogs); $("mobileLogs").addEventListener("click", openLogs);
  document.querySelectorAll("[data-home-shelf]").forEach((button) => button.addEventListener("click", () => selectLibraryShelf(button.dataset.homeShelf)));
  $("homeOpenOralFocus").addEventListener("click", () => openOralFocusIndex());
  $("homeOpenEnglish").addEventListener("click", () => selectLibraryShelf("english"));
  $("homeOpenPolitics").addEventListener("click", () => selectLibraryShelf("politics"));
  $("homeOpenReview").addEventListener("click", openReview); $("homeOpenStats").addEventListener("click", openLogs);
  $("homeContinue").addEventListener("click", () => resumeActivityTarget(state.homeContinueTarget));
  window.addEventListener("resize", () => { window.clearTimeout(state.homeResizeTimer); state.homeResizeTimer = window.setTimeout(() => { if ($("homeView").classList.contains("active")) renderHome(); if ($("libraryView").classList.contains("active") && !$("bookTree").classList.contains("hidden") && !$("libraryWorkspace").classList.contains("resource-open") && !$("libraryWorkspace").classList.contains("reader-open")) renderBooks(); }, 120); });
  $("sidebar").addEventListener("mouseenter", () => $("sidebar").classList.add("is-expanded")); $("sidebar").addEventListener("mouseleave", () => $("sidebar").classList.remove("is-expanded"));
  $("readerBack").addEventListener("click", returnFromReader); $("readerBook").addEventListener("click", returnFromReader);
  $("readerFinishSession").addEventListener("click", finishReaderSession);
  $("readerSectionPicker").addEventListener("click", () => { const menu = $("readerCrumbMenu"); const willOpen = menu.classList.contains("hidden"); if (willOpen) { renderSectionMenu(); menu.classList.remove("hidden"); $("readerSectionPicker").classList.add("active"); $("readerSectionPicker").setAttribute("aria-expanded", "true"); } else closeSectionMenu(); });
  [$("readerPreviousSection"), $("previousSection")].forEach((button) => button.addEventListener("click", () => navigateSection(-1))); [$("readerNextSection"), $("nextSectionLink")].forEach((button) => button.addEventListener("click", () => navigateSection(1)));
  $("toggleSectionNoteDock").addEventListener("click", (event) => state.noteOpen ? closeNotePopover() : openNotePopover(event.currentTarget)); $("closeSectionNote").addEventListener("click", () => closeNotePopover({ restoreFocus: true })); $("sectionNote").addEventListener("input", scheduleNoteSave);
  $("reviewReportBack").addEventListener("click", setHomeMode); $("reviewDailySummary").addEventListener("input", scheduleDailySummarySave); $("reviewMarkNoText").addEventListener("click", markReviewNoText);
  $("logsBack").addEventListener("click", renderLogsList); $("weeklyBack").addEventListener("click", renderLogsList); $("openWeeklyReport").addEventListener("click", openWeeklyReport); $("openStatsFromRecords").addEventListener("click", openStats); $("statsBackToRecords").addEventListener("click", openLogs); $("weeklySummary").addEventListener("input", scheduleWeeklySave); $("englishExamsBack").addEventListener("click", () => selectLibraryShelf("english")); $("englishExamOverviewBack").addEventListener("click", renderEnglishExams);
  document.querySelectorAll("[data-section-material]").forEach((button) => button.addEventListener("click", () => { state.material = button.dataset.sectionMaterial; renderMaterial(); })); document.addEventListener("click", (event) => { if (!event.target.closest(".reader-toolbar")) closeSectionMenu(); });
  document.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (state.noteOpen) { closeNotePopover({ restoreFocus: true }); return; } closeSectionMenu(); });
  window.addEventListener("hashchange", applyRouteHash);
}

function initializeReadingTimer() {
  window.addEventListener("scroll", markReadingScroll, { passive: true });
  window.addEventListener("scroll", markWorkspaceActivity, { passive: true });
  ["click", "input", "change", "keydown"].forEach((eventName) => document.addEventListener(eventName, markWorkspaceActivity, { passive: true }));
  document.addEventListener("visibilitychange", () => { collectReadingTime(); collectWorkspaceTime(); if (document.hidden) { flushReadingTime(); flushWorkspaceTime(); } });
  window.addEventListener("pagehide", () => { flushReadingTime({ beacon: true }); flushWorkspaceTime({ beacon: true }); });
  window.setInterval(() => { collectReadingTime(); collectWorkspaceTime(); if (state.readingPendingSeconds >= READING_FLUSH_SECONDS) flushReadingTime(); if (state.workspacePendingSeconds >= READING_FLUSH_SECONDS) flushWorkspaceTime(); }, 5000);
}

async function loadBootstrap() {
  try {
    const response = await fetch("/api/bootstrap", { cache: "no-store" }); const data = await response.json(); state.books = data.books || []; state.questionBanks = data.question_banks || [];
    try { await loadOralFocus(); } catch { state.oralFocus = { available: false, subjects: [] }; }
    state.books.forEach((book) => book.sections.forEach((section) => state.sections.set(section.id, { ...section, book_title: book.title, book_id: book.id }))); renderBooks(); await loadStats();
  } catch { $("bookTree").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取本地学习库</strong><span>请确认 YuReader 服务正在运行。</span></div>`; refreshIcons(); }
}

bindNavigation(); initializeReadingTimer(); refreshIcons(); loadBootstrap().then(applyRouteHash);
