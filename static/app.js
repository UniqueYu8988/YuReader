const DOMAIN_LABELS = { medicine: "医学", politics: "政治", english: "英语" };
const SHELF_ORDER = ["medicine", "politics", "english", "exams", "notes"];
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
const state = { books: [], questionBanks: [], sections: new Map(), current: null, libraryBookId: null, libraryDomain: "medicine", inlineBookId: null, resource: null, resourceBookId: null, resourceCache: new Map(), resourceLoads: new Map(), englishNotebook: null, englishNotebookSaveTimer: null, englishExamOverview: null, englishExamOverviewBankId: "", readerOriginBookId: null, material: "cleaned", saveTimer: null, noteOpen: false, noteTrigger: null, openRequest: 0, review: null, reviewSummarySaveTimer: null, logs: null, weekly: null, weeklySaveTimer: null, stats: null, homeContinueTarget: null, homeResumeTargets: new Map(), readingActive: false, readingSectionId: "", readingLastTick: Date.now(), readingLastScroll: 0, readingPendingSeconds: 0, readingFlushKey: "", workspaceActivity: null, workspaceActive: false, workspaceLastTick: Date.now(), workspaceLastActive: 0, workspacePendingSeconds: 0, workspaceFlushSequence: 0, workspaceFlushKey: "", homeResizeTimer: null, practice: null, practiceIndex: 0, practiceReturn: "reader", practiceOverviewBankId: "", practiceAnalysisSaveTimer: null, practiceReadingItems: [], practiceReadingToken: 0, subjectivePractice: null, subjectiveSaveTimer: null };
const $ = (id) => document.getElementById(id);
const READING_IDLE_MS = 10 * 60 * 1000;
const READING_FLUSH_SECONDS = 15;
const THEME_STORAGE_KEY = "yureader-theme";
const ROUTE_ALIASES = {
  today: "home", home: "home", dashboard: "home",
  library: "library", books: "library", bookshelf: "library", shelf: "library",
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

function inlineMarkdown(value, imageBase = "") {
  let output = escapeHtml(value);
  output = output.replace(/&lt;br\s*\/??&gt;/gi, "<br>");
  output = output.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
    if (imageBase && /^(?:\.\/)?images\//.test(url)) url = `${imageBase}${url.replace(/^(?:\.\/)+/, "")}`;
    return `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}">`;
  });
  output = output.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${label}</a>`);
  output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  output = output.replace(/==([^=]+)==/g, "<mark>$1</mark>");
  return output;
}

function splitTableRow(line, imageBase = "") {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => inlineMarkdown(cell.trim(), imageBase));
}



function isTableSeparator(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function sanitizeTableHtml(value) {
  const documentNode = new DOMParser().parseFromString(String(value), "text/html");
  const table = documentNode.body.querySelector("table");
  if (!table) return `<p>${escapeHtml(value)}</p>`;
  const allowed = new Set(["table", "thead", "tbody", "tfoot", "tr", "th", "td", "br", "sup", "sub"]);
  function sanitizeNode(node) {
    if (node.nodeType === Node.TEXT_NODE) return escapeHtml(node.textContent || "");
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = node.tagName.toLowerCase();
    if (!allowed.has(tag)) return [...node.childNodes].map(sanitizeNode).join("");
    let attrs = "";
    if (tag === "td" || tag === "th") {
      ["rowspan", "colspan"].forEach((name) => {
        const raw = node.getAttribute(name);
        if (/^[1-9]\d?$/.test(raw || "")) attrs += ` ${name}="${raw}"`;
      });
    }
    if (tag === "br") return "<br>";
    return `<${tag}${attrs}>${[...node.childNodes].map(sanitizeNode).join("")}</${tag}>`;
  }
  return `<div class="knowledge-table-wrap">${sanitizeNode(table)}</div>`;
}

function renderMarkdown(markdown, imageBase = "") {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) { const level = Math.min(6, heading[1].length); blocks.push(`<h${level}>${inlineMarkdown(heading[2], imageBase)}</h${level}>`); index += 1; continue; }
    if (/^\s*<table\b/i.test(line)) {
      const tableLines = [line]; index += 1;
      while (index < lines.length && !/<\/table>\s*$/i.test(tableLines[tableLines.length - 1])) tableLines.push(lines[index++]);
      blocks.push(sanitizeTableHtml(tableLines.join("\n"))); continue;
    }
    if (/^\s*>/.test(line)) { const quote = []; while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, "")); blocks.push(`<blockquote>${inlineMarkdown(quote.join(" "), imageBase)}</blockquote>`); continue; }
    if (/^\s*\|/.test(line) && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      const rows = []; while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(splitTableRow(lines[index++], imageBase));
      const head = rows[0] || []; const body = rows.slice(2);
      blocks.push(`<div class="knowledge-table-wrap"><table><thead><tr>${head.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    const list = line.match(/^\s*([-*+] |\d+[.)]\s+)(.+)$/);
    if (list) {
      const ordered = /^\d/.test(list[1]); const items = [];
      while (index < lines.length) { const item = lines[index].match(/^\s*([-*+] |\d+[.)]\s+)(.+)$/); if (!item || /^\d/.test(item[1]) !== ordered) break; items.push(`<li>${inlineMarkdown(item[2], imageBase)}</li>`); index += 1; }
      blocks.push(`<${ordered ? "ol" : "ul"}>${items.join("")}</${ordered ? "ol" : "ul"}>`); continue;
    }
    const paragraph = [line.trim()]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,6})\s/.test(lines[index]) && !/^\s*<table\b/i.test(lines[index]) && !/^\s*([-*+] |\d+[.)]\s+|>|\|)/.test(lines[index])) paragraph.push(lines[index++].trim());
    blocks.push(`<p>${inlineMarkdown(paragraph.join(" "), imageBase)}</p>`);
  }
  return blocks.join("") || `<div class="section-material-empty"><i data-lucide="file-text"></i><strong>暂无内容</strong><span>这一节还没有可以展示的 Markdown。</span></div>`;
}

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
  ["home", "library", "practice", "review", "logs", "stats"].forEach((view) => $(`${view}View`).classList.toggle("active", view === viewMode));
  const primaryMode = mode === "home" ? "home" : ["library", "reader", "practice"].includes(mode) ? "library" : mode === "review" ? "review" : "logs";
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.classList.toggle("active", primaryMode === "home"));
  $("libraryNav").classList.toggle("active", primaryMode === "library"); $("mobileLibrary").classList.toggle("active", primaryMode === "library");
  $("reviewNav").classList.toggle("active", primaryMode === "review"); $("mobileReview").classList.toggle("active", primaryMode === "review");
  $("logsNav").classList.toggle("active", primaryMode === "logs"); $("mobileLogs").classList.toggle("active", primaryMode === "logs");
  $("pageTitle").textContent = mode === "home" ? "今日" : mode === "reader" ? "阅读" : mode === "library" ? "学习库" : mode === "practice" ? "练习" : mode === "review" ? "回顾" : mode === "logs" ? "记录" : "统计";
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
  if (state.libraryDomain === "notes" && !state.englishNotebook) { openEnglishNotebook(); return; }
  renderBooks($("librarySearch").value); window.scrollTo({ top: 0, behavior: "auto" });
}

