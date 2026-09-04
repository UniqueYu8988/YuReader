import { $, state } from "../core/state.js";
import { refreshIcons } from "../core/utils.js";

export const GUIDE_SECTIONS = [
  {
    key: "home",
    title: "今日工作台",
    subtitle: "作息目标中枢与快捷检索",
    icon: "house",
    views: ["home"],
    summary: "聚合今日专注时间、宏观目标达成率与四大核心模块入口，支持一键穿透秒搜教材与笔记。",
    features: [
      {
        badge: "快捷检索",
        title: "全局穿透秒搜 (Ctrl + K)",
        desc: "按下 <kbd>Ctrl</kbd> + <kbd>K</kbd> 呼出搜索框，毫秒级跨模块检索 11 本口腔教材原文、政治核心讲义、英语历年真题、重点名解论述题及复盘笔记，支持键盘上下键选定并直达对应段落。"
      },
      {
        badge: "自律中枢",
        title: "今日目标管理与进度反馈",
        desc: "点击右上角「编辑目标」，可量化设置今日总专注时长，以及医学（教材/名解/论述）、英语（基础/阅读理解）、政治（讲义/练习）的分科学时与篇数。做题与研读时进度条实时更新，直观呈现达成百分比。"
      },
      {
        badge: "即时传送",
        title: "四大核心入口直达",
        desc: "首页设有「口腔重点背诵」「英语方法与真题」「政治讲义与测验」「昨日回顾复盘」四大卡片，点击一秒穿透至核心学习区域。"
      }
    ]
  },
  {
    key: "library",
    title: "学习中心与错题",
    subtitle: "全科学术资源架与二刷攻坚",
    icon: "library",
    views: ["library"],
    summary: "分类陈列口腔医学 11 本核心教材、政治五大科目讲义、英语方法论与历年真题库，以及客观题错题重练中心。",
    features: [
      {
        badge: "学科书架",
        title: "三大学科分类资料架",
        desc: "顶部「医学」「政治」「英语」「错题」快速切换。教材卡片标明章节总数与研读进度；点击任意教材进入目录主页，带有「继续学习」记忆书签与整书目录树。"
      },
      {
        badge: "弱项突破",
        title: "错题攻坚中心 (Mistakes Bank)",
        desc: "所有在政治理论与考研英语中答错的客观题自动聚合于此。支持按政治/英语及待攻坚/已斩杀筛选；点击错题卡进入独立二刷练习，答对后自动标记为已斩杀，攻克知识盲区。"
      },
      {
        badge: "真题导览",
        title: "英语历年真题题型导览",
        desc: "覆盖近 15 年考研英语真题，支持按「完形填空」「阅读理解各篇」「新题型」「英译汉」「小作文/大作文」针对性进入作答，真实还原考场结构。"
      }
    ]
  },
  {
    key: "reader",
    title: "讲义与教材研读",
    subtitle: "深度阅读、语法显微镜与读练闭环",
    icon: "book-open",
    views: ["reader"],
    summary: "纯净沉浸式正文阅读器，融合长难句分层显微镜、政治考点胶囊、节末即时测验与 Obsidian 独立笔记抽屉。",
    features: [
      {
        badge: "考研英语",
        title: "长难句「成分显微镜」与即时查词",
        desc: "在《长难句88练》与语法文章中，自动对句子成分分层标注：主干/主句（陶土边框）、谓语动词（棕褐底纹）、从句（青黛标识）、修饰成分（微弱斜体）。双击文章中任意英文单词唤起轻量字典气泡，查看考研释义并可一键「收录至生词笔记」。"
      },
      {
        badge: "考研政治",
        title: "考点 Callouts 与节末测验直通卡",
        desc: "政治基础讲义自动标注高频考点锚点（根本标志、本质属性、主要矛盾等）。小节末尾自动嵌入「考点即时测验」直通卡，点击一键开练，彻底打通阅读输入到做题输出闭环。"
      },
      {
        badge: "便捷导航",
        title: "面包屑导航与章节速切",
        desc: "顶部面包屑支持点击下拉菜单快速选择同书同章任意小节；底部常驻「上一节」「结束阅读」「下一节」，沉浸阅读不中断。"
      },
      {
        badge: "知识沉淀",
        title: "右下角 Obsidian 笔记抽屉",
        desc: "点击右下角紫晶 Obsidian 浮钮随时唤出笔记抽屉，Markdown 编辑，输入防抖自动保存，并支持一键唤醒本地 Obsidian 客户端打开独立章节笔记。"
      }
    ]
  },
  {
    key: "oralFocus",
    title: "口腔重点背诵",
    subtitle: "名解论述、背诵遮罩与艾宾浩斯记忆卡",
    icon: "brain",
    views: ["oralFocus", "oral-focus"],
    summary: "针对口腔综合 6 大亚专科（口外、口内、口病、口解、修复、正畸）的名词解释与简答论述，提供列表研读与 Anki 翻转背诵卡双模式。",
    features: [
      {
        badge: "双模式",
        title: "目录列表模式 vs 翻转背诵卡 (Anki)",
        desc: "在章节顶栏可自由切换「目录列表」与「翻转背诵卡」。背诵卡模式下，卡片正面呈现题干与重要度评级，点击卡片或按 <kbd>Space</kbd> 空格键一秒翻转查看权威采分点，沉浸高效背诵。"
      },
      {
        badge: "记忆曲线",
        title: "艾宾浩斯三档记忆评级",
        desc: "背诵卡下方提供三档评级：<strong style='color:var(--error-strong)'>完全遗忘</strong>（重新排队，10分钟后再测）、<strong style='color:var(--primary-strong)'>模糊犹豫</strong>（+2 天后复测）、<strong style='color:var(--success-strong)'>熟练掌握</strong>（+4 天稳固记忆），依据记忆遗忘曲线精准调度。"
      },
      {
        badge: "主动回忆",
        title: "主动回忆背诵遮罩 (Cloze Mode)",
        desc: "顶栏点击「背诵遮罩」开关，标准答案中的核心数值、药物浓度、英文缩写与解剖关键词将被温和遮挡（<code>···</code>）。背诵时先尝试自我默写，点击任意项可即时点亮翻开，再次点击复原。"
      },
      {
        badge: "提纲脉络",
        title: "提纲骨架徽章流 (Outline Stream)",
        desc: "论述题与综合名解正文顶部提取概念、适应证、禁忌证、主要表现等二级提纲徽章流，点击平滑滚动至采分点，告别大段文字视疲劳。"
      },
      {
        badge: "自测验证",
        title: "「只看题目」快速自测",
        desc: "点击「只看题目」开关可瞬间收起整章所有参考答案，适合考前对照目录快速过筛，进行自查自纠。"
      }
    ]
  },
  {
    key: "practice",
    title: "做题与练习系统",
    subtitle: "全键盘心流、排除法、题文联动与错因诊断",
    icon: "pen-tool",
    views: ["practice"],
    summary: "深度考研真题与章节题库做题系统，支持全键盘极速盲打作答、右键排除选项、疑难存疑插旗、阅读理解双栏对齐与错因一秒同步。",
    features: [
      {
        badge: "键盘心流",
        title: "全键盘极速作答 (Flow)",
        desc: "按键 <kbd>A</kbd> / <kbd>B</kbd> / <kbd>C</kbd> / <kbd>D</kbd>（或 <kbd>1</kbd>-<kbd>4</kbd>）直选选项；按 <kbd>Enter</kbd> 提交作答；揭晓后按 <kbd>Enter</kbd> / <kbd>Space</kbd> / <kbd>→</kbd> 快速切入下一题；按 <kbd>←</kbd> 回退上一题。在笔记框打字时快捷键安全隔离。"
      },
      {
        badge: "考场技巧",
        title: "选项右键排除划线法",
        desc: "在任意选项上单击鼠标右键（<code>contextmenu</code>），选项文字即被添加贯穿划线并弱化对比度；再次右键取消排除。若按键选中已被排除项，系统智能解除排除并选定。"
      },
      {
        badge: "复盘标记",
        title: "疑难插旗复查 (快捷键 F)",
        desc: "做题过程中随时按 <kbd>F</kbd> 或点击题头小旗标记存疑。右上角答题卡（Session Map）同步渲染琥珀色小旗角标；做完全组后结算页新增「复查存疑题目」一键直通。"
      },
      {
        badge: "题文对齐",
        title: "阅读理解双栏对齐与自然段徽章",
        desc: "阅读理解分栏布局中，左侧文章正文每个自然段悬挂 <kbd>[P1]</kbd>、<kbd>[P2]</kbd> 等宽段落徽标。右侧题干中涉及的段落关键词（如 <code>Paragraph 5</code>）自动变为交互胶囊，点击后左侧文章平滑滚动居中并触发暖色脉冲高亮。"
      },
      {
        badge: "智能归因",
        title: "一键六维错因诊断胶囊",
        desc: "做错或解析卡顶部提供 <kbd>概念混淆</kbd> <kbd>审题失误</kbd> <kbd>知识盲区</kbd> <kbd>偷换概念</kbd> <kbd>无中生有</kbd> <kbd>粗心失误</kbd> 胶囊，点击一秒格式化写入个人解析并异步同步至本地 Obsidian Vault。"
      },
      {
        badge: "主观题",
        title: "主观题独立作答与思考对照",
        desc: "针对英语翻译与大小作文，左侧原文材料，右侧独立输入大文本域、实时字数统计与目标字数提示，完成后展开参考解析对照反思。"
      }
    ]
  },
  {
    key: "review",
    title: "每日回顾工作流",
    subtitle: "昨日笔记整合与 AI 框架复盘",
    icon: "history",
    views: ["review"],
    summary: "基于每日学习闭环的复盘中心，整合昨日三科学时与笔记卡片流，支持一键发送侧边栏 AI 生成系统化总结并沉淀至日记。",
    features: [
      {
        badge: "昨日全貌",
        title: "昨日三科概览看板",
        desc: "聚合昨日有效研习时长、产出笔记条数以及医学/政治/英语三科的细分学时与产出明细。"
      },
      {
        badge: "AI 复盘",
        title: "一键复制笔记摘要（发给侧边栏）",
        desc: "点击顶部「复制笔记摘要」，系统将昨日所有零散笔记按学科自动排版并复制到剪贴板，直接粘贴到右侧 Gemini 侧边栏即可生成高水准的知识框架与串联总结。"
      },
      {
        badge: "笔记卡片流",
        title: "按学科卡片化复盘",
        desc: "笔记按全部、医学、政治、英语分类展示，带有准确的图书与章节来源锚点，支持随时回顾与检查。"
      },
      {
        badge: "日记沉淀",
        title: "统一 Obsidian 今日复盘抽屉",
        desc: "将侧边栏生成的总结粘贴到右下角抽屉中，自动保存并同步至 Obsidian 独立复盘记录中，完成昨日到今日的学习闭环。"
      }
    ]
  },
  {
    key: "logs",
    title: "成长档案与周报织网",
    subtitle: "周期性成长脉络与知识织网",
    icon: "mails",
    views: ["logs"],
    summary: "周度成长足迹、多维学时统计与周期性宏观知识织网，助你在考研漫长备考周期中清晰看到积累过程。",
    features: [
      {
        badge: "周期看板",
        title: "本周学时与活跃天数概览",
        desc: "汇总近 7 天有效专注时长、学习天数、完成复盘天数以及三科投入占比，把控整体复习节奏。"
      },
      {
        badge: "跨科织网",
        title: "一键生成周度织网摘要",
        desc: "点击「生成周度织网摘要」，提取整周核心产出，让侧边栏 AI 深度诊断本周高频薄弱环节，输出跨学科关联图谱与下周攻坚建议。"
      },
      {
        badge: "时间轴",
        title: "成长足迹与分类筛选",
        desc: "支持按「全部足迹」「周报归档」「每日记录」「学时统计」自由筛选，翻阅历经数月打磨积累下的学术记录。"
      }
    ]
  },
  {
    key: "stats",
    title: "学业全景与活力节律",
    subtitle: "宏观画像、三时段热力图与生产力杠杆",
    icon: "chart-pie",
    views: ["stats"],
    summary: "多维度量化考研生产力：四维宏观里程碑、近 12 周晨午暮三时段热力图、三科学术资产深度纵深与输入/输出杠杆比率。",
    features: [
      {
        badge: "核心画像",
        title: "四维宏观里程碑",
        desc: "累计专注学时、连续研习天数、客观题做题总数与正确率、笔记与复盘字数，见证从零到一的扎实蜕变。"
      },
      {
        badge: "作息优化",
        title: "近 12 周晨午暮活力热力图",
        desc: "将每日专注时段细分为晨间 (05-12)、午后 (12-18)、晚间 (18-24+)，以活力胶囊形式直观反映个人作息节律，算法自动识别并提示黄金高效专注时段。"
      },
      {
        badge: "学科纵深",
        title: "三大学科学术资产卡片",
        desc: "展示医学教材本数与笔记篇数、政治题量与正确率、英语真题量与词汇沉淀，点击卡片右上角「前往学习」可一键直达对应学科书架。"
      },
      {
        badge: "学习科学",
        title: "被动输入 VS 主动输出配比",
        desc: "统计被动输入（教材精读、看解析）与主动输出（做题、背诵、复盘）的时间分配比率，指导用户坚决践行“以测代练”的高效考研学习法则。"
      }
    ]
  }
];

