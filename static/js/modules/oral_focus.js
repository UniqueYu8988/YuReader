import { setActiveView, setRouteHash } from "../core/router.js";
import { $, ORAL_FOCUS_TYPE_STORAGE_KEY, ORAL_REFERENCE_STORAGE_KEY, state } from "../core/state.js";
import { startWorkspaceTimer, stopReadingTimer } from "../core/timer.js";
import { escapeHtml, formatInteger, refreshIcons, renderMarkdown, showToast } from "../core/utils.js";
import { closeNotePopover } from "../views/reader.js";

export function selectedOralFocusSubject() {
  const subjects = state.oralFocus?.subjects || [];
  return subjects.find((item) => item.id === state.oralFocusSubjectId) || subjects[0] || null;
}

export function renderOralFocusDirectory() {
  const subjects = state.oralFocus?.subjects || [];
  const subject = selectedOralFocusSubject();
  if (!subject) {
    $("oralFocusSubjectTabs").innerHTML = "";
    $("oralFocusChapterList").innerHTML = `<div class="knowledge-index-empty"><strong>口腔重点资料尚未导入</strong><span>运行本地 DOCX 导入后，这里会显示章节。</span></div>`;
    return;
  }
  state.oralFocusSubjectId = subject.id;
  if (!state.oralFocusTypeFilter) {
    try {
      state.oralFocusTypeFilter = localStorage.getItem(ORAL_FOCUS_TYPE_STORAGE_KEY) || "definition";
    } catch {
      state.oralFocusTypeFilter = "definition";
    }
  }
  const type = state.oralFocusTypeFilter || "definition";
  const typeLabel = type === "definition" ? "名词解释" : "简答论述";

  // Filter chapters strictly by type
  const chapters = (subject.chapters || []).filter((chapter) => {
    if (chapter.type) return chapter.type === type;
    return chapter.id.includes(`-${type}-`);
  }).map((chapter) => {
    const items = chapter.items || [];
    return { ...chapter, filtered_items: items, completed: items.filter((item) => item.completed).length };
  }).filter((chapter) => chapter.filtered_items.length);

  const filteredItems = chapters.flatMap((chapter) => chapter.filtered_items);
  const completedCount = filteredItems.filter((item) => item.completed).length;

  $("oralFocusDirectoryTitle").textContent = `${subject.short_title || subject.title} · ${typeLabel}`;
  $("oralFocusSummary").textContent = `${formatInteger(completedCount)} / ${formatInteger(filteredItems.length)}`;

  // Subject tabs
  $("oralFocusSubjectTabs").innerHTML = subjects.map((entry) => {
    const items = (entry.chapters || []).filter((ch) => ch.type === type || ch.id.includes(`-${type}-`)).flatMap((ch) => ch.items || []);
    const completed = items.filter((item) => item.completed).length;
    return `<button type="button" class="${entry.id === subject.id ? "active" : ""}" data-oral-subject="${escapeHtml(entry.id)}" aria-pressed="${entry.id === subject.id ? "true" : "false"}"><strong>${escapeHtml(entry.short_title)}</strong><small>${formatInteger(completed)} / ${formatInteger(items.length)}</small></button>`;
  }).join("");

  // Type filter tabs counts
  const defItems = (subject.chapters || []).filter((ch) => ch.type === "definition" || ch.id.includes("-definition-")).flatMap((ch) => ch.items || []);
  const essayItems = (subject.chapters || []).filter((ch) => ch.type === "essay" || ch.id.includes("-essay-")).flatMap((ch) => ch.items || []);
  const defCountEl = $("oftDefCount");
  if (defCountEl) defCountEl.textContent = formatInteger(defItems.length);
  const essayCountEl = $("oftEssayCount");
  if (essayCountEl) essayCountEl.textContent = formatInteger(essayItems.length);

  document.querySelectorAll("[data-oral-filter-type]").forEach((btn) => {
    const isActive = btn.dataset.oralFilterType === type;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  $("oralFocusChapterPanel").classList.add("hidden");
  $("oralFocusChapterList").classList.remove("hidden");
  $("oralFocusChapterList").innerHTML = chapters.length ? chapters.map((chapter) => `<button class="oral-focus-chapter-entry" type="button" data-oral-chapter="${escapeHtml(chapter.id)}"><span class="oral-focus-chapter-number">${String(chapter.order || 0).padStart(2, "0")}</span><span><strong>${escapeHtml(chapter.title || "未分章")}</strong><small>${formatInteger(chapter.completed)} / ${formatInteger(chapter.filtered_items.length)}</small></span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="knowledge-index-empty"><strong>本科暂无${typeLabel}</strong><span>切换其他学科，或返回医学学习选择另一类资料。</span></div>`;

  $("oralFocusSubjectTabs").querySelectorAll("[data-oral-subject]").forEach((button) => button.addEventListener("click", () => { state.oralFocusSubjectId = button.dataset.oralSubject; state.oralFocusChapterId = ""; state.oralFocusChapter = null; renderOralFocusDirectory(); window.scrollTo({ top: 0, behavior: "auto" }); }));
  $("oralFocusChapterList").querySelectorAll("[data-oral-chapter]").forEach((button) => button.addEventListener("click", () => openOralFocusChapter(button.dataset.oralChapter)));
  $("oralFocusTypeFilterBar")?.querySelectorAll("[data-oral-filter-type]").forEach((btn) => btn.addEventListener("click", () => {
    state.oralFocusTypeFilter = btn.dataset.oralFilterType;
    try { localStorage.setItem(ORAL_FOCUS_TYPE_STORAGE_KEY, state.oralFocusTypeFilter); } catch {}
    state.oralFocusChapterId = "";
    state.oralFocusChapter = null;
    renderOralFocusDirectory();
  }));

  refreshIcons();
}

export function oralFocusAnswerHtml(item) {
  if (item.answer_status === "source_missing") {
    return `<div class="oral-focus-source-missing-box">
      <div class="of-missing-head">
        <i data-lucide="info"></i>
        <strong>原资料未提供参考答案</strong>
      </div>
      <p>该考点在原始整理讲义中未附带完整解答（仅有题名或中文译名）。建议使用右侧 Obsidian 笔记与侧边栏 AI 查阅官方教材进行理解补充。</p>
    </div>`;
  }
  const tagsHtml = (item.source_tags && item.source_tags.length)
    ? `<div class="oral-focus-tags-row">${item.source_tags.map((t) => `<span class="oral-focus-source-tag">${escapeHtml(t)}</span>`).join("")}</div>`
    : "";
  const translation = item.definition_translation ? `<div class="oral-focus-translation"><small>中文译名</small><strong>${escapeHtml(item.definition_translation)}</strong></div>` : "";
  return `${tagsHtml}${translation}<article class="knowledge-article oral-focus-answer-copy">${renderMarkdown(item.answer_markdown || "暂无可识别的标准答案。")}</article>`;
}

export function enhanceOralFocusSource(root) {
  const circledNumbers = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
  root.querySelectorAll("p").forEach((paragraph) => {
    const firstText = [...paragraph.childNodes].find((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
    const source = firstText?.textContent || "";
    const markerMatch = source.match(/^\s*[（(](\d{1,2})[）)]\s*/);
    const circledMatch = source.match(new RegExp(`^\\s*([${circledNumbers}])\\s*`));
    const markerValue = markerMatch?.[1] || (circledMatch ? String(circledNumbers.indexOf(circledMatch[1]) + 1) : "");
    const markerLength = markerMatch?.[0].length || circledMatch?.[0].length || 0;
    if (markerValue) {
      firstText.textContent = firstText.textContent.slice(markerLength);
      const content = document.createElement("span");
      while (paragraph.firstChild) content.appendChild(paragraph.firstChild);
      const marker = document.createElement("span"); marker.className = "oral-focus-point-marker"; marker.textContent = markerValue.padStart(2, "0");
      paragraph.classList.add("oral-focus-structured-point"); paragraph.append(marker, content);
    }
  });
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) if (walker.currentNode.textContent.includes("／")) textNodes.push(walker.currentNode);
  textNodes.forEach((node) => {
    if (node.parentElement?.closest("code, pre, a, .oral-focus-point-marker")) return;
    const parts = node.textContent.split("／"); if (parts.length < 2) return;
    const fragment = document.createDocumentFragment();
    parts.forEach((part, index) => { if (index) { const separator = document.createElement("span"); separator.className = "oral-focus-source-separator"; separator.textContent = "／"; fragment.appendChild(separator); } fragment.appendChild(document.createTextNode(part)); });
    node.replaceWith(fragment);
  });
}

export function renderOralFocusChapterCards(focusItemId = "") {
  const payload = state.oralFocusChapter; if (!payload) return;
  const items = payload.items || [];
  const completed = items.filter((item) => item.progress?.memory_note?.trim() || item.progress?.answer?.trim() || item.progress?.mastery !== "unseen").length;
  $("oralFocusChapterTitle").textContent = payload.chapter?.title || "未分章";
  $("oralFocusChapterSummary").textContent = `${formatInteger(completed)} / ${formatInteger(items.length)}`;
  $("oralFocusChapterAnswerToggle").setAttribute("aria-checked", String(state.oralFocusReferenceVisible));
  $("oralFocusChapterAnswerToggle").querySelector("span").textContent = state.oralFocusReferenceVisible ? "完整答案" : "只看题目";
  $("oralFocusItems").classList.toggle("answers-visible", state.oralFocusReferenceVisible);
  $("oralFocusItems").innerHTML = items.map((item, index) => {
    const mode = state.oralFocusCardModes.get(item.id) || "answer";
    const noteExpanded = state.oralFocusExpandedNotes.has(item.id);
    const showBody = state.oralFocusReferenceVisible || noteExpanded;
    const note = item.progress?.memory_note || "";
    const star = item.star_level ? `<span class="oral-focus-card-stars" aria-label="${item.star_level} 星">${"★".repeat(item.star_level)}</span>` : "";
    const tags = (item.source_tags && item.source_tags.length)
      ? `<div class="oral-focus-card-tags">${item.source_tags.map((t) => `<span class="of-tag">${escapeHtml(t)}</span>`).join("")}</div>`
      : "";
    const missingBadge = item.answer_status === "source_missing"
      ? `<span class="of-badge-missing" title="原资料未提供参考答案">原资料无答案</span>`
      : "";
    const bilingualHint = item.type === "definition" && /^[A-Za-z]/.test(item.title || "")
      ? `<small class="of-bilingual-hint">先说出中文译名，再解释</small>`
      : "";
    const body = !showBody ? "" : `<div class="oral-focus-card-body"><nav class="oral-focus-card-tabs" aria-label="答案与笔记"><button type="button" data-oral-card-mode="answer" data-oral-card-id="${escapeHtml(item.id)}" class="${mode === "answer" ? "active" : ""}" ${state.oralFocusReferenceVisible ? "" : "disabled"}>答案</button><button type="button" data-oral-card-mode="note" data-oral-card-id="${escapeHtml(item.id)}" class="${mode === "note" ? "active" : ""}">笔记</button></nav><section class="${mode === "answer" ? "" : "hidden"}" data-oral-card-answer>${state.oralFocusReferenceVisible ? oralFocusAnswerHtml(item) : ""}</section><section class="oral-focus-card-note ${mode === "note" ? "" : "hidden"}" data-oral-card-note>${note.trim() ? `<article class="knowledge-article">${renderMarkdown(note)}</article>` : `<p>这道题还没有补充笔记。</p>`}</section></div>`;
    return `<article class="oral-focus-study-card${focusItemId === item.id ? " is-focused" : ""}" data-oral-card="${escapeHtml(item.id)}"><header><span>${String(index + 1).padStart(2, "0")}</span><div><h4>${escapeHtml(item.title)}</h4>${bilingualHint}${tags}</div><div class="oral-focus-card-tools">${missingBadge}${star}<button type="button" data-oral-note-open="${escapeHtml(item.id)}" aria-label="编辑《${escapeHtml(item.title)}》的 Obsidian 笔记" title="补充笔记"><img src="/assets/obsidian.svg" alt=""></button></div></header>${body}</article>`;
  }).join("");
  $("oralFocusItems").querySelectorAll("[data-oral-card-mode]").forEach((button) => button.addEventListener("click", () => { state.oralFocusCardModes.set(button.dataset.oralCardId, button.dataset.oralCardMode); renderOralFocusChapterCards(button.dataset.oralCardId); }));
  $("oralFocusItems").querySelectorAll("[data-oral-note-open]").forEach((button) => button.addEventListener("click", () => openOralFocusCardNote(button.dataset.oralNoteOpen)));
  $("oralFocusItems").querySelectorAll(".oral-focus-answer-copy").forEach(enhanceOralFocusSource);
  refreshIcons();
  if (focusItemId) window.setTimeout(() => $("oralFocusItems").querySelector(`[data-oral-card="${focusItemId}"]`)?.scrollIntoView({ block: "center", behavior: "auto" }), 0);
}

export async function openOralFocusChapter(chapterId, focusItemId = "") {
  if (!chapterId) return;
  state.oralFocusChapterId = chapterId;
  $("oralFocusChapterList").classList.add("hidden");
  $("oralFocusChapterPanel").classList.remove("hidden");
  $("oralFocusItems").innerHTML = `<div class="practice-reading-loading">正在读取章节题目…</div>`;
  try {
    const typeQuery = state.oralFocusTypeFilter ? `&type=${encodeURIComponent(state.oralFocusTypeFilter)}` : "";
    const revealQuery = state.oralFocusReferenceVisible ? "&reveal=1" : "";
    const response = await fetch(`/api/oral-focus/chapter?subject_id=${encodeURIComponent(state.oralFocusSubjectId)}&chapter_id=${encodeURIComponent(chapterId)}${typeQuery}${revealQuery}`, { cache: "no-store" });
    if (!response.ok) throw new Error("chapter unavailable");
    state.oralFocusChapter = await response.json();
    renderOralFocusChapterCards(focusItemId);
    const subject = state.oralFocusChapter.subject || {};
    startWorkspaceTimer({ activity_type: "subjective_practice", domain: "medicine", subject_id: subject.title || subject.id, resource_id: `oral-focus:${subject.id}`, item_id: focusItemId || `chapter:${chapterId}`, resume_target: { view: "oral_focus", resource_id: `oral-focus:${subject.id}`, item_id: focusItemId || "" } });
  } catch {
    $("oralFocusItems").innerHTML = `<div class="knowledge-index-empty"><strong>暂时无法读取该章节题目</strong></div>`;
  }
}

export async function toggleOralFocusChapterAnswers() {
  state.oralFocusReferenceVisible = !state.oralFocusReferenceVisible;
  try { localStorage.setItem(ORAL_REFERENCE_STORAGE_KEY, String(state.oralFocusReferenceVisible)); } catch {}
  if (state.oralFocusReferenceVisible && !state.oralFocusChapter?.reference_revealed && state.oralFocusChapterId) {
    await openOralFocusChapter(state.oralFocusChapterId);
    return;
  }
  renderOralFocusChapterCards();
}

export async function openOralFocusCardNote(itemId) {
  const item = state.oralFocusChapter?.items?.find((entry) => entry.id === itemId);
  if (!item) return;
  state.oralFocusItem = item;
  state.oralFocusCardModes.set(itemId, "note");
  state.oralFocusExpandedNotes.add(itemId);
  renderOralFocusChapterCards(itemId);
  $("oralFocusNote").value = item.progress?.memory_note || "";
  $("oralFocusObsidian").href = item.obsidian_uri || "obsidian://open";
  $("oralFocusNoteSaved").textContent = item.progress?.memory_note?.trim() ? (item.progress?.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
  setOralFocusNoteOpen(true);
}

export function renderOralFocusNoteContent() {
  const markdown = $("oralFocusNote")?.value || state.oralFocusItem?.progress?.memory_note || "";
  $("oralFocusNoteContent").classList.toggle("hidden", !markdown.trim());
  $("oralFocusNoteBody").innerHTML = markdown.trim() ? renderMarkdown(markdown) : "";
}

export async function loadOralFocus() {
  const response = await fetch("/api/oral-focus", { cache: "no-store" });
  if (!response.ok) throw new Error("oral focus unavailable");
  state.oralFocus = await response.json();
  if (!state.oralFocusSubjectId) state.oralFocusSubjectId = state.oralFocus.subjects?.[0]?.id || "";
  return state.oralFocus;
}

export async function openOralFocusIndex(subjectId = "", type = null) {
  setRouteHash("library/oral-focus"); stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("oralFocus");
  setOralFocusNoteOpen(false); $("oralFocusNoteFloat").classList.add("hidden");
  $("oralFocusQuestion").classList.add("hidden"); $("oralFocusDirectory").classList.remove("hidden");
  try {
    if (!state.oralFocus?.available) await loadOralFocus();
    if (type !== null) {
      if (type !== state.oralFocusTypeFilter) {
        state.oralFocusChapterId = ""; state.oralFocusChapter = null;
      }
      state.oralFocusTypeFilter = type;
      try { localStorage.setItem(ORAL_FOCUS_TYPE_STORAGE_KEY, type); } catch {}
    } else if (!state.oralFocusTypeFilter) {
      try {
        state.oralFocusTypeFilter = localStorage.getItem(ORAL_FOCUS_TYPE_STORAGE_KEY) || "definition";
      } catch {
        state.oralFocusTypeFilter = "definition";
      }
    }
    if (subjectId && subjectId !== state.oralFocusSubjectId) {
      state.oralFocusChapterId = ""; state.oralFocusChapter = null;
      state.oralFocusSubjectId = subjectId;
    }
    renderOralFocusDirectory();
  } catch {
    state.oralFocus = { available: false, subjects: [] }; renderOralFocusDirectory();
  }
  window.scrollTo({ top: 0, behavior: "auto" });
}

export async function openOralFocusItem(itemId) {
  if (!itemId) return;
  setRouteHash("library/oral-focus"); stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("oralFocus");
  $("oralFocusQuestion").classList.add("hidden"); $("oralFocusDirectory").classList.remove("hidden");
  try {
    if (!state.oralFocus?.available) await loadOralFocus();
    const response = await fetch(`/api/oral-focus/item?item_id=${encodeURIComponent(itemId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("item unavailable");
    const item = await response.json(); state.oralFocusSubjectId = item.subject?.id || state.oralFocusSubjectId;
    state.oralFocusTypeFilter = item.type || state.oralFocusTypeFilter; renderOralFocusDirectory();
    await openOralFocusChapter(item.chapter?.id, itemId);
  } catch { $("oralFocusChapterList").innerHTML = `<div class="knowledge-index-empty"><strong>暂时无法读取这道题</strong></div>`; }
}

export async function toggleOralFocusReference() {
  const item = state.oralFocusItem; if (!item) return;
  state.oralFocusReferenceVisible = !state.oralFocusReferenceVisible;
  try { localStorage.setItem(ORAL_REFERENCE_STORAGE_KEY, String(state.oralFocusReferenceVisible)); } catch {}
  if (state.oralFocusReferenceVisible && !item.reference_revealed) {
    const response = await fetch(`/api/oral-focus/item?item_id=${encodeURIComponent(item.id)}&reveal=1`, { cache: "no-store" });
    if (!response.ok) { state.oralFocusReferenceVisible = false; showToast("暂时无法读取标准答案"); return; }
    const revealed = await response.json();
    state.oralFocusItem = { ...revealed, progress: item.progress };
  }
  renderOralFocusChapterCards();
}

export async function saveOralFocusNote() {
  const item = state.oralFocusItem; if (!item || !state.oralFocusNoteDirty) return;
  window.clearTimeout(state.oralFocusSaveTimer); state.oralFocusSaveTimer = null;
  const memoryNote = $("oralFocusNote").value;
  $("oralFocusNoteSaved").textContent = "保存中…";
  try {
    const response = await fetch("/api/oral-focus/progress", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item_id: item.id, answer: item.progress?.answer || "", memory_note: memoryNote, mastery: item.progress?.mastery || "unseen" }) });
    if (!response.ok) throw new Error("save failed");
    const result = await response.json(); item.progress = result.progress; state.oralFocusNoteDirty = false;
    const directoryItem = (state.oralFocus?.subjects || []).flatMap((subject) => subject.chapters || []).flatMap((chapter) => chapter.items || []).find((entry) => entry.id === item.id);
    if (directoryItem) directoryItem.completed = result.saved;
    const chapterItem = state.oralFocusChapter?.items?.find((entry) => entry.id === item.id);
    if (chapterItem) chapterItem.progress = result.progress;
    $("oralFocusObsidian").href = result.obsidian_uri || item.obsidian_uri || "obsidian://open";
    $("oralFocusNoteSaved").textContent = memoryNote.trim() ? (result.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
  } catch { $("oralFocusNoteSaved").textContent = "保存失败，请稍后重试"; }
}

export function scheduleOralFocusNoteSave() {
  if (!state.oralFocusItem) return;
  state.oralFocusItem.progress.memory_note = $("oralFocusNote").value;
  renderOralFocusNoteContent();
  state.oralFocusNoteDirty = true; $("oralFocusNoteSaved").textContent = "保存中…"; window.clearTimeout(state.oralFocusSaveTimer);
  state.oralFocusSaveTimer = window.setTimeout(saveOralFocusNote, 420);
}

export function setOralFocusNoteOpen(open) {
  state.oralFocusNoteOpen = open;
  $("oralFocusNoteFloat").classList.toggle("note-is-open", open);
  $("oralFocusNotePopover").classList.toggle("is-open", open);
  $("oralFocusNotePopover").setAttribute("aria-hidden", String(!open));
  $("toggleOralFocusNote").setAttribute("aria-expanded", String(open));
  if (open) window.setTimeout(() => $("oralFocusNote").focus(), 120);
}

export async function navigateOralFocus(step) {
  const index = state.oralFocusFlatItems.findIndex((entry) => entry.id === state.oralFocusItem?.id);
  const target = state.oralFocusFlatItems[index + step]; if (!target) return;
  await saveOralFocusNote(); openOralFocusItem(target.id);
}

let flashcardIndex = 0;
let isFlashcardFlipped = false;
let oralViewMode = "list";

export function setOralFocusViewMode(mode) {
  oralViewMode = mode;
  $("oralModeListBtn")?.classList.toggle("active", mode === "list");
  $("oralModeCardBtn")?.classList.toggle("active", mode === "card");
  $("oralFocusItems")?.classList.toggle("hidden", mode !== "list");
  $("oralFocusFlashcardDeck")?.classList.toggle("hidden", mode !== "card");

  if (mode === "card") {
    flashcardIndex = 0;
    renderOralFlashcard();
  }
}

export function renderOralFlashcard() {
  const items = state.oralFocusChapter?.items || [];
  const deck = $("oralFocusFlashcardDeck");
  if (!deck || !items.length) return;

  if (flashcardIndex < 0) flashcardIndex = 0;
  if (flashcardIndex >= items.length) flashcardIndex = items.length - 1;

  const item = items[flashcardIndex];
  isFlashcardFlipped = false;
  $("fcCard")?.classList.remove("is-flipped");

  if ($("fcCounterText")) $("fcCounterText").textContent = `第 ${flashcardIndex + 1} / ${items.length} 题`;
  if ($("fcMetaText")) {
    const starText = item.star_level ? "★".repeat(item.star_level) + " 重点" : "";
    const masteryText = item.progress?.mastery === "mastered" ? "🟢 已熟记" : item.progress?.mastery === "fuzzy" ? "🟡 需巩固" : "⚪ 未掌握";
    $("fcMetaText").textContent = [starText, masteryText].filter(Boolean).join(" · ");
  }
  if ($("fcCardType")) $("fcCardType").textContent = item.type === "definition" ? "名词解释" : "简答论述";
  if ($("fcCardSubject")) $("fcCardSubject").textContent = state.oralFocusChapter?.subject?.title || "医学全书";
  if ($("fcFrontStem")) {
    const isBilingual = item.type === "definition" && /^[A-Za-z]/.test(item.title || "");
    const tagsHtml = (item.source_tags && item.source_tags.length)
      ? `<div class="fc-front-tags">${item.source_tags.map((t) => `<span class="of-tag">${escapeHtml(t)}</span>`).join("")}</div>`
      : "";
    $("fcFrontStem").innerHTML = `<div class="fc-front-title">${escapeHtml(item.title || "")}</div>${isBilingual ? `<div class="fc-bilingual-hint">先在心中回忆【中文译名】与【核心定义】</div>` : ""}${tagsHtml}`;
  }
  if ($("fcBackContent")) {
    $("fcBackContent").innerHTML = oralFocusAnswerHtml(item);
    enhanceOralFocusSource($("fcBackContent"));
  }

  if ($("fcPrevBtn")) $("fcPrevBtn").disabled = flashcardIndex <= 0;
  if ($("fcNextBtn")) $("fcNextBtn").disabled = flashcardIndex >= items.length - 1;

  refreshIcons();
}

export function flipFlashcard(forceState = null) {
  if (forceState !== null) {
    isFlashcardFlipped = forceState;
  } else {
    isFlashcardFlipped = !isFlashcardFlipped;
  }
  $("fcCard")?.classList.toggle("is-flipped", isFlashcardFlipped);
}

export function stepFlashcard(delta) {
  const items = state.oralFocusChapter?.items || [];
  const next = flashcardIndex + delta;
  if (next >= 0 && next < items.length) {
    flashcardIndex = next;
    renderOralFlashcard();
  }
}

export async function submitFlashcardRating(rating, days) {
  const items = state.oralFocusChapter?.items || [];
  const item = items[flashcardIndex];
  if (!item) return;

  try {
    const res = await fetch("/api/oral-focus/progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        item_id: item.id,
        mastery: rating,
        eb_interval_days: days,
        answer: item.progress?.answer || "",
        memory_note: item.progress?.memory_note || "",
      }),
    });
    if (!res.ok) throw new Error("progress failed");
    const result = await res.json();
    item.progress = result.progress;

    if (rating === "mastered") {
      showToast(`🟢 已掌握！艾宾浩斯排程：+${days}天后复查`);
    } else if (rating === "fuzzy") {
      showToast(`🟡 模糊犹豫！排程：明天(+${days}天)重点复习`);
    } else {
      showToast(`🔴 完全遗忘！已移入今日待背队列`);
    }

    if (flashcardIndex < items.length - 1) {
      flashcardIndex += 1;
      renderOralFlashcard();
    } else {
      renderOralFlashcard();
      showToast("🎉 本章所有重点词条背诵完成！");
    }
  } catch {
    showToast("保存进度失败，请重试");
  }
}

let flashcardEventsBound = false;
export function bindFlashcardEvents() {
  if (flashcardEventsBound) return;

  $("oralModeListBtn")?.addEventListener("click", () => setOralFocusViewMode("list"));
  $("oralModeCardBtn")?.addEventListener("click", () => setOralFocusViewMode("card"));
  $("fcCard")?.addEventListener("click", (e) => {
    if (e.target.closest("button") || e.target.closest("a")) return;
    flipFlashcard();
  });
  $("fcUnflipBtn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    flipFlashcard(false);
  });
  $("fcPrevBtn")?.addEventListener("click", () => stepFlashcard(-1));
  $("fcNextBtn")?.addEventListener("click", () => stepFlashcard(1));

  document.querySelectorAll("#fcEbbinghausControls [data-eb-rating]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rating = btn.dataset.ebRating;
      const days = parseInt(btn.dataset.ebDays || "1", 10);
      submitFlashcardRating(rating, days);
    });
  });

  window.addEventListener("keydown", (e) => {
    const deck = $("oralFocusFlashcardDeck");
    if (!deck || deck.classList.contains("hidden") || $("oralFocusView")?.classList.contains("hidden")) return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.code === "Space") {
      e.preventDefault();
      flipFlashcard();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      stepFlashcard(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      stepFlashcard(1);
    } else if (e.key === "1") {
      submitFlashcardRating("learning", 1);
    } else if (e.key === "2") {
      submitFlashcardRating("fuzzy", 2);
    } else if (e.key === "3") {
      submitFlashcardRating("mastered", 4);
    }
  });

  flashcardEventsBound = true;
}