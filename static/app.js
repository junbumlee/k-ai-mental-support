/* K리더용 걱정인형 — 세 줄 기록 + LLM 피드백 클라이언트 로직 */

const STORAGE_KEYS = {
  entries: "worrydoll.entries.v1",
  communityPosts: "worrydoll.communityPosts.v1",
  profile: "worrydoll.profile.v1",
};

// 리더 상황 카테고리 — id는 영문, label·placeholder는 사용자/LLM에 노출되는 한국어
const CATEGORIES = [
  {
    id: "performance",
    label: "성과 압박",
    prompt: "오늘 어떤 숫자나 평가가 가장 무겁게 느껴졌나요?",
    repeatPrompt: "성과 압박이 반복되고 있어요. 이번에는 어떤 지표, 회의, 평가 기준이 마음을 가장 눌렀나요?",
    placeholder: "예: 이번 주 KPI 보고에서 목표 달성률 질문을 받았다",
    repeatPlaceholder: "예: 지난번엔 매출이었고, 오늘은 전환율이 낮다는 말을 듣고 팀장으로서 무능해 보일까 걱정됐다",
  },
  {
    id: "team",
    label: "팀원 관리",
    prompt: "오늘 팀원 누구의 어떤 행동이 신경 쓰였나요?",
    repeatPrompt: "팀원 관리 고민이 다시 올라왔어요. 같은 팀원인지, 다른 팀원인지, 어떤 행동이 반복됐는지 적어볼까요?",
    placeholder: "예: 팀원이 회의에서 맡은 일을 모호하게 답했다",
    repeatPlaceholder: "예: 같은 팀원이 두 번째로 일정 질문에 침묵했고, 내가 계속 챙겨야 하나 싶었다",
  },
  {
    id: "evaluation",
    label: "평가·고과",
    prompt: "구체적으로 어떤 평가 상황이 떠오르나요?",
    repeatPrompt: "평가·고과 고민이 이어지고 있어요. 이번에는 누구의 평가, 어떤 기준, 어떤 말이 가장 걸렸나요?",
    placeholder: "예: 평가 면담에서 낮은 등급을 설명해야 했다",
    repeatPlaceholder: "예: 지난 면담 이후 같은 팀원의 승진 기준을 설명해야 하는데 납득시키지 못할까 걱정됐다",
  },
  {
    id: "report",
    label: "상사·보고",
    prompt: "보고에서 가장 떨렸던 한 순간을 적어보세요.",
    repeatPrompt: "상사·보고 장면이 반복되고 있어요. 이번에는 어떤 질문, 표정, 후속 지시가 가장 크게 남았나요?",
    placeholder: "예: 임원 보고에서 예상 못한 질문을 받았다",
    repeatPlaceholder: "예: 지난번엔 자료 누락이었고, 오늘은 임원의 짧은 침묵 때문에 내 판단을 의심하게 됐다",
  },
  {
    id: "conflict",
    label: "팀 내 갈등",
    prompt: "누구와의 어떤 장면이 머리에서 안 떠나나요?",
    repeatPrompt: "팀 내 갈등이 다시 선택됐어요. 이번에는 누구 사이의 갈등이고, 내가 어떤 역할을 해야 한다고 느꼈나요?",
    placeholder: "예: 두 팀원이 회의에서 서로 말을 끊었다",
    repeatPlaceholder: "예: 같은 두 팀원이 세 번째로 의견 충돌했고, 내가 중재를 못해서 팀 분위기가 망가질까 걱정됐다",
  },
];
const COMMUNITY_CATEGORIES = CATEGORIES;
const DEFAULT_SITUATION_PLACEHOLDER = "예: 회의에서 내 의견을 말하려다 멈췄다";
const DEFAULT_SITUATION_QUESTION = "오늘 마음에 걸렸던 순간은 어떤 장면이었나요?";
const PROFILE_FIELD_MAP = {
  job_role: "job-role",
  company_type: "company-type",
  industry: "industry",
  age_group: "age-group",
  org_culture: "org-culture",
  leader_authority: "leader-authority",
};

const state = {
  entries: loadEntries(),
  communityPosts: loadCommunityPosts(),
  profile: loadProfile(),
  user: null,
  selectedCategory: null,  // { id, label, placeholder } | null
  selectedCommunityCategory: null,
  communitySearch: "",
  pendingFeedback: null,
  pendingEntry: null,
};