function selectLibraryShelf(shelf) {
  if (!SHELF_ORDER.includes(shelf)) return;
  state.openRequest += 1; stopReadingTimer(); closeNotePopover();
  state.libraryDomain = shelf; state.inlineBookId = null; state.englishNotebook = null;
  state.resourceBookId = null; state.resource = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden"); $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library");
  if (shelf === "notes") { openEnglishNotebook(); return; }
  renderBooks($("librarySearch").value); window.scrollTo({ top: 0, behavior: "auto" });
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
  if (target.view === "english_notebook") { openEnglishNotebook(target.item_id); return; }
  if (target.view === "subjective_practice") { openSubjectivePractice(target.resource_id, target.item_id); return; }
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
  const hour = new Date().getHours();
  $("homeDate").textContent = today.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("homeGreeting").textContent = hour < 11 ? "早上好，从一小节开始" : hour < 18 ? "今天继续学一点" : "晚上好，留下一点理解";
  const continuation = stats.continue_activity;
  const continueTarget = stats.continue_target || null;
  state.homeContinueTarget = continueTarget;
  $("homeLeadText").textContent = continuation ? `上次在${continuation.activity_label}中停在“${continuation.title}”。` : "学习库已经准备好，选择一个学科开始今天的学习。";
  $("homeContinueLabel").textContent = continuation?.activity_label ? `继续${continuation.activity_label}` : "继续学习";
  $("homeContinueTitle").textContent = continuation?.title || "进入学习库选择内容";
  $("homeTodayDuration").textContent = formatDuration(stats.today_activity_seconds, true);
  $("homeTodaySections").textContent = `${formatInteger(stats.today_activity_count)} 个活动`;
  $("homeTodayNotes").textContent = `${formatInteger(stats.today_note_count)} 节笔记`;

  const pending = stats.review_pending;
  $("homeReviewTitle").textContent = pending ? `${reviewDateLabel(pending.date)}待回顾` : "暂时没有待回顾";
  $("homeReviewMeta").textContent = pending ? `${formatDuration(pending.duration_seconds)} · ${formatInteger(pending.activity_count)} 条活动 · ${formatInteger(pending.note_count)} 节笔记` : "新的学习日会在这里等待整理";
  $("homeOpenReview").disabled = !pending;

  state.homeResumeTargets.clear();
  const todayActivities = stats.today_activities || [];
  $("homeTraceList").innerHTML = todayActivities.length ? todayActivities.map((item, index) => {
    const key = homeActivityTargetKey("activity", index); state.homeResumeTargets.set(key, item.resume_target);
    return `<button class="reader-home-trace-row" type="button" data-home-resume="${key}"><span><strong>${escapeHtml(item.activity_label || activityTypeLabel(item.activity_type))}</strong><small>${escapeHtml(item.title || item.item_id || "学习条目")} · ${escapeHtml(item.subject_id || item.domain || "")}</small></span><span>${formatDuration(item.duration_seconds, true)}</span><i data-lucide="arrow-up-right"></i></button>`;
  }).join("") : `<div class="reader-home-trace-empty"><i data-lucide="sun-medium"></i><strong>今天还没有学习轨迹</strong><span>从一个学科开始，阅读、练习和笔记会在这里汇合。</span></div>`;
  $("homeTraceList").querySelectorAll("[data-home-resume]").forEach((button) => button.addEventListener("click", () => resumeActivityTarget(state.homeResumeTargets.get(button.dataset.homeResume))));

  const recent = stats.recent_resources || [];
  $("homeRecentList").innerHTML = recent.length ? recent.map((item, index) => {
    const key = homeActivityTargetKey("resource", index); state.homeResumeTargets.set(key, item.resume_target);
    return `<button class="reader-home-recent-row" type="button" data-home-resume="${key}"><span><strong>${escapeHtml(item.title || item.resource_id || "学习资料")}</strong><small>${escapeHtml(item.subject_id || item.domain || "")}</small></span><i data-lucide="arrow-right"></i></button>`;
  }).join("") : `<span class="reader-home-recent-empty">完成一次学习后，最近资料会显示在这里。</span>`;
  $("homeRecentList").querySelectorAll("[data-home-resume]").forEach((button) => button.addEventListener("click", () => resumeActivityTarget(state.homeResumeTargets.get(button.dataset.homeResume))));

  const counts = {
    medicine: state.books.filter((book) => (book.domain || "medicine") === "medicine").length,
    politics: state.books.filter((book) => (book.domain || "medicine") === "politics").length,
    english: englishShelfBooks().length,
  };
  $("homeMedicineMeta").textContent = `${formatInteger(counts.medicine)} 本书 · 教材章节精读`;
  $("homePoliticsMeta").textContent = `${formatInteger(counts.politics)} 本书 · 讲义与练习联动`;
  $("homeEnglishMeta").textContent = `${formatInteger(counts.english)} 本书 · 方法课与词汇`;
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
  const counts = {
    medicine: state.books.filter((book) => (book.domain || "medicine") === "medicine").length,
    politics: state.books.filter((book) => (book.domain || "medicine") === "politics").length,
    english: englishShelfBooks().length,
  };
  document.querySelectorAll("[data-shelf]").forEach((button) => {
    const shelf = button.dataset.shelf;
    button.classList.toggle("active", shelf === state.libraryDomain);
    const badge = button.querySelector("em");
    if (badge) badge.textContent = String(counts[shelf] ?? "");
  });
}

