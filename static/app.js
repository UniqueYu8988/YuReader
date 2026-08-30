const DOMAIN_LABELS = { medicine: "医学", politics: "政治", english: "英语" };
const DOMAIN_ORDER = ["medicine", "politics", "english"];
const state = { books: [], sections: new Map(), current: null, libraryBookId: null, libraryDomain: "medicine", inlineBookId: null, resource: null, resourceBookId: null, readerOriginBookId: null, material: "cleaned", saveTimer: null, noteOpen: false, noteTrigger: null, openRequest: 0, review: null, reviewSubjectId: "", reviewSubjectSaveTimer: null, reviewSummarySaveTimer: null, logs: null, weekly: null, weeklySaveTimer: null, stats: null, readingActive: false, readingSectionId: "", readingLastTick: Date.now(), readingLastScroll: 0, readingPendingSeconds: 0, homeResizeTimer: null, practice: null, practiceIndex: 0, practiceReturn: "reader", practiceAnalysisSaveTimer: null };
const $ = (id) => document.getElementById(id);
const READING_IDLE_MS = 10 * 60 * 1000;
const READING_FLUSH_SECONDS = 15;

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

function bookCoverTitle(title) {
  const text = String(title || "本地书籍").trim();
  const splitAt = text.startsWith("口腔") && text.length > 2 ? 2 : Math.ceil(text.length / 2);
  return `${escapeHtml(text.slice(0, splitAt))}<br>${escapeHtml(text.slice(splitAt))}`;
}

function setActiveView(mode) {
  const viewMode = mode === "reader" ? "library" : mode;
  ["home", "library", "practice", "review", "logs", "stats"].forEach((view) => $(`${view}View`).classList.toggle("active", view === viewMode));
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.classList.toggle("active", mode === "home"));
  $("libraryNav").classList.toggle("active", viewMode === "library"); $("mobileLibrary").classList.toggle("active", viewMode === "library");
  $("reviewNav").classList.toggle("active", mode === "review"); $("mobileReview").classList.toggle("active", mode === "review");
  $("logsNav").classList.toggle("active", mode === "logs"); $("mobileLogs").classList.toggle("active", mode === "logs");
  $("statsNav").classList.toggle("active", mode === "stats"); $("mobileStats").classList.toggle("active", mode === "stats");
  $("pageTitle").textContent = mode === "home" ? "今日学习" : mode === "reader" ? "阅读" : mode === "library" ? "书架" : mode === "practice" ? "练习" : mode === "review" ? "复习" : mode === "logs" ? "日志" : "统计";
}

function setHomeMode() {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("home"); renderHome(); window.scrollTo({ top: 0, behavior: "auto" });
}

function setLibraryMode() {
  state.openRequest += 1; stopReadingTimer();
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden"); $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library"); closeNotePopover(); window.scrollTo({ top: 0, behavior: "auto" });
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

async function flushReadingTime({ beacon = false, refresh = false } = {}) {
  collectReadingTime();
  const seconds = Math.min(600, Math.floor(state.readingPendingSeconds));
  if (seconds < 1 || !state.readingSectionId) return;
  const sectionId = state.readingSectionId; state.readingPendingSeconds -= seconds;
  const body = JSON.stringify({ section_id: sectionId, seconds });
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon("/api/reading-time", new Blob([body], { type: "application/json" })); return;
  }
  try {
    const response = await fetch("/api/reading-time", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
    if (!response.ok) throw new Error("timer save failed");
    if (refresh) loadStats();
  } catch { state.readingPendingSeconds += seconds; }
}

function startReadingTimer(sectionId) {
  collectReadingTime(); flushReadingTime();
  state.readingSectionId = sectionId; state.readingActive = true; state.readingLastTick = Date.now(); state.readingLastScroll = state.readingLastTick;
}

function stopReadingTimer() {
  collectReadingTime(); state.readingActive = false; flushReadingTime({ refresh: true });
}

function markReadingScroll() {
  if (!state.readingActive || !state.readingSectionId) return;
  collectReadingTime(); state.readingLastScroll = Date.now(); state.readingLastTick = state.readingLastScroll;
}