let activeGuideKey = "home";

export function getRecommendedGuideKey() {
  const currentView = state.activeView;
  if (currentView) {
    const found = GUIDE_SECTIONS.find((sec) => sec.views.includes(currentView));
    if (found) return found.key;
  }
  for (const sec of GUIDE_SECTIONS) {
    for (const v of sec.views) {
      if ($(`${v}View`)?.classList.contains("active")) {
        return sec.key;
      }
    }
  }
  return "home";
}

export function openGuide(specifiedKey = null) {
  const targetKey = specifiedKey || getRecommendedGuideKey();
  activeGuideKey = targetKey;

  const modal = $("appGuideModal");
  if (!modal) return;

  renderGuideNav();
  renderGuideContent(activeGuideKey);

  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  refreshIcons();

  window.setTimeout(() => {
    const activeTab = modal.querySelector(`.guide-nav-item[data-guide-key="${activeGuideKey}"]`);
    activeTab?.focus();
  }, 100);
}

export function closeGuide() {
  const modal = $("appGuideModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

export function switchGuideTab(key) {
  const target = GUIDE_SECTIONS.find((sec) => sec.key === key);
  if (!target) return;
  activeGuideKey = key;
  renderGuideNav();
  renderGuideContent(key);
  refreshIcons();
}

function renderGuideNav() {
  const nav = $("appGuideNav");
  if (!nav) return;

  nav.innerHTML = GUIDE_SECTIONS.map((sec) => {
    const isActive = sec.key === activeGuideKey;
    return `
      <button type="button" class="guide-nav-item ${isActive ? "active" : ""}" data-guide-key="${sec.key}" data-guide-tab="${sec.key}" role="tab" aria-selected="${isActive}">
        <i data-lucide="${sec.icon}"></i>
        <div class="guide-nav-text">
          <strong>${sec.title}</strong>
          <small>${sec.subtitle}</small>
        </div>
        ${isActive ? `<i data-lucide="chevron-right" class="guide-nav-active-arrow"></i>` : ""}
      </button>
    `;
  }).join("");

  nav.querySelectorAll(".guide-nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchGuideTab(btn.dataset.guideKey));
  });
}

function renderGuideContent(key) {
  const contentEl = $("appGuideContent");
  if (!contentEl) return;

  const section = GUIDE_SECTIONS.find((sec) => sec.key === key) || GUIDE_SECTIONS[0];

  contentEl.innerHTML = `
    <header class="guide-content-header">
      <div class="guide-header-badge">
        <i data-lucide="${section.icon}"></i>
        <span>${section.subtitle}</span>
      </div>
      <h2>${section.title} 使用指南</h2>
      <p class="guide-content-summary">${section.summary}</p>
    </header>

    <div class="guide-feature-list">
      ${section.features.map((feat, idx) => `
        <article class="guide-feature-card">
          <div class="guide-feature-num">0${idx + 1}</div>
          <div class="guide-feature-main">
            <header class="guide-feature-head">
              <span class="guide-feature-tag">${feat.badge}</span>
              <h3>${feat.title}</h3>
            </header>
            <div class="guide-feature-desc">${feat.desc}</div>
          </div>
        </article>
      `).join("")}
    </div>

    <footer class="guide-content-footer">
      <div class="guide-shortcut-summary">
        <i data-lucide="sparkles"></i>
        <span>小贴士：在任意页面均可随时按下 <kbd>?</kbd>（<code>Shift + /</code>）或点击右下角指南针图标呼出本说明书。</span>
      </div>
    </footer>
  `;
}

export function bindGuideEvents() {
  const launcher = $("appGuideLauncher");
  const guideNav = $("guideNav");
  const closeBtn = $("appGuideClose");
  const backdrop = $("appGuideBackdrop");

  launcher?.addEventListener("click", () => openGuide());
  guideNav?.addEventListener("click", () => openGuide());
  closeBtn?.addEventListener("click", closeGuide);
  backdrop?.addEventListener("click", closeGuide);

  document.addEventListener("keydown", (e) => {
    if (e.target?.matches?.("input, textarea, [contenteditable='true']") || state.practiceNoteOpen) {
      if (e.key === "Escape" && !$("appGuideModal")?.classList.contains("hidden")) {
        closeGuide();
      }
      return;
    }

    if (e.key === "?" || (e.shiftKey && e.code === "Slash")) {
      e.preventDefault();
      const modal = $("appGuideModal");
      if (modal && !modal.classList.contains("hidden")) {
        closeGuide();
      } else {
        openGuide();
      }
      return;
    }

    if (e.key === "Escape" && !$("appGuideModal")?.classList.contains("hidden")) {
      e.preventDefault();
      closeGuide();
    }
  });
}
