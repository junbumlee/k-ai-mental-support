/* 걱정인형: 리더스 — 클라이언트 로직 */

const STORAGE_KEYS = {
  entries: "leaders.entries.v1",
  profile: "leaders.profile.v1",
};

const state = {
  entries: loadEntries(),
  profile: loadProfile(),
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

/* ───── 프로필 ───── */
const roleLevelInput = document.getElementById("role-level");
const teamSizeInput = document.getElementById("team-size");
const industryInput = document.getElementById("industry");

roleLevelInput.value = state.profile.roleLevel || "";
teamSizeInput.value = state.profile.teamSize || "";
industryInput.value = state.profile.industry || "";

document.getElementById("save-profile").addEventListener("click", () => {
  state.profile.roleLevel = roleLevelInput.value.trim();
  state.profile.teamSize = teamSizeInput.value.trim();
  state.profile.industry = industryInput.value.trim();
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
  if (currentRec && currentRecBtn === btn) {
    stopCurrentRec();
    return;
  }
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
  } catch {
    btn.classList.remove("recording");
    currentRec = null;
    currentRecBtn = null;
    toast("음성 인식을 다시 시도해주세요");
  }
}

/* ───── 폼 제출 ───── */
const form = document.getElementById("leader-form");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const entry = {
    situation: document.getElementById("situation").value.trim(),
    thought: document.getElementById("thought").value.trim(),
    reframe: document.getElementById("reframe").value.trim(),
    role_level: state.profile.roleLevel || null,
    team_size: state.profile.teamSize || null,
    industry: state.profile.industry || null,
  };
  if (!entry.situation || !entry.thought) return;

  const submitBtn = document.getElementById("submit-btn");
  const label = submitBtn.querySelector(".btn-label");
  const original = label.textContent;
  submitBtn.disabled = true;
  const stopProgress = startProgressLabel(label, "리더스 걱정인형이 분석 중이에요");

  try {
    const res = await fetch("/api/leader", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
    const data = await res.json();
    state.pendingEntry = entry;
    state.pendingFeedback = data;
    renderFeedback(data);
  } catch {
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
  "리더의 자리에서 느꼈을 무게를 살피고 있어요",
  "한 번 더 깊이 들여다보고 있어요",
  "조금 더 다정한 표현을 고르고 있어요",
  "당신의 맥락을 놓치지 않으려 천천히 보고 있어요",
  "어떻게 되돌려 물어볼지 신중히 고르고 있어요",
  "이번 주에 시도해볼 한 걸음을 그려보고 있어요",
  "성급하게 결론짓지 않으려 다시 살피고 있어요",
  "당신이 적어준 단어를 그대로 받아 안고 있어요",
  "팀과 본인 사이의 균형을 함께 짚어보고 있어요",
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
    data.reframe || "그 판단을 뒷받침하는 근거와 반대 근거를 각각 하나씩 떠올려볼까요?";
  tpl.querySelector(".question-text").textContent =
    data.question || "이번 주 팀 현장에서, 오늘보다 한 가지 다르게 해볼 수 있는 일이 있을까요?";

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
  document.getElementById("feedback").classList.add("hidden");
  state.pendingEntry = null;
  state.pendingFeedback = null;
  toast("오늘의 고민이 기록됐어요");
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
    background: #1a2235; color: #fff; padding: 10px 18px; border-radius: 999px;
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