function renderHome() {
  const stats = state.stats || {};
  const today = stats.today ? new Date(`${stats.today}T00:00:00`) : new Date();
  const hour = new Date().getHours();
  $("homeDate").textContent = today.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("homeGreeting").textContent = hour < 11 ? "早上好，从一小节开始" : hour < 18 ? "今天继续读一点" : "晚上好，留下一点理解";
  $("homeLeadText").textContent = stats.last_section ? `上次读到《${stats.last_section.book_title}》的“${stats.last_section.title}”。` : "书架已经准备好，选择一个小节开始今天的学习。";
  $("homeContinueTitle").textContent = stats.last_section ? `${stats.last_section.book_title} · ${stats.last_section.title}` : "打开书架选择章节";
  $("homeContinue").dataset.sectionId = stats.last_section?.id || "";
  $("homeTodayDuration").textContent = formatDuration(stats.today_reading_seconds, true);
  $("homeTodaySections").textContent = `${formatInteger(stats.today_section_count)} 个小节`;
  $("homeTodayNotes").textContent = `${formatInteger(stats.today_note_count)} 节笔记`;
  $("homeReviewHint").textContent = stats.today_review_saved ? "今日复习已经沉淀" : "读取昨天的章节笔记";

  const recentBookId = stats.last_section?.book_id;
  const shelfWidth = $("homeBookShelf").clientWidth;
  const desktopCapacity = shelfWidth ? Math.floor((shelfWidth + 18) / 130) : 6;
  const bookLimit = window.matchMedia("(max-width: 760px)").matches ? 3 : Math.max(1, Math.min(6, desktopCapacity));
  const books = [...state.books].sort((a, b) => Number(b.id === recentBookId) - Number(a.id === recentBookId)).slice(0, bookLimit);
  $("homeBookShelf").innerHTML = books.length ? books.map((book) => `<button type="button" class="reader-home-book" data-home-book="${escapeHtml(book.id)}" aria-label="打开《${escapeHtml(book.title)}》"><span class="reader-book-cover"><strong>${bookCoverTitle(book.title)}</strong><em>${escapeHtml(book.edition || "")}</em></span><span><strong>${escapeHtml(book.title)}</strong><small>${book.sections.length} 个小节</small></span></button>`).join("") : `<div class="reader-home-book-empty">书架中还没有可阅读的书籍</div>`;
  $("homeBookShelf").querySelectorAll("[data-home-book]").forEach((button) => button.addEventListener("click", () => openResource(button.dataset.homeBook)));
  refreshIcons();
}

function activityLevel(count, maximum) {
  if (!count || !maximum) return 0;
  return Math.min(4, Math.max(1, Math.ceil((Math.log(count + 1) / Math.log(maximum + 1)) * 4)));
}

function renderStats() {
  const stats = state.stats || {};
  const coverage = Number(stats.note_coverage || 0);
  $("statsCoverage").textContent = `${coverage.toFixed(coverage % 1 ? 1 : 0)}%`;
  $("statsTodayDuration").textContent = formatDuration(stats.today_reading_seconds, true);
  $("statsTotalDuration").textContent = formatDuration(stats.total_reading_seconds, true);
  $("statsNoted").textContent = formatInteger(stats.noted_section_count);
  $("statsCharacters").textContent = formatInteger(stats.note_character_count);
  $("statsActiveDays").textContent = formatInteger(stats.active_day_count);
  $("statsStreak").textContent = `${formatInteger(stats.streak)} 天`;
  $("activitySummary").textContent = `近 ${stats.weeks || 12} 周 · ${formatDuration(stats.heatmap_total_seconds)}`;

  const days = stats.days || [];
  const weeks = Math.max(1, stats.weeks || 12);
  $("activityGrid").style.setProperty("--reader-activity-weeks", weeks);
  $("activityMonths").style.setProperty("--reader-activity-weeks", weeks);
  $("activityGrid").innerHTML = days.map((day) => {
    const level = activityLevel(day.count, stats.max);
    const label = new Date(`${day.date}T00:00:00`).toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
    const details = `${formatDuration(day.reading_seconds)} · ${day.section_count} 个小节`;
    return `<span class="reader-activity-cell level-${level}${day.future ? " future" : ""}${day.date === stats.today ? " today" : ""}" title="${escapeHtml(`${label}：${details}`)}" aria-label="${escapeHtml(`${label}，${details}`)}"></span>`;
  }).join("");
  const monthLabels = [];
  for (let week = 0; week < weeks; week += 1) {
    const day = days[week * 7];
    const month = day ? new Date(`${day.date}T00:00:00`).getMonth() : -1;
    const previous = week && days[(week - 1) * 7] ? new Date(`${days[(week - 1) * 7].date}T00:00:00`).getMonth() : -1;
    monthLabels.push(`<span>${week === 0 || month !== previous ? `${month + 1}月` : ""}</span>`);
  }
  $("activityMonths").innerHTML = monthLabels.join("");

  const distribution = stats.book_distribution || [];
  const maximum = Math.max(1, ...distribution.map((item) => item.note_count));
  $("bookDistribution").innerHTML = distribution.length ? distribution.map((item) => `<button type="button" class="reader-distribution-row" data-stats-book="${escapeHtml(item.book_id)}"><span><strong>${escapeHtml(item.title)}</strong><small>${item.note_count} / ${item.section_count} 节</small></span><span class="reader-distribution-track"><i style="--reader-progress:${Math.round(item.note_count / maximum * 100)}%"></i></span><em>${item.section_count ? Math.round(item.note_count / item.section_count * 100) : 0}%</em></button>`).join("") : `<div class="reader-home-book-empty">暂无书目数据</div>`;
  $("bookDistribution").querySelectorAll("[data-stats-book]").forEach((button) => button.addEventListener("click", () => openResource(button.dataset.statsBook)));
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
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("stats"); window.scrollTo({ top: 0, behavior: "auto" });
  await loadStats();
}