/* ───── 탭 ───── */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) => {
      p.classList.toggle("active", p.dataset.panel === target);
    });
    if (target === "list") renderEntries();
    if (target === "community") renderCommunityPosts();
    if (target === "report") renderReport();
  });
});

/* ───── 카테고리 칩 ───── */
const categoryRow = document.getElementById("category-row");
const situationEl = document.getElementById("situation");
const situationQuestionEl = document.getElementById("situation-question");

CATEGORIES.forEach((cat) => {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "category-chip";
  btn.dataset.id = cat.id;
  btn.setAttribute("role", "radio");
  btn.setAttribute("aria-checked", "false");
  btn.textContent = cat.label;
  btn.addEventListener("click", () => selectCategory(cat));
  categoryRow.appendChild(btn);
});

function selectCategory(cat) {
  // 같은 칩 재클릭 → 해제
  const isUnselect = state.selectedCategory && state.selectedCategory.id === cat.id;
  state.selectedCategory = isUnselect ? null : cat;

  document.querySelectorAll(".category-chip").forEach((chip) => {
    const active = !isUnselect && chip.dataset.id === cat.id;
    chip.classList.toggle("active", active);
    chip.setAttribute("aria-checked", active ? "true" : "false");
  });

  if (!state.selectedCategory) {
    situationQuestionEl.textContent = DEFAULT_SITUATION_QUESTION;
    situationEl.placeholder = DEFAULT_SITUATION_PLACEHOLDER;
    return;
  }

  const count = getCategoryUseCount(cat.label);
  const repeated = count > 0;
  situationQuestionEl.textContent = repeated ? cat.repeatPrompt : cat.prompt;
  situationEl.placeholder = repeated ? cat.repeatPlaceholder : cat.placeholder;
}

const communityCategoryRow = document.getElementById("community-category-row");
if (communityCategoryRow) {
  COMMUNITY_CATEGORIES.forEach((cat) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "category-chip community-category-chip";
    btn.dataset.id = cat.id;
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", "false");
    btn.textContent = cat.label;
    btn.addEventListener("click", () => selectCommunityCategory(cat));
    communityCategoryRow.appendChild(btn);
  });
  selectCommunityCategory(COMMUNITY_CATEGORIES[0]);
}

function selectCommunityCategory(cat) {
  if (!cat) return;
  state.selectedCommunityCategory = cat;
  document.querySelectorAll(".community-category-chip").forEach((chip) => {
    const active = chip.dataset.id === cat.id;
    chip.classList.toggle("active", active);
    chip.setAttribute("aria-checked", active ? "true" : "false");
  });
}

/* ───── 프로필 ───── */
applyProfileToForm(state.profile);
syncSessionProfile();

document.getElementById("save-profile").addEventListener("click", async () => {
  const payload = collectProfileFromForm();
  try {
    const res = await fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      toast(data.message || "필수 정보를 모두 선택해주세요");
      return;
    }
    state.profile = data.profile || payload;
    localStorage.setItem(STORAGE_KEYS.profile, JSON.stringify(state.profile));
    applyProfileToForm(state.profile);
    renderCommunityPosts();
    renderReport();
    toast("저장됐어요");
  } catch {
    toast("연결이 불안정해요. 다시 시도해주세요");
  }
});

/* ───── 전체 삭제 ───── */
document.getElementById("clear-all").addEventListener("click", () => {
  if (!confirm("상담 기록과 커뮤니티 활동을 모두 삭제할까요? 되돌릴 수 없어요.")) return;
  state.entries = [];
  state.communityPosts = [];
  localStorage.removeItem(STORAGE_KEYS.entries);
  localStorage.removeItem(STORAGE_KEYS.communityPosts);
  renderEntries();
  renderCommunityPosts();
  renderReport();
  toast("기록이 모두 삭제됐어요");
});

document.getElementById("export-entries").addEventListener("click", () => {
  exportEntriesAsPdf({
    title: "K리더용 걱정인형 기록",
    filenamePrefix: "worrydoll",
  });
});

const communityForm = document.getElementById("community-form");
const communitySearchEl = document.getElementById("community-search");

if (communityForm) {
  communityForm.addEventListener("submit", handleCommunitySubmit);
}

if (communitySearchEl) {
  communitySearchEl.addEventListener("input", () => {
    state.communitySearch = communitySearchEl.value.trim();
    renderCommunityPosts();
  });
}

document.querySelectorAll(".diagnosis-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    toast("심층 진단 도구 연결은 준비 중이에요");
  });
});

