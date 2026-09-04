import { openOralFocusIndex, openOralFocusItem } from "../modules/oral_focus.js";
import { openPractice, openSubjectivePractice } from "../modules/practice.js";
import { renderHome } from "../views/home.js";
import { openLogs, openStats } from "../views/logs.js";
import { closeNotePopover, openSection, renderBooks } from "../views/reader.js";
import { openReview } from "../views/review.js";
import { $, ROUTE_ALIASES, SHELF_ORDER, state } from "./state.js";
import { startReadingTimer, stopReadingTimer } from "./timer.js";
import { showToast } from "./utils.js";

export function setRouteHash(route) {
  const next = `#${route}`;
  if (window.location.hash !== next) window.history.replaceState(null, "", next);
}

export function hashRoute() {
  const raw = decodeURIComponent(window.location.hash.replace(/^#\/?/, "")).trim().toLowerCase();
  const queryRoute = new URLSearchParams(window.location.search).get("view")?.trim().toLowerCase() || "";
  return ROUTE_ALIASES[raw || queryRoute] || "";
}

export function setActiveView(mode) {
  state.activeView = mode;
  const viewMode = mode === "reader" ? "library" : mode;
  ["home", "library", "oralFocus", "practice", "review", "logs", "stats"].forEach((view) => $(`${view}View`).classList.toggle("active", view === viewMode));
  const primaryMode = mode === "home" ? "home" : ["library", "reader", "oralFocus", "practice"].includes(mode) ? "library" : mode === "review" ? "review" : mode === "stats" ? "stats" : "logs";
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.classList.toggle("active", primaryMode === "home"));
  $("libraryNav").classList.toggle("active", primaryMode === "library"); $("mobileLibrary").classList.toggle("active", primaryMode === "library");
  $("reviewNav").classList.toggle("active", primaryMode === "review"); $("mobileReview").classList.toggle("active", primaryMode === "review");
  $("logsNav").classList.toggle("active", primaryMode === "logs"); $("mobileLogs").classList.toggle("active", primaryMode === "logs");
  $("statsNav")?.classList.toggle("active", primaryMode === "stats"); $("mobileStats")?.classList.toggle("active", primaryMode === "stats");
  $("pageTitle").textContent = mode === "home" ? "今日" : mode === "reader" ? "阅读" : mode === "oralFocus" ? "口腔重点" : mode === "library" ? "学习" : mode === "practice" ? "练习" : mode === "review" ? "回顾" : mode === "logs" ? "记录" : "统计";
}

export function hideAllNoteFloats() {
  $("sectionNoteFloat")?.classList.add("hidden");
  $("oralFocusNoteFloat")?.classList.add("hidden");
  $("practiceNoteFloat")?.classList.add("hidden");
  $("reviewNoteFloat")?.classList.add("hidden");
  $("logsNoteFloat")?.classList.add("hidden");
}

export function setHomeMode() {
  setRouteHash("today");
  state.openRequest += 1;
  stopReadingTimer();
  closeNotePopover();
  hideAllNoteFloats();
  setActiveView("home");
  renderHome();
  window.scrollTo({ top: 0, behavior: "auto" });
}

export function setLibraryMode() {
  setRouteHash("library");
  state.openRequest += 1;
  stopReadingTimer();
  state.resourceBookId = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open");
  $("readerContent").classList.add("hidden");
  hideAllNoteFloats();
  setActiveView("library");
  closeNotePopover();
  renderBooks();
  window.scrollTo({ top: 0, behavior: "auto" });
}

export function selectLibraryShelf(shelf) {
  if (!SHELF_ORDER.includes(shelf)) return;
  setRouteHash("library");
  state.openRequest += 1;
  stopReadingTimer();
  closeNotePopover();
  state.libraryDomain = shelf;
  if (shelf === "english") {
    state.englishCenterYear = "";
  }
  state.resourceBookId = null;
  state.resource = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open");
  $("readerContent").classList.add("hidden");
  hideAllNoteFloats();
  setActiveView("library");
  renderBooks();
  window.scrollTo({ top: 0, behavior: "auto" });
}

export function setReaderMode() {
  hideAllNoteFloats();
  $("libraryWorkspace").classList.remove("resource-open");
  $("libraryWorkspace").classList.add("reader-open");
  $("readerContent").classList.remove("hidden");
  $("sectionNoteFloat")?.classList.remove("hidden");
  setActiveView("reader");
  if (state.current?.id) startReadingTimer(state.current.id);
}

export function homeActivityTargetKey(prefix, index) {
  return `${prefix}-${index}`;
}

export async function resumeActivityTarget(target) {
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

export function applyRouteHash() {
  const route = hashRoute();
  if (route === "home") setHomeMode();
  else if (route === "library") setLibraryMode();
  else if (route === "library-english") selectLibraryShelf("english");
  else if (route === "library-medicine") selectLibraryShelf("medicine");
  else if (route === "library-politics") selectLibraryShelf("politics");
  else if (route === "oralFocus") openOralFocusIndex();
  else if (route === "review") openReview();
  else if (route === "logs") openLogs();
  else if (route === "stats") openStats();
}

window.selectLibraryShelf = selectLibraryShelf;
window.setLibraryMode = setLibraryMode;
window.setHomeMode = setHomeMode;
window.setActiveView = setActiveView;
