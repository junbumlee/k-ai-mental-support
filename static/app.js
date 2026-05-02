/* K리더용 걱정인형 — 세 줄 기록 + LLM 피드백 클라이언트 로직 */

const STORAGE_KEYS = {
  entries: "worrydoll.entries.v1",
  profile: "worrydoll.profile.v1",
};

// 리더 상황 카테고리 — id는 영문, label·placeholder는 사용자/LLM에 노출되는 한국어
const CATEGORIES = [
  { id: "performance", label: "성과 압박",  placeholder: "오늘 어떤 숫자나 평가가 가장 무겁게 느껴졌나요?" },
  { id: "team",        label: "팀원 관리",  placeholder: "오늘 팀원 누구의 어떤 행동이 신경 쓰였나요?" },
  { id: "evaluation",  label: "평가·고과",  placeholder: "구체적으로 어떤 평가 상황이 떠오르나요?" },
  { id: "report",      label: "상사·보고",  placeholder: "보고에서 가장 떨렸던 한 순간을 적어보세요" },
  { id: "conflict",    label: "팀 내 갈등", placeholder: "누구와의 어떤 장면이 머리에서 안 떠나나요?" },
  { id: "other",       label: "기타",      placeholder: "지금 머릿속에 가장 먼저 떠오르는 한 줄을 적어보세요" },
];
const DEFAULT_SITUATION_PLACEHOLDER = "예: 회의에서 내 의견을 말하려다 멈췄다";

const state = {
  entries: loadEntries(),
  profile: loadProfile(),
  selectedCategory: null,  // { id, label, placeholder } | null
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
  });
});

/* ───── 카테고리 칩 ───── */
const categoryRow = document.getElementById("category-row");
const situationEl = document.getElementById("situation");

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

  situationEl.placeholder = state.selectedCategory
    ? state.selectedCategory.placeholder
    : DEFAULT_SITUATION_PLACEHOLDER;
}

/* ───── 프로필 ───── */
const jobInput = document.getElementById("job-role");
jobInput.value = state.profile.jobRole || "";
document.getElementById("save-profile").addEventListener("click", () => {
  state.profile.jobRole = jobInput.value.trim();
  localStorage.setItem(STORAGE_KEYS.profile, JSON.stringify(state.profile));
  toast("저장됐어요");
});

/* ───── 전체 삭제 ───── */
document.getElementById("clear-all").addEventListener("click", () => {
  if (!confirm("모든 기록을 삭제할까요? 되돌릴 수 없어요.")) return;
  state.entries = [];
  localStorage.removeItem(STORAGE_KEYS.entries);
  renderEntries();
  toast("기록이 모두 삭제됐어요");
});

/* ───── STT ───── */
let currentRec = null;
let currentRecBtn = null;

document.querySelectorAll(".stt-btn").forEach((btn) => {
  btn.addEventListener("click", () => startSTT(btn));
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
  const entry = {
    situation: document.getElementById("situation").value.trim(),
    thought: document.getElementById("thought").value.trim(),
    reframe: document.getElementById("reframe").value.trim(),
    job_role: state.profile.jobRole || null,
    category: state.selectedCategory ? state.selectedCategory.label : null,
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

/* 경과 시간에 따라 라벨을 단계적으로 바꿔, 사용자가 응답 지연을 인지하고
   창을 닫지 않도록 안내. AbortController는 사용하지 않으므로
   백엔드(Vercel maxDuration 내)에서 응답이 오면 늦게라도 처리된다. */
function startProgressLabel(labelEl, baseText) {
  const dots = '<span class="loading-dots"></span>';
  const stages = [
    { at: 0,   text: baseText },
    { at: 20,  text: "조금만 더 깊이 보고 있어요" },
    { at: 60,  text: "AI 응답이 평소보다 느려요. 1~2분 더 걸릴 수 있어요" },
    { at: 150, text: "거의 다 됐어요. 창을 닫지 말고 잠시만요" },
  ];
  const start = Date.now();
  const apply = () => {
    const elapsed = (Date.now() - start) / 1000;
    let stage = stages[0];
    for (const s of stages) if (elapsed >= s.at) stage = s;
    labelEl.innerHTML = `${stage.text}${dots}`;
  };
  apply();
  const timer = setInterval(apply, 5000);
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
    id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
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
  situationEl.placeholder = DEFAULT_SITUATION_PLACEHOLDER;
  document.getElementById("feedback").classList.add("hidden");
  state.pendingEntry = null;
  state.pendingFeedback = null;
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
}

/* ───── Helpers ───── */
function loadEntries() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEYS.entries) || "[]");
  } catch {
    return [];
  }
}
function loadProfile() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEYS.profile) || "{}");
  } catch {
    return {};
  }
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
