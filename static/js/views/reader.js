import { setActiveView, setLibraryMode, setReaderMode } from "../core/router.js";
import { $, DOMAIN_LABELS, state } from "../core/state.js";
import { stopReadingTimer } from "../core/timer.js";
import { bookCoverTitle, bookToc, escapeHtml, formatCharacters, prepareSectionMarkdown, refreshIcons, renderMarkdown, renderSectionGuide, showToast } from "../core/utils.js";
import { bindEnglishCenterGroups, englishPanel, englishShelfBooks, loadEnglishCenterOverview, renderEnglishCenter, selectedEnglishBank } from "../domains/english.js";
import { renderMedicineCenter } from "../domains/medicine.js";
import { bindPoliticsEvents, renderPoliticsCenter } from "../domains/politics.js";
import { openOralFocusIndex } from "../modules/oral_focus.js";
import { loadResourcePractice, loadSectionPractice, openPractice } from "../modules/practice.js";
import { bindMistakesEvents, loadMistakes, renderMistakes } from "../domains/mistakes.js";
import { loadStats } from "./logs.js";

export function domainBooks() {
  if (state.libraryDomain === "english") return englishShelfBooks();
  return state.books.filter((book) => (book.domain || "medicine") === state.libraryDomain);
}

export function renderDomainTabs() {
  document.querySelectorAll("[data-shelf]").forEach((button) => {
    const shelf = button.dataset.shelf;
    const active = shelf === state.libraryDomain;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

export function sectionEntryHtml(section) {
  return `<button class="reader-section-entry ${section.id === state.current?.id ? "active" : ""}" type="button" data-section-id="${escapeHtml(section.id)}"><span>${String(section.section_order || 1).padStart(2, "0")}</span><span><strong>${escapeHtml(section.title)}</strong><small>${formatCharacters(section.character_count) || "阅读小节"}</small></span><i data-lucide="arrow-up-right"></i></button>`;
}

export function chapterListHtml(book, chapters, { openAll = false } = {}) {
  return `<div class="reader-chapter-list">${chapters.map((chapter) => {
    const chapterOpen = openAll ? true : (chapter.id === state.current?.chapter_id || chapter.order === 1);
    return `<details class="reader-chapter-group" data-chapter-id="${escapeHtml(chapter.id)}" ${chapterOpen ? "open" : ""}>
      <summary><span>${String(chapter.order).padStart(2, "0")}</span><strong>${escapeHtml(chapter.title)}</strong><em>${chapter.sections.length} 节</em><i data-lucide="chevron-right"></i></summary>
      <div class="reader-section-list">${chapter.sections.map((section) => sectionEntryHtml(section)).join("")}</div>
    </details>`;
  }).join("")}</div>`;
}

export function learningRailSize() {
  if (window.innerWidth <= 560) return 4;
  if (window.innerWidth <= 840) return 6;
  if (window.innerWidth <= 1100) return 8;
  return 10;
}

export function recentFirstBooks(books, domain) {
  const recent = (state.stats?.recent_resources || []).filter((entry) => entry.domain === domain).map((entry) => entry.resource_id);
  const rank = new Map(recent.map((id, index) => [id, index]));
  return [...books].sort((a, b) => {
    const aRank = rank.has(a.id) ? rank.get(a.id) : Number.MAX_SAFE_INTEGER;
    const bRank = rank.has(b.id) ? rank.get(b.id) : Number.MAX_SAFE_INTEGER;
    return aRank - bRank;
  });
}

export function learningSectionHeader(index, title, meta, railId = "", icon = "") {
  const iconHtml = icon ? `<i data-lucide="${escapeHtml(icon)}"></i>` : "";
  return `<header class="learning-section-heading"><div><h3>${iconHtml}<span>${escapeHtml(title)}</span></h3></div>${railId ? `<nav aria-label="${escapeHtml(title)}翻页"><small data-rail-position="${escapeHtml(railId)}"></small><button type="button" data-rail-move="${escapeHtml(railId)}:-1" aria-label="上一组"><i data-lucide="arrow-left"></i></button><button type="button" data-rail-move="${escapeHtml(railId)}:1" aria-label="下一组"><i data-lucide="arrow-right"></i></button></nav>` : ""}</header>`;
}

export function learningBookCard(book, recentId = "") {
  const shortTitle = bookCoverTitle(book);
  return `<button class="learning-book-card${book.id === recentId ? " recent" : ""}" type="button" data-library-book="${escapeHtml(book.id)}" title="《${escapeHtml(book.title)}》" aria-label="打开《${escapeHtml(book.title)}》"><span class="reader-book-cover" aria-hidden="true"><strong>${shortTitle}</strong></span><span class="learning-book-short-name">${shortTitle}</span></button>`;
}

export function learningRailHtml(railId, items, renderItem, customSize = null) {
  const size = customSize || learningRailSize(); const pageCount = Math.max(1, Math.ceil(items.length / size));
  const page = Math.min(pageCount - 1, Math.max(0, Number(state.libraryRailPages[railId] || 0)));
  state.libraryRailPages[railId] = page;
  const visible = items.slice(page * size, page * size + size);
  return `<div class="learning-rail" data-learning-rail="${escapeHtml(railId)}" style="--learning-rail-count:${Math.max(1, Math.min(size, visible.length))}">${visible.map(renderItem).join("") || `<div class="learning-empty"><strong>资料尚未导入</strong><span>板块会保留在这里，导入后自动出现。</span></div>`}</div><span class="hidden" data-rail-pages="${escapeHtml(railId)}" data-page="${page}" data-page-count="${pageCount}"></span>`;
}

export function renderLearningCenterOverview(payload, bankInfo) {
  const container = $("englishUnifiedExamList");
  if (!container || state.libraryDomain !== "english") return;
  const curType = state.englishCenterType || "reading";
  const groups = (payload.groups || []).filter((group) => {
    const start = Number(group.start_number || 0);
    if (!curType || curType === "all") return true;
    return curType === "cloze" ? start <= 20 : curType === "reading" ? start >= 21 && start <= 40 : start >= 41;
  });
  const showSubjective = curType === "all" || curType === "subjective";
  const subjectiveItems = showSubjective ? (payload.subjective?.sections || []) : [];

  let html = "";
  if (curType !== "subjective" && groups.length) {
    html += groups.map((group) => {
      const isReadingText = group.start_number >= 21 && group.end_number <= 40;
      const readingIndex = isReadingText ? `T${Math.floor((group.start_number - 21) / 5) + 1}` : String(group.start_number).padStart(2, "0");
      const range = `第 ${group.start_number}–${group.end_number} 题 · ${group.question_count} 题 · ${group.answered_count || 0}/${group.question_count} 已答`;
      return `<button class="english-paper-row${isReadingText ? " is-reading-text" : ""}" type="button" data-english-objective-bank="${escapeHtml(bankInfo.bank.id)}" data-english-objective-knowledge="${escapeHtml(group.knowledge_id || "")}" data-english-objective-start="${Number(group.start_index || 0)}"><span class="english-paper-row-index">${escapeHtml(readingIndex)}</span><span class="english-paper-row-copy"><small>${escapeHtml(group.part || "真题训练")}</small><strong>${escapeHtml(group.label)}</strong><em>${escapeHtml(range)}</em></span><span class="english-paper-row-status"><strong>进入答题</strong></span><i data-lucide="arrow-right"></i></button>`;
    }).join("");
  }
  if (subjectiveItems.length) {
    html += subjectiveItems.map((item, idx) => `<button class="english-paper-row is-subjective" type="button" data-english-subjective-book="${escapeHtml(item.book_id)}" data-english-subjective-section="${escapeHtml(item.section_id)}" data-english-subjective-bank="${escapeHtml(bankInfo.bank.id)}"><span class="english-paper-row-index">${String(idx + 5).padStart(2, "0")}</span><span class="english-paper-row-copy"><small>${bankInfo.year} · SECTION III / IV</small><strong>${escapeHtml(item.title)}</strong><em>${escapeHtml(item.range || "独立作答")}</em></span><span class="english-paper-row-status"><strong>进入作答</strong></span><i data-lucide="arrow-up-right"></i></button>`).join("");
  }
  if (!html) {
    html = `<div class="learning-empty"><strong>该题型暂无可用题目</strong><span>切换其他年份或题型。</span></div>`;
  }
  container.innerHTML = html;
  bindEnglishCenterGroups();
  refreshIcons();
}

export function bindLearningCenter() {
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
  bindPoliticsEvents();
}

export function renderBooks() {
  renderDomainTabs();
  englishPanel("");
  const tree = $("bookTree");
  const mistakesView = $("libraryMistakesView");

  if (state.libraryDomain === "mistakes") {
    tree.classList.add("hidden");
    mistakesView?.classList.remove("hidden");
    bindMistakesEvents();
    loadMistakes();
  } else {
    mistakesView?.classList.add("hidden");
    tree.classList.remove("hidden");
    tree.innerHTML = state.libraryDomain === "politics" ? renderPoliticsCenter() : state.libraryDomain === "english" ? renderEnglishCenter() : renderMedicineCenter();
    bindLearningCenter();
    if (state.libraryDomain === "english") loadEnglishCenterOverview();
    loadMistakes(); // load badge count in background
  }
  refreshIcons();
}

export function renderResource() {
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

export function renderResourceLoading(book) {
  state.resource = { book, summary: {} };
  renderResource();
  $("resourcePanel").classList.add("is-loading");
  $("resourceProgressTrack").classList.add("is-loading");
  $("resourceProgressTrack").title = "正在读取本地学习记录";
}

export function fetchResource(bookId, force = false) {
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

export function prefetchResource(bookId) {
  if (!bookId || state.resourceCache.has(bookId)) return;
  fetchResource(bookId).catch(() => {});
}

export async function openResource(bookId) {
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

export async function openResourceSection(bookId, sectionId) {
  if (!bookId || !sectionId) return;
  await openResource(bookId);
  if (state.resourceBookId !== bookId) return;
  const book = state.books.find((item) => item.id === bookId);
  if (!book?.sections?.some((section) => section.id === sectionId)) return;
  state.readerOriginBookId = bookId;
  await openSection(sectionId);
}

export async function openSection(sectionId) {
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
  const isWorkbook = book?.id === "english-method-88-sentences";
  const isWordMethod = book?.id === "english-method-wordbook";
  const materialLabel = isWorkbook ? "练习册 · 原书练习模板" : isWordMethod ? "词汇方法补充 · 辅助方法书" : (section.material_kind === "cleaned" ? "清洗正文" : "原始 Markdown");
  const lengthLabel = formatCharacters(section.character_count); $("readerBookMeta").textContent = `${materialLabel}${lengthLabel ? ` · ${lengthLabel}` : ""}`; $("readerBookMeta").title = section.path || materialLabel; $("readerNoteMeta").textContent = section.note?.trim() ? "已有笔记" : "暂无笔记";
  state.material = "cleaned"; closeSectionMenu(); closeChapterQuestions(); closeNotePopover(); renderSectionMenu(); renderChapterQuestions(section.chapter_questions || []); renderMaterial(); setNavigationState(); renderBooks(); loadSectionPractice();
  const savedScroll = Number(localStorage.getItem(`yureader_scroll_${section.id}`) || 0);
  if (savedScroll > 80) {
    window.setTimeout(() => {
      window.scrollTo({ top: savedScroll, behavior: "smooth" });
      showToast("已恢复上次阅读位置");
    }, 120);
  } else {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

let readerScrollTimer = null;
window.addEventListener("scroll", () => {
  if (state.activeView !== "reader" || !state.current?.id) return;
  window.clearTimeout(readerScrollTimer);
  readerScrollTimer = window.setTimeout(() => {
    if (state.activeView === "reader" && state.current?.id) {
      if (window.scrollY > 80) {
        localStorage.setItem(`yureader_scroll_${state.current.id}`, Math.round(window.scrollY));
      } else {
        localStorage.removeItem(`yureader_scroll_${state.current.id}`);
      }
    }
  }, 250);
}, { passive: true });

export function enhanceEnglishReadingLayout(article, bookId) {
  if (!article || !bookId) return;
  if (bookId === "english-method-88-sentences" || bookId === "english-grammar-long-sentences") {
    const templateKeywords = ["结构分析", "谓语", "主干", "词汇梳理", "翻译", "自己翻译", "参考翻译", "写作应用", "总结与反思"];
    article.querySelectorAll("p, h2, h3, h4, h5").forEach((el) => {
      const text = el.textContent.trim().replace(/^[\s·•]+/g, "");
      if (templateKeywords.some((kw) => text === kw || text.startsWith(kw))) {
        el.classList.add("workbook-template-field");
      }
      if (text.startsWith("主干") || text.startsWith("主句")) {
        el.classList.add("syntax-clause", "is-main");
      } else if (text.startsWith("谓语")) {
        el.classList.add("syntax-clause", "is-verb");
      } else if (/^(?:定语从句|状语从句|宾语从句|主语从句|表语从句|同位语从句|从句)/.test(text)) {
        el.classList.add("syntax-clause", "is-sub");
      } else if (/^(?:插入语|伴随状语|独立主格)/.test(text)) {
        el.classList.add("syntax-clause", "is-mod");
      }
    });
  } else if (bookId === "english-method-wordbook") {
    article.querySelectorAll("p").forEach((el) => {
      const text = el.textContent.trim();
      if (!text) return;
      if (/^[a-zA-Z\s-]+\s+(\/[^/]+\/|\[[^\]]+\])/.test(text)) {
        el.classList.add("wordbook-head-block");
      } else if (/^(?:n|v|adj|adv|prep|conj|pron|art|num)\./.test(text)) {
        el.classList.add("wordbook-pos-def");
      } else if (text.startsWith("千方百计记单词")) {
        el.classList.add("wordbook-mnemonic-block");
      } else if (text.startsWith("例")) {
        el.classList.add("wordbook-example-block");
      } else if (text.startsWith("真题")) {
        el.classList.add("wordbook-exam-block");
      } else if (text.startsWith("派生")) {
        el.classList.add("wordbook-derivatives-block");
      }
    });
  }
}

export function enhancePoliticsReadingLayout(article, bookId) {
  if (!article || !bookId || !bookId.startsWith("politics-")) return;
  const assertionRe = /(【(?:核心考点|根本标志|本质属性|本质特征|基本前提|根本立足点|主要矛盾|根本保证|出发点和落脚点|重要转折点|根本动力|第一要务|核心概念|历史意义|基本矛盾|根本矛盾|关键所在)】|(?:根本标志|本质属性|本质特征|基本前提|根本立足点|主要矛盾|根本矛盾|根本保证|出发点和落脚点|重要转折点|根本动力|第一要务|核心概念|关键所在)(?:\s*(?:是|在于|为|贯穿|决定))?|(?:本质上(?:是|属于|统一)|根本上(?:是|讲|属于)|本质就在于))/g;

  const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement?.closest("code, pre, a, h1, h2, h3, .politics-core-assertion, .politics-callout-capsule")) continue;
    if (assertionRe.test(node.textContent)) {
      textNodes.push(node);
    }
    assertionRe.lastIndex = 0;
  }

  textNodes.forEach((node) => {
    const raw = node.textContent;
    assertionRe.lastIndex = 0;
    const html = escapeHtml(raw).replace(assertionRe, '<mark class="politics-core-assertion">$1</mark>');
    const span = document.createElement("span");
    span.innerHTML = html;
    node.replaceWith(span);
  });

  article.querySelectorAll("p").forEach((p) => {
    const text = p.textContent.trim();
    if (/^【(?:核心考点|根本标志|本质属性|基本前提|重点提示|易混辨析|历史意义)】/.test(text)) {
      p.classList.add("politics-callout-capsule");
    }
  });
}

export async function loadSectionPracticeBridge(article, currentSection) {
  if (!article || !currentSection?.book_id || !currentSection?.id) return;
  const existing = document.getElementById("sectionPracticeBridge");
  if (existing) existing.remove();

  try {
    const response = await fetch(`/api/practice/availability?book_id=${encodeURIComponent(currentSection.book_id)}&section_id=${encodeURIComponent(currentSection.id)}`, { cache: "no-store" });
    if (!response.ok || state.current?.id !== currentSection.id) return;
    const payload = await response.json();
    const entry = payload.entries?.[0];
    if (!entry) return;

    const bridgeEl = document.createElement("div");
    bridgeEl.id = "sectionPracticeBridge";
    bridgeEl.className = "section-practice-bridge";
    bridgeEl.innerHTML = `
      <div class="spb-content">
        <span class="spb-badge"><i data-lucide="sparkles"></i> 考点即时测验</span>
        <h4>${escapeHtml(entry.unit_label || entry.label || "本节配套巩固练习")}</h4>
        <p>已通读本节讲义？立即通过配套题库检测掌握程度（共 ${entry.question_count} 题）</p>
      </div>
      <button type="button" class="spb-start-btn" id="spbStartBtn">
        <span>进入测验</span>
        <i data-lucide="arrow-right"></i>
      </button>
    `;
    article.appendChild(bridgeEl);
    bridgeEl.querySelector("#spbStartBtn")?.addEventListener("click", () => openPractice(entry, "reader"));
    refreshIcons();
  } catch {}
}

let lookupPopoverEl = null;
export function initEnglishReadingLookup(article) {
  if (!article || !state.current?.book_id?.startsWith("english-")) return;
  if (!lookupPopoverEl) {
    lookupPopoverEl = document.createElement("div");
    lookupPopoverEl.className = "reading-word-popover hidden";
    document.body.appendChild(lookupPopoverEl);

    document.addEventListener("click", (e) => {
      if (!lookupPopoverEl.contains(e.target) && !lookupPopoverEl.classList.contains("hidden")) {
        lookupPopoverEl.classList.add("hidden");
      }
    });
  }

  article.addEventListener("dblclick", (e) => {
    const sel = window.getSelection();
    const word = sel?.toString()?.trim()?.toLowerCase()?.replace(/[^a-z-]/g, "") || "";
    if (word.length >= 3) {
      showWordPopover(word, e.pageX, e.pageY);
    }
  });
}

function showWordPopover(word, x, y) {
  if (!lookupPopoverEl) return;
  lookupPopoverEl.innerHTML = `
    <div class="rwp-head">
      <strong class="rwp-word">${escapeHtml(word)}</strong>
      <span class="rwp-tag">考研重点词</span>
    </div>
    <div class="rwp-actions">
      <button type="button" class="rwp-note-btn" id="rwpAddNote">
        <i data-lucide="bookmark-plus"></i>
        <span>收录至生词笔记</span>
      </button>
    </div>
  `;
  lookupPopoverEl.style.left = `${Math.min(window.innerWidth - 220, Math.max(10, x - 50))}px`;
  lookupPopoverEl.style.top = `${y + 16}px`;
  lookupPopoverEl.classList.remove("hidden");
  refreshIcons();

  lookupPopoverEl.querySelector("#rwpAddNote")?.addEventListener("click", () => {
    const existing = $("sectionNote").value || "";
    const noteEntry = `- **${word}**: [考研重点词，待复习巩固]`;
    if (!existing.includes(`**${word}**`)) {
      $("sectionNote").value = existing ? `${existing.trim()}\n${noteEntry}` : noteEntry;
      scheduleNoteSave();
      showToast(`已将 "${word}" 收录至本节生词笔记`);
    } else {
      showToast(`"${word}" 已在生词笔记中`);
    }
    lookupPopoverEl.classList.add("hidden");
  });
}

export function renderSectionMenu() {
  const menu = $("readerCrumbMenu"); const book = state.books.find((item) => item.id === state.current?.book_id);
  if (!book) { menu.innerHTML = ""; return; }
  menu.innerHTML = bookToc(book).map((chapter) => `<section><header><span>${String(chapter.order).padStart(2, "0")}</span><strong>${escapeHtml(chapter.title)}</strong></header>${chapter.sections.map((section) => `<button type="button" class="${section.id === state.current.id ? "active" : ""}" data-menu-section="${escapeHtml(section.id)}"><span>${String(section.section_order || 1).padStart(2, "0")} · ${escapeHtml(section.title)}</span><small>${formatCharacters(section.character_count)}</small></button>`).join("")}</section>`).join("");
  menu.querySelectorAll("[data-menu-section]").forEach((button) => button.addEventListener("click", () => { closeSectionMenu(); openSection(button.dataset.menuSection); })); refreshIcons();
}

export function setNavigationState() {
  const book = state.books.find((item) => item.id === state.current?.book_id); const index = book?.sections.findIndex((section) => section.id === state.current.id) ?? -1;
  const previous = index > 0; const next = index >= 0 && index < book.sections.length - 1;
  [$("readerPreviousSection"), $("previousSection")].forEach((button) => { if (button) button.disabled = !previous; });
  [$("readerNextSection"), $("nextSectionLink"), $("readerEndNextSection")].forEach((button) => { if (button) button.disabled = !next; });
  if ($("rseSectionTitle")) $("rseSectionTitle").textContent = state.current?.title ? `“${state.current.title}” 研读达成` : "本节研读已完成";
}

export function returnFromResource() {
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); closeChapterQuestions();
  state.resourceBookId = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open");
  $("readerContent").classList.add("hidden");
  $("sectionNoteFloat").classList.add("hidden");
  setActiveView("library"); window.scrollTo({ top: 0, behavior: "auto" });
  renderBooks();
}

export function returnFromReader() {
  closeChapterQuestions();
  if (state.readerOriginBookId) openResource(state.readerOriginBookId);
  else setLibraryMode();
}

export function finishReaderSession() {
  showToast("本次研读已归档，学时已记入今日画像！");
  const bookId = state.current?.book_id;
  if (bookId) openResource(bookId);
  else setLibraryMode();
}

export function renderMaterial() {
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
    enhanceEnglishReadingLayout(article, state.current?.book_id);
    enhancePoliticsReadingLayout(article, state.current?.book_id);
    loadSectionPracticeBridge(article, state.current);
    initEnglishReadingLookup(article);
  }
  document.querySelectorAll("[data-section-material]").forEach((button) => { const active = button.dataset.sectionMaterial === state.material; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); }); refreshIcons();
}

export function navigateSection(step) {
  const book = state.books.find((item) => item.id === state.current?.book_id); const index = book?.sections.findIndex((section) => section.id === state.current.id) ?? -1; const target = book?.sections[index + step]; if (target) openSection(target.id);
}

export function setNoteControlsExpanded(expanded) {
  document.querySelectorAll('[aria-controls="sectionNotePopover"]').forEach((button) => {
    button.setAttribute("aria-expanded", String(expanded));
    button.classList.toggle("active", expanded);
  });
}

export function openNotePopover(trigger = null) {
  state.noteOpen = true; state.noteTrigger = trigger;
  $("sectionNoteFloat").classList.add("note-is-open"); $("sectionNotePopover").classList.add("is-open"); $("sectionNotePopover").setAttribute("aria-hidden", "false"); setNoteControlsExpanded(true); window.setTimeout(() => $("sectionNote").focus(), 120);
}

export function closeNotePopover({ restoreFocus = false } = {}) {
  const trigger = state.noteTrigger; state.noteOpen = false; state.noteTrigger = null;
  $("sectionNoteFloat")?.classList.remove("note-is-open"); $("sectionNotePopover")?.classList.remove("is-open"); $("sectionNotePopover")?.setAttribute("aria-hidden", "true"); setNoteControlsExpanded(false);
  if (restoreFocus && trigger?.isConnected) trigger.focus();
}

export function closeSectionMenu() { $("readerCrumbMenu")?.classList.add("hidden"); $("readerSectionPicker")?.classList.remove("active"); $("readerSectionPicker")?.setAttribute("aria-expanded", "false"); }


export function scheduleNoteSave() {
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

let currentChapterQuestions = [];
let activeQuestionsFilter = "all";

export function closeChapterQuestions() {
  const drawer = $("readerQuestionsDrawer");
  const trigger = $("readerToolbarQuestions");
  if (drawer) drawer.classList.add("hidden");
  if (trigger) {
    trigger.classList.remove("active");
    trigger.setAttribute("aria-expanded", "false");
  }
}

export function toggleChapterQuestions(force = null) {
  const drawer = $("readerQuestionsDrawer");
  const trigger = $("readerToolbarQuestions");
  if (!drawer || !trigger) return;
  const isCurrentlyOpen = !drawer.classList.contains("hidden");
  const willOpen = force !== null ? force : !isCurrentlyOpen;

  if (willOpen) {
    closeSectionMenu();
    drawer.classList.remove("hidden");
    trigger.classList.add("active");
    trigger.setAttribute("aria-expanded", "true");
    renderQuestionsList();
  } else {
    closeChapterQuestions();
  }
}

export function setChapterQuestionsFilter(filter) {
  activeQuestionsFilter = filter;
  const drawer = $("readerQuestionsDrawer");
  if (!drawer) return;
  drawer.querySelectorAll(".rq-tab").forEach((tab) => {
    const active = tab.dataset.rqFilter === filter;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  renderQuestionsList();
}

function renderQuestionsList() {
  const listEl = $("rqListBody");
  if (!listEl) return;

  const filtered = currentChapterQuestions.filter((item) => {
    if (activeQuestionsFilter === "definition") return item.type === "definition";
    if (activeQuestionsFilter === "essay") return item.type === "essay";
    return true;
  });

  if (!filtered.length) {
    listEl.innerHTML = `
      <div class="rq-empty">
        <p>本分类下暂无考点题目。</p>
      </div>
    `;
    return;
  }

  const imageBase = state.current?.book_id ? `/api/book-assets/${encodeURIComponent(state.current.book_id)}/` : "";

  listEl.innerHTML = filtered.map((item, idx) => {
    const isDef = item.type === "definition";
    const tagClass = isDef ? "definition" : "essay";
    const tagLabel = item.type_label || (isDef ? "名词解释" : "简答论述");
    const stars = "★".repeat(Math.max(1, Math.min(5, Number(item.star_level) || 1)));
    const prompt = item.prompt || item.source_title_raw || "";
    const answerMarkdown = item.answer_markdown || "暂无可用的参考答案。";

    return `
      <article class="rq-card" data-question-id="${escapeHtml(item.id)}">
        <div class="rq-card-top">
          <div class="rq-card-meta">
            <span class="rq-card-num">Q${idx + 1}</span>
            <span class="rq-card-tag ${tagClass}">${escapeHtml(tagLabel)}</span>
            <span class="rq-card-stars" title="${escapeHtml(String(item.star_level || 1))}星考点">${stars}</span>
          </div>
          <button type="button" class="rq-card-copy-btn" data-copy-prompt="${escapeHtml(prompt)}" title="复制题目">
            <i data-lucide="copy"></i>
            <span>复制题目</span>
          </button>
        </div>
        <div class="rq-card-prompt">${escapeHtml(prompt)}</div>
        <details class="rq-answer-collapse">
          <summary class="rq-answer-summary">
            <i data-lucide="chevron-right"></i>
            <span>查看参考答案</span>
            <small class="rq-char-hint">${item.character_count || answerMarkdown.length} 字</small>
          </summary>
          <div class="rq-answer-body knowledge-article">
            ${renderMarkdown(answerMarkdown, imageBase)}
          </div>
        </details>
      </article>
    `;
  }).join("");

  listEl.querySelectorAll("[data-copy-prompt]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const text = btn.dataset.copyPrompt;
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        showToast("已复制题目");
      }).catch(() => {
        showToast("复制失败");
      });
    });
  });

  refreshIcons();
}