/* ───── STT ───── */
let currentRec = null;
let currentRecBtn = null;

document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const btn = event.target.closest(".stt-btn");
  if (!btn) return;
  startSTT(btn);
});

function stopCurrentRec() {
  if (currentRec) {
    try { currentRec.abort(); } catch {}
  }
  currentRec = null;
  if (currentRecBtn) currentRecBtn.classList.remove("recording");
  currentRecBtn = null;
}

function startSTT(btn) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    toast("이 브라우저는 음성 입력을 지원하지 않아요");
    return;
  }

  // 같은 버튼 재클릭 → 토글로 중단
  if (currentRec && currentRecBtn === btn) {
    stopCurrentRec();
    return;
  }
  // 다른 버튼이 녹음 중이면 먼저 중단
  if (currentRec) stopCurrentRec();

  const targetId = btn.dataset.target;
  const textarea = document.getElementById(targetId);
  if (!textarea) {
    toast("입력 칸을 찾을 수 없어요");
    return;
  }

  const rec = new SpeechRecognition();
  rec.lang = "ko-KR";
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.continuous = false;

  rec.onresult = (e) => {
    const text = e.results[0][0].transcript;
    const existing = textarea.value.trim();
    textarea.value = existing ? `${existing} ${text}` : text;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  };
  rec.onerror = (e) => {
    const err = e.error || "unknown";
    if (err === "not-allowed" || err === "service-not-allowed") {
      toast("마이크 권한이 필요해요");
    } else if (err === "no-speech") {
      toast("말소리가 감지되지 않았어요");
    } else if (err !== "aborted") {
      toast(`음성 인식 실패 (${err})`);
    }
  };
  rec.onend = () => {
    if (currentRec === rec) {
      currentRec = null;
      currentRecBtn = null;
    }
    btn.classList.remove("recording");
  };

  try {
    rec.start();
    currentRec = rec;
    currentRecBtn = btn;
    btn.classList.add("recording");
  } catch (err) {
    // start()는 이미 active 상태면 InvalidStateError를 던짐
    btn.classList.remove("recording");
    currentRec = null;
    currentRecBtn = null;
    toast("음성 인식을 다시 시도해주세요");
  }
}

/* ───── 폼 제출 ───── */
const form = document.getElementById("diary-form");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const profile = collectProfileFromForm();
  state.profile = { ...state.profile, ...profile };
  const entry = {
    situation: document.getElementById("situation").value.trim(),
    thought: document.getElementById("thought").value.trim(),
    reframe: document.getElementById("reframe").value.trim(),
    job_role: state.profile.job_role || null,
    category: state.selectedCategory ? state.selectedCategory.label : null,
    category_count: state.selectedCategory ? getCategoryUseCount(state.selectedCategory.label) + 1 : null,
    company_type: state.profile.company_type || null,
    industry: state.profile.industry || null,
    age_group: state.profile.age_group || null,
    org_culture: state.profile.org_culture || null,
    leader_authority: state.profile.leader_authority || null,
  };
  if (!entry.situation || !entry.thought) return;

  const submitBtn = document.getElementById("submit-btn");
  const label = submitBtn.querySelector(".btn-label");
  const original = label.textContent;
  submitBtn.disabled = true;
  const stopProgress = startProgressLabel(label, "K리더용 걱정인형이 생각 중이에요");

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
    if (res.status === 401) {
      window.location.href = "/login";
      return;
    }
    const data = await res.json();
    state.pendingEntry = entry;
    state.pendingFeedback = data;
    renderFeedback(data);
  } catch (err) {
    toast("연결이 불안정해요. 다시 시도해주세요");
  } finally {
    stopProgress();
    submitBtn.disabled = false;
    label.textContent = original;
  }
});

/* 5초마다 심리상담가 톤의 대기 메시지를 무작위로 회전. 60s/150s 시점에는
   응답 지연 안내를 덧붙여 사용자가 창을 닫지 않도록 한다. AbortController는
   쓰지 않아 백엔드(Vercel maxDuration 내) 응답이면 늦게라도 처리된다. */
const COUNSELOR_MESSAGES = [
  "오늘 적어주신 마음을 천천히 읽고 있어요",
  "그 장면을 함께 떠올려보고 있어요",
  "어떤 단어가 가장 무겁게 느껴졌을지 살피고 있어요",
  "한 번 더 깊이 들여다보고 있어요",
  "조금 더 다정한 표현을 고르고 있어요",
  "당신의 맥락을 놓치지 않으려 천천히 보고 있어요",
  "어떻게 되돌려 물어볼지 신중히 고르고 있어요",
  "내일을 위한 작은 한 걸음을 그려보고 있어요",
  "성급하게 결론짓지 않으려 다시 살피고 있어요",
  "당신이 적어준 단어를 그대로 받아 안고 있어요",
  "마음 한쪽에 있던 감정을 함께 짚어보고 있어요",
  "지금 이 순간에 필요한 질문 하나를 다듬고 있어요",
];
function startProgressLabel(labelEl, baseText) {
  const dots = '<span class="loading-dots"></span>';
  const start = Date.now();
  let lastIdx = -1;
  const pickMessage = () => {
    let idx;
    do { idx = Math.floor(Math.random() * COUNSELOR_MESSAGES.length); }
    while (idx === lastIdx && COUNSELOR_MESSAGES.length > 1);
    lastIdx = idx;
    return COUNSELOR_MESSAGES[idx];
  };
  const apply = (firstTick) => {
    const elapsed = (Date.now() - start) / 1000;
    const main = firstTick ? baseText : pickMessage();
    let suffix = "";
    if (elapsed >= 150) suffix = " · 거의 다 됐어요, 창을 닫지 말고 잠시만요";
    else if (elapsed >= 60) suffix = " · 평소보다 조금 더 걸리고 있어요";
    labelEl.innerHTML = `${main}${dots}${suffix ? `<span class="progress-suffix">${suffix}</span>` : ""}`;
  };
  apply(true);
  const timer = setInterval(() => apply(false), 5000);
  return () => clearInterval(timer);
}