function formatEnglishDate(value) {
  const parsed = new Date(`${String(value || "")}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? String(value || "") : parsed.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function englishPanel(mode = "") {
  const search = $("librarySearch")?.closest(".knowledge-search");
  const isHub = mode === "hub"; const isNotebook = mode === "notebook"; const isExams = mode === "exams"; const isExamOverview = mode === "exam-overview";
  $("englishHub")?.classList.toggle("hidden", !isHub);
  $("englishNotebook")?.classList.toggle("hidden", !isNotebook);
  $("englishExams")?.classList.toggle("hidden", !isExams);
  $("englishExamOverview")?.classList.toggle("hidden", !isExamOverview);
  $("bookTree")?.classList.toggle("hidden", isHub || isNotebook || isExams || isExamOverview);
  if (search) search.classList.toggle("hidden", isHub || isNotebook || isExams || isExamOverview);
}

function englishResource(kind) {
  const books = state.books.filter((book) => (book.domain || "medicine") === "english");
  const patterns = {
    exam: /真题|试卷|exam/i,
    method: /语法|长难句|grammar/i,
    vocabulary: /词汇|红宝书|单词|vocab/i,
  };
  const primary = books.find((book) => patterns[kind].test(`${book.title} ${book.subject || ""} ${book.resource_type || ""}`));
  if (primary || kind !== "method") return primary || null;
  return books.find((book) => /阅读|方法|reading/i.test(`${book.title} ${book.subject || ""}`)) || null;
}

function englishModuleHtml({ kind, eyebrow, title, description, icon, resource, bank, count, action }) {
  const available = Boolean(resource || bank) || kind === "notebook";
  const attr = bank ? "data-english-exams" : resource ? `data-english-resource="${escapeHtml(resource.id)}"` : kind === "notebook" ? "data-english-notebook" : "disabled";
  return `<button class="english-module-row ${kind}${available ? "" : " unavailable"}" type="button" ${attr}>
    <span class="english-module-index"><i data-lucide="${icon}"></i></span>
    <span class="english-module-copy"><small>${eyebrow}</small><strong>${title}</strong><em>${description}</em></span>
    <span class="english-module-status">${count ? `<small>${escapeHtml(count)}</small>` : ""}<strong>${available ? action : "资料制作中"}</strong></span>
    <i data-lucide="${available ? "arrow-up-right" : "clock-3"}"></i>
  </button>`;
}

function renderEnglishHub() {
  englishPanel("hub");
  const exam = englishResource("exam"); const method = englishResource("method"); const vocabulary = englishResource("vocabulary");
  const examBanks = state.questionBanks.filter((bank) => bank.domain === "english");
  const examBank = examBanks[0] || null;
  const modules = [
    { kind: "exam", eyebrow: "01 · PRACTICE", title: "真题训练", description: "按年份完成题目，题干、答案和个人解析彼此独立。", icon: "file-check-2", resource: exam, bank: examBank, count: examBanks.length ? `${examBanks.length} 个题库` : exam ? `${exam.sections.length} 个单元` : "", action: "进入真题" },
    { kind: "method", eyebrow: "02 · METHOD", title: "方法课", description: "语法、长难句与阅读方法按课程目录连续学习。", icon: "route", resource: method, count: method ? `${method.sections.length} 节` : "", action: "开始课程" },
    { kind: "vocabulary", eyebrow: "03 · VOCABULARY", title: "词汇本", description: "以 Unit 为单位积累，不把每个单词拆成孤立页面。", icon: "text-cursor-input", resource: vocabulary, count: vocabulary ? `${vocabulary.sections.length} 个单元` : "", action: "打开词表" },
    { kind: "notebook", eyebrow: "04 · WEEKLY NOTE", title: "英语周记", description: "周一到周日共用一份 Markdown，承接侧边栏生成的内容。", icon: "notebook-pen", resource: null, count: "每周一份", action: "打开本周" },
  ];
  $("englishModuleList").innerHTML = modules.map(englishModuleHtml).join("");
  $("englishModuleList").querySelectorAll("[data-english-resource]").forEach((button) => button.addEventListener("click", () => openResource(button.dataset.englishResource)));
  $("englishModuleList").querySelector("[data-english-exams]")?.addEventListener("click", renderEnglishExams);
  $("englishModuleList").querySelector("[data-english-notebook]")?.addEventListener("click", () => openEnglishNotebook());
  refreshIcons();
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
  $("englishExamOverviewCompanion").querySelectorAll("[data-paper-resource]").forEach((button) => button.addEventListener("click", () => openSubjectivePractice(button.dataset.paperResource, button.dataset.paperResourceSection)));
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

function renderEnglishWeekStrip(payload) {
  const strip = $("englishWeekStrip");
  if (!strip) return;
  const labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const start = new Date(`${String(payload?.start || "")}T12:00:00`);
  strip.innerHTML = labels.map((label, index) => {
    const current = new Date(start); current.setDate(start.getDate() + index);
    const iso = Number.isNaN(current.getTime()) ? "" : current.toISOString().slice(0, 10);
    const today = payload?.week === payload?.current_week && iso === payload?.today;
    return `<span class="english-week-day${today ? " today" : ""}"><strong>${label}</strong><small>${formatEnglishDate(iso)}</small></span>`;
  }).join("");
}

function renderEnglishArchiveList(payload) {
  const list = $("englishArchiveList"); const archives = payload?.archives || [];
  if (!list) return;
  $("englishArchiveCount").textContent = `${archives.length} 份`;
  list.innerHTML = archives.length ? archives.map((entry) => `<button class="english-archive-row${entry.week === payload.week ? " current" : ""}" type="button" data-english-week="${escapeHtml(entry.week)}"><span><strong>${escapeHtml(entry.week)} · ${formatEnglishDate(entry.start)}—${formatEnglishDate(entry.end)}</strong><small>${entry.week === payload.current_week ? "本周" : "已归档"}</small></span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="english-archive-empty">还没有历史周记。输入本周内容后，这里会留下每周一份的归档。</div>`;
  list.querySelectorAll("[data-english-week]").forEach((button) => button.addEventListener("click", () => openEnglishNotebook(button.dataset.englishWeek)));
  refreshIcons();
}

function renderEnglishNotebook() {
  englishPanel("notebook");
  const payload = state.englishNotebook;
  const editor = $("englishNotebookEditor"); const insertButton = $("englishInsertDay");
  if (!payload) {
    $("englishNotebookTitle").textContent = "英语周记";
    $("englishNotebookMeta").textContent = "正在读取本周内容…";
    $("englishNotebookSaved").textContent = "读取中…";
    editor.value = ""; editor.disabled = true; insertButton.disabled = true;
    $("englishWeekStrip").innerHTML = ""; $("englishArchiveList").innerHTML = ""; $("englishArchiveCount").textContent = "";
    return;
  }
  $("englishNotebookTitle").textContent = `${payload.week} · 英语周记`;
  $("englishNotebookMeta").textContent = `${formatEnglishDate(payload.start)} — ${formatEnglishDate(payload.end)} · 周一至周日共一份归档`;
  $("englishNotebookObsidian").href = payload.obsidian_uri || "obsidian://open";
  editor.value = payload.content || ""; editor.disabled = Boolean(payload.error);
  insertButton.disabled = Boolean(payload.error) || payload.week !== payload.current_week;
  $("englishNotebookSaved").textContent = payload.error ? "暂时无法读取，请确认本地服务" : payload.character_count ? (payload.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
  renderEnglishWeekStrip(payload); renderEnglishArchiveList(payload); refreshIcons();
}

async function openEnglishNotebook(week = "") {
  const requestId = ++state.openRequest;
  stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden");
  state.libraryDomain = "notes"; state.resourceBookId = null; state.resource = null; state.englishNotebook = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden");
  setActiveView("library"); renderDomainTabs(); renderEnglishNotebook(); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const suffix = week ? `?week=${encodeURIComponent(week)}` : "";
    const response = await fetch(`/api/english-notebook${suffix}`, { cache: "no-store" });
    if (!response.ok) throw new Error("english notebook unavailable");
    const payload = await response.json();
    if (requestId !== state.openRequest) return;
    state.englishNotebook = payload;
    startWorkspaceTimer({ activity_type: "notebook", domain: "english", subject_id: "english-notebook", resource_id: "english-notebook", item_id: payload.week, resume_target: { view: "english_notebook", resource_id: "english-notebook", item_id: payload.week } });
    renderEnglishNotebook();
  } catch {
    if (requestId !== state.openRequest) return;
    const currentYear = new Date().getFullYear();
    state.englishNotebook = { week: week || `${currentYear}-W01`, current_week: "", start: "", end: "", content: "", archives: [], error: true };
    renderEnglishNotebook();
  }
}

function scheduleEnglishNotebookSave() {
  const payload = state.englishNotebook; if (!payload || payload.error) return;
  const content = $("englishNotebookEditor").value; $("englishNotebookSaved").textContent = "保存中…"; window.clearTimeout(state.englishNotebookSaveTimer);
  state.englishNotebookSaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/english-notebook", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ week: payload.week, content }) });
      if (!response.ok) throw new Error("save failed");
      const result = await response.json();
      if (state.englishNotebook?.week !== payload.week) return;
      state.englishNotebook = result; $("englishNotebookObsidian").href = result.obsidian_uri || "obsidian://open"; $("englishNotebookSaved").textContent = content.trim() ? (result.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存"; renderEnglishArchiveList(result);
    } catch { if (state.englishNotebook?.week === payload.week) $("englishNotebookSaved").textContent = "保存失败，请稍后重试"; }
  }, 420);
}

function insertEnglishDayHeading() {
  const payload = state.englishNotebook; const editor = $("englishNotebookEditor");
  if (!payload || payload.error || payload.week !== payload.current_week) return;
  const weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][Number(payload.today_weekday)] || "今天";
  const marker = `## ${weekday} · ${formatEnglishDate(payload.today)}`;
  if (editor.value.includes(marker)) { editor.focus(); return; }
  const heading = `\n\n${marker}\n\n`;
  const start = editor.selectionStart ?? editor.value.length; const end = editor.selectionEnd ?? start;
  editor.value = `${editor.value.slice(0, start)}${heading}${editor.value.slice(end)}`; editor.selectionStart = editor.selectionEnd = start + heading.length; editor.focus(); scheduleEnglishNotebookSave();
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

function renderBooks(filter = "") {
  renderDomainTabs();
  if (state.libraryDomain === "exams") { renderEnglishExams(); return; }
  if (state.libraryDomain === "notes") { renderEnglishNotebook(); return; }
  if (state.libraryDomain === "english") { renderEnglishHub(); return; }
  englishPanel("");
  const query = filter.trim().toLowerCase(); const tree = $("bookTree");
  const matchedBooks = domainBooks().filter((book) => !query || searchableBook(book).includes(query));
  if (!matchedBooks.length) {
    tree.innerHTML = query
      ? `<div class="knowledge-index-empty"><i data-lucide="search-x"></i><strong>没有找到匹配内容</strong><span>换一个书名或章节关键词试试。</span></div>`
      : `<div class="knowledge-index-empty"><i data-lucide="library"></i><strong>${escapeHtml(DOMAIN_LABELS[state.libraryDomain] || "医学")}学习库还是空的</strong><span>这个领域还没有正式资料，放入学习库后刷新页面。</span></div>`;
    refreshIcons(); return;
  }
  const covers = matchedBooks.map((book) => `<button class="reader-book-overview ${book.id === state.resourceBookId ? "active" : ""}" type="button" data-library-book="${escapeHtml(book.id)}" title="打开《${escapeHtml(book.title)}》资料学习主页" aria-label="打开《${escapeHtml(book.title)}》资料学习主页"><span class="reader-book-cover" aria-hidden="true"><strong>${bookCoverTitle(book)}</strong><em>${escapeHtml(book.edition || "")}</em></span></button>`).join("");
  let directory = "";
  if (query) {
    const selectedBookId = matchedBooks.some((book) => book.id === state.inlineBookId) ? state.inlineBookId : matchedBooks[0].id;
    const selected = matchedBooks.find((book) => book.id === selectedBookId);
    const chapters = bookToc(selected).map((chapter) => ({ ...chapter, sections: chapter.sections.filter((section) => `${selected.title} ${chapter.title} ${section.title}`.toLowerCase().includes(query)) })).filter((chapter) => chapter.sections.length);
    const bookIndex = state.books.findIndex((item) => item.id === selected.id) + 1;
    directory = `<section class="reader-directory" data-book-group="${escapeHtml(selected.id)}">
        <header class="reader-directory-heading"><div><small>BOOK ${String(bookIndex).padStart(2, "0")} · ${escapeHtml(selected.edition || "本地书籍")}</small><strong>${escapeHtml(selected.title)}</strong></div><span>${(selected.toc?.length || chapters.length)} 章 · ${selected.sections.length} 个学习小节</span></header>
        ${chapterListHtml(selected, chapters, { openAll: true })}
      </section>`;
  }
  tree.innerHTML = `<div class="reader-cover-shelf" aria-label="图书列表">${covers}</div>${directory}`;
  tree.querySelectorAll("[data-library-book]").forEach((button) => button.addEventListener("click", () => {
    const bookId = button.dataset.libraryBook;
    if (query) { state.inlineBookId = state.inlineBookId === bookId ? null : bookId; renderBooks($("librarySearch").value); }
    else openResource(bookId);
  }));
  tree.querySelectorAll("[data-library-book]").forEach((button) => {
    button.addEventListener("pointerenter", () => prefetchResource(button.dataset.libraryBook), { once: true });
    button.addEventListener("focus", () => prefetchResource(button.dataset.libraryBook), { once: true });
  });
  tree.querySelectorAll("[data-section-id]").forEach((button) => button.addEventListener("click", () => { state.readerOriginBookId = null; openSection(button.dataset.sectionId); }));
  refreshIcons();
}

function formatDateTime(value) {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) return String(value || "");
  const day = parsed.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
  const clock = parsed.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return `${day} ${clock}`;
}

function renderResource() {
  const payload = state.resource; const book = payload?.book; const summary = payload?.summary || {};
  if (!book) { $("resourceFacts").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取这份资料</strong><span>请确认书架服务正在运行。</span></div>`; return; }
  $("resourcePanel").classList.remove("is-loading");
  $("resourceFacts").classList.remove("is-loading"); $("resourceFacts").removeAttribute("aria-busy"); $("resourceFacts").removeAttribute("aria-label");
  $("resourceProgressTrack").classList.remove("is-loading");
  $("resourceDomainLabel").textContent = `${book.domain_label || DOMAIN_LABELS[book.domain] || "医学"} · ${book.resource_type_label || book.resource_type || "教材"}`;
  $("resourceTitle").textContent = book.title;
  $("resourceMeta").textContent = `${book.edition ? `${book.edition} · ` : ""}${book.subject}`;
  const lastSection = summary.last_section;
  const lastText = lastSection ? `${lastSection.chapter_title}　${lastSection.title}` : "还没有学习记录";
  const progress = Number(summary.progress || 0);
  const progressText = `${progress.toFixed(progress % 1 ? 1 : 0)}%`;
  $("resourceProgressBar").style.width = `${Math.min(100, Math.max(0, progress))}%`;
  $("resourceProgressTrack").title = `阅读进度 ${progressText}（已学习小节 / 全部小节）`;
  const learnedCount = Number(summary.learned_section_count || 0);
  const totalCount = Number(summary.section_count || 0);
  const noteCount = Number(summary.note_count || 0);
  const readingSeconds = Number(summary.reading_seconds || 0);
  const studiedAt = summary.last_studied_at ? formatDateTime(summary.last_studied_at) : "暂无记录";
  $("resourceFacts").innerHTML =
    `<div class="resource-fact-location"><span>上次学习位置</span><strong class="resource-location">${escapeHtml(lastText)}</strong></div>`
    + `<div><span>阅读进度</span><strong class="resource-value">${progressText}</strong><em>${learnedCount} / ${totalCount} 小节</em></div>`
    + `<div><span>已学习小节</span><strong class="resource-value">${formatInteger(learnedCount)}</strong><em>${noteCount ? `${formatInteger(noteCount)} 节笔记` : "暂无章节笔记"}</em></div>`
    + `<div><span>最近学习时间</span><strong class="resource-location">${escapeHtml(studiedAt)}</strong><em>${readingSeconds ? `阅读 ${formatDuration(readingSeconds)}` : "暂无阅读时长"}</em></div>`;
  $("resourceContinueTitle").textContent = lastSection ? `${lastSection.title} · ${lastSection.chapter_title}` : `从 ${book.sections[0] ? book.sections[0].title : "第一章"} 开始阅读`;
  $("resourceContinue").dataset.sectionId = lastSection?.id || book.sections[0]?.id || "";
  const chapters = bookToc(book).filter((chapter) => chapter.sections.length);
  $("resourceDirectory").innerHTML =
    `<header class="resource-directory-heading"><div><p class="eyebrow">分层目录</p><h3>${escapeHtml(book.title)}</h3></div><span>${book.toc?.length || chapters.length} 章 · ${book.sections.length} 个学习小节</span></header>`
    + `<section class="reader-directory resource-directory-list">${chapterListHtml(book, chapters)}</section>`;
  $("resourceDirectory").querySelectorAll("[data-section-id]").forEach((button) => button.addEventListener("click", () => { state.readerOriginBookId = state.resourceBookId; openSection(button.dataset.sectionId); }));
  refreshIcons();
}

function renderResourceLoading(book) {
  state.resource = { book, summary: {} };
  renderResource();
  $("resourcePanel").classList.add("is-loading");
  $("resourceProgressTrack").classList.add("is-loading");
  $("resourceProgressTrack").title = "正在读取本地学习记录";
  $("resourceFacts").classList.add("is-loading");
  $("resourceFacts").setAttribute("aria-busy", "true");
  $("resourceFacts").setAttribute("aria-label", "正在读取本地学习记录");
  $("resourceFacts").innerHTML = ["上次学习位置", "阅读进度", "已学习小节", "最近学习时间"].map((label, index) => `<div${index === 0 ? ' class="resource-fact-location"' : ""}><span>${label}</span><i class="resource-loading-line ${index === 0 ? "wide" : ""}" aria-hidden="true"></i><i class="resource-loading-line short" aria-hidden="true"></i></div>`).join("");
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
      $("resourcePanel").classList.remove("is-loading"); $("resourceProgressTrack").classList.remove("is-loading"); $("resourceFacts").classList.remove("is-loading"); $("resourceFacts").removeAttribute("aria-busy");
      $("resourceFacts").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取这份资料</strong><span>请确认书架服务正在运行。</span></div>`;
    }
  }
  renderBooks($("librarySearch").value); window.scrollTo({ top: 0, behavior: "auto" });
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
  if (state.practiceOverviewBankId) openEnglishExamOverview(state.practiceOverviewBankId);
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
  renderBooks($("librarySearch").value);
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
  state.material = "cleaned"; closeSectionMenu(); closeNotePopover(); renderSectionMenu(); renderMaterial(); setNavigationState(); renderBooks($("librarySearch").value); loadSectionPractice(); window.scrollTo({ top: 0, behavior: "smooth" });
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
    fresh.classList.remove("hidden"); fresh.querySelector("span").textContent = `${practiceEntryLabel(entry)} · ${entry.question_count}题`;
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
    container.classList.remove("hidden"); container.innerHTML = `<button class="resource-continue" type="button"><span><small>真实题库</small><strong>${practiceEntryLabel(entry)} · ${entry.question_count} 题</strong></span><i data-lucide="arrow-right"></i></button>`;
    container.querySelector("button").addEventListener("click", () => openPractice(entry, "resource")); refreshIcons();
  } catch { /* The resource page remains usable without a bank. */ }
}

