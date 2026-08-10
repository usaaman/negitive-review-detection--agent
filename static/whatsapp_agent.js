/**
 * static/whatsapp_agent.js
 * ------------------------
 * Frontend logic for WhatsApp Agent UI — handles file selector population,
 * tag helper insertion, campaign send execution, results rendering, and history fetching.
 */

document.addEventListener("DOMContentLoaded", () => {
  const whatsappForm = document.getElementById("whatsapp-form");
  const fileSelect = document.getElementById("file-select");
  const phoneCountBadge = document.getElementById("phone-count-badge");
  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const statusIndicator = document.getElementById("status-indicator");
  const statusText = document.getElementById("status-text");
  const errorCard = document.getElementById("error-card");
  const resultsCard = document.getElementById("results-card");
  const resultsBody = document.getElementById("results-body");
  const statTotal = document.getElementById("stat-total");
  const statSent = document.getElementById("stat-sent");
  const statFailed = document.getElementById("stat-failed");
  const historyContainer = document.getElementById("history-container");

  let filesData = [];

  // 1. Fetch available output files from /whatsapp-agent/files
  async function loadAvailableFiles() {
    try {
      const response = await fetch("/whatsapp-agent/files");
      if (!response.ok) throw new Error("Failed to load available report files.");
      
      filesData = await response.json();
      fileSelect.innerHTML = `<option value="" disabled selected>-- Select an Excel report file --</option>`;

      if (!filesData || filesData.length === 0) {
        const opt = document.createElement("option");
        opt.disabled = true;
        opt.textContent = "No .xlsx report files found in outputs/";
        fileSelect.appendChild(opt);
        phoneCountBadge.textContent = "0 valid numbers";
        return;
      }

      filesData.forEach((fileInfo) => {
        const opt = document.createElement("option");
        opt.value = fileInfo.filename;
        opt.textContent = `${fileInfo.filename} (${fileInfo.valid_phone_count} valid numbers)`;
        fileSelect.appendChild(opt);
      });

      // Auto-select first file if available
      if (filesData.length > 0) {
        fileSelect.selectedIndex = 1;
        updatePhoneCountBadge(filesData[0].filename);
      }
    } catch (err) {
      showError(err.message);
      phoneCountBadge.textContent = "0 valid numbers";
    }
  }

  function updatePhoneCountBadge(filename) {
    const selected = filesData.find((f) => f.filename === filename);
    if (selected) {
      phoneCountBadge.textContent = `${selected.valid_phone_count} valid numbers`;
    } else {
      phoneCountBadge.textContent = "0 valid numbers";
    }
  }

  fileSelect.addEventListener("change", (e) => {
    updatePhoneCountBadge(e.target.value);
  });

  // 2. Clickable tag helper for {business_name}
  document.querySelectorAll(".tag-badge").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tag = btn.getAttribute("data-tag");
      if (!tag) return;
      
      const start = messageInput.selectionStart || 0;
      const end = messageInput.selectionEnd || 0;
      const text = messageInput.value;
      
      messageInput.value = text.slice(0, start) + tag + text.slice(end);
      messageInput.focus();
      messageInput.setSelectionRange(start + tag.length, start + tag.length);
    });
  });

  // 3. Handle Campaign Submission
  whatsappForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();
    resultsCard.style.display = "none";

    const fileName = fileSelect.value;
    const messageTemplate = messageInput.value.trim();

    if (!fileName) {
      showError("Please select an Excel report file first.");
      return;
    }

    if (!messageTemplate) {
      showError("Message template cannot be empty.");
      return;
    }

    // UI Loading State
    sendBtn.disabled = true;
    statusIndicator.style.visibility = "visible";
    statusText.textContent = "Launching Chrome driver & checking WhatsApp Web login...";

    try {
      const response = await fetch("/whatsapp-agent/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_name: fileName,
          message_template: messageTemplate
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || "Failed to dispatch WhatsApp campaign.");
      }

      // Display Campaign Results
      renderResults(data.result);
      loadHistory(); // Refresh audit log history
    } catch (err) {
      showError(err.message);
    } finally {
      sendBtn.disabled = false;
      statusIndicator.style.visibility = "hidden";
    }
  });

  function renderResults(result) {
    statTotal.textContent = result.total || 0;
    statSent.textContent = result.sent || 0;
    statFailed.textContent = result.failed || 0;

    resultsBody.innerHTML = "";
    if (result.details && result.details.length > 0) {
      result.details.forEach((item) => {
        const tr = document.createElement("tr");
        const isSent = item.status === "sent";
        const statusBadge = isSent
          ? `<span class="badge-status sent">SENT</span>`
          : `<span class="badge-status failed">FAILED</span>`;
        const errText = item.error ? item.error : (isSent ? "Message delivered" : "Unknown error");

        tr.innerHTML = `
          <td style="font-family: var(--font-mono); font-weight: 500;">+${item.phone}</td>
          <td>${escapeHtml(item.business_name || "N/A")}</td>
          <td>${statusBadge}</td>
          <td style="color: ${isSent ? 'var(--text-muted)' : 'var(--danger)'}; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(errText)}</td>
        `;
        resultsBody.appendChild(tr);
      });
    }

    resultsCard.style.display = "block";
    resultsCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // 4. Fetch & Render Campaign History from /whatsapp-agent/history
  async function loadHistory() {
    try {
      const response = await fetch("/whatsapp-agent/history");
      if (!response.ok) return;

      const history = await response.json();
      if (!historyContainer) return;

      if (!history || history.length === 0) {
        historyContainer.innerHTML = `
          <div style="text-align: center; padding: 30px; color: var(--muted); font-family: var(--font-mono); font-size: 13px; border: 1px dashed var(--border); border-radius: 8px;">
            No WhatsApp campaigns dispatched yet. Send your first campaign above to create an audit log.
          </div>
        `;
        return;
      }

      historyContainer.innerHTML = "";
      history.forEach((entry, idx) => {
        const card = document.createElement("div");
        card.className = "history-card";
        
        const dateStr = entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "Unknown date";
        const res = entry.result || {};
        const total = res.total || 0;
        const sent = res.sent || 0;
        const failed = res.failed || 0;
        const details = res.details || [];

        card.innerHTML = `
          <div class="history-header" data-idx="${idx}">
            <div>
              <div class="history-title">📄 ${escapeHtml(entry.file_name || "Report File")}</div>
              <div class="history-meta">Dispatched: ${dateStr}</div>
            </div>
            <div class="history-badges">
              <span class="history-badge sent">Sent: ${sent}/${total}</span>
              ${failed > 0 ? `<span class="history-badge failed">Failed: ${failed}</span>` : ""}
            </div>
          </div>
          <div class="history-details" id="history-details-${idx}">
            <div style="margin-bottom: 12px; font-family: var(--font-mono); font-size: 12px; color: var(--muted);">
              <strong>Message Template:</strong> ${escapeHtml(entry.message_template || entry.message_preview || "")}
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Phone</th>
                    <th>Business Name</th>
                    <th>Status</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  ${details.map(d => `
                    <tr>
                      <td style="font-family: var(--font-mono);">+${d.phone}</td>
                      <td>${escapeHtml(d.business_name || "N/A")}</td>
                      <td><span class="badge-status ${d.status === "sent" ? "sent" : "failed"}">${d.status.toUpperCase()}</span></td>
                      <td style="font-family: var(--font-mono); font-size: 11px; color: ${d.status === "sent" ? "var(--text-muted)" : "var(--danger)"};">${escapeHtml(d.error || "-")}</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
          </div>
        `;

        historyContainer.appendChild(card);
      });

      // Accordion toggle listeners
      document.querySelectorAll(".history-header").forEach((header) => {
        header.addEventListener("click", () => {
          const idx = header.getAttribute("data-idx");
          const detailsEl = document.getElementById(`history-details-${idx}`);
          if (detailsEl) {
            detailsEl.classList.toggle("open");
          }
        });
      });
    } catch (err) {
      console.error("Failed to load campaign history:", err);
    }
  }

  function showError(msg) {
    errorCard.textContent = msg;
    errorCard.style.display = "block";
    errorCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function hideError() {
    errorCard.style.display = "none";
    errorCard.textContent = "";
  }

  function escapeHtml(text) {
    if (!text) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Initial loads
  loadAvailableFiles();
  loadHistory();
});