/* ───── 피드백 렌더링 ───── */
function renderFeedback(data) {
  const container = document.getElementById("feedback");
  container.classList.remove("hidden");
  container.innerHTML = "";

  if (data.mode === "crisis") {
    const tpl = document.getElementById("crisis-template").content.cloneNode(true);
    tpl.querySelector(".crisis-message").textContent = data.message;
    const ul = tpl.querySelector(".hotlines");
    data.hotlines.forEach((h) => {
      const li = document.createElement("li");
      li.innerHTML = `${h.name} <a href="tel:${h.number}">${h.number}</a>`;
      ul.appendChild(li);
    });
    container.appendChild(tpl);
    container.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const tpl = document.getElementById("feedback-template").content.cloneNode(true);
  if (data.mode === "fallback" && data.message) {
    const notice = document.createElement("div");
    notice.className = "feedback-fallback";
    notice.textContent = data.message;
    tpl.querySelector(".feedback-card").prepend(notice);
  }
  tpl.querySelector(".empathy").textContent = data.empathy || "이야기를 들려주셔서 고마워요.";

  const distortEl = tpl.querySelector(".distortions");
  const chipRow = tpl.querySelector(".chip-row");
  if (data.distortions && data.distortions.length) {
    distortEl.classList.remove("hidden");
    data.distortions.forEach((d) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = d;
      chipRow.appendChild(chip);
    });
  }

  tpl.querySelector(".reframe-text").textContent =
    data.reframe || "그 생각의 근거와 반대 근거를 각각 하나씩 떠올려볼까요?";
  tpl.querySelector(".question-text").textContent =
    data.question || "내일 한 번, 조금만 다르게 해볼 수 있는 일이 있을까요?";

  tpl.querySelector('[data-action="save"]').addEventListener("click", saveEntry);
  tpl.querySelector('[data-action="discard"]').addEventListener("click", discardEntry);

  container.appendChild(tpl);
  container.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ───── 저장 ───── */
function saveEntry() {
  if (!state.pendingEntry || !state.pendingFeedback) return;
  const record = {
    id: createId(),
    createdAt: new Date().toISOString(),
    entry: state.pendingEntry,
    feedback: state.pendingFeedback,
  };
  state.entries.unshift(record);
  localStorage.setItem(STORAGE_KEYS.entries, JSON.stringify(state.entries));

  form.reset();
  state.selectedCategory = null;
  document.querySelectorAll(".category-chip").forEach((chip) => {
    chip.classList.remove("active");
    chip.setAttribute("aria-checked", "false");
  });
  situationQuestionEl.textContent = DEFAULT_SITUATION_QUESTION;
  situationEl.placeholder = DEFAULT_SITUATION_PLACEHOLDER;
  document.getElementById("feedback").classList.add("hidden");
  state.pendingEntry = null;
  state.pendingFeedback = null;
  renderReport();
  toast("오늘의 걱정이 기록됐어요");
}

function discardEntry() {
  state.pendingEntry = null;
  state.pendingFeedback = null;
  document.getElementById("feedback").classList.add("hidden");
  stopCurrentRec();
  document.getElementById("situation").focus();
}

/* ───── 기록 리스트 ───── */
function renderEntries() {
  const container = document.getElementById("entries");
  const empty = document.getElementById("empty-state");
  container.innerHTML = "";
  if (!state.entries.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  state.entries.forEach((record) => {
    const tpl = document.getElementById("entry-template").content.cloneNode(true);
    const article = tpl.querySelector(".entry-card");
    article.dataset.id = record.id;

    tpl.querySelector("time").textContent = formatDate(record.createdAt);
    const categoryEl = tpl.querySelector(".entry-category");
    if (record.entry.category) {
      categoryEl.textContent = record.entry.category;
      categoryEl.classList.remove("hidden");
    }
    tpl.querySelector(".entry-situation").textContent = record.entry.situation;
    tpl.querySelector(".entry-thought").textContent = record.entry.thought;
    const reframe = tpl.querySelector(".entry-reframe");
    if (record.entry.reframe) reframe.textContent = record.entry.reframe;
    else reframe.remove();

    const fb = record.feedback || {};
    const parts = [];
    if (fb.empathy) parts.push(fb.empathy);
    if (fb.reframe) parts.push(`→ ${fb.reframe}`);
    tpl.querySelector(".entry-feedback").textContent = parts.join(" ");

    tpl.querySelector(".delete-btn").addEventListener("click", () => deleteEntry(record.id));
    container.appendChild(tpl);
  });
}

function deleteEntry(id) {
  state.entries = state.entries.filter((r) => r.id !== id);
  localStorage.setItem(STORAGE_KEYS.entries, JSON.stringify(state.entries));
  renderEntries();
  renderReport();
}

function exportEntriesAsPdf(options) {
  if (!state.entries.length) {
    toast("내보낼 기록이 아직 없어요");
    return;
  }
  const exporter = window.WorryDollExport;
  if (!exporter) {
    toast("내보내기 기능을 불러오지 못했어요");
    return;
  }
  const opened = exporter.openPdfPrintWindow(state.entries, options);
  toast(opened ? "인쇄 창에서 PDF로 저장할 수 있어요" : "팝업 차단을 해제한 뒤 다시 시도해주세요");
}

/* ───── 커뮤니티 ───── */
function handleCommunitySubmit(event) {
  event.preventDefault();
  const contentEl = document.getElementById("community-content");
  const content = contentEl.value.trim();
  if (!content) return;

  const category = state.selectedCommunityCategory || COMMUNITY_CATEGORIES[0];
  const post = {
    id: createId(),
    createdAt: new Date().toISOString(),
    category: category ? category.label : "",
    content,
    author: getPublicAuthor(state.profile),
    comments: [],
  };

  state.communityPosts.unshift(post);
  saveCommunityPosts();
  communityForm.reset();
  renderCommunityPosts();
  renderReport();
  toast("커뮤니티에 올라갔어요");
}

function renderCommunityPosts() {
  const container = document.getElementById("community-feed");
  const empty = document.getElementById("community-empty-state");
  if (!container || !empty) return;

  const query = state.communitySearch.toLowerCase();
  const posts = state.communityPosts.filter((post) => communityPostMatches(post, query));

  container.innerHTML = "";
  if (!posts.length) {
    empty.textContent = state.communityPosts.length ? "검색 결과가 없어요." : "아직 커뮤니티 글이 없어요.";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  posts.forEach((post) => {
    const tpl = document.getElementById("community-post-template").content.cloneNode(true);
    const article = tpl.querySelector(".community-card");
    article.dataset.id = post.id;

    tpl.querySelector(".community-author").textContent = formatAuthor(post.author);
    tpl.querySelector("time").textContent = formatDate(post.createdAt);
    tpl.querySelector(".community-category").textContent = post.category || "미분류";
    tpl.querySelector(".community-content").textContent = post.content;

    const commentList = tpl.querySelector(".comment-list");
    renderCommentList(commentList, post.comments || []);

    const commentInput = tpl.querySelector(".comment-input");
    const commentInputId = `comment-${post.id}`;
    commentInput.id = commentInputId;
    tpl.querySelector(".comment-stt-btn").dataset.target = commentInputId;

    tpl.querySelector(".comment-form").addEventListener("submit", (event) => {
      event.preventDefault();
      addCommunityComment(post.id, commentInput.value.trim());
    });
    tpl.querySelector(".delete-post-btn").addEventListener("click", () => deleteCommunityPost(post.id));

    container.appendChild(tpl);
  });
}

function communityPostMatches(post, query) {
  if (!query) return true;
  const haystack = [
    post.category,
    post.content,
    formatAuthor(post.author),
    ...(post.comments || []).map((comment) => `${formatAuthor(comment.author)} ${comment.text}`),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
}

function renderCommentList(container, comments) {
  container.innerHTML = "";
  comments.forEach((comment) => {
    const tpl = document.getElementById("comment-template").content.cloneNode(true);
    tpl.querySelector(".comment-author").textContent = formatAuthor(comment.author);
    tpl.querySelector("time").textContent = formatDate(comment.createdAt);
    tpl.querySelector("p").textContent = comment.text;
    container.appendChild(tpl);
  });
}

function addCommunityComment(postId, text) {
  if (!text) return;
  const post = state.communityPosts.find((item) => item.id === postId);
  if (!post) return;
  post.comments = post.comments || [];
  post.comments.push({
    id: createId(),
    createdAt: new Date().toISOString(),
    text,
    author: getPublicAuthor(state.profile),
  });
  saveCommunityPosts();
  renderCommunityPosts();
  renderReport();
  toast("댓글이 달렸어요");
}

function deleteCommunityPost(postId) {
  state.communityPosts = state.communityPosts.filter((post) => post.id !== postId);
  saveCommunityPosts();
  renderCommunityPosts();
  renderReport();
}

/* ───── 리포트 ───── */
const CATEGORY_INSIGHTS = {
  "성과 압박": "성과 기준과 실제로 통제 가능한 행동을 분리해 보면 부담의 크기를 더 정확히 볼 수 있어요.",
  "팀원 관리": "팀원의 행동을 리더십 전체 평가로 바로 연결하기보다, 관찰 가능한 행동과 필요한 대화를 나눠보는 흐름이 좋아요.",
  "평가·고과": "평가 장면에서는 공정성 부담이 커지기 쉬워요. 기준, 사실, 전달 방식을 나눠서 보는 것이 도움이 됩니다.",
  "상사·보고": "보고 장면의 침묵이나 질문을 능력 평가로 단정하기보다, 확인된 피드백과 추측을 구분해볼 필요가 있어요.",
  "팀 내 갈등": "갈등 상황에서는 중재 책임을 전부 떠안기 쉽습니다. 누구의 말과 행동이 사실로 확인됐는지부터 좁혀보세요.",
};

function renderReport() {
  const summary = document.getElementById("report-summary");
  const feed = document.getElementById("report-feed");
  const empty = document.getElementById("report-empty-state");
  if (!summary || !feed || !empty) return;

  const data = buildReportData();
  renderReportSummary(summary, data);
  renderReportFeed(feed, empty, data.activities);
}

function buildReportData() {
  const categoryCounts = new Map();
  const bumpCategory = (category) => {
    if (!category) return;
    categoryCounts.set(category, (categoryCounts.get(category) || 0) + 1);
  };

  state.entries.forEach((record) => bumpCategory(record.entry && record.entry.category));
  state.communityPosts.forEach((post) => bumpCategory(post.category));

  const categoryRows = Array.from(categoryCounts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "ko"));

  const activities = [
    ...state.entries.map((record) => ({
      id: record.id,
      type: "entry",
      typeLabel: "상담 기록",
      createdAt: record.createdAt,
      category: record.entry.category,
      primary: record.entry.situation,
      secondary: record.entry.thought,
      footer: record.feedback && record.feedback.reframe ? record.feedback.reframe : "",
    })),
    ...state.communityPosts.map((post) => ({
      id: post.id,
      type: "community",
      typeLabel: "커뮤니티 글",
      createdAt: post.createdAt,
      category: post.category,
      primary: post.content,
      secondary: formatAuthor(post.author),
      footer: `${(post.comments || []).length}개의 댓글`,
    })),
  ].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

  const commentCount = state.communityPosts.reduce(
    (sum, post) => sum + ((post.comments && post.comments.length) || 0),
    0
  );

  return {
    entryCount: state.entries.length,
    postCount: state.communityPosts.length,
    commentCount,
    categoryRows,
    topCategory: categoryRows[0] || null,
    latestEntry: state.entries[0] || null,
    activities,
  };
}

function renderReportSummary(container, data) {
  container.innerHTML = "";

  const card = document.createElement("article");
  card.className = "card report-card";

  const title = document.createElement("h2");
  title.textContent = "자동 심리분석 리포트";
  card.appendChild(title);

  const lead = document.createElement("p");
  lead.className = "report-lead";
  lead.textContent = getReportLead(data);
  card.appendChild(lead);

  const metrics = document.createElement("div");
  metrics.className = "report-metrics";
  [
    ["상담 기록", data.entryCount],
    ["커뮤니티 글", data.postCount],
    ["댓글", data.commentCount],
  ].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "report-metric";
    const strong = document.createElement("strong");
    strong.textContent = value;
    const span = document.createElement("span");
    span.textContent = label;
    item.append(strong, span);
    metrics.appendChild(item);
  });
  card.appendChild(metrics);

  if (data.categoryRows.length) {
    const categories = document.createElement("div");
    categories.className = "report-category-row";
    data.categoryRows.forEach((row) => {
      const chip = document.createElement("span");
      chip.className = "report-category-chip";
      chip.textContent = `${row.label} ${row.count}`;
      categories.appendChild(chip);
    });
    card.appendChild(categories);
  }

  const insights = document.createElement("ul");
  insights.className = "report-insights";
  getReportInsights(data).forEach((text) => {
    const item = document.createElement("li");
    item.textContent = text;
    insights.appendChild(item);
  });
  card.appendChild(insights);

  container.appendChild(card);
}

function renderReportFeed(container, empty, activities) {
  container.innerHTML = "";
  if (!activities.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  activities.forEach((activity) => {
    const article = document.createElement("article");
    article.className = "report-activity-card";

    const header = document.createElement("header");
    const meta = document.createElement("div");
    meta.className = "report-activity-meta";
    const type = document.createElement("span");
    type.className = `report-type report-type-${activity.type}`;
    type.textContent = activity.typeLabel;
    const time = document.createElement("time");
    time.textContent = formatDate(activity.createdAt);
    meta.append(type, time);

    const category = document.createElement("span");
    category.className = "entry-category";
    category.textContent = activity.category || "미분류";
    header.append(meta, category);

    const primary = document.createElement("p");
    primary.className = "report-primary";
    primary.textContent = activity.primary;
    article.append(header, primary);

    if (activity.secondary) {
      const secondary = document.createElement("p");
      secondary.className = "report-secondary";
      secondary.textContent = activity.secondary;
      article.appendChild(secondary);
    }

    if (activity.footer) {
      const footer = document.createElement("footer");
      footer.textContent = activity.footer;
      article.appendChild(footer);
    }

    container.appendChild(article);
  });
}

function getReportLead(data) {
  if (!data.activities.length) {
    return "쓰기와 커뮤니티 활동이 쌓이면 자동으로 업데이트됩니다.";
  }
  if (!data.topCategory) {
    return "최근 활동이 쌓이고 있어요. 분류가 추가되면 반복되는 주제를 더 선명하게 볼 수 있습니다.";
  }
  return `최근 활동에서는 '${data.topCategory.label}' 맥락이 가장 자주 나타납니다. 같은 분류가 반복될수록 지금 마음을 압박하는 업무 장면을 더 구체적으로 볼 수 있어요.`;
}

function getReportInsights(data) {
  if (!data.activities.length) {
    return ["상담 기록과 커뮤니티 글을 남기면 이곳에 자동 분석이 생성됩니다."];
  }

  const insights = [];
  if (data.topCategory) {
    insights.push(CATEGORY_INSIGHTS[data.topCategory.label] || `${data.topCategory.label} 주제가 반복되고 있어요.`);
  }
  if (data.latestEntry && data.latestEntry.entry && data.latestEntry.entry.thought) {
    insights.push(`최근 자동 생각은 '${truncateText(data.latestEntry.entry.thought, 48)}' 쪽에 가까워요. 사실과 해석을 나눠 적어보면 다음 행동이 더 또렷해질 수 있습니다.`);
  }
  if (data.postCount) {
    insights.push(`커뮤니티에는 ${data.postCount}개의 고민을 공유했습니다. 혼자 정리한 기록과 공개적으로 나눈 고민을 함께 보면 반복되는 업무 맥락이 더 잘 보입니다.`);
  }
  if (!insights.length) {
    insights.push("활동이 더 쌓이면 반복 주제와 최근 신호를 자동으로 정리합니다.");
  }
  return insights;
}

/* ───── Helpers ───── */
function loadEntries() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEYS.entries) || "[]");
  } catch {
    return [];
  }
}