function reviewDateLabel(value) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}

function setReviewPanel(mode) {
  document.querySelector(".review-heading").classList.toggle("hidden", mode !== "tasks");
  $("reviewTaskList").classList.toggle("hidden", mode !== "tasks");
  $("reviewEmpty").classList.toggle("hidden", mode !== "tasks" || Boolean(state.review?.subjects?.length));
  $("reviewSubjectDetail").classList.toggle("hidden", mode !== "subject");
  $("reviewReportPanel").classList.toggle("hidden", mode !== "report");
  $("reviewReportEntry").classList.toggle("hidden", mode !== "tasks" || !state.review?.all_complete);
}

function renderReviewTasks() {
  const review = state.review; const subjects = review?.subjects || [];
  $("reviewTitle").textContent = review ? `${reviewDateLabel(review.review_date)}的复习` : "复习";
  $("reviewSummary").textContent = review ? `${subjects.length} 个学科 · ${review.note_count} 条章节笔记` : "正在整理前一天保存的章节笔记…";
  $("reviewProgressText").textContent = `${review?.completed_count || 0} / ${subjects.length}`;
  $("reviewTaskList").innerHTML = subjects.map((subject) => `<button class="review-task-row ${subject.completed ? "completed" : ""}" type="button" data-review-book="${escapeHtml(subject.book_id)}"><span class="review-task-state"><i data-lucide="${subject.completed ? "circle-check" : "circle"}"></i></span><span class="review-task-name"><strong>${escapeHtml(subject.title)}</strong><small>${subject.completed ? "复习成果已归档" : "等待侧边栏复习"}</small></span><span><small>笔记</small><strong>${subject.note_count}</strong></span><span><small>字数</small><strong>${formatInteger(subject.character_count)}</strong></span><span><small>学习时长</small><strong>${subject.time_tracked ? formatDuration(subject.reading_seconds) : "暂无记录"}</strong></span><i data-lucide="arrow-right"></i></button>`).join("");
  $("reviewTaskList").querySelectorAll("[data-review-book]").forEach((button) => button.addEventListener("click", () => openReviewSubject(button.dataset.reviewBook)));
  setReviewPanel("tasks"); refreshIcons();
}