export function renderChapterQuestions(questions = []) {
  currentChapterQuestions = questions;
  const count = questions.length;
  const trigger = $("readerToolbarQuestions");
  const countEl = $("readerQuestionsCount");
  const totalPill = $("rqTotalPill");
  const countAll = $("rqCountAll");
  const countDef = $("rqCountDef");
  const countEssay = $("rqCountEssay");

  if (!trigger) return;

  if (count === 0) {
    trigger.classList.add("hidden");
    closeChapterQuestions();
    return;
  }

  trigger.classList.remove("hidden");
  if (countEl) countEl.textContent = String(count);
  if (totalPill) totalPill.textContent = `${count} 题`;

  const defCount = questions.filter((q) => q.type === "definition").length;
  const essayCount = questions.filter((q) => q.type === "essay").length;

  if (countAll) countAll.textContent = String(count);
  if (countDef) countDef.textContent = String(defCount);
  if (countEssay) countEssay.textContent = String(essayCount);

  const drawer = $("readerQuestionsDrawer");
  if (drawer && !drawer.classList.contains("hidden")) {
    renderQuestionsList();
  }
}

window.openSection = openSection;
window.showWordPopover = showWordPopover;
window.toggleChapterQuestions = toggleChapterQuestions;
window.closeChapterQuestions = closeChapterQuestions;