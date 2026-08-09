document.addEventListener("DOMContentLoaded", () => {
  const fileSelect = document.getElementById("file-select");
  const emailCountBadge = document.getElementById("email-count-badge");
  const emailForm = document.getElementById("email-form");
  const subjectInput = document.getElementById("subject-input");
  const messageInput = document.getElementById("message-input");
  const sendBtn = document.getElementById("send-btn");
  const statusIndicator = document.getElementById("status-indicator");
  const errorCard = document.getElementById("error-card");
  const resultsCard = document.getElementById("results-card");
  const statTotal = document.getElementById("stat-total");
  const statSent = document.getElementById("stat-sent");
  const statFailed = document.getElementById("stat-failed");
  const resultsBody = document.getElementById("results-body");
  const historyContainer = document.getElementById("history-container");

  let availableFiles = [];

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // 1. Fetch available files on page load
  async function loadFiles() {
    try {
      const res = await fetch("/email-agent/files");
      if (!res.ok) throw new Error("Failed to load files list.");
      
      const files = await res.json();
      availableFiles = files;
      
      fileSelect.innerHTML = "";
      
      if (!files || files.length === 0) {
        fileSelect.innerHTML = `<option value="" disabled selected>No .xlsx report files found in outputs/ folder</option>`;
        emailCountBadge.textContent = "0 valid emails";
        return;
      }
      
      fileSelect.innerHTML = `<option value="" disabled selected>-- Select an Excel report file --</option>`;
      files.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.filename;
        opt.textContent = `${f.filename} (${f.valid_email_count} email${f.valid_email_count === 1 ? '' : 's'})`;
        fileSelect.appendChild(opt);
      });
    } catch (err) {
      errorCard.textContent = "Error loading files: " + err.message;
      errorCard.style.display = "block";
    }
  }

  // 2. Fetch campaign history on page load & after send
  async function loadHistory() {
    if (!historyContainer) return;
    try {
      const res = await fetch("/email-agent/history");
      if (!res.ok) throw new Error("Failed to load campaign history.");

      const history = await res.json();
      if (!history || history.length === 0) {
        historyContainer.innerHTML = `<p style="font-family: var(--font-mono); font-size: 13px; color: var(--text-muted); padding: 12px 0;">No past campaign history found.</p>`;
        return;
      }

      historyContainer.innerHTML = history.map((item, idx) => {
        const dateStr = item.timestamp ? new Date(item.timestamp).toLocaleString() : "Unknown Date";
        const resObj = item.result || {};
        const sentCount = resObj.sent || 0;
        const failedCount = resObj.failed || 0;
        const details = resObj.details || [];

        const detailsRows = details.map(d => {
          const isSent = d.status === "sent";
          const badge = isSent
            ? `<span class="badge-status sent">Sent</span>`
            : `<span class="badge-status failed">Failed</span>`;
          const errText = d.error ? escapeHtml(d.error) : "OK";
          return `
            <tr>
              <td style="font-family: var(--font-mono); font-weight: 500;">${escapeHtml(d.email)}</td>
              <td>${badge}</td>
              <td style="color: ${isSent ? 'var(--text-muted)' : 'var(--danger)'}; font-family: var(--font-mono); font-size: 12px;">${errText}</td>
            </tr>
          `;
        }).join("");

        return `
          <div class="history-card">
            <div class="history-header" onclick="toggleHistoryDetails(${idx})">
              <div>
                <div class="history-title">📌 ${escapeHtml(item.subject || 'No Subject')}</div>
                <div class="history-meta">📅 ${dateStr} · 📁 ${escapeHtml(item.file_name || 'N/A')}</div>
              </div>
              <div class="history-badges">
                <span class="history-badge sent">${sentCount} sent</span>
                ${failedCount > 0 ? `<span class="history-badge failed">${failedCount} failed</span>` : ''}
                <span style="font-family: var(--font-mono); font-size: 12px; color: var(--accent);">▼</span>
              </div>
            </div>
            <div class="history-details" id="history-details-${idx}">
              <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px; font-family: var(--font-mono);">
                <strong>Preview:</strong> "${escapeHtml(item.message_preview || '')}..."
              </p>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Recipient Email</th>
                      <th>Status</th>
                      <th>Details / Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${detailsRows || '<tr><td colspan="3">No recipient details</td></tr>'}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        `;
      }).join("");

    } catch (err) {
      historyContainer.innerHTML = `<p style="font-family: var(--font-mono); font-size: 13px; color: var(--danger); padding: 12px 0;">Error loading history: ${escapeHtml(err.message)}</p>`;
    }
  }

  window.toggleHistoryDetails = function(idx) {
    const el = document.getElementById(`history-details-${idx}`);
    if (el) {
      el.classList.toggle("open");
    }
  };

  // 3. Dropdown Selection Handler
  fileSelect.addEventListener("change", (e) => {
    const selectedFilename = e.target.value;
    const fileObj = availableFiles.find(f => f.filename === selectedFilename);
    if (fileObj) {
      emailCountBadge.textContent = `${fileObj.valid_email_count} valid email${fileObj.valid_email_count === 1 ? '' : 's'}`;
    } else {
      emailCountBadge.textContent = "0 valid emails";
    }
  });

  // 4. Form Submit Handler
  emailForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const fileName = fileSelect.value;
    const subject = subjectInput.value.trim();
    const message = messageInput.value.trim();

    if (!fileName) {
      errorCard.textContent = "Please select an Excel report file first.";
      errorCard.style.display = "block";
      return;
    }

    // Reset UI
    errorCard.style.display = "none";
    resultsCard.style.display = "none";
    sendBtn.disabled = true;
    sendBtn.innerHTML = `<span>Dispatching...</span>`;
    statusIndicator.style.visibility = "visible";

    try {
      const res = await fetch("/email-agent/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_name: fileName,
          subject: subject,
          message: message
        }),
      });

      const data = await res.json();

      sendBtn.disabled = false;
      sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
      statusIndicator.style.visibility = "hidden";

      if (!res.ok || !data.success) {
        errorCard.textContent = "Error: " + (data.error || "Failed to send emails.");
        errorCard.style.display = "block";
        return;
      }

      // Display results summary
      statTotal.textContent = data.total;
      statSent.textContent = data.sent;
      statFailed.textContent = data.failed;

      // Render per-recipient status table
      resultsBody.innerHTML = (data.details || []).map(item => {
        const isSent = item.status === "sent";
        const statusBadge = isSent
          ? `<span class="badge-status sent">Sent</span>`
          : `<span class="badge-status failed">Failed</span>`;
        const errDetail = item.error ? escapeHtml(item.error) : "OK";

        return `
          <tr>
            <td style="font-family: var(--font-mono); font-weight: 500;">${escapeHtml(item.email)}</td>
            <td>${statusBadge}</td>
            <td style="color: ${isSent ? 'var(--text-muted)' : 'var(--danger)'}; font-family: var(--font-mono); font-size: 12px;">${errDetail}</td>
          </tr>
        `;
      }).join("");

      resultsCard.style.display = "block";

      // Refresh history list immediately
      loadHistory();

    } catch (err) {
      sendBtn.disabled = false;
      sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
      statusIndicator.style.visibility = "hidden";
      errorCard.textContent = "Network / Request Error: " + err.message;
      errorCard.style.display = "block";
    }
  });

  // Initial loads
  loadFiles();
  loadHistory();
});
