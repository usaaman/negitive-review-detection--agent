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

  // --- 0. Section Tab Switching ---
  window.showSection = function(sectionName) {
    const campaignSec = document.getElementById("campaign-section");
    const repliesSec = document.getElementById("replies-section");
    const placementSec = document.getElementById("placement-section");
    const historySec = document.getElementById("history-section");
    const allSubTabs = document.querySelectorAll("[data-section]");

    allSubTabs.forEach(tab => {
      if (tab.getAttribute("data-section") === sectionName) {
        tab.classList.add("active");
      } else {
        tab.classList.remove("active");
      }
    });

    if (campaignSec) campaignSec.style.display = sectionName === "campaign" ? "block" : "none";
    if (repliesSec) repliesSec.style.display = sectionName === "replies" ? "block" : "none";
    if (placementSec) placementSec.style.display = sectionName === "placement" ? "block" : "none";
    if (historySec) historySec.style.display = sectionName === "history" ? "block" : "none";

    if (sectionName === "placement") {
      if (typeof window.loadDeliveryStats === "function") {
        window.loadDeliveryStats();
      }
    }
  };

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-section]");
    if (btn) {
      const sectionName = btn.getAttribute("data-section");
      if (sectionName && typeof window.showSection === "function") {
        window.showSection(sectionName);
      }
    }
  });

  // --- 1. Tab Switching & AI Button State ---
  function switchTab(mode) {
    if (sendingModeInput) sendingModeInput.value = mode;
    errorCard.style.display = "none";
  }

  function updateGenerateAiBtnState() {
    if (!generateAiBtn) return;
    const hasExcelFile = fileSelect && fileSelect.value !== "";
    const hasManualEmails = getManualEmailsList().length > 0;
    generateAiBtn.disabled = !(hasExcelFile || hasManualEmails);
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
      updateGenerateAiBtnState();
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
        updateGenerateAiBtnState();
        return;
      }
      
      fileSelect.innerHTML = `<option value="" disabled selected>-- Select an Excel report file --</option>`;
      files.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.filename;
        opt.textContent = `${f.filename} (${f.valid_email_count} email${f.valid_email_count === 1 ? '' : 's'})`;
        fileSelect.appendChild(opt);
      });
      
      updateGenerateAiBtnState();
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
      } else {
        emailCountBadge.textContent = "0 valid emails";
      }
      updateGenerateAiBtnState();
    });
  }

  // --- 8. Gemini AI Drafts Generation ---
  if (generateAiBtn) {
    generateAiBtn.addEventListener("click", async () => {
      const filename = fileSelect.value || "";
      const manualEmails = getManualEmailsList();
      const instructionsText = document.getElementById("ai-instructions") ? document.getElementById("ai-instructions").value.trim() : "";

      if (!filename && manualEmails.length === 0) {
        showError("Please select a Scan Report file or enter manual email addresses first.");
        return;
      }

      errorCard.style.display = "none";
      emailForm.style.display = "none";
      aiDraftsSkeleton.style.display = "flex";
      window.scrollTo({ top: 0, behavior: 'smooth' });

      try {
        const res = await fetch("/email-agent/generate-drafts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            file_name: filename,
            manual_emails: manualEmails,
            prompt_instructions: instructionsText
          })
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
    if (generateAiBtn) generateAiBtn.disabled = disabled;
    subjectInput.disabled = disabled;
    messageInput.disabled = disabled;
    if (manualEmailsTextarea) manualEmailsTextarea.disabled = disabled;
    if (senderNameInput) senderNameInput.disabled = disabled;
    if (generateAiBtn && !disabled) updateGenerateAiBtnState();
  }

  // --- 10. Form Submit Handler ---
  if (emailForm) {
    emailForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const subject = subjectInput.value.trim();
      const message = messageInput.value.trim();
      const senderName = senderNameInput ? senderNameInput.value.trim() : "";

      const fileName = fileSelect ? fileSelect.value : "";
      const emailsList = getManualEmailsList();

      if (!fileName && emailsList.length === 0) {
        showError("Please select an Excel report file or enter manual email addresses first.");
        return;
      }

      let payload = {
        subject: subject,
        message: message,
        sender_name: senderName,
        file_name: fileName,
        manual_emails: emailsList
      };

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
  loadHistory();
});

// ============================================================
// REPLY ASSISTANT
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  let replyMonitoring = false;
  let replyMonitorTimer = null;
  let currentReplyId = null;
  let allReplies = [];
  let activeReplyTab = "new";

  const monitorBtn =
    document.getElementById("reply-monitor-btn");

  const checkRepliesBtn =
    document.getElementById("check-replies-btn");

  const monitorStatus =
    document.getElementById("monitor-status");

  const replyNotification =
    document.getElementById("reply-notification");

  const replyNotificationText =
    document.getElementById("reply-notification-text");

  const repliesContainer =
    document.getElementById("replies-container");

  const replyModal =
    document.getElementById("reply-modal");

  const closeReplyModal =
    document.getElementById("close-reply-modal");

  const aiResponseInput =
    document.getElementById("ai-response-input");

  const sendReplyBtn =
    document.getElementById("send-reply-btn");

  const regenerateReplyBtn =
    document.getElementById("regenerate-reply-btn");

  const replyModalBusiness =
    document.getElementById("reply-modal-business");

  const replyModalEmail =
    document.getElementById("reply-modal-email");

  const originalEmailContent =
    document.getElementById("original-email-content");

  const customerReplyContent =
    document.getElementById("customer-reply-content");

  const aiReason =
    document.getElementById("ai-reason");

  const newRepliesCount =
    document.getElementById("new-replies-count");

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function loadReplies() {
    if (!repliesContainer) return;

    try {
      const res = await fetch("/email-agent/replies");
      if (!res.ok) {
        throw new Error("Failed to load replies.");
      }
      allReplies = await res.json();
      renderReplies();
    } catch (err) {
      repliesContainer.innerHTML = `
        <p class="empty-replies">
          ${escapeHtml(err.message)}
        </p>
      `;
    }
  }

  function renderReplies() {
    const replies = Array.isArray(allReplies) ? allReplies : [];

    const needsAttention = replies.filter(
      r => r.status !== "Replied"
    ).length;

    const positiveHistory = replies.filter(
      r => r.status === "Replied" && r.positive_lead === true
    ).length;

    const historyRepliesCountEl = document.getElementById("history-replies-count");

    if (newRepliesCount) {
      newRepliesCount.textContent = needsAttention;
    }

    if (historyRepliesCountEl) {
      historyRepliesCountEl.textContent = positiveHistory;
    }

    let filtered = [];

    if (activeReplyTab === "new") {
      filtered = replies.filter(
        r => r.status !== "Replied"
      );
    } else if (activeReplyTab === "history") {
      filtered = replies.filter(
        r => r.status === "Replied" && r.positive_lead === true
      );
    }

    if (!filtered.length) {
      repliesContainer.innerHTML = `
        <p class="empty-replies">
          No replies in this category.
        </p>
      `;
      return;
    }

    repliesContainer.innerHTML = filtered.map(reply => {
      const date = reply.received_at
        ? new Date(reply.received_at).toLocaleString()
        : "Unknown date";

      let statusClass = "";

      if (reply.positive_lead) {
        statusClass = "positive";
      } else if (reply.status === "Replied") {
        statusClass = "replied";
      } else if (
        reply.intent === "negative" ||
        reply.intent === "unsubscribe"
      ) {
        statusClass = "negative";
      } else {
        statusClass = "new";
      }

      return `
        <div
          class="reply-card"
          onclick="openReply('${escapeHtml(reply.id)}')"
        >
          <div class="reply-card-top">
            <div>
              <div class="reply-business">
                ${escapeHtml(
                  reply.business_name ||
                  reply.sender_name ||
                  "Unknown Business"
                )}
              </div>
              <div class="reply-email">
                ${escapeHtml(reply.sender_email || "")}
              </div>
            </div>
            <span class="reply-status ${statusClass}">
              ${escapeHtml(
                reply.positive_lead
                  ? "Positive Lead"
                  : reply.status || "New"
              )}
            </span>
          </div>
          <div class="reply-snippet">
            ${escapeHtml((reply.reply_body || "").slice(0, 240))}
            ${(reply.reply_body || "").length > 240 ? "..." : ""}
          </div>
          <div class="reply-meta">
            ${date} · ${escapeHtml(reply.intent || "unclassified")}
          </div>
        </div>
      `;
    }).join("");
  }

  async function checkReplies(showMessage = true) {
    if (checkRepliesBtn) {
      checkRepliesBtn.disabled = true;
      checkRepliesBtn.textContent = "Checking...";
    }

    try {
      const res = await fetch("/email-agent/replies/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || "Failed to check replies.");
      }

      if (showMessage) {
        alert(`Check complete. Found ${data.new_replies} new replies.`);
      }

      if (data.new_replies > 0) {
        showNotification(data.new_replies);
      }

      await loadReplies();
    } catch (err) {
      console.error("Check replies error:", err);
      if (showMessage) {
        alert("Error checking replies: " + err.message);
      }
    } finally {
      if (checkRepliesBtn) {
        checkRepliesBtn.disabled = false;
        checkRepliesBtn.textContent = "Check Replies Now";
      }
    }
  }

  function showNotification(count) {
    if (replyNotification) {
      replyNotification.style.display = "inline-flex";
      if (replyNotificationText) {
        replyNotificationText.textContent = `${count} new reply${count > 1 ? 's' : ''}`;
      }
    }
  }

  window.openReply = async function(replyId) {
    currentReplyId = replyId;
    
    if (replyModal) {
      replyModal.style.display = "block";
    }

    if (replyModalBusiness) replyModalBusiness.textContent = "Loading...";
    if (replyModalEmail) replyModalEmail.textContent = "";
    if (originalEmailContent) originalEmailContent.textContent = "";
    if (customerReplyContent) customerReplyContent.textContent = "";
    if (aiResponseInput) aiResponseInput.value = "";
    if (aiReason) aiReason.textContent = "";

    try {
      const res = await fetch(`/email-agent/replies/${replyId}`);
      if (!res.ok) throw new Error("Failed to load reply details.");
      
      const data = await res.json();
      if (!data.success || !data.reply) throw new Error(data.error || "Failed to load reply.");

      const r = data.reply;
      if (replyModalBusiness) {
        replyModalBusiness.textContent = r.business_name || r.sender_name || "Unknown Business";
      }
      if (replyModalEmail) {
        replyModalEmail.textContent = r.sender_email;
      }
      if (originalEmailContent) {
        originalEmailContent.textContent = r.original_message || "(Original email content missing)";
      }
      if (customerReplyContent) {
        customerReplyContent.textContent = r.reply_body || "(Empty body)";
      }
      if (aiResponseInput) {
        aiResponseInput.value = r.ai_draft || "";
      }
      if (aiReason) {
        aiReason.textContent = r.ai_reason ? "Reason: " + r.ai_reason : "";
      }
    } catch (err) {
      if (replyModalBusiness) replyModalBusiness.textContent = "Error";
      if (originalEmailContent) originalEmailContent.textContent = "Error loading details: " + err.message;
    }
  };

  if (closeReplyModal) {
    closeReplyModal.addEventListener("click", () => {
      if (replyModal) replyModal.style.display = "none";
    });
  }

  // Backdrop click to close
  const backdrop = document.querySelector(".reply-modal-backdrop");
  if (backdrop) {
    backdrop.addEventListener("click", () => {
      if (replyModal) replyModal.style.display = "none";
    });
  }

  if (sendReplyBtn) {
    sendReplyBtn.addEventListener("click", async () => {
      if (!currentReplyId) return;

      const responseText = aiResponseInput ? aiResponseInput.value.trim() : "";
      if (!responseText) {
        alert("Response cannot be empty.");
        return;
      }

      sendReplyBtn.disabled = true;
      sendReplyBtn.textContent = "Sending...";

      try {
        const res = await fetch(`/email-agent/replies/${currentReplyId}/send`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ response: responseText })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || "Failed to send response.");
        }

        alert("Reply sent successfully! 🎉");
        if (replyModal) replyModal.style.display = "none";
        await loadReplies();
      } catch (err) {
        alert("Error sending reply: " + err.message);
      } finally {
        sendReplyBtn.disabled = false;
        sendReplyBtn.textContent = "Done & Send";
      }
    });
  }

  if (regenerateReplyBtn) {
    regenerateReplyBtn.addEventListener("click", async () => {
      if (!currentReplyId) return;

      regenerateReplyBtn.disabled = true;
      regenerateReplyBtn.textContent = "Regenerating...";

      try {
        const res = await fetch(`/email-agent/replies/${currentReplyId}/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.error || "Failed to regenerate draft.");
        }

        const r = data.reply;
        if (aiResponseInput) {
          aiResponseInput.value = r.ai_draft || "";
        }
        if (aiReason) {
          aiReason.textContent = r.ai_reason ? "Reason: " + r.ai_reason : "";
        }
        alert("AI response regenerated! ✨");
      } catch (err) {
        alert("Error regenerating: " + err.message);
      } finally {
        regenerateReplyBtn.disabled = false;
        regenerateReplyBtn.textContent = "Regenerate";
      }
    });
  }

  // Auto-monitoring is OFF by default until user clicks Start Monitoring button
  if (monitorStatus) {
    monitorStatus.textContent = "OFF · Not monitoring";
    monitorStatus.classList.remove("active");
  }
  if (monitorBtn) {
    monitorBtn.textContent = "Start Monitoring";
    monitorBtn.classList.remove("active");
    monitorBtn.style.opacity = "1";
    monitorBtn.style.cursor = "pointer";
  }

  // --- Notification Bell & Dropdown Logic ---
  const bellBtn = document.getElementById("bell-btn");
  const bellBadge = document.getElementById("bell-badge");
  const bellDropdown = document.getElementById("bell-dropdown");
  const bellList = document.getElementById("bell-list");
  const clearBellBtn = document.getElementById("clear-bell-btn");
  const toastContainer = document.getElementById("toast-container");

  let knownUnreadCount = 0;

  function showToast(message, replyId = null) {
    if (!toastContainer) return;
    const toast = document.createElement("div");
    toast.className = "toast-alert";
    toast.innerHTML = `
      <span style="font-size: 18px;">📩</span>
      <div style="flex: 1;">
        <div style="font-size: 12px; font-weight: 600;">New Email Reply!</div>
        <div style="font-size: 11px; color: var(--muted);">${escapeHtml(message)}</div>
      </div>
    `;
    toast.style.cursor = "pointer";
    toast.addEventListener("click", () => {
      if (typeof window.showSection === "function") {
        window.showSection("replies");
      }
      if (replyId) {
        window.openReply(replyId);
      }
      toast.remove();
    });

    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = "opacity 0.4s ease, transform 0.4s ease";
      toast.style.opacity = "0";
      toast.style.transform = "translateX(100%)";
      setTimeout(() => toast.remove(), 400);
    }, 6000);
  }

  if (bellBtn && bellDropdown) {
    bellBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      bellDropdown.style.display = bellDropdown.style.display === "none" ? "block" : "none";
    });

    document.addEventListener("click", (e) => {
      if (!bellDropdown.contains(e.target) && e.target !== bellBtn) {
        bellDropdown.style.display = "none";
      }
    });
  }

  if (clearBellBtn) {
    clearBellBtn.addEventListener("click", async () => {
      try {
        const unreadItems = bellList ? bellList.querySelectorAll("[data-reply-id]") : [];
        for (const item of unreadItems) {
          const rId = item.getAttribute("data-reply-id");
          if (rId) {
            await fetch(`/email-agent/replies/${rId}/mark-read`, { method: "POST" });
          }
        }
        if (bellBadge) bellBadge.style.display = "none";
        if (bellList) bellList.innerHTML = `<div class="bell-empty">No unread notifications</div>`;
        knownUnreadCount = 0;
        await loadReplies();
      } catch (err) {
        console.error("Clear notifications error:", err);
      }
    });
  }

  async function pollNotifications() {
    try {
      const res = await fetch("/email-agent/notifications");
      if (!res.ok) return;
      const data = await res.json();
      const count = data.unread_count || 0;
      const unreadList = data.unread_replies || [];

      if (bellBadge) {
        if (count > 0) {
          bellBadge.textContent = count;
          bellBadge.style.display = "inline-block";
        } else {
          bellBadge.style.display = "none";
        }
      }

      if (count > knownUnreadCount) {
        const newItems = unreadList.slice(0, count - knownUnreadCount);
        newItems.forEach(r => {
          showToast(`From: ${r.sender_email || r.sender_name} (${r.business_name || 'Business'})`, r.id);
        });
        loadReplies();
      }
      knownUnreadCount = count;

      if (bellList) {
        if (!unreadList.length) {
          bellList.innerHTML = `<div class="bell-empty">No unread notifications</div>`;
        } else {
          bellList.innerHTML = unreadList.map(r => `
            <div class="bell-item" data-reply-id="${escapeHtml(r.id)}" onclick="window.openReply('${escapeHtml(r.id)}')">
              <div class="bell-item-title">📩 ${escapeHtml(r.business_name || r.sender_email)}</div>
              <div class="bell-item-sub">${escapeHtml((r.reply_body || '').slice(0, 70))}...</div>
            </div>
          `).join("");
        }
      }
    } catch (e) {
      console.error("Notification polling error:", e);
    }
  }

  // --- Auto-Scanning & Polling (User Click Controlled) ---
  let monitoringIntervalId = null;
  const replyMonitorBtn = document.getElementById("reply-monitor-btn");
  const monitorStatusEl = document.getElementById("monitor-status");

  if (replyMonitorBtn) {
    replyMonitorBtn.addEventListener("click", () => {
      if (monitoringIntervalId) {
        // Turn OFF
        clearInterval(monitoringIntervalId);
        monitoringIntervalId = null;
        replyMonitorBtn.textContent = "Start Monitoring";
        if (monitorStatusEl) monitorStatusEl.textContent = "OFF · Not monitoring";
      } else {
        // Turn ON
        replyMonitorBtn.textContent = "Stop Monitoring";
        if (monitorStatusEl) monitorStatusEl.textContent = "ON · Scanning active";
        pollNotifications();
        checkReplies(true);
        monitoringIntervalId = setInterval(pollNotifications, 10000);
      }
    });
  }

  // --- Delivery Tracker Logic ---
  let deliveryStatsData = null;
  let activePlacementTab = "all";

  window.loadDeliveryStats = async function() {
    try {
      const res = await fetch("/email-agent/delivery-stats");
      if (!res.ok) throw new Error("Failed to load delivery stats.");
      deliveryStatsData = await res.json();
      renderPlacementStats();
    } catch (err) {
      console.error("loadDeliveryStats error:", err);
    }
  };

  function renderPlacementStats() {
    if (!deliveryStatsData) return;
    const { total_sent, inbox_count, failed_count } = deliveryStatsData;

    const totalEl = document.getElementById("placement-total-count");
    const inboxEl = document.getElementById("placement-inbox-count");
    const failedEl = document.getElementById("placement-failed-count");

    if (totalEl) totalEl.textContent = total_sent || 0;
    if (inboxEl) inboxEl.textContent = inbox_count || 0;
    if (failedEl) failedEl.textContent = failed_count || 0;

    const tabAll = document.getElementById("tab-count-all");
    const tabInbox = document.getElementById("tab-count-inbox");
    const tabFailed = document.getElementById("tab-count-failed");

    if (tabAll) tabAll.textContent = total_sent || 0;
    if (tabInbox) tabInbox.textContent = inbox_count || 0;
    if (tabFailed) tabFailed.textContent = failed_count || 0;

    renderPlacementTable();
  }

  function renderPlacementTable() {
    const tableBody = document.getElementById("placement-table-body");
    if (!tableBody || !deliveryStatsData) return;

    let items = [];
    const { inbox_emails = [], failed_emails = [] } = deliveryStatsData;

    if (activePlacementTab === "all") {
      items = [...inbox_emails, ...failed_emails];
    } else if (activePlacementTab === "inbox") {
      items = inbox_emails;
    } else if (activePlacementTab === "failed") {
      items = failed_emails;
    }

    if (!items.length) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align: center; color: var(--muted); padding: 24px;">No emails found in this category.</td>
        </tr>
      `;
      return;
    }

    tableBody.innerHTML = items.map(item => {
      const placement = item.placement || (item.status === 'failed' ? 'failed' : 'inbox');
      const badgeClass = placement === 'failed' ? 'failed' : 'inbox';
      const badgeText = placement === 'failed' ? '❌ Failed' : '📥 Inbox';

      const dateStr = item.timestamp ? new Date(item.timestamp).toLocaleString() : 'N/A';

      let actionHtml = '';
      if (placement === 'failed') {
        actionHtml = `<span style="color: var(--muted); font-size: 11px;">${escapeHtml(item.error || 'Bounce')}</span>`;
      } else {
        actionHtml = `<span style="color: var(--accent-email); font-size: 11px;">Delivered</span>`;
      }

      return `
        <tr>
          <td style="font-weight: 600;">${escapeHtml(item.email)}</td>
          <td>${escapeHtml(item.business_name)}</td>
          <td style="color: var(--muted);">${escapeHtml(item.subject || 'N/A')}</td>
          <td style="font-family: var(--font-mono); font-size: 11px;">${dateStr}</td>
          <td><span class="placement-badge ${badgeClass}">${badgeText}</span></td>
          <td>${actionHtml}</td>
        </tr>
      `;
    }).join("");
  }

  const imapCheckBtn = document.getElementById("imap-check-spam-btn");
  if (imapCheckBtn) {
    imapCheckBtn.addEventListener("click", async () => {
      imapCheckBtn.disabled = true;
      imapCheckBtn.innerHTML = "<span>Checking IMAP Bounces...</span>";
      try {
        const res = await fetch("/email-agent/check-spam", { method: "POST" });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || "IMAP check failed.");
        alert(`IMAP Check complete! Detected ${data.detected_bounces || 0} bounced emails.`);
        await window.loadDeliveryStats();
      } catch (err) {
        alert("IMAP Check Error: " + err.message);
      } finally {
        imapCheckBtn.disabled = false;
        imapCheckBtn.innerHTML = "<span>⚡ Run IMAP Bounce Inspector</span>";
      }
    });
  }

  const placementTabs = document.querySelectorAll("[data-placement-tab]");
  placementTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      placementTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activePlacementTab = tab.getAttribute("data-placement-tab");
      renderPlacementTable();
    });
  });

  if (replyNotification) {
    replyNotification.addEventListener("click", () => {
      replyNotification.style.display = "none";
      if (typeof window.showSection === "function") {
        window.showSection("replies");
      }
      const needsAttentionTab = document.querySelector('[data-reply-tab="new"]');
      if (needsAttentionTab) {
        needsAttentionTab.click();
      }
    });
  }

  if (checkRepliesBtn) {
    checkRepliesBtn.addEventListener("click", () => {
      checkReplies(true);
    });
  }

  const replyTabs = document.querySelectorAll(".reply-tab");
  replyTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      replyTabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activeReplyTab = tab.getAttribute("data-reply-tab");
      renderReplies();
    });
  });

  // Initial loads
  loadReplies();
  window.loadDeliveryStats();
});

