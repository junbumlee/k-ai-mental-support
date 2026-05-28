const form = document.getElementById("onboarding-form");
const message = document.getElementById("profile-message");
const nextPath = form.dataset.next || "/";

const FIELD_MAP = {
  job_role: "job-role",
  company_type: "company-type",
  industry: "industry",
  age_group: "age-group",
  org_culture: "org-culture",
  leader_authority: "leader-authority",
};

fetch("/api/me")
  .then((res) => res.json())
  .then((data) => {
    const profile = data.profile || {};
    Object.entries(FIELD_MAP).forEach(([key, id]) => {
      const el = document.getElementById(id);
      if (el && profile[key]) el.value = profile[key];
    });
  })
  .catch(() => {});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";

  const payload = Object.fromEntries(
    Object.entries(FIELD_MAP).map(([key, id]) => [key, document.getElementById(id).value.trim()])
  );

  const submitBtn = form.querySelector("button[type='submit']");
  submitBtn.disabled = true;
  try {
    const response = await fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      message.textContent = data.message || "저장에 실패했어요.";
      return;
    }
    window.location.href = nextPath;
  } catch {
    message.textContent = "연결이 불안정해요. 다시 시도해주세요.";
  } finally {
    submitBtn.disabled = false;
  }
});