function loadCommunityPosts() {
  try {
    const posts = JSON.parse(localStorage.getItem(STORAGE_KEYS.communityPosts) || "[]");
    if (!Array.isArray(posts)) return [];
    return posts
      .filter((post) => post && typeof post === "object")
      .map((post) => ({
        id: post.id || createId(),
        createdAt: post.createdAt || new Date().toISOString(),
        category: post.category || "",
        content: post.content || "",
        author: normalizeAuthor(post.author),
        comments: Array.isArray(post.comments)
          ? post.comments
              .filter((comment) => comment && typeof comment === "object")
              .map((comment) => ({
                id: comment.id || createId(),
                createdAt: comment.createdAt || new Date().toISOString(),
                text: comment.text || "",
                author: normalizeAuthor(comment.author),
              }))
          : [],
      }))
      .filter((post) => post.content.trim());
  } catch {
    return [];
  }
}

function saveCommunityPosts() {
  localStorage.setItem(STORAGE_KEYS.communityPosts, JSON.stringify(state.communityPosts));
}

function loadProfile() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEYS.profile) || "{}");
    return normalizeProfile(stored);
  } catch {
    return {};
  }
}

function normalizeProfile(profile) {
  if (!profile || typeof profile !== "object") return {};
  return {
    ...profile,
    job_role: profile.job_role || profile.jobRole || "",
  };
}