function openReviewSubject(bookId) {
  const subject = state.review?.subjects?.find((item) => item.book_id === bookId); if (!subject) return;
  state.reviewSubjectId = bookId; $("reviewSubjectTitle").textContent = subject.title; $("reviewSubjectMeta").textContent = `${subject.note_count} 条笔记 · ${formatInteger(subject.character_count)} 字 · ${subject.time_tracked ? formatDuration(subject.reading_seconds) : "暂无分科学习时长"}`;
  $("reviewSubjectNotes").innerHTML = subject.notes.map((item) => `<section class="review-note-entry"><header><div><small>${escapeHtml(item.chapter_title || subject.title)}</small><h3>${escapeHtml(item.section_title)}</h3></div><button class="icon-button" type="button" data-review-section="${escapeHtml(item.section_id)}" aria-label="打开原章节"><i data-lucide="arrow-up-right"></i></button></header><div class="knowledge-article note-stream">${renderMarkdown(item.markdown)}</div></section>`).join("");
  $("reviewSubjectNotes").querySelectorAll("[data-review-section]").forEach((button) => button.addEventListener("click", () => { state.readerOriginBookId = null; openSection(button.dataset.reviewSection); }));
  $("reviewSubjectResult").value = subject.result || ""; $("reviewSubjectSaved").textContent = subject.completed ? "已保存 · 待办完成" : "粘贴后自动保存并完成待办";
  setReviewPanel("subject"); refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

function openReviewReport() {
  if (!state.review?.all_complete) return;
  $("reviewCombinedDocument").innerHTML = renderMarkdown(state.review.combined_markdown || "");
  $("reviewDailySummary").value = state.review.daily_summary || ""; $("reviewSummarySaved").textContent = state.review.daily_summary?.trim() ? "已保存到日志开头" : "粘贴后自动保存到文档开头";
  $("reviewLogObsidian").href = state.review.log_uri || "obsidian://open"; setReviewPanel("report"); refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

async function openReview() {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("review"); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const response = await fetch("/api/reviews", { cache: "no-store" });
    if (!response.ok) throw new Error("review unavailable");
    state.review = await response.json(); state.reviewSubjectId = ""; renderReviewTasks();
  } catch {
    $("reviewSummary").textContent = "暂时无法读取本地复习内容"; $("reviewEmpty").classList.remove("hidden");
  }
}

function scheduleSubjectReviewSave() {
  if (!state.review || !state.reviewSubjectId) return; const content = $("reviewSubjectResult").value; $("reviewSubjectSaved").textContent = "保存中…"; window.clearTimeout(state.reviewSubjectSaveTimer);
  state.reviewSubjectSaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/review-subject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: state.review.review_date, book_id: state.reviewSubjectId, content }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); state.review = result.review; const subject = state.review.subjects.find((item) => item.book_id === state.reviewSubjectId); $("reviewSubjectSaved").textContent = subject?.completed ? "已保存 · 待办完成" : "已清空 · 待办未完成"; if (!$("reviewTaskList").classList.contains("hidden")) renderReviewTasks(); loadStats(); } catch { $("reviewSubjectSaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

function scheduleDailySummarySave() {
  if (!state.review?.all_complete) return; const content = $("reviewDailySummary").value; $("reviewSummarySaved").textContent = "保存中…"; window.clearTimeout(state.reviewSummarySaveTimer);
  state.reviewSummarySaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/review-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: state.review.review_date, content }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); state.review = result.review; $("reviewSummarySaved").textContent = content.trim() ? "已保存到日志开头" : "总述已清空"; $("reviewCombinedDocument").innerHTML = renderMarkdown(state.review.combined_markdown || ""); $("reviewLogObsidian").href = result.obsidian_uri || state.review.log_uri || "obsidian://open"; loadStats(); } catch { $("reviewSummarySaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

async function openLogs() {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("logs"); window.scrollTo({ top: 0, behavior: "auto" });
  try { const response = await fetch("/api/logs", { cache: "no-store" }); if (!response.ok) throw new Error("logs unavailable"); state.logs = await response.json(); renderLogsList(); } catch { $("logsList").innerHTML = `<div class="review-empty"><strong>暂时无法读取学习日志</strong></div>`; }
}

function renderLogsList() {
  $("logsDetail").classList.add("hidden"); $("weeklyReport").classList.add("hidden"); $("logsList").classList.remove("hidden"); const entries = state.logs?.entries || []; const weeks = state.logs?.weekly_entries || [];
  const dailyRows = entries.length ? entries.map((entry) => `<button class="log-mail-row" type="button" data-log-date="${entry.date}"><span><strong>${reviewDateLabel(entry.date)}</strong><small>${entry.has_summary ? "已有昨日日志总述" : "分科复习归档"}</small></span><span>${entry.subject_count} 个学科</span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="review-empty"><i data-lucide="mail-open"></i><strong>还没有学习日志</strong><span>完成一次昨日复习后，归档会出现在这里。</span></div>`;
  const weeklyRows = weeks.length ? `<div class="log-section-label"><span>周报归档</span><small>${weeks.length} 份</small></div>${weeks.map((entry) => `<button class="log-mail-row weekly" type="button" data-log-week="${entry.week}"><span><strong>${entry.week} 周报</strong><small>阶段性复习档案</small></span><span></span><span>${formatInteger(entry.character_count)} 字</span><i data-lucide="arrow-right"></i></button>`).join("")}` : "";
  $("logsList").innerHTML = `${dailyRows}${weeklyRows}`;
  $("logsList").querySelectorAll("[data-log-date]").forEach((button) => button.addEventListener("click", () => openLogDetail(button.dataset.logDate)));
  $("logsList").querySelectorAll("[data-log-week]").forEach((button) => button.addEventListener("click", () => openWeeklyReport(button.dataset.logWeek))); refreshIcons();
}

async function openLogDetail(day) {
  const response = await fetch(`/api/logs?date=${encodeURIComponent(day)}`, { cache: "no-store" }); if (!response.ok) return; const payload = await response.json(); const detail = payload.detail; if (!detail) return;
  $("logsList").classList.add("hidden"); $("logsDetail").classList.remove("hidden"); $("logsArticle").innerHTML = renderMarkdown(detail.content); $("logsObsidianLink").href = detail.obsidian_uri || "obsidian://open"; refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

async function openWeeklyReport(week = "") {
  const suffix = typeof week === "string" && week ? `?week=${encodeURIComponent(week)}` : ""; const response = await fetch(`/api/weekly-report${suffix}`, { cache: "no-store" }); if (!response.ok) return; state.weekly = await response.json(); $("logsList").classList.add("hidden"); $("logsDetail").classList.add("hidden"); $("weeklyReport").classList.remove("hidden"); $("weeklyTitle").textContent = `${state.weekly.week} 周报`; $("weeklyMeta").textContent = `${state.weekly.start} 至 ${state.weekly.end} · ${state.weekly.day_count} 篇每日总结`; $("weeklySource").innerHTML = renderMarkdown(state.weekly.source_markdown); $("weeklySummary").value = state.weekly.report || ""; $("weeklyObsidianLink").href = state.weekly.obsidian_uri || "obsidian://open"; refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

function scheduleWeeklySave() {
  if (!state.weekly) return; const content = $("weeklySummary").value; $("weeklySaved").textContent = "保存中…"; window.clearTimeout(state.weeklySaveTimer); state.weeklySaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/weekly-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ week: state.weekly.week, content }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); $("weeklySaved").textContent = content.trim() ? "已保存为独立周报" : "周报已清空"; $("weeklyObsidianLink").href = result.obsidian_uri || "obsidian://open"; const logsResponse = await fetch("/api/logs", { cache: "no-store" }); if (logsResponse.ok) state.logs = await logsResponse.json(); } catch { $("weeklySaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

function searchableBook(book) {
  return `${book.title} ${book.id} ${bookToc(book).map((chapter) => `${chapter.title} ${chapter.sections.map((section) => section.title).join(" ")}`).join(" ")}`.toLowerCase();
}

function domainBooks() {
  return state.books.filter((book) => (book.domain || "medicine") === state.libraryDomain);
}

function renderDomainTabs() {
  const counts = {};
  DOMAIN_ORDER.forEach((domain) => { counts[domain] = state.books.filter((book) => (book.domain || "medicine") === domain).length; });
  document.querySelectorAll("[data-domain]").forEach((button) => {
    const domain = button.dataset.domain;
    button.classList.toggle("active", domain === state.libraryDomain);
    const badge = button.querySelector("em");
    if (badge) badge.textContent = String(counts[domain] || 0);
  });
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
  const query = filter.trim().toLowerCase(); const tree = $("bookTree");
  const matchedBooks = domainBooks().filter((book) => !query || searchableBook(book).includes(query));
  if (!matchedBooks.length) {
    tree.innerHTML = query
      ? `<div class="knowledge-index-empty"><i data-lucide="search-x"></i><strong>没有找到匹配内容</strong><span>换一个书名或章节关键词试试。</span></div>`
      : `<div class="knowledge-index-empty"><i data-lucide="library"></i><strong>${escapeHtml(DOMAIN_LABELS[state.libraryDomain] || "医学")}书架还是空的</strong><span>这个领域还没有正式资料，放入书架后刷新页面。</span></div>`;
    refreshIcons(); return;
  }
  const covers = matchedBooks.map((book) => `<button class="reader-book-overview ${book.id === state.resourceBookId ? "active" : ""}" type="button" data-library-book="${escapeHtml(book.id)}" title="打开《${escapeHtml(book.title)}》资料学习主页" aria-label="打开《${escapeHtml(book.title)}》资料学习主页"><span class="reader-book-cover" aria-hidden="true"><strong>${bookCoverTitle(book.title)}</strong><em>${escapeHtml(book.edition || "")}</em></span></button>`).join("");
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

async function openResource(bookId) {
  if (!bookId) return;
  state.openRequest += 1; stopReadingTimer(); closeNotePopover();
  $("libraryWorkspace").classList.remove("reader-open");
  $("libraryWorkspace").classList.add("resource-open");
  $("readerContent").classList.add("hidden");
  $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library");
  state.resourceBookId = bookId;
  try {
    const response = await fetch(`/api/resource/${encodeURIComponent(bookId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("resource unavailable");
    const payload = await response.json();
    if (state.resourceBookId !== bookId) return;
    state.resource = payload; renderResource(); loadResourcePractice(bookId);
  } catch {
    if (state.resourceBookId !== bookId) return;
    $("resourceFacts").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取这份资料</strong><span>请确认书架服务正在运行。</span></div>`;
  }
  renderBooks($("librarySearch").value); window.scrollTo({ top: 0, behavior: "auto" });
}

function returnFromResource() {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover();
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
  $("sectionNote").value = section.note || ""; $("noteSavedText").textContent = section.note?.trim() ? "已保存到本节" : "输入后自动保存";
  state.material = "cleaned"; closeSectionMenu(); closeNotePopover(); renderSectionMenu(); renderMaterial(); setNavigationState(); renderBooks($("librarySearch").value); loadSectionPractice(); window.scrollTo({ top: 0, behavior: "smooth" });
}

function practiceEntryLabel(entry) {
  return entry.match_level === "comprehensive" ? "综合测试" : entry.match_level === "chapter" ? "本章练习" : "本节练习";
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

async function openPractice(entry, returnTo) {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); state.practiceReturn = returnTo; state.practiceIndex = 0;
  try {
    const query = new URLSearchParams({ bank_id: entry.bank_id, knowledge_id: entry.knowledge_id, match_level: entry.match_level });
    const response = await fetch(`/api/practice/session?${query}`, { cache: "no-store" }); if (!response.ok) throw new Error("practice unavailable");
    state.practice = { ...(await response.json()), entry }; setActiveView("practice"); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
  } catch { showToast("暂时无法读取这组题目"); }
}

async function renderPracticeQuestion() {
  const practice = state.practice; const item = practice?.questions?.[state.practiceIndex]; if (!item) return;
  $("practiceEyebrow").textContent = practice.entry.match_level === "comprehensive" ? "综合测试 · 真实题库" : `${practiceEntryLabel(practice.entry)} · 真实题库`;
  $("practiceTitle").textContent = practice.bank.title; $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题`;
  $("practiceProgressText").textContent = `${state.practiceIndex + 1} / ${practice.question_count}`; $("practiceProgressBar").style.setProperty("--practice-progress", `${((state.practiceIndex + 1) / practice.question_count) * 100}%`);
  $("practiceResult").classList.add("hidden"); $("practiceSubmit").classList.remove("hidden"); $("practiceSubmit").disabled = false; $("practiceSubmit").querySelector("strong").textContent = "查看答案与解析";
  const query = new URLSearchParams({ bank_id: practice.bank.id, question_id: item.question_id }); const response = await fetch(`/api/practice/question?${query}`, { cache: "no-store" }); if (!response.ok) { showToast("题目读取失败"); return; }
  const payload = await response.json(); const question = payload.question; state.practice.question = payload;
  $("practiceQuestionType").textContent = question.question_type === "multiple_choice" ? "多项选择" : "单项选择"; $("practiceQuestionNumber").textContent = `第 ${state.practiceIndex + 1} 题`;
  $("practiceStem").innerHTML = renderMarkdown(question.stem_md || ""); const prior = payload.attempt?.selected_answers || [];
  $("practiceOptions").innerHTML = (question.options || []).map((option) => `<label><input type="${question.question_type === "multiple_choice" ? "checkbox" : "radio"}" name="practice-answer" value="${escapeHtml(option.label)}" ${prior.includes(option.label) ? "checked" : ""}><span><strong>${escapeHtml(option.label)}</strong><em>${renderMarkdown(option.text_md || "")}</em></span></label>`).join("");
  $("practicePrevious").disabled = state.practiceIndex === 0; $("practiceNext").disabled = state.practiceIndex >= practice.question_count - 1;
  if (payload.attempt) showPracticeResult(payload); refreshIcons();
}

function showPracticeResult(payload) {
  const question = payload.question; const attempt = payload.attempt || {}; $("practiceSubmit").classList.add("hidden"); $("practiceResult").classList.remove("hidden");
  $("practiceResultTitle").textContent = attempt.correct ? "回答正确" : "继续梳理这个知识点"; $("practiceCorrectAnswer").textContent = `正确答案：${(question.correct_answers || []).join("、")}`;
  $("practiceSourceAnalysis").innerHTML = renderMarkdown(question.source_analysis_md || "暂无原书解析"); $("practicePersonalAnalysis").value = payload.personal_analysis || ""; $("practiceAnalysisSaved").textContent = payload.personal_analysis?.trim() ? "已保存到练习笔记" : "粘贴侧边栏的分析，自动保存"; refreshIcons();
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

function returnFromPractice() { if (state.practiceReturn === "resource" && state.resourceBookId) openResource(state.resourceBookId); else if (state.current?.id) setReaderMode(); else setLibraryMode(); }

function renderMaterial() {
  const article = $("knowledgeArticle"); const source = state.material === "note" ? state.current?.note : state.current?.markdown;
  const imageBase = state.current?.book_id ? `/api/book-assets/${encodeURIComponent(state.current.book_id)}/` : "";
  article.classList.toggle("note-stream", state.material === "note");
  article.innerHTML = state.material === "note" && !state.current?.note?.trim() ? `<div class="section-material-empty"><i data-lucide="notebook-pen"></i><strong>这一节还没有笔记</strong><span>打开右下角笔记入口，粘贴 AI 整理结果即可。</span></div>` : renderMarkdown(source || "暂无内容", imageBase);
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
      if (!response.ok) throw new Error("save failed");
      const cached = state.sections.get(sectionId); if (cached) state.sections.set(sectionId, { ...cached, note: content });
      if (state.current?.id !== sectionId) return;
      state.current.note = content; $("noteSavedText").textContent = content.trim() ? "已自动保存" : "输入后自动保存"; $("readerNoteMeta").textContent = content.trim() ? "已有笔记" : "暂无笔记"; if (state.material === "note") renderMaterial(); loadStats();
    } catch { if (state.current?.id === sectionId) $("noteSavedText").textContent = "保存失败，请稍后重试"; }
  }, 420);
}

function bindNavigation() {
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.addEventListener("click", setHomeMode));
  $("libraryNav").addEventListener("click", setLibraryMode); $("mobileLibrary").addEventListener("click", setLibraryMode);
  document.querySelectorAll("[data-domain]").forEach((button) => button.addEventListener("click", () => { state.libraryDomain = button.dataset.domain; state.inlineBookId = null; renderBooks($("librarySearch").value); }));
  $("resourceBack").addEventListener("click", returnFromResource);
  $("resourceContinue").addEventListener("click", () => { const sectionId = $("resourceContinue").dataset.sectionId; if (sectionId) { state.readerOriginBookId = state.resourceBookId; state.inlineBookId = null; openSection(sectionId); } });
  $("practiceBack").addEventListener("click", returnFromPractice); $("practiceSubmit").addEventListener("click", submitPracticeAnswer); $("practicePrevious").addEventListener("click", () => { if (state.practiceIndex > 0) { state.practiceIndex -= 1; renderPracticeQuestion(); } }); $("practiceNext").addEventListener("click", () => { if (state.practiceIndex < (state.practice?.question_count || 1) - 1) { state.practiceIndex += 1; renderPracticeQuestion(); } }); $("practicePersonalAnalysis").addEventListener("input", schedulePracticeAnalysisSave);
  $("reviewNav").addEventListener("click", openReview); $("mobileReview").addEventListener("click", openReview);
  $("logsNav").addEventListener("click", openLogs); $("mobileLogs").addEventListener("click", openLogs);
  $("statsNav").addEventListener("click", openStats); $("mobileStats").addEventListener("click", openStats);
  $("homeOpenLibrary").addEventListener("click", setLibraryMode); $("homeAllBooks").addEventListener("click", setLibraryMode); $("homeOpenReview").addEventListener("click", openReview); $("homeOpenStats").addEventListener("click", openStats);
  $("homeContinue").addEventListener("click", () => { const sectionId = $("homeContinue").dataset.sectionId; state.readerOriginBookId = null; if (sectionId) openSection(sectionId); else setLibraryMode(); });
  window.addEventListener("resize", () => { window.clearTimeout(state.homeResizeTimer); state.homeResizeTimer = window.setTimeout(() => { if ($("homeView").classList.contains("active")) renderHome(); }, 120); });
  $("sidebar").addEventListener("mouseenter", () => $("sidebar").classList.add("is-expanded")); $("sidebar").addEventListener("mouseleave", () => $("sidebar").classList.remove("is-expanded"));
  $("readerBack").addEventListener("click", returnFromReader); $("readerBook").addEventListener("click", returnFromReader);
  $("readerSectionPicker").addEventListener("click", () => { const menu = $("readerCrumbMenu"); const willOpen = menu.classList.contains("hidden"); if (willOpen) { renderSectionMenu(); menu.classList.remove("hidden"); $("readerSectionPicker").classList.add("active"); $("readerSectionPicker").setAttribute("aria-expanded", "true"); } else closeSectionMenu(); });
  [$("readerPreviousSection"), $("previousSection")].forEach((button) => button.addEventListener("click", () => navigateSection(-1))); [$("readerNextSection"), $("nextSectionLink")].forEach((button) => button.addEventListener("click", () => navigateSection(1)));
  $("toggleSectionNoteDock").addEventListener("click", (event) => state.noteOpen ? closeNotePopover() : openNotePopover(event.currentTarget)); $("closeSectionNote").addEventListener("click", () => closeNotePopover({ restoreFocus: true })); $("sectionNote").addEventListener("input", scheduleNoteSave);
  $("reviewSubjectBack").addEventListener("click", renderReviewTasks); $("reviewReportBack").addEventListener("click", renderReviewTasks); $("reviewReportEntry").addEventListener("click", openReviewReport); $("reviewSubjectResult").addEventListener("input", scheduleSubjectReviewSave); $("reviewDailySummary").addEventListener("input", scheduleDailySummarySave);
  $("logsBack").addEventListener("click", renderLogsList); $("weeklyBack").addEventListener("click", renderLogsList); $("openWeeklyReport").addEventListener("click", openWeeklyReport); $("weeklySummary").addEventListener("input", scheduleWeeklySave);
  document.querySelectorAll("[data-section-material]").forEach((button) => button.addEventListener("click", () => { state.material = button.dataset.sectionMaterial; renderMaterial(); })); $("librarySearch").addEventListener("input", (event) => renderBooks(event.target.value)); document.addEventListener("click", (event) => { if (!event.target.closest(".reader-toolbar")) closeSectionMenu(); });
  document.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (state.noteOpen) { closeNotePopover({ restoreFocus: true }); return; } closeSectionMenu(); });
}

function initializeReadingTimer() {
  window.addEventListener("scroll", markReadingScroll, { passive: true });
  document.addEventListener("visibilitychange", () => { collectReadingTime(); if (document.hidden) flushReadingTime(); });
  window.addEventListener("pagehide", () => flushReadingTime({ beacon: true }));
  window.setInterval(() => { collectReadingTime(); if (state.readingPendingSeconds >= READING_FLUSH_SECONDS) flushReadingTime(); }, 5000);
}

async function loadBootstrap() {
  try {
    const response = await fetch("/api/bootstrap", { cache: "no-store" }); const data = await response.json(); state.books = data.books || [];
    state.books.forEach((book) => book.sections.forEach((section) => state.sections.set(section.id, { ...section, book_title: book.title, book_id: book.id }))); renderBooks(); await loadStats();
  } catch { $("bookTree").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取本地书架</strong><span>请确认 YuReader 服务正在运行。</span></div>`; refreshIcons(); }
}

bindNavigation(); initializeReadingTimer(); refreshIcons(); loadBootstrap();
