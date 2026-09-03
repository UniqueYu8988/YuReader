import { $, BOOK_COVER_LABELS, THEME_STORAGE_KEY, state } from "./state.js";

export const { inlineMarkdown, renderMarkdown } = window.YuReaderMarkdown.create(escapeHtml);
if (typeof window !== 'undefined') { window.renderMarkdown = renderMarkdown; window.inlineMarkdown = inlineMarkdown; }

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

export function formatInteger(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value || 0));
}

export function formatDuration(seconds, compact = false) {
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

export function formatCharacters(value) {
  const count = Number(value || 0);
  if (!count) return "";
  return count >= 10000 ? `${(count / 10000).toFixed(1)} 万字` : `${(count / 1000).toFixed(1)} 千字`;
}

export function showToast(message) {
  const toast = $("toast"); toast.textContent = message; toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => toast.classList.remove("is-visible"), 2200);
}

export function refreshIcons() {
  window.lucide?.createIcons?.({ attrs: { "stroke-width": 1.7 } });
}

export function normalizeSectionHeading(value) {
  return String(value || "").normalize("NFKC").replace(/[*_`~#]/g, "").replace(/[\s·•:：,，。.!！?？()（）\[\]【】]/g, "").toLowerCase();
}

export function displayGuideTitle(value) {
  return String(value || "").replace(/^\s*[、．.]\s*/, "").trim();
}

export function prepareSectionMarkdown(markdown, sectionTitle) {
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

export function renderSectionGuide(article, guideElement, guideItems, kind) {
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

export function bookToc(book) {
  if (book.toc?.length) return book.toc;
  return [{ id: `${book.id}-contents`, order: 1, title: "目录", sections: book.sections || [] }];
}

export function bookCoverTitle(book) {
  const shortTitle = BOOK_COVER_LABELS[book?.id];
  if (shortTitle) return escapeHtml(shortTitle);
  const text = String(book?.title || "本地书籍").trim();
  const splitAt = text.startsWith("口腔") && text.length > 2 ? 2 : Math.ceil(text.length / 2);
  return `${escapeHtml(text.slice(0, splitAt))}<br>${escapeHtml(text.slice(splitAt))}`;
}

export function searchableBook(book) {
  return `${book.title} ${book.id} ${bookToc(book).map((chapter) => `${chapter.title} ${chapter.sections.map((section) => section.title).join(" ")}`).join(" ")}`.toLowerCase();
}

export function applyTheme(theme, { persist = true } = {}) {
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

export function toggleTheme() {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
}