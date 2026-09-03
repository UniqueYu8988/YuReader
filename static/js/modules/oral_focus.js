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
  const type = state.oralFocusTypeFilter;
  const typeLabel = type === "definition" ? "名词解释" : type === "essay" ? "论述题" : "重点题";
  const chapters = (subject.chapters || []).map((chapter) => {
    const items = (chapter.items || []).filter((item) => !type || item.type === type);
    return { ...chapter, filtered_items: items, completed: items.filter((item) => item.completed).length };
  }).filter((chapter) => chapter.filtered_items.length);
  const filteredItems = chapters.flatMap((chapter) => chapter.filtered_items);
  const completedCount = filteredItems.filter((item) => item.completed).length;
  $("oralFocusDirectoryTitle").textContent = `${subject.short_title || subject.title} · ${typeLabel}`;
  $("oralFocusSummary").textContent = `${formatInteger(completedCount)} / ${formatInteger(filteredItems.length)}`;
  $("oralFocusSubjectTabs").innerHTML = subjects.map((entry) => {
    const items = (entry.chapters || []).flatMap((chapter) => chapter.items || []).filter((item) => !type || item.type === type);
    const completed = items.filter((item) => item.completed).length;
    return `<button type="button" class="${entry.id === subject.id ? "active" : ""}" data-oral-subject="${escapeHtml(entry.id)}" aria-pressed="${entry.id === subject.id ? "true" : "false"}"><strong>${escapeHtml(entry.short_title)}</strong><small>${formatInteger(completed)} / ${formatInteger(items.length)}</small></button>`;
  }).join("");
  $("oralFocusChapterPanel").classList.add("hidden");
  $("oralFocusChapterList").classList.remove("hidden");
  $("oralFocusChapterList").innerHTML = chapters.length ? chapters.map((chapter) => `<button class="oral-focus-chapter-entry" type="button" data-oral-chapter="${escapeHtml(chapter.id)}"><span class="oral-focus-chapter-number">${String(chapter.order || 0).padStart(2, "0")}</span><span><strong>${escapeHtml(chapter.title || "未分章")}</strong><small>${formatInteger(chapter.completed)} / ${formatInteger(chapter.filtered_items.length)}</small></span><i data-lucide="arrow-right"></i></button>`).join("") : `<div class="knowledge-index-empty"><strong>本科暂无${typeLabel}</strong><span>切换其他学科，或返回医学学习库选择另一类资料。</span></div>`;
  $("oralFocusSubjectTabs").querySelectorAll("[data-oral-subject]").forEach((button) => button.addEventListener("click", () => { state.oralFocusSubjectId = button.dataset.oralSubject; state.oralFocusChapterId = ""; state.oralFocusChapter = null; renderOralFocusDirectory(); window.scrollTo({ top: 0, behavior: "auto" }); }));
  $("oralFocusChapterList").querySelectorAll("[data-oral-chapter]").forEach((button) => button.addEventListener("click", () => openOralFocusChapter(button.dataset.oralChapter)));
  refreshIcons();
}

export function oralFocusAnswerHtml(item) {
  const translation = item.definition_translation ? `<div class="oral-focus-translation"><small>中文译名</small><strong>${escapeHtml(item.definition_translation)}</strong></div>` : "";
  return `${translation}<article class="knowledge-article oral-focus-answer-copy">${renderMarkdown(item.answer_markdown || "暂无可识别的标准答案。")}</article>`;
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
    const body = !showBody ? "" : `<div class="oral-focus-card-body"><nav class="oral-focus-card-tabs" aria-label="答案与笔记"><button type="button" data-oral-card-mode="answer" data-oral-card-id="${escapeHtml(item.id)}" class="${mode === "answer" ? "active" : ""}" ${state.oralFocusReferenceVisible ? "" : "disabled"}>答案</button><button type="button" data-oral-card-mode="note" data-oral-card-id="${escapeHtml(item.id)}" class="${mode === "note" ? "active" : ""}">笔记</button></nav><section class="${mode === "answer" ? "" : "hidden"}" data-oral-card-answer>${state.oralFocusReferenceVisible ? oralFocusAnswerHtml(item) : ""}</section><section class="oral-focus-card-note ${mode === "note" ? "" : "hidden"}" data-oral-card-note>${note.trim() ? `<article class="knowledge-article">${renderMarkdown(note)}</article>` : `<p>这道题还没有补充笔记。</p>`}</section></div>`;
    return `<article class="oral-focus-study-card${focusItemId === item.id ? " is-focused" : ""}" data-oral-card="${escapeHtml(item.id)}"><header><span>${String(index + 1).padStart(2, "0")}</span><div><h4>${escapeHtml(item.title)}</h4>${item.type === "definition" && /^[A-Za-z]/.test(item.title || "") ? `<small>先说出中文译名，再解释</small>` : ""}</div><div class="oral-focus-card-tools">${star}<button type="button" data-oral-note-open="${escapeHtml(item.id)}" aria-label="编辑《${escapeHtml(item.title)}》的 Obsidian 笔记" title="补充笔记"><img src="/assets/obsidian.svg" alt=""></button></div></header>${body}</article>`;
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
    if ((subjectId && subjectId !== state.oralFocusSubjectId) || (type !== null && type !== state.oralFocusTypeFilter)) {
      state.oralFocusChapterId = ""; state.oralFocusChapter = null;
    }
    if (subjectId) state.oralFocusSubjectId = subjectId;
    if (type !== null) {
      state.oralFocusTypeFilter = type;
      try { localStorage.setItem(ORAL_FOCUS_TYPE_STORAGE_KEY, type); } catch {}
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
  renderOralFocusQuestion();
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