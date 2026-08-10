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

  // New UI Elements
  const tabReport = document.getElementById("tab-report");
  const tabManual = document.getElementById("tab-manual");
  const sendingModeInput = document.getElementById("sending-mode");
  const reportModeContent = document.getElementById("report-mode");
  const manualModeContent = document.getElementById("manual-mode");
  const manualEmailsTextarea = document.getElementById("manual-emails");
  const manualCountBadge = document.getElementById("manual-count-badge");
  const senderNameInput = document.getElementById("sender-name");
  
  const uploadZone = document.getElementById("upload-zone");
  const fileUploadInput = document.getElementById("file-upload");
  
  const tagBadges = document.querySelectorAll(".tag-badge");
  
  const progressWrapper = document.getElementById("progress-wrapper");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressLabel = document.getElementById("progress-label");
  const progressPercentage = document.getElementById("progress-percentage");
  const progressStats = document.getElementById("progress-stats");
  const progressTimeEstimate = document.getElementById("progress-time-estimate");

  // AI Composer Elements
  const generateAiBtn = document.getElementById("generate-ai-btn");
  const aiDraftsWrapper = document.getElementById("ai-drafts-wrapper");
  const aiDraftsSkeleton = document.getElementById("ai-drafts-skeleton");
  const aiDraftsList = document.getElementById("ai-drafts-list");
  const aiDiscardBtn = document.getElementById("ai-discard-btn");
  const aiSendBtn = document.getElementById("ai-send-btn");

  let availableFiles = [];
  let pollIntervalId = null;

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // --- 1. Tab Switching ---
  function switchTab(mode) {
    sendingModeInput.value = mode;
    if (mode === "report-mode") {
      tabReport.classList.add("active");
      tabManual.classList.remove("active");
      reportModeContent.classList.add("active");
      manualModeContent.classList.remove("active");
    } else {
      tabReport.classList.remove("active");
      tabManual.classList.add("active");
      reportModeContent.classList.remove("active");
      manualModeContent.classList.add("active");
    }
    errorCard.style.display = "none";
  }

  if (tabReport && tabManual) {
    tabReport.addEventListener("click", () => switchTab("report-mode"));
    tabManual.addEventListener("click", () => switchTab("manual-mode"));
  }

  // --- 2. Manual Emails Count ---
  function getManualEmailsList() {
    if (!manualEmailsTextarea) return [];
    const text = manualEmailsTextarea.value || "";
    return text.split(/[\s,\n]+/).map(e => e.trim()).filter(e => e.includes("@"));
  }

  if (manualEmailsTextarea) {
    manualEmailsTextarea.addEventListener("input", () => {
      const list = getManualEmailsList();
      manualCountBadge.textContent = `${list.length} email${list.length === 1 ? '' : 's'}`;
    });
  }

  // --- 3. Drag & Drop File Upload ---
  if (uploadZone && fileUploadInput) {
    uploadZone.addEventListener("click", () => fileUploadInput.click());

    uploadZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      uploadZone.classList.add("dragover");
    });

    ["dragleave", "dragend"].forEach(type => {
      uploadZone.addEventListener(type, () => uploadZone.classList.remove("dragover"));
    });

    uploadZone.addEventListener("drop", (e) => {
      e.preventDefault();
      uploadZone.classList.remove("dragover");
      if (e.dataTransfer.files.length > 0) {
        handleFileUpload(e.dataTransfer.files[0]);
      }
    });

    fileUploadInput.addEventListener("change", () => {
      if (fileUploadInput.files.length > 0) {
        handleFileUpload(fileUploadInput.files[0]);
      }
    });
  }

  async function handleFileUpload(file) {
    if (!file.name.endsWith(".xlsx")) {
      showError("Only .xlsx Excel files are allowed.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    errorCard.style.display = "none";
    uploadZone.style.opacity = "0.5";
    uploadZone.querySelector("p").innerHTML = `<span>Uploading ${escapeHtml(file.name)}...</span>`;

    try {
      const res = await fetch("/email-agent/upload", {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      uploadZone.style.opacity = "1";
      uploadZone.querySelector("p").innerHTML = `📂 Drag & Drop custom Excel file here or <strong>browse files</strong>`;

      if (!res.ok || !data.success) {
        showError(data.error || "Failed to upload file.");
        return;
      }

      // Reload files and select the uploaded one
      await loadFiles();
      fileSelect.value = data.filename;
      emailCountBadge.textContent = `${data.valid_email_count} valid email${data.valid_email_count === 1 ? '' : 's'}`;
      if (generateAiBtn) generateAiBtn.disabled = data.valid_email_count === 0;

    } catch (err) {
      uploadZone.style.opacity = "1";
      uploadZone.querySelector("p").innerHTML = `📂 Drag & Drop custom Excel file here or <strong>browse files</strong>`;
      showError("Upload Error: " + err.message);
    }
  }

  function showError(msg) {
    errorCard.textContent = msg;
    errorCard.style.display = "block";
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // --- 4. Personalization Tags Injection ---
  tagBadges.forEach(btn => {
    btn.addEventListener("click", () => {
      const tag = btn.getAttribute("data-tag");
      const mode = sendingModeInput.value;
      
      if (mode !== "report-mode") {
        alert("Personalization tags helper only works when sending to a scan report Excel file.");
        return;
      }

      const startPos = messageInput.selectionStart;
      const endPos = messageInput.selectionEnd;
      const text = messageInput.value;

      messageInput.value = text.substring(0, startPos) + tag + text.substring(endPos, text.length);
      
      messageInput.focus();
      messageInput.selectionStart = startPos + tag.length;
      messageInput.selectionEnd = startPos + tag.length;
    });
  });

  // --- 5. Fetch available files ---
  async function loadFiles() {
    if (!fileSelect) return;
    try {
      const res = await fetch("/email-agent/files");
      if (!res.ok) throw new Error("Failed to load files list.");
      
      const files = await res.json();
      availableFiles = files;
      
      fileSelect.innerHTML = "";
      
      if (!files || files.length === 0) {
        fileSelect.innerHTML = `<option value="" disabled selected>No .xlsx report files found in outputs/ folder</option>`;
        emailCountBadge.textContent = "0 valid emails";
        if (generateAiBtn) generateAiBtn.disabled = true;
        return;
      }
      
      fileSelect.innerHTML = `<option value="" disabled selected>-- Select an Excel report file --</option>`;
      files.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.filename;
        opt.textContent = `${f.filename} (${f.valid_email_count} email${f.valid_email_count === 1 ? '' : 's'})`;
        fileSelect.appendChild(opt);
      });
      
      if (generateAiBtn) generateAiBtn.disabled = true; // wait for file select change
    } catch (err) {
      showError("Error loading files: " + err.message);
    }
  }

  // --- 6. Fetch campaign history & reuse template ---
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

        const rawJsonString = encodeURIComponent(JSON.stringify(item));

        return `
          <div class="history-card">
            <div class="history-header" onclick="toggleHistoryDetails(${idx})">
              <div>
                <div class="history-title">📌 ${escapeHtml(item.subject || 'No Subject')}</div>
                <div class="history-meta">📅 ${dateStr} · 📁 ${escapeHtml(item.file_name || 'N/A')}</div>
              </div>
              <div class="history-badges" onclick="event.stopPropagation()">
                <button type="button" class="reuse-btn" onclick="reuseCampaign('${rawJsonString}')">🔄 Reuse</button>
                <span class="history-badge sent">${sentCount} sent</span>
                ${failedCount > 0 ? `<span class="history-badge failed">${failedCount} failed</span>` : ''}
                <span style="font-family: var(--font-mono); font-size: 12px; color: var(--accent); cursor: pointer;" onclick="toggleHistoryDetails(${idx})">▼</span>
              </div>
            </div>
            <div class="history-details" id="history-details-${idx}">
              <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px; font-family: var(--font-mono); word-break: break-word;">
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

  window.reuseCampaign = function(encodedData) {
    try {
      const campaign = JSON.parse(decodeURIComponent(encodedData));
      
      subjectInput.value = campaign.subject || "";
      const fullMessage = campaign.message_body || campaign.message_preview || "";
      messageInput.value = fullMessage;
      
      const fileName = campaign.file_name || "";
      if (fileName === "Manual Entry") {
        switchTab("manual-mode");
        const emails = (campaign.result.details || []).map(d => d.email).join(", ");
        manualEmailsTextarea.value = emails;
        const list = getManualEmailsList();
        manualCountBadge.textContent = `${list.length} email${list.length === 1 ? '' : 's'}`;
      } else {
        switchTab("report-mode");
        const fileExists = availableFiles.some(f => f.filename === fileName);
        if (fileExists) {
          fileSelect.value = fileName;
          const fileObj = availableFiles.find(f => f.filename === fileName);
          emailCountBadge.textContent = `${fileObj.valid_email_count} valid email${fileObj.valid_email_count === 1 ? '' : 's'}`;
          if (generateAiBtn) generateAiBtn.disabled = false;
        } else {
          const opt = document.createElement("option");
          opt.value = fileName;
          opt.textContent = `${fileName} (Not found locally)`;
          fileSelect.appendChild(opt);
          fileSelect.value = fileName;
          emailCountBadge.textContent = "0 valid emails";
          if (generateAiBtn) generateAiBtn.disabled = true;
        }
      }

      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      alert("Failed to reuse campaign details: " + err.message);
    }
  };

  // --- 7. Dropdown Selection Handler ---
  if (fileSelect) {
    fileSelect.addEventListener("change", (e) => {
      const selectedFilename = e.target.value;
      const fileObj = availableFiles.find(f => f.filename === selectedFilename);
      if (fileObj) {
        emailCountBadge.textContent = `${fileObj.valid_email_count} valid email${fileObj.valid_email_count === 1 ? '' : 's'}`;
        if (generateAiBtn) generateAiBtn.disabled = fileObj.valid_email_count === 0;
      } else {
        emailCountBadge.textContent = "0 valid emails";
        if (generateAiBtn) generateAiBtn.disabled = true;
      }
    });
  }

  // --- 8. Gemini AI Drafts Generation ---
  if (generateAiBtn) {
    generateAiBtn.addEventListener("click", async () => {
      const filename = fileSelect.value;
      if (!filename) return;

      errorCard.style.display = "none";
      emailForm.style.display = "none";
      aiDraftsSkeleton.style.display = "flex";
      window.scrollTo({ top: 0, behavior: 'smooth' });

      try {
        const res = await fetch("/email-agent/generate-drafts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_name: filename })
        });
        const data = await res.json();

        aiDraftsSkeleton.style.display = "none";

        if (!res.ok || !data.success) {
          emailForm.style.display = "block";
          showError(data.error || "Failed to generate AI drafts.");
          return;
        }

        renderAiDrafts(data.drafts);

      } catch (err) {
        aiDraftsSkeleton.style.display = "none";
        emailForm.style.display = "block";
        showError("AI Generation Connection Error: " + err.message);
      }
    });
  }

  function renderAiDrafts(drafts) {
    aiDraftsList.innerHTML = drafts.map((draft, idx) => {
      return `
        <div class="history-card" style="border-color: rgba(94, 234, 212, 0.25);">
          <div class="history-header" style="background: rgba(94, 234, 212, 0.04); cursor: default; padding: 12px 20px;">
            <div>
              <div class="history-title" style="color: var(--accent-email); font-size: 14.5px;">🏢 ${escapeHtml(draft.business_name)}</div>
              <div class="history-meta" style="margin-top: 2px;">📧 Recipient: <span style="font-family: var(--font-mono); color: var(--text);">${escapeHtml(draft.email)}</span></div>
            </div>
          </div>
          <div style="padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; background: rgba(20, 26, 38, 0.35);">
            <div class="form-group" style="margin-bottom: 0;">
              <label style="font-size: 10px; color: var(--muted); font-family: var(--font-mono); letter-spacing: 0.05em;">Subject Line</label>
              <input type="text" class="ai-draft-subject" data-email="${escapeHtml(draft.email)}" data-bizname="${escapeHtml(draft.business_name)}" value="${escapeHtml(draft.subject)}" style="background: var(--bg); border-color: var(--border); font-size: 13.5px; padding: 8px 12px;">
            </div>
            <div class="form-group" style="margin-bottom: 0;">
              <label style="font-size: 10px; color: var(--muted); font-family: var(--font-mono); letter-spacing: 0.05em;">Message Body</label>
              <textarea class="ai-draft-body" data-email="${escapeHtml(draft.email)}" rows="6" style="background: var(--bg); border-color: var(--border); font-size: 13px; line-height: 1.5; padding: 10px 12px;">${escapeHtml(draft.body)}</textarea>
            </div>
          </div>
        </div>
      `;
    }).join("");

    aiDraftsWrapper.style.display = "block";
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  if (aiDiscardBtn) {
    aiDiscardBtn.addEventListener("click", () => {
      aiDraftsWrapper.style.display = "none";
      emailForm.style.display = "block";
      aiDraftsList.innerHTML = "";
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  if (aiSendBtn) {
    aiSendBtn.addEventListener("click", async () => {
      const cards = document.querySelectorAll("#ai-drafts-list .history-card");
      const drafts = [];
      cards.forEach(card => {
        const subInput = card.querySelector(".ai-draft-subject");
        const bodyTextarea = card.querySelector(".ai-draft-body");
        drafts.push({
          email: subInput.getAttribute("data-email"),
          business_name: subInput.getAttribute("data-bizname"),
          subject: subInput.value.trim(),
          body: bodyTextarea.value.trim()
        });
      });

      if (drafts.length === 0) {
        alert("No drafts to send.");
        return;
      }

      aiDraftsWrapper.style.display = "none";
      emailForm.style.display = "block";
      setFormDisabled(true);
      sendBtn.innerHTML = `<span>Initializing AI campaign...</span>`;
      statusIndicator.style.visibility = "visible";

      try {
        const res = await fetch("/email-agent/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_name: "ai_drafts",
            drafts: drafts,
            sender_name: senderNameInput.value.trim()
          })
        });
        const data = await res.json();

        if (!res.ok || !data.success) {
          setFormDisabled(false);
          sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
          statusIndicator.style.visibility = "hidden";
          showError("AI Send Error: " + (data.error || "Failed to dispatch campaign."));
          return;
        }

        sendBtn.innerHTML = `<span>Sending Campaign...</span>`;
        startPolling(data.campaign_id);

      } catch (err) {
        setFormDisabled(false);
        sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
        statusIndicator.style.visibility = "hidden";
        showError("AI Send Connection Error: " + err.message);
      }
    });
  }

  // --- 9. Campaign Status Polling ---
  function startPolling(campaignId) {
    if (pollIntervalId) clearInterval(pollIntervalId);
    
    progressWrapper.style.display = "block";
    progressBarFill.style.width = "0%";
    progressPercentage.textContent = "0%";
    progressStats.textContent = "Sent: 0 | Failed: 0";
    progressTimeEstimate.textContent = "Calculating time...";

    const startTime = Date.now();

    pollIntervalId = setInterval(async () => {
      try {
        const res = await fetch(`/email-agent/status/${campaignId}`);
        if (!res.ok) throw new Error("Status fetch failed.");

        const data = await res.json();
        
        const sent = data.sent || 0;
        const failed = data.failed || 0;
        const total = data.total || 0;
        const processed = sent + failed;

        const percent = total > 0 ? Math.round((processed / total) * 100) : 0;
        progressBarFill.style.width = `${percent}%`;
        progressPercentage.textContent = `${percent}%`;
        progressStats.textContent = `Sent: ${sent} | Failed: ${failed} | Total: ${total}`;

        if (data.status === "running") {
          progressLabel.textContent = `Sending Email ${processed + 1} of ${total}...`;
          
          const remaining = total - processed;
          const secondsLeft = Math.round(remaining * 1.5);
          progressTimeEstimate.textContent = `Est. Time: ~${secondsLeft}s remaining`;
        }

        statTotal.textContent = total;
        statSent.textContent = sent;
        statFailed.textContent = failed;
        
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

        if (data.status === "completed" || data.status === "failed") {
          clearInterval(pollIntervalId);
          pollIntervalId = null;
          
          progressLabel.textContent = data.status === "completed" ? "Campaign Sent Successfully! 🎉" : "Campaign Failed ❌";
          progressTimeEstimate.textContent = `Completed in ${Math.round((Date.now() - startTime) / 1000)}s`;
          
          setFormDisabled(false);
          sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
          statusIndicator.style.visibility = "hidden";

          if (data.status === "failed" && data.error) {
            showError("SMTP Error: " + data.error);
          }

          loadHistory();
        }

      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1500);
  }

  function setFormDisabled(disabled) {
    sendBtn.disabled = disabled;
    if (fileSelect) fileSelect.disabled = disabled;
    if (generateAiBtn) generateAiBtn.disabled = disabled || (!fileSelect.value);
    subjectInput.disabled = disabled;
    messageInput.disabled = disabled;
    if (manualEmailsTextarea) manualEmailsTextarea.disabled = disabled;
    if (senderNameInput) senderNameInput.disabled = disabled;
    if (tabReport) tabReport.disabled = disabled;
    if (tabManual) tabManual.disabled = disabled;
  }

  // --- 10. Form Submit Handler ---
  if (emailForm) {
    emailForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const mode = sendingModeInput.value;
      const subject = subjectInput.value.trim();
      const message = messageInput.value.trim();
      const senderName = senderNameInput ? senderNameInput.value.trim() : "";

      let payload = {
        subject: subject,
        message: message,
        sender_name: senderName
      };

      if (mode === "report-mode") {
        const fileName = fileSelect.value;
        if (!fileName) {
          showError("Please select or upload an Excel report file first.");
          return;
        }
        payload.file_name = fileName;
      } else {
        const emailsList = getManualEmailsList();
        if (emailsList.length === 0) {
          showError("Please enter at least one valid email address in the manual list.");
          return;
        }
        payload.file_name = "manual";
        payload.manual_emails = emailsList;
      }

      errorCard.style.display = "none";
      resultsCard.style.display = "none";
      setFormDisabled(true);
      sendBtn.innerHTML = `<span>Initializing...</span>`;
      statusIndicator.style.visibility = "visible";

      try {
        const res = await fetch("/email-agent/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        const data = await res.json();

        if (!res.ok || !data.success) {
          setFormDisabled(false);
          sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
          statusIndicator.style.visibility = "hidden";
          showError("Error: " + (data.error || "Failed to initialize campaign. Check console or credentials."));
          return;
        }

        sendBtn.innerHTML = `<span>Sending...</span>`;
        startPolling(data.campaign_id);

      } catch (err) {
        setFormDisabled(false);
        sendBtn.innerHTML = `<span>🚀 Send Emails</span>`;
        statusIndicator.style.visibility = "hidden";
        showError("Connection Error: " + err.message);
      }
    });
  }

  // Initial loads
  loadFiles();
  loadHistory();
});
