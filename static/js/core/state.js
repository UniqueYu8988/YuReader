export const DOMAIN_LABELS = { medicine: "医学", politics: "政治", english: "英语", mistakes: "错题" };
export const SHELF_ORDER = ["medicine", "politics", "english", "mistakes"];
export const BOOK_COVER_LABELS = {
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
export const ORAL_REFERENCE_STORAGE_KEY = "yureader-oral-reference-visible";
export const ORAL_FOCUS_TYPE_STORAGE_KEY = "yureader-oral-focus-type";
export const THEME_STORAGE_KEY = "yureader-theme";
export const READING_IDLE_MS = 10 * 60 * 1000;
export const READING_FLUSH_SECONDS = 15;

export const ROUTE_ALIASES = {
  today: "home", home: "home", dashboard: "home",
  library: "library", books: "library", bookshelf: "library", shelf: "library",
  "oral-focus": "oralFocus", "library/oral-focus": "oralFocus",
  review: "review", reviews: "review", "yesterday-review": "review",
  records: "logs", record: "logs", logs: "logs", log: "logs",
  "records/stats": "stats", stats: "stats", statistics: "stats",
};

export const state = {
  books: [], questionBanks: [], sections: new Map(), current: null,
  libraryBookId: null, libraryDomain: "medicine", resource: null,
  resourceBookId: null, resourceCache: new Map(), resourceLoads: new Map(),
  libraryRailPages: {}, englishCenterTrack: 1, englishCenterYear: "",
  englishCenterType: "reading", englishCenterOverviewCache: new Map(),
  englishExamOverview: null, englishExamOverviewBankId: "",
  readerOriginBookId: null, material: "cleaned", saveTimer: null,
  noteOpen: false, noteTrigger: null, openRequest: 0, review: null,
  reviewSummarySaveTimer: null, logs: null, weekly: null,
  weeklySaveTimer: null, stats: null, homeContinueTarget: null,
  homeResumeTargets: new Map(), readingActive: false, readingSectionId: "",
  readingLastTick: Date.now(), readingLastScroll: 0, readingPendingSeconds: 0,
  readingFlushKey: "", workspaceActivity: null, workspaceActive: false,
  workspaceLastTick: Date.now(), workspaceLastActive: 0, workspacePendingSeconds: 0,
  workspaceFlushSequence: 0, workspaceFlushKey: "", homeResizeTimer: null,
  practice: null, practiceIndex: 0, practiceReturn: "reader",
  practiceOverviewBankId: "", practiceAnalysisSaveTimer: null,
  practiceReadingItems: [], practiceReadingToken: 0, subjectivePractice: null,
  subjectiveReturn: "exam-overview", subjectiveSaveTimer: null, oralFocus: null,
  oralFocusSubjectId: "", oralFocusTypeFilter: "", oralFocusChapterId: "",
  oralFocusChapter: null, oralFocusItem: null, oralFocusFlatItems: [],
  oralFocusCardModes: new Map(), oralFocusExpandedNotes: new Set(),
  oralFocusSaveTimer: null, oralFocusNoteDirty: false, oralFocusNoteOpen: false,
  oralFocusReferenceVisible: (() => {
    try { return localStorage.getItem(ORAL_REFERENCE_STORAGE_KEY) === "true"; } catch { return false; }
  })(),
};

export const $ = (id) => document.getElementById(id);
if (typeof window !== 'undefined') window.$ = $;