function collectProfileFromForm() {
  const payload = {};
  Object.entries(PROFILE_FIELD_MAP).forEach(([key, id]) => {
    const el = document.getElementById(id);
    payload[key] = el ? el.value.trim() : "";
  });
  return payload;
}

function applyProfileToForm(profile) {
  const normalized = normalizeProfile(profile);
  Object.entries(PROFILE_FIELD_MAP).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (el) el.value = normalized[key] || "";
  });
}

function getPublicAuthor(profile) {
  const normalized = normalizeProfile(profile);
  return normalizeAuthor({
    company_type: normalized.company_type || "",
    industry: normalized.industry || "",
  });
}

function normalizeAuthor(author) {
  if (!author || typeof author !== "object") {
    return { company_type: "", industry: "" };
  }
  return {
    company_type: String(author.company_type || "").trim().slice(0, 30),
    industry: String(author.industry || "").trim().slice(0, 30),
  };
}

function formatAuthor(author) {
  const normalized = normalizeAuthor(author);
  const parts = [normalized.company_type, normalized.industry].filter(Boolean);
  return parts.length ? parts.join(" · ") : "익명 리더";
}

async function syncSessionProfile() {
  try {
    const res = await fetch("/api/me");
    const data = await res.json();
    if (!data.authenticated) {
      window.location.href = "/login";
      return;
    }
    state.user = data.user || null;
    state.profile = normalizeProfile(data.profile || state.profile);
    localStorage.setItem(STORAGE_KEYS.profile, JSON.stringify(state.profile));
    applyProfileToForm(state.profile);
    renderAccount();
    renderCommunityPosts();
    renderReport();
  } catch {
    renderAccount();
  }
}

function renderAccount() {
  const nameEl = document.getElementById("account-name");
  const emailEl = document.getElementById("account-email");
  if (!nameEl || !emailEl || !state.user) return;
  nameEl.textContent = state.user.name || "로그인 사용자";
  emailEl.textContent = state.user.email || "";
}

function getCategoryUseCount(label) {
  return state.entries.filter((record) => record.entry && record.entry.category === label).length;
}

function formatDate(iso) {
  const d = new Date(iso);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}.${mm}.${dd} ${hh}:${mi}`;
}

function createId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function truncateText(text, maxLength) {
  const value = String(text || "").trim();
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}…`;
}

function toast(message) {
  const el = document.createElement("div");
  el.textContent = message;
  el.style.cssText = `
    position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
    background: #2b2531; color: #fff; padding: 10px 18px; border-radius: 999px;
    font-size: 13px; z-index: 999; box-shadow: 0 8px 24px rgba(0,0,0,0.2);
    opacity: 0; transition: opacity 0.2s;
  `;
  document.body.appendChild(el);
  requestAnimationFrame(() => (el.style.opacity = "1"));
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 1800);
}
