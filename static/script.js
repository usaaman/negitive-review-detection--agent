const form = document.getElementById("scan-form");
const runBtn = document.getElementById("run-btn");
const runBtnLabel = document.getElementById("run-btn-label");

const statusPanel = document.getElementById("status-panel");
const statusText = document.getElementById("status-text");

const errorPanel = document.getElementById("error-panel");
const errorText = document.getElementById("error-text");

const resultsPanel = document.getElementById("results-panel");
const resultsBody = document.getElementById("results-body");
const reportSummary = document.getElementById("report-summary");
const downloadLink = document.getElementById("download-link");
const placeholderPanel = document.getElementById("placeholder-panel");

const statusMessages = [
  "Scanning the map grid…",
  "Pulling storefronts off Maps…",
  "Cross-checking star ratings…",
  "Reading recent reviews…",
  "Flagging weak signals…",
];

let statusInterval = null;

function cycleStatusMessages() {
  let i = 0;
  statusText.textContent = statusMessages[0];
  statusInterval = setInterval(() => {
    i = (i + 1) % statusMessages.length;
    statusText.textContent = statusMessages[i];
  }, 2200);
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderRow(row) {
  const hasReview = row["Review Link"] && row["Review Link"] !== "N/A";
  const stars = row["Review Stars"];
  const starsHtml = (stars === "N/A" || stars === null)
    ? `<span class="stars-val none">—</span>`
    : `<span class="stars-val">★ ${escapeHtml(stars)}</span>`;

  const linkHtml = hasReview
    ? `<a class="open-link" href="${escapeHtml(row["Review Link"])}" target="_blank" rel="noopener">open review →</a>`
    : `<a class="no-link" href="${escapeHtml(row["Business Maps Link"])}" target="_blank" rel="noopener">view listing →</a>`;

  const email = row["Email"];
  const emailHtml = (email && email !== "N/A")
    ? `<a class="open-link" href="mailto:${escapeHtml(email)}">${escapeHtml(email)}</a>`
    : `<span class="no-link">—</span>`;

  const website = row["Website"];
  const websiteHtml = (website && website !== "N/A")
    ? `<a class="open-link" href="${escapeHtml(website)}" target="_blank" rel="noopener">visit →</a>`
    : `<span class="no-link">—</span>`;

  return `
    <tr>
      <td class="col-flag"><span class="flag-dot ${hasReview ? "hit" : ""}"></span></td>
      <td>
        <div class="biz-name">${escapeHtml(row["Business Name"])}</div>
        <div class="biz-meta">${escapeHtml(row["Business Rating"])} ★ overall · ${escapeHtml(row["Address"])}</div>
      </td>
      <td class="col-email">${emailHtml}</td>
      <td class="col-email">${websiteHtml}</td>
      <td class="col-stars">${starsHtml}</td>
      <td class="review-text">${escapeHtml(row["Review Text"])}</td>
      <td class="col-open">${linkHtml}</td>
    </tr>
  `;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  errorPanel.hidden = true;
  resultsPanel.hidden = true;
  placeholderPanel.hidden = true;
  statusPanel.hidden = false;
  runBtn.disabled = true;
  runBtnLabel.textContent = "Scanning…";
  cycleStatusMessages();

  const payload = {
    location: document.getElementById("location").value,
    category: document.getElementById("category").value,
    max_businesses: document.getElementById("max_businesses").value,
    max_reviews: document.getElementById("max_reviews").value,
    rating_threshold: document.getElementById("rating_threshold").value,
    negative_star_max: document.getElementById("negative_star_max").value,
  };

  try {
    const res = await fetch("/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();

    clearInterval(statusInterval);
    statusPanel.hidden = true;
    runBtn.disabled = false;
    runBtnLabel.textContent = "Run scan";

    if (!res.ok || data.error) {
      errorText.textContent = "Scan failed: " + (data.error || "Unknown error.");
      errorPanel.hidden = false;
      placeholderPanel.hidden = false;
      return;
    }

    if (!data.results || data.results.length === 0) {
      reportSummary.textContent = `${data.total_scanned} businesses scanned · none fell below threshold.`;
      resultsBody.innerHTML = "";
      downloadLink.hidden = true;
      resultsPanel.hidden = false;
      return;
    }

    let summary = `${data.total_scanned} businesses scanned · ${data.flagged_count} flagged below threshold`;
    if (data.dropped_no_contact) {
      summary += ` · ${data.dropped_no_contact} dropped (no email or phone)`;
    }
    reportSummary.textContent = summary + ".";
    resultsBody.innerHTML = data.results.map(renderRow).join("");

    if (data.filename) {
      downloadLink.href = "/download/" + encodeURIComponent(data.filename);
      downloadLink.hidden = false;
    } else {
      downloadLink.hidden = true;
    }

    resultsPanel.hidden = false;
  } catch (err) {
    clearInterval(statusInterval);
    statusPanel.hidden = true;
    runBtn.disabled = false;
    runBtnLabel.textContent = "Run scan";
    errorText.textContent = "Scan failed: " + err.message;
    errorPanel.hidden = false;
    placeholderPanel.hidden = false;
  }
});
