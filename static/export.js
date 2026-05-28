(function (global) {
  function text(value) {
    return String(value || "").replace(/\r\n/g, "\n").trim();
  }

  function escapeHtml(value) {
    return text(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDate(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return text(iso) || "날짜 없음";
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const hh = String(date.getHours()).padStart(2, "0");
    const mi = String(date.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  }

  function printDate(now) {
    const date = new Date(now || Date.now());
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    return `${yyyy}${mm}${dd}`;
  }

  function field(label, value) {
    const clean = text(value);
    if (!clean) return "";
    const paragraphs = clean
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => `<p>${escapeHtml(line)}</p>`)
      .join("");
    return `<section class="entry-field"><h3>${escapeHtml(label)}</h3>${paragraphs}</section>`;
  }

  function buildEntriesPdfHtml(entries, options) {
    const opts = options || {};
    const title = opts.title || "걱정인형 기록";
    const records = Array.isArray(entries) ? entries : [];
    const exportedAt = opts.exportedAt || new Date().toISOString();
    const filename = makeExportFilename(opts.filenamePrefix, exportedAt);
    const body = records.length
      ? records.map((record, index) => {
          const entry = record.entry || {};
          const feedback = record.feedback || {};
          const distortions = Array.isArray(feedback.distortions)
            ? feedback.distortions.join(", ")
            : feedback.distortions;
          return `
            <article class="entry-card">
              <header>
                <p class="entry-number">${index + 1}</p>
                <div>
                  <h2>${escapeHtml(formatDate(record.createdAt))}</h2>
                  ${entry.category ? `<p class="category">${escapeHtml(entry.category)}</p>` : ""}
                </div>
              </header>
              <div class="entry-grid">
                ${field("상황", entry.situation)}
                ${field("그때 떠오른 생각", entry.thought)}
                ${field("스스로 시도한 재구성", entry.reframe)}
                ${field("공감", feedback.empathy)}
                ${field("생각의 습관", distortions)}
                ${field("되묻기", feedback.reframe)}
                ${field("관찰 과제", feedback.question)}
              </div>
            </article>`;
        }).join("")
      : `<p class="empty">아직 저장된 기록이 없습니다.</p>`;

    return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>${escapeHtml(filename.replace(/\.pdf$/, ""))}</title>
  <style>
    @page { margin: 18mm 16mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #27222d;
      background: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
      line-height: 1.65;
    }
    .cover {
      padding: 0 0 18px;
      border-bottom: 2px solid #e98a9c;
      margin-bottom: 20px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: 0;
    }
    .meta {
      margin: 0;
      color: #6a6072;
      font-size: 13px;
    }
    .entry-card {
      break-inside: avoid;
      page-break-inside: avoid;
      border: 1px solid #f0d4da;
      border-radius: 10px;
      padding: 18px;
      margin: 0 0 16px;
    }
    .entry-card header {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
    }
    .entry-number {
      width: 32px;
      height: 32px;
      margin: 0;
      border-radius: 50%;
      background: #f9d7dd;
      color: #b64f64;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
    }
    h2 {
      margin: 0;
      font-size: 17px;
    }
    .category {
      display: inline-block;
      margin: 6px 0 0;
      padding: 2px 9px;
      border-radius: 999px;
      background: #fff0f3;
      color: #b64f64;
      font-size: 12px;
      font-weight: 600;
    }
    .entry-grid {
      display: grid;
      gap: 10px;
    }
    .entry-field {
      padding: 10px 12px;
      border-radius: 8px;
      background: #fff8f9;
    }
    .entry-field h3 {
      margin: 0 0 4px;
      color: #b64f64;
      font-size: 12px;
    }
    .entry-field p {
      margin: 0 0 4px;
      font-size: 14px;
    }
    .entry-field p:last-child { margin-bottom: 0; }
    .empty {
      margin: 40px 0;
      text-align: center;
      color: #6a6072;
    }
    @media print {
      .entry-card { box-shadow: none; }
    }
  </style>
</head>
<body>
  <main>
    <section class="cover">
      <h1>${escapeHtml(title)}</h1>
      <p class="meta">내보낸 시각: ${escapeHtml(formatDate(exportedAt))}</p>
      <p class="meta">기록 수: ${records.length}</p>
    </section>
    ${body}
  </main>
</body>
</html>`;
  }

  function makeExportFilename(prefix, now) {
    return `${prefix || "worrydoll"}-${printDate(now)}.pdf`;
  }

  function openPdfPrintWindow(entries, options) {
    const opts = options || {};
    const opener = opts.openWindow || global.open;
    if (typeof opener !== "function") return false;
    const printWindow = opener("", "_blank", "width=900,height=1100");
    if (!printWindow || !printWindow.document) return false;
    const html = buildEntriesPdfHtml(entries, opts);
    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
    if (opts.autoPrint === false) return true;
    const triggerPrint = () => {
      if (typeof printWindow.focus === "function") printWindow.focus();
      if (typeof printWindow.print === "function") printWindow.print();
    };
    if (printWindow.document.readyState === "complete") {
      setTimeout(triggerPrint, 100);
    } else if (typeof printWindow.addEventListener === "function") {
      printWindow.addEventListener("load", () => setTimeout(triggerPrint, 100), { once: true });
    } else {
      setTimeout(triggerPrint, 250);
    }
    return true;
  }

  const api = {
    buildEntriesPdfHtml,
    makeExportFilename,
    openPdfPrintWindow,
  };

  global.WorryDollExport = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