async function openPractice(entry, returnTo, startIndex = 0) {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); state.practiceReturn = returnTo; state.practiceOverviewBankId = returnTo === "english-exam-overview" ? entry.bank_id : ""; state.practiceIndex = Math.max(0, Number(startIndex) || 0);
  state.subjectivePractice = null; $("subjectivePracticeWorkspace")?.classList.add("hidden"); $("practiceWorkspace")?.classList.remove("hidden");
  try {
    const query = new URLSearchParams({ bank_id: entry.bank_id, knowledge_id: entry.knowledge_id, match_level: entry.match_level });
    const response = await fetch(`/api/practice/session?${query}`, { cache: "no-store" }); if (!response.ok) throw new Error("practice unavailable");
    state.practice = { ...(await response.json()), entry }; setActiveView("practice"); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
  } catch { showToast("暂时无法读取这组题目"); }
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
  const practice = state.practice; const reading = isReadingComprehensionPractice(practice); $("practiceQuestionSurface").classList.toggle("is-reading-comprehension", reading); $("practiceReadingLayout").classList.toggle("hidden", !reading); $("practicePagination").classList.toggle("hidden", reading); $("practiceWorkspace")?.classList.toggle("reading-comprehension-active", reading);
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
  $("practicePrevious").disabled = state.practiceIndex === 0; $("practiceNext").disabled = state.practiceIndex >= practice.question_count - 1;
  if (payload.attempt) showPracticeResult(payload); refreshIcons();
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
  try { const response = await fetch("/api/practice/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, selected_answers: selected }) }); if (!response.ok) throw new Error("answer failed"); const result = await response.json(); state.practice.question = { ...state.practice.question, question: result.question, attempt: result.attempt }; showPracticeResult(state.practice.question); state.practice.questions[state.practiceIndex] = { ...state.practice.questions[state.practiceIndex], answered: true, correct: result.attempt.correct }; } catch { $("practiceSubmit").disabled = false; showToast("提交失败，请稍后重试"); }
}

function schedulePracticeAnalysisSave() {
  const question = state.practice?.question?.question; if (!question || !state.practice?.question?.attempt) return; const content = $("practicePersonalAnalysis").value; $("practiceAnalysisSaved").textContent = "保存中…"; window.clearTimeout(state.practiceAnalysisSaveTimer);
  state.practiceAnalysisSaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/practice/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, content }) }); if (!response.ok) throw new Error("analysis failed"); const result = await response.json(); $("practiceAnalysisSaved").textContent = content.trim() ? "已保存到练习笔记" : "个人解析已清空"; $("practiceObsidian").href = result.obsidian_uri || "obsidian://open"; } catch { $("practiceAnalysisSaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

function returnFromPractice() { if (state.practiceReturn === "home") setHomeMode(); else if (state.practiceReturn === "english-exams") { setActiveView("library"); renderEnglishExams(); } else if (state.practiceReturn === "english-exam-overview" && state.practiceOverviewBankId) openEnglishExamOverview(state.practiceOverviewBankId); else if (state.practiceReturn === "resource" && state.resourceBookId) openResource(state.resourceBookId); else if (state.current?.id) setReaderMode(); else setLibraryMode(); }

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
  $("resourceContinue").addEventListener("click", () => { const sectionId = $("resourceContinue").dataset.sectionId; if (sectionId) { state.readerOriginBookId = state.resourceBookId; state.inlineBookId = null; openSection(sectionId); } });
  $("practiceBack").addEventListener("click", returnFromPractice); $("subjectivePracticeBack").addEventListener("click", returnFromSubjectivePractice); $("subjectiveRevealReference").addEventListener("click", toggleSubjectiveReference); $("subjectiveAnswer").addEventListener("input", scheduleSubjectiveSave); $("subjectiveReflection").addEventListener("input", scheduleSubjectiveSave); $("practiceSubmit").addEventListener("click", submitPracticeAnswer); $("practicePrevious").addEventListener("click", () => { if (state.practiceIndex > 0) { state.practiceIndex -= 1; renderPracticeQuestion(); } }); $("practiceNext").addEventListener("click", () => { if (state.practiceIndex < (state.practice?.question_count || 1) - 1) { state.practiceIndex += 1; renderPracticeQuestion(); } }); $("practicePersonalAnalysis").addEventListener("input", schedulePracticeAnalysisSave);
  $("reviewNav").addEventListener("click", openReview); $("mobileReview").addEventListener("click", openReview);
  $("logsNav").addEventListener("click", openLogs); $("mobileLogs").addEventListener("click", openLogs);
  document.querySelectorAll("[data-home-shelf]").forEach((button) => button.addEventListener("click", () => selectLibraryShelf(button.dataset.homeShelf)));
  $("homeOpenReview").addEventListener("click", openReview); $("homeOpenStats").addEventListener("click", openLogs);
  $("homeContinue").addEventListener("click", () => resumeActivityTarget(state.homeContinueTarget));
  window.addEventListener("resize", () => { window.clearTimeout(state.homeResizeTimer); state.homeResizeTimer = window.setTimeout(() => { if ($("homeView").classList.contains("active")) renderHome(); }, 120); });
  $("sidebar").addEventListener("mouseenter", () => $("sidebar").classList.add("is-expanded")); $("sidebar").addEventListener("mouseleave", () => $("sidebar").classList.remove("is-expanded"));
  $("readerBack").addEventListener("click", returnFromReader); $("readerBook").addEventListener("click", returnFromReader);
  $("readerSectionPicker").addEventListener("click", () => { const menu = $("readerCrumbMenu"); const willOpen = menu.classList.contains("hidden"); if (willOpen) { renderSectionMenu(); menu.classList.remove("hidden"); $("readerSectionPicker").classList.add("active"); $("readerSectionPicker").setAttribute("aria-expanded", "true"); } else closeSectionMenu(); });
  [$("readerPreviousSection"), $("previousSection")].forEach((button) => button.addEventListener("click", () => navigateSection(-1))); [$("readerNextSection"), $("nextSectionLink")].forEach((button) => button.addEventListener("click", () => navigateSection(1)));
  $("toggleSectionNoteDock").addEventListener("click", (event) => state.noteOpen ? closeNotePopover() : openNotePopover(event.currentTarget)); $("closeSectionNote").addEventListener("click", () => closeNotePopover({ restoreFocus: true })); $("sectionNote").addEventListener("input", scheduleNoteSave);
  $("reviewReportBack").addEventListener("click", setHomeMode); $("reviewDailySummary").addEventListener("input", scheduleDailySummarySave); $("reviewMarkNoText").addEventListener("click", markReviewNoText);
  $("logsBack").addEventListener("click", renderLogsList); $("weeklyBack").addEventListener("click", renderLogsList); $("openWeeklyReport").addEventListener("click", openWeeklyReport); $("openStatsFromRecords").addEventListener("click", openStats); $("statsBackToRecords").addEventListener("click", openLogs); $("weeklySummary").addEventListener("input", scheduleWeeklySave); $("englishExamsBack").addEventListener("click", () => selectLibraryShelf("english")); $("englishExamOverviewBack").addEventListener("click", renderEnglishExams); $("englishNotebookBack").addEventListener("click", () => selectLibraryShelf("english")); $("englishNotebookEditor").addEventListener("input", scheduleEnglishNotebookSave); $("englishInsertDay").addEventListener("click", insertEnglishDayHeading);
  document.querySelectorAll("[data-section-material]").forEach((button) => button.addEventListener("click", () => { state.material = button.dataset.sectionMaterial; renderMaterial(); })); $("librarySearch").addEventListener("input", (event) => renderBooks(event.target.value)); document.addEventListener("click", (event) => { if (!event.target.closest(".reader-toolbar")) closeSectionMenu(); });
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
    state.books.forEach((book) => book.sections.forEach((section) => state.sections.set(section.id, { ...section, book_title: book.title, book_id: book.id }))); renderBooks(); await loadStats();
  } catch { $("bookTree").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取本地学习库</strong><span>请确认 YuReader 服务正在运行。</span></div>`; refreshIcons(); }
}

bindNavigation(); initializeReadingTimer(); refreshIcons(); loadBootstrap().then(applyRouteHash);
