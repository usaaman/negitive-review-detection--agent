/**
 * static/whatsapp_agent.js
 * ------------------------
 * Frontend logic for WhatsApp Agent UI — handles file selector population,
 * tag helper insertion, settings configuration, customize mode preview,
 * background campaign execution, live polling status dashboard, resume functionality,
 * and sent history audit log.
 */

document.addEventListener("DOMContentLoaded", () => {
  const whatsappForm = document.getElementById("whatsapp-form");
  const fileSelect = document.getElementById("file-select");
  const phoneCountBadge = document.getElementById("phone-count-badge");
  const messageInput = document.getElementById("message-input");
  const minDelayInput = document.getElementById("min-delay");
  const maxDelayInput = document.getElementById("max-delay");
  const dailyLimitToggle = document.getElementById("daily-limit-toggle");
  const dailyLimitValInput = document.getElementById("daily-limit-val");
  const sendBtn = document.getElementById("send-btn");
  const statusIndicator = document.getElementById("status-indicator");
  const statusText = document.getElementById("status-text");
  const errorCard = document.getElementById("error-card");
  const resultsCard = document.getElementById("results-card");
  const resultsBody = document.getElementById("results-body");
  const statTotal = document.getElementById("stat-total");
  const statSent = document.getElementById("stat-sent");
  const statFailed = document.getElementById("stat-failed");
  const statSkipped = document.getElementById("stat-skipped");
  const historyContainer = document.getElementById("history-container");

  // Customize Mode Elements
  const customizeModeBtn = document.getElementById("customize-mode-btn");
  const customizePreviewWrapper = document.getElementById("customize-preview-wrapper");
  const customizeLeadsList = document.getElementById("customize-leads-list");
  const customizeCount = document.getElementById("customize-count");

  // Progress Dashboard Elements
  const progressWrapper = document.getElementById("progress-wrapper");
  const progressLabel = document.getElementById("progress-label");
  const progressPercentage = document.getElementById("progress-percentage");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressStats = document.getElementById("progress-stats");
  const progressTimeEstimate = document.getElementById("progress-time-estimate");
  const pauseBanner = document.getElementById("pause-banner");
  const pauseMessage = document.getElementById("pause-message");
  const resumeBtn = document.getElementById("resume-btn");

  let filesData = [];
  let pollIntervalId = null;
  let currentCampaignId = null;

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
    if (customizePreviewWrapper.style.display !== "none") {
      fetchAndRenderCustomizePreview();
    }
  });

  // 2. Clickable tag helper badges
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

      if (customizePreviewWrapper.style.display !== "none") {
        fetchAndRenderCustomizePreview();
      }
    });
  });

  // 3. Optional "Customize Messages Individually" Mode Toggle
  if (customizeModeBtn) {
    customizeModeBtn.addEventListener("click", () => {
      if (customizePreviewWrapper.style.display === "none") {
        const fileName = fileSelect.value;
        const messageTemplate = messageInput.value.trim();

        if (!fileName) {
          showError("Please select an Excel report file first.");
          return;
        }
        if (!messageTemplate) {
          showError("Please enter a message template first.");
          return;
        }

        hideError();
        customizePreviewWrapper.style.display = "block";
        fetchAndRenderCustomizePreview();
      } else {
        customizePreviewWrapper.style.display = "none";
        customizeLeadsList.innerHTML = "";
      }
    });
  }

  async function fetchAndRenderCustomizePreview() {
    const fileName = fileSelect.value;
    const messageTemplate = messageInput.value.trim();
    if (!fileName || !messageTemplate) return;

    customizeLeadsList.innerHTML = `<div style="text-align: center; color: var(--muted); font-family: var(--font-mono); padding: 15px;">Generating custom previews...</div>`;

    try {
      const res = await fetch("/whatsapp-agent/preview-leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_name: fileName, message_template: messageTemplate })
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || "Failed to generate previews.");
      }

      const leads = data.leads || [];
      customizeCount.textContent = `${leads.length} lead${leads.length === 1 ? '' : 's'}`;

      if (leads.length === 0) {
        customizeLeadsList.innerHTML = `<div style="text-align: center; color: var(--muted); font-family: var(--font-mono); padding: 15px;">No valid phone numbers found to preview.</div>`;
        return;
      }

      customizeLeadsList.innerHTML = leads.map((lead, idx) => `
        <div class="history-card" style="border-color: rgba(37, 211, 102, 0.25); margin-bottom: 0;">
          <div class="history-header" style="background: rgba(37, 211, 102, 0.04); cursor: default; padding: 10px 16px;">
            <div>
              <div class="history-title" style="color: var(--accent-whatsapp); font-size: 13.5px;">🏢 ${escapeHtml(lead.business_name)}</div>
              <div class="history-meta" style="margin-top: 2px;">📱 Phone: <span style="font-family: var(--font-mono); color: var(--text);">+${escapeHtml(lead.phone)}</span></div>
            </div>
          </div>
          <div style="padding: 12px 16px; background: rgba(20, 26, 38, 0.35);">
            <textarea class="custom-lead-msg" data-phone="${escapeHtml(lead.phone)}" data-biz="${escapeHtml(lead.business_name)}" rows="3" style="font-size: 13px; line-height: 1.4; padding: 8px 10px;">${escapeHtml(lead.message)}</textarea>
          </div>
        </div>
      `).join("");

    } catch (err) {
      customizeLeadsList.innerHTML = `<div style="color: var(--danger); font-family: var(--font-mono); padding: 15px;">Error: ${escapeHtml(err.message)}</div>`;
    }
  }

  // 4. Handle Campaign Submission
  whatsappForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();

    const fileName = fileSelect.value;
    const messageTemplate = messageInput.value.trim();
    const minDelay = parseInt(minDelayInput.value) || 20;
    const maxDelay = parseInt(maxDelayInput.value) || 40;
    const dailyLimitEnabled = dailyLimitToggle.checked;
    const dailyLimit = parseInt(dailyLimitValInput.value) || 150;

    if (!fileName) {
      showError("Please select an Excel report file first.");
      return;
    }

    if (!messageTemplate && customizePreviewWrapper.style.display === "none") {
      showError("Message template cannot be empty.");
      return;
    }

    let drafts = null;
    if (customizePreviewWrapper.style.display !== "none") {
      const customElements = document.querySelectorAll(".custom-lead-msg");
      drafts = Array.from(customElements).map(el => ({
        phone: el.getAttribute("data-phone"),
        business_name: el.getAttribute("data-biz"),
        message: el.value.trim()
      }));
    }

    setFormDisabled(true);
    statusIndicator.style.visibility = "visible";
    statusText.textContent = "Launching Chrome driver & initializing campaign...";

    try {
      const response = await fetch("/whatsapp-agent/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_name: fileName,
          message_template: messageTemplate,
          min_delay: minDelay,
          max_delay: maxDelay,
          daily_limit_enabled: dailyLimitEnabled,
          daily_limit: dailyLimit,
          drafts: drafts
        })
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || "Failed to dispatch WhatsApp campaign.");
      }

      currentCampaignId = data.campaign_id;
      startPolling(currentCampaignId);

    } catch (err) {
      setFormDisabled(false);
      statusIndicator.style.visibility = "hidden";
      showError(err.message);
    }
  });

  // 5. Live Progress Dashboard Polling
  function startPolling(campaignId) {
    if (pollIntervalId) clearInterval(pollIntervalId);

    progressWrapper.style.display = "block";
    resultsCard.style.display = "block";
    pauseBanner.style.display = "none";
    progressBarFill.style.width = "0%";
    progressPercentage.textContent = "0%";
    progressStats.textContent = "Sent: 0 | Failed: 0 | Skipped: 0";
    progressTimeEstimate.textContent = "Calculating time...";

    const startTime = Date.now();

    pollIntervalId = setInterval(async () => {
      try {
        const response = await fetch(`/whatsapp-agent/status/${campaignId}`);
        if (!response.ok) throw new Error("Failed to fetch campaign status.");

        const data = await response.json();

        const sent = data.sent || 0;
        const failed = data.failed || 0;
        const skipped = data.skipped || 0;
        const total = data.total || 0;
        const processed = sent + failed + skipped;

        const percent = total > 0 ? Math.round((processed / total) * 100) : 0;
        progressBarFill.style.width = `${percent}%`;
        progressPercentage.textContent = `${percent}%`;
        progressStats.textContent = `Sent: ${sent} | Failed: ${failed} | Skipped: ${skipped}`;

        const minDelay = data.min_delay || 20;
        const maxDelay = data.max_delay || 40;
        const avgDelay = (minDelay + maxDelay) / 2;
        const remaining = total - processed;
        const secondsLeft = Math.round(remaining * avgDelay);

        if (data.status === "running") {
          progressLabel.textContent = `Sending WhatsApp message ${processed + 1} of ${total}...`;
          progressTimeEstimate.textContent = `Est. Time: ~${secondsLeft}s remaining`;
          statusText.textContent = data.status_message || "Dispatching WhatsApp messages...";
        }

        statTotal.textContent = total;
        statSent.textContent = sent;
        statFailed.textContent = failed;
        statSkipped.textContent = skipped;

        renderResultsRows(data.details || []);

        if (data.status === "paused") {
          clearInterval(pollIntervalId);
          pollIntervalId = null;

          progressLabel.textContent = "Campaign Paused ⏸️";
          progressTimeEstimate.textContent = `Processed ${processed} of ${total}`;
          pauseMessage.textContent = data.status_message || "Daily limit reached — resume tomorrow";
          pauseBanner.style.display = "flex";

          setFormDisabled(false);
          statusIndicator.style.visibility = "hidden";
          loadHistory();
        } else if (data.status === "completed" || data.status === "failed") {
          clearInterval(pollIntervalId);
          pollIntervalId = null;

          progressLabel.textContent = data.status === "completed" ? "WhatsApp Campaign Completed! 🎉" : "Campaign Failed ❌";
          progressTimeEstimate.textContent = `Finished in ${Math.round((Date.now() - startTime) / 1000)}s`;

          if (data.status === "failed" && data.error) {
            showError("Selenium Error: " + data.error);
          }

          setFormDisabled(false);
          statusIndicator.style.visibility = "hidden";
          loadHistory();
        }

      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1500);
  }

  function renderResultsRows(details) {
    resultsBody.innerHTML = details.map((item) => {
      let badgeClass = "skipped";
      if (item.status === "sent") badgeClass = "sent";
      else if (item.status === "failed") badgeClass = "failed";

      const errText = item.error ? item.error : (item.status === "sent" ? "Message delivered" : "-");

      return `
        <tr>
          <td style="font-family: var(--font-mono); font-weight: 500;">+${escapeHtml(item.phone)}</td>
          <td>${escapeHtml(item.business_name || "N/A")}</td>
          <td><span class="badge-status ${badgeClass}">${escapeHtml(item.status.toUpperCase())}</span></td>
          <td style="color: ${item.status === 'sent' ? 'var(--text-muted)' : (item.status === 'failed' ? 'var(--danger)' : 'var(--accent-lead)')}; font-family: var(--font-mono); font-size: 12px;">${escapeHtml(errText)}</td>
        </tr>
      `;
    }).join("");
  }

  // 6. Handle Campaign Resume Button
  if (resumeBtn) {
    resumeBtn.addEventListener("click", async () => {
      if (!currentCampaignId) return;

      const minDelay = parseInt(minDelayInput.value) || 20;
      const maxDelay = parseInt(maxDelayInput.value) || 40;
      const dailyLimitEnabled = dailyLimitToggle.checked;
      const dailyLimit = parseInt(dailyLimitValInput.value) || 150;

      setFormDisabled(true);
      pauseBanner.style.display = "none";
      statusIndicator.style.visibility = "visible";
      statusText.textContent = "Resuming campaign session...";

      try {
        const response = await fetch(`/whatsapp-agent/resume/${currentCampaignId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            min_delay: minDelay,
            max_delay: maxDelay,
            daily_limit_enabled: dailyLimitEnabled,
            daily_limit: dailyLimit
          })
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
          throw new Error(data.error || "Failed to resume campaign.");
        }

        startPolling(currentCampaignId);

      } catch (err) {
        setFormDisabled(false);
        statusIndicator.style.visibility = "hidden";
        showError("Resume Error: " + err.message);
      }
    });
  }

  // 7. Fetch & Render Campaign History from /whatsapp-agent/history
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

      historyContainer.innerHTML = history.map((entry, idx) => {
        const dateStr = entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "Unknown date";
        const res = entry.result || {};
        const total = res.total || 0;
        const sent = res.sent || 0;
        const failed = res.failed || 0;
        const skipped = res.skipped || 0;
        const details = res.details || [];

        return `
          <div class="history-card">
            <div class="history-header" onclick="toggleHistoryDetails(${idx})">
              <div>
                <div class="history-title">📄 ${escapeHtml(entry.file_name || "Report File")}</div>
                <div class="history-meta">Dispatched: ${dateStr}</div>
              </div>
              <div class="history-badges" onclick="event.stopPropagation()">
                <span class="history-badge sent">Sent: ${sent}/${total}</span>
                ${failed > 0 ? `<span class="history-badge failed">Failed: ${failed}</span>` : ""}
                ${skipped > 0 ? `<span class="history-badge skipped">Skipped: ${skipped}</span>` : ""}
                <span style="font-family: var(--font-mono); font-size: 12px; color: var(--accent); cursor: pointer;" onclick="toggleHistoryDetails(${idx})">▼</span>
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
                        <td style="font-family: var(--font-mono);">+${escapeHtml(d.phone)}</td>
                        <td>${escapeHtml(d.business_name || "N/A")}</td>
                        <td><span class="badge-status ${d.status}">${escapeHtml(d.status.toUpperCase())}</span></td>
                        <td style="font-family: var(--font-mono); font-size: 11px; color: ${d.status === "sent" ? "var(--text-muted)" : (d.status === "failed" ? "var(--danger)" : "var(--accent-lead)")};">${escapeHtml(d.error || "-")}</td>
                      </tr>
                    `).join("")}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        `;
      }).join("");

    } catch (err) {
      console.error("Failed to load campaign history:", err);
    }
  }

  window.toggleHistoryDetails = function(idx) {
    const detailsEl = document.getElementById(`history-details-${idx}`);
    if (detailsEl) {
      detailsEl.classList.toggle("open");
    }
  };

  function setFormDisabled(disabled) {
    sendBtn.disabled = disabled;
    fileSelect.disabled = disabled;
    messageInput.disabled = disabled;
    minDelayInput.disabled = disabled;
    maxDelayInput.disabled = disabled;
    dailyLimitToggle.disabled = disabled;
    dailyLimitValInput.disabled = disabled;
    if (customizeModeBtn) customizeModeBtn.disabled = disabled;
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

  // 8. Handle Switch WhatsApp Number button click
  const switchNumberBtn = document.getElementById("switch-number-btn");
  if (switchNumberBtn) {
    switchNumberBtn.addEventListener("click", async () => {
      const confirmed = confirm("This will log out the current WhatsApp number. You'll need to scan a new QR code next time you send a campaign. Continue?");
      if (!confirmed) return;

      try {
        switchNumberBtn.disabled = true;
        switchNumberBtn.textContent = "Clearing Session...";

        const response = await fetch("/whatsapp-agent/switch-number", {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });

        const contentType = response.headers.get("content-type");
        let data;
        if (contentType && contentType.includes("application/json")) {
          data = await response.json();
        } else {
          throw new Error(`Server returned non-JSON response (Status: ${response.status}). Please check login session.`);
        }

        if (!response.ok || !data.success) {
          throw new Error(data.error || "Failed to reset WhatsApp session.");
        }

        alert("WhatsApp session cleared successfully! You will see a QR code to scan the next time you send a campaign.");
      } catch (err) {
        showError("Reset Error: " + err.message);
      } finally {
        switchNumberBtn.disabled = false;
        switchNumberBtn.textContent = "🔄 Switch WhatsApp Number";
      }
    });
  }

  // Initial loads
  loadAvailableFiles();
  loadHistory();
});
