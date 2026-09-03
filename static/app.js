import { applyRouteHash, resumeActivityTarget, selectLibraryShelf, setHomeMode, setLibraryMode } from "./js/core/router.js";
import { $, state } from "./js/core/state.js";
import { collectReadingTime, collectWorkspaceTime, flushReadingTime, flushWorkspaceTime, initializeReadingTimer, markReadingScroll, markWorkspaceActivity } from "./js/core/timer.js";
import { applyTheme, refreshIcons, toggleTheme } from "./js/core/utils.js";
import { renderEnglishExams } from "./js/domains/english.js";
import { loadOralFocus, navigateOralFocus, openOralFocusIndex, renderOralFocusDirectory, saveOralFocusNote, scheduleOralFocusNoteSave, setOralFocusNoteOpen, toggleOralFocusChapterAnswers, toggleOralFocusReference } from "./js/modules/oral_focus.js";
import { finishPracticeSession, renderPracticeQuestion, returnFromPractice, returnFromSubjectivePractice, reviewFirstWrongPracticeQuestion, schedulePracticeAnalysisSave, scheduleSubjectiveSave, submitPracticeAnswer, togglePracticeSessionMap, toggleSubjectiveReference } from "./js/modules/practice.js";
import { renderHome } from "./js/views/home.js";
import { loadStats, openLogs, openStats, openWeeklyReport, renderLogsList, scheduleWeeklySave } from "./js/views/logs.js";
import { closeNotePopover, closeSectionMenu, finishReaderSession, navigateSection, openNotePopover, openSection, renderBooks, renderMaterial, renderSectionMenu, returnFromReader, returnFromResource, scheduleNoteSave } from "./js/views/reader.js";
import { markReviewNoText, openReview, scheduleDailySummarySave } from "./js/views/review.js";

export function bindNavigation() {
  document.querySelectorAll("[data-dashboard]").forEach((button) => button.addEventListener("click", setHomeMode));
  $("themeToggle")?.addEventListener("click", toggleTheme);
  applyTheme(document.documentElement.dataset.theme || "light", { persist: false });
  $("libraryNav").addEventListener("click", setLibraryMode); $("mobileLibrary").addEventListener("click", setLibraryMode);
  document.querySelectorAll("[data-shelf]").forEach((button) => button.addEventListener("click", () => selectLibraryShelf(button.dataset.shelf)));
  $("resourceBack").addEventListener("click", returnFromResource);
  $("resourceContinue").addEventListener("click", () => { const sectionId = $("resourceContinue").dataset.sectionId; if (sectionId) { state.readerOriginBookId = state.resourceBookId; openSection(sectionId); } });
  $("oralFocusBackToLibrary").addEventListener("click", async () => { await saveOralFocusNote(); state.libraryDomain = "medicine"; $("oralFocusNoteFloat").classList.add("hidden"); setLibraryMode(); });
  $("oralFocusBackToDirectory").addEventListener("click", async () => { await saveOralFocusNote(); setOralFocusNoteOpen(false); $("oralFocusNoteFloat").classList.add("hidden"); openOralFocusIndex(state.oralFocusSubjectId, state.oralFocusTypeFilter); });
  $("oralFocusBackToChapters").addEventListener("click", async () => { await saveOralFocusNote(); setOralFocusNoteOpen(false); $("oralFocusNoteFloat").classList.add("hidden"); state.oralFocusChapterId = ""; state.oralFocusChapter = null; renderOralFocusDirectory(); window.scrollTo({ top: 0, behavior: "auto" }); });
  $("oralFocusChapterAnswerToggle").addEventListener("click", toggleOralFocusChapterAnswers);
  $("oralFocusReferenceToggle").addEventListener("click", toggleOralFocusReference);
  $("oralFocusNote").addEventListener("input", scheduleOralFocusNoteSave);
  $("toggleOralFocusNote").addEventListener("click", () => setOralFocusNoteOpen(!state.oralFocusNoteOpen));
  $("closeOralFocusNote").addEventListener("click", () => setOralFocusNoteOpen(false));
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
  document.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (state.oralFocusNoteOpen) { setOralFocusNoteOpen(false); return; } if (state.noteOpen) { closeNotePopover({ restoreFocus: true }); return; } closeSectionMenu(); });
  window.addEventListener("hashchange", applyRouteHash);
}

export async function loadBootstrap() {
  try {
    const response = await fetch("/api/bootstrap", { cache: "no-store" }); const data = await response.json(); state.books = data.books || []; state.questionBanks = data.question_banks || [];
    try { await loadOralFocus(); } catch { state.oralFocus = { available: false, subjects: [] }; }
    state.books.forEach((book) => book.sections.forEach((section) => state.sections.set(section.id, { ...section, book_title: book.title, book_id: book.id }))); renderBooks(); await loadStats();
  } catch { $("bookTree").innerHTML = `<div class="knowledge-index-empty"><i data-lucide="cloud-off"></i><strong>暂时无法读取本地学习库</strong><span>请确认 YuReader 服务正在运行。</span></div>`; refreshIcons(); }
}

bindNavigation(); initializeReadingTimer(); refreshIcons(); loadBootstrap().then(applyRouteHash);
