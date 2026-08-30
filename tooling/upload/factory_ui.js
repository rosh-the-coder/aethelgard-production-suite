/**
 * Artwork Studio — Batch Production mode + Catalog Batch Runs + settings hooks.
 */
(function () {
  "use strict";

  let lastValidation = null;
  let lastFile = null;
  let lastFileBytes = null;
  let currentBatchId = null;

  function toast(msg) {
    if (typeof showToast === "function") showToast(msg);
    else console.log(msg);
  }

  function el(id) {
    return document.getElementById(id);
  }

  async function fileToBase64(file) {
    const buf = await file.arrayBuffer();
    lastFileBytes = new Uint8Array(buf);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < lastFileBytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, lastFileBytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }


  function ensureBatchStyles() {
    if (el("batchProductionStyles")) return;
    const style = document.createElement("style");
    style.id = "batchProductionStyles";
    style.textContent = `
      #view-generator.batch-mode { grid-template-columns: minmax(0, 1fr) !important; }
      #view-generator.batch-mode .workspace-panel,
      #view-generator.batch-mode #genInitialState,
      #view-generator.batch-mode #genLoadingState,
      #view-generator.batch-mode #genResultsGridPanel { display: none !important; }
      #view-generator.batch-mode .control-panel { max-width: 760px; width: 100%; min-width: 0; }
      #genPanelBatch { min-width: 0; max-width: 100%; overflow-x: hidden; }
      #genPanelBatch .batch-stack { display:flex; flex-direction:column; gap:16px; min-width:0; }
      #genPanelBatch .batch-card {
        background: var(--panel-2, #1e1b18); border:1px solid var(--line,#2e2a24);
        border-radius:12px; padding:14px 16px; min-width:0; overflow-wrap:anywhere; word-break:break-word;
      }
      #genPanelBatch .batch-card h4 {
        margin:0 0 8px; font-family:var(--font-display,Outfit,sans-serif);
        font-size:0.95rem; font-weight:600; color:var(--ink,#efece6);
      }
      #genPanelBatch .batch-meta { margin:0; font-size:0.8rem; line-height:1.45; color:var(--ink-muted,#a39e94); }
      #genPanelBatch .batch-actions { display:flex; flex-wrap:wrap; gap:8px; }
      #genPanelBatch .batch-actions .btn { flex:1 1 160px; }
      #genPanelBatch input[type=file] { max-width:100%; width:100%; }
      #genPanelBatch .batch-listing {
        border:1px solid var(--line,#2e2a24); border-radius:10px; padding:12px 14px;
        margin-top:8px; background:rgba(0,0,0,.22); min-width:0;
      }
      #genPanelBatch .batch-listing strong { display:block; margin-bottom:4px; color:var(--ink,#efece6); font-size:0.86rem; }
      #genPanelBatch .batch-ok { border-color:rgba(111,191,138,.4); }
      #genPanelBatch .batch-bad { border-color:rgba(239,68,68,.45); color:#fca5a5; }
      #genPanelBatch .batch-warn-live {
        border-color:rgba(212,168,75,.45); background:rgba(212,168,75,.08); color:#fcd34d;
        font-size:0.78rem; line-height:1.45;
      }
      #batchRunsContent .batch-run-card {
        padding:16px 18px; margin-bottom:14px; border:1px solid var(--border-color);
        border-radius:12px; background:rgba(0,0,0,.25); max-width:100%; overflow-wrap:anywhere;
      }
    `;
    document.head.appendChild(style);
  }

  function ensureBatchPanel() {
    ensureBatchStyles();
    // Rebuild if an older cramped panel exists without the new stack layout
    const existing = el("genPanelBatch");
    if (existing && !existing.querySelector(".batch-stack")) {
      existing.remove();
    }
    if (el("genPanelBatch")) return;
    const poster = el("genPanelPoster");
    const host = poster && poster.parentElement;
    if (!host) return;

    const modeRow = host.querySelector(".gen-mode-btn")?.parentElement;
    if (modeRow && !el("genModeBatch")) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-outline gen-mode-btn";
      btn.id = "genModeBatch";
      btn.style.cssText = "flex:1; padding:8px; font-size:0.75rem;";
      btn.textContent = "Batch Production";
      btn.onclick = () => setGeneratorMode("batch");
      modeRow.appendChild(btn);
    }

    const panel = document.createElement("div");
    panel.id = "genPanelBatch";
    panel.style.display = "none";
    panel.innerHTML = `
      <div class="batch-stack">
        <p class="batch-meta" style="margin:0;">
          One spreadsheet row = one artwork. Same <code>listing_id</code> = one listing.
          Daily limit: <strong>20 artworks</strong>. Never auto-publishes.
        </p>
        <div class="batch-card" id="batchQuotaBar"></div>
        <div class="batch-actions">
          <button type="button" class="btn btn-outline" style="padding:10px 12px;font-size:0.78rem;" onclick="batchDownloadTemplate('xlsx')">Download XLSX template</button>
          <button type="button" class="btn btn-outline" style="padding:10px 12px;font-size:0.78rem;" onclick="batchDownloadTemplate('csv')">Download CSV template</button>
        </div>
        <div class="batch-card">
          <h4>1. Upload spreadsheet</h4>
          <div style="display:flex;flex-direction:column;gap:10px;min-width:0;">
            <input type="file" id="batchFileInput" accept=".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
            <label style="display:flex;align-items:flex-start;gap:8px;font-size:0.78rem;line-height:1.4;margin:0;">
              <input type="checkbox" id="batchDryRun" checked style="margin-top:3px;">
              <span><strong>Dry-run</strong> — no paid APIs, no real Etsy. Uncheck only when providers are ready for live generation.</span>
            </label>
            <div id="batchLiveWarn" class="batch-card batch-warn-live" style="display:none;margin:0;padding:10px 12px;">
              Live mode calls your image providers and creates real product folders. Etsy stays draft-only.
            </div>
          </div>
        </div>
        <button type="button" class="btn btn-outline" style="width:100%;padding:12px;" onclick="batchValidateFile()">2. Validate file</button>
        <div id="batchValidation" style="display:none;"></div>
        <div id="batchPreview" style="display:none;"></div>
        <button type="button" class="btn" id="batchConfirmBtn" disabled style="width:100%;padding:14px;background:var(--primary);" onclick="batchConfirmStart()">
          3. Confirm &amp; start production
        </button>
        <div id="batchProgress" style="display:none;"></div>
      </div>
    `;
    host.appendChild(panel);
    el("batchDryRun")?.addEventListener("change", () => {
      const warn = el("batchLiveWarn");
      if (warn) warn.style.display = el("batchDryRun").checked ? "none" : "block";
    });
  }

  async function refreshQuota() {
    try {
      const res = await fetch("/api/quota");
      const q = await res.json();
      const bar = el("batchQuotaBar");
      if (bar) {
        bar.innerHTML =
          "<h4>Daily generation allowance</h4>" +
          '<p class="batch-meta">' + (q.label || "") + " · " + (q.remaining_label || "") + "</p>" +
          '<p class="batch-meta" style="margin-top:4px;opacity:.8;">Resets at 00:00 local time</p>';
      }
      const dashQ = el("fd-quota");
      if (dashQ) {
        dashQ.hidden = false;
        dashQ.textContent = "Daily generation: " + (q.label || "") + " · " + (q.remaining_label || "");
      }
    } catch (_) {}
  }

  window.batchDownloadTemplate = function (fmt) {
    window.open(fmt === "csv" ? "/api/templates/batch.csv" : "/api/templates/batch.xlsx", "_blank");
  };

  window.batchValidateFile = async function () {
    const input = el("batchFileInput");
    const file = input && input.files && input.files[0];
    if (!file) {
      alert("Choose a CSV or XLSX file first.");
      return;
    }
    lastFile = file;
    const b64 = await fileToBase64(file);
    const res = await fetch("/api/batches/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, content_base64: b64 }),
    });
    const data = await res.json();
    lastValidation = data;
    const box = el("batchValidation");
    const preview = el("batchPreview");
    const btn = el("batchConfirmBtn");
    if (!box) return;
    box.style.display = "block";
    if (data.error) {
      box.innerHTML = '<div class="batch-card batch-bad"><h4>Validation failed</h4><p class="batch-meta">' + data.error + "</p></div>";
      if (btn) btn.disabled = true;
      return;
    }
    const ok = !!data.ok;
    box.innerHTML =
      '<div class="batch-card ' + (ok ? "batch-ok" : "batch-bad") + '">' +
      "<h4>" + (ok ? "Validation passed" : "Validation blocked") + "</h4>" +
      '<p class="batch-meta">File: ' + (data.filename || file.name) + "</p>" +
      '<p class="batch-meta" style="margin-top:6px;">Rows: ' + data.total_rows +
      " · Valid: " + data.valid_rows + " · Invalid: " + data.invalid_rows + "</p>" +
      '<p class="batch-meta">Listings: ' + data.listings_detected +
      " · Artworks: " + data.artworks_requested +
      " · Quota remaining: " + ((data.quota && data.quota.remaining) || "—") + "</p>" +
      (data.errors && data.errors.length
        ? "<ul style='margin:10px 0 0;padding-left:18px;font-size:0.78rem;'>" +
          data.errors.slice(0, 12).map((e) => "<li>Row " + (e.row || "—") + ": " + (e.errors || []).join("; ") + "</li>").join("") +
          "</ul>"
        : "") +
      '<div style="margin-top:12px;"><button type="button" class="btn btn-outline" style="padding:6px 10px;font-size:0.72rem;" onclick="batchDownloadReport()">Download validation report</button></div>' +
      "</div>";

    if (preview) {
      preview.style.display = "block";
      const groups = data.grouping_preview || [];
      preview.innerHTML =
        '<div class="batch-card"><h4>Batch preview by listing</h4>' +
        groups.map((g) => (
          '<div class="batch-listing">' +
          "<strong>" + (g.listing_name || g.listing_id) + " · " + g.artwork_count + " artwork(s)</strong>" +
          '<p class="batch-meta">Modes: ' + (g.modes || []).join(", ") + " · Type: " + (g.product_type || "single") + "</p>" +
          '<p class="batch-meta" style="margin-top:4px;">Expected: artworks, prints, mockups, SEO, delivery package, 1 Etsy draft</p>' +
          "</div>"
        )).join("") +
        "</div>";
    }
    if (btn) {
      btn.disabled = !ok;
      const rem = (data.quota && data.quota.remaining) || 0;
      btn.textContent =
        "3. Confirm & start — consumes " + data.artworks_requested + " of " + rem + " remaining today";
    }
    refreshQuota();
  };

  window.batchDownloadReport = function () {
    if (!lastValidation || !lastValidation.report) return;
    const blob = new Blob([lastValidation.report], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "batch_validation_report.txt";
    a.click();
  };

  window.batchConfirmStart = async function () {
    if (!lastFile || !lastValidation || !lastValidation.ok) {
      alert("Validate a clean batch first.");
      return;
    }
    const artworks = lastValidation.artworks_requested;
    const rem = (lastValidation.quota && lastValidation.quota.remaining) || 0;
    const dryRun = !!(el("batchDryRun") && el("batchDryRun").checked);
    const modeNote = dryRun
      ? "Dry-run: placeholder artifacts only."
      : "LIVE: will call image providers for each artwork.";
    if (!confirm("This batch will consume " + artworks + " of " + rem + " remaining artworks today.\n\n" + modeNote + "\n\nContinue?")) {
      return;
    }
    const b64 = await fileToBase64(lastFile);
    const createRes = await fetch("/api/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: lastFile.name, content_base64: b64, dry_run: dryRun }),
    });
    const created = await createRes.json();
    if (!createRes.ok || !created.success) {
      alert(created.error || "Could not create batch");
      return;
    }
    currentBatchId = created.batch.id;
    const startRes = await fetch("/api/batches/" + encodeURIComponent(currentBatchId) + "/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const started = await startRes.json();
    if (!startRes.ok || !started.success) {
      alert(started.error || "Could not start batch");
      return;
    }
    toast("Batch " + currentBatchId + " started");
    el("batchProgress").style.display = "block";
    pollBatchProgress(currentBatchId);
    refreshQuota();
    if (typeof loadFactoryDashboard === "function") loadFactoryDashboard();
  };

  async function pollBatchProgress(batchId) {
    const box = el("batchProgress");
    if (!box) return;
    const tick = async () => {
      try {
        const res = await fetch("/api/batches/" + encodeURIComponent(batchId));
        const data = await res.json();
        const p = data.progress || {};
        const pct = Math.max(0, Math.min(100, Number(p.percentage || 0)));
        const failedJobs = (data.jobs || []).filter((j) => j.status === "failed");
        const errHtml = failedJobs.length
          ? '<div class="batch-card batch-bad" style="margin-top:12px;"><h4>Failures</h4>' +
            failedJobs.slice(0, 6).map((j) =>
              '<p class="batch-meta" style="margin-top:6px;"><strong>' + (j.artwork_id || j.id) + "</strong> — " +
              (j.error || j.message || "failed") + "</p>"
            ).join("") + "</div>"
          : "";
        box.className = "batch-card";
        box.innerHTML =
          "<h4>Batch " + data.id + "</h4>" +
          '<p class="batch-meta">' + (p.artworks_completed || 0) + " / " + (p.artworks_total || 0) +
          " artworks · " + (p.listings_ready || 0) + " / " + (p.listings_total || 0) + " listings ready</p>" +
          '<div class="fd-progress"><div class="fd-progress__bar" style="width:' + pct + '%"></div></div>' +
          '<p class="batch-meta">' + pct + "% · status: " + (p.status || data.status) +
          (data.dry_run ? " · dry-run" : " · live") + "</p>" +
          errHtml +
          '<div class="batch-actions" style="margin-top:12px;">' +
          '<button type="button" class="btn btn-outline" style="padding:8px 10px;font-size:0.72rem;" onclick="switchView(\'catalog\');setTimeout(()=>switchCatalogTab && switchCatalogTab(\'batches\'),50)">Open Batch Runs</button>' +
          '<button type="button" class="btn btn-outline" style="padding:8px 10px;font-size:0.72rem;" onclick="batchRetry(\'' + data.id + "')\">Retry failed</button>" +
          '<button type="button" class="btn btn-outline" style="padding:8px 10px;font-size:0.72rem;" onclick="batchCancel(\'' + data.id + "')\">Cancel queued</button>" +
          "</div>";
        if (["complete", "partial", "failed", "cancelled"].includes(p.status || data.status)) {
          if (typeof loadFactoryDashboard === "function") loadFactoryDashboard();
          return;
        }
        setTimeout(tick, 1500);
      } catch (e) {
        setTimeout(tick, 2500);
      }
    };
    tick();
  }

  window.batchCancel = async function (batchId) {
    if (!confirm("Cancel queued items that have not started?")) return;
    const res = await fetch("/api/batches/" + encodeURIComponent(batchId) + "/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    toast(data.success ? "Cancelled queued jobs" : data.error || "Cancel failed");
    pollBatchProgress(batchId);
  };

  const prevSetMode = window.setGeneratorMode;
  window.setGeneratorMode = function (mode) {
    ensureBatchPanel();
    if (typeof prevSetMode === "function" && mode !== "batch") {
      prevSetMode(mode);
    } else if (typeof prevSetMode === "function" && mode === "batch") {
      prevSetMode("ai");
    }
    const map = {
      ai: "genModeAi",
      public_domain: "genModePd",
      graphic_poster: "genModePoster",
      batch: "genModeBatch",
      upload: "genModeUpload",
    };
    document.querySelectorAll(".gen-mode-btn").forEach((b) => b.classList.remove("active"));
    el(map[mode])?.classList.add("active");
    if (el("genPanelAi")) el("genPanelAi").style.display = mode === "ai" ? "block" : "none";
    if (el("genPanelPd")) el("genPanelPd").style.display = mode === "public_domain" ? "block" : "none";
    if (el("genPanelPoster")) el("genPanelPoster").style.display = mode === "graphic_poster" ? "block" : "none";
    if (el("genPanelUpload")) el("genPanelUpload").style.display = mode === "upload" ? "block" : "none";
    if (el("genPanelBatch")) el("genPanelBatch").style.display = mode === "batch" ? "block" : "none";
    const genView = el("view-generator");
    if (genView) genView.classList.toggle("batch-mode", mode === "batch");
    if (mode === "batch") refreshQuota();
    try { window.generatorMode = mode; } catch (_) {}
  };


  // Catalog Batch Runs tab
  function ensureBatchRunsTab() {
    if (el("catalogTabBatches")) return;
    const lib = el("catalogTabLibrary");
    if (!lib) return;
    const btn = document.createElement("button");
    btn.className = "sub-tab-btn";
    btn.id = "catalogTabBatches";
    btn.type = "button";
    btn.textContent = "Batch Runs";
    btn.onclick = () => switchCatalogTab("batches");
    lib.parentElement.insertBefore(btn, lib.nextSibling);

    const masonryParent = el("catalogGridMode");
    if (masonryParent && !el("batchRunsPanel")) {
      const panel = document.createElement("div");
      panel.id = "batchRunsPanel";
      panel.style.display = "none";
      panel.innerHTML = '<div id="batchRunsContent" style="font-size:0.85rem;color:var(--text-secondary);">Loading batches…</div>';
      masonryParent.appendChild(panel);
    }
  }

  const prevSwitchCatalog = window.switchCatalogTab;
  window.switchCatalogTab = function (tab) {
    ensureBatchRunsTab();
    if (typeof prevSwitchCatalog === "function" && tab !== "batches") {
      prevSwitchCatalog(tab);
    }
    const masonry = el("catalogMasonry");
    const libTool = el("libraryToolbar");
    const batchPanel = el("batchRunsPanel");
    document.querySelectorAll("#catalogTabListings, #catalogTabLibrary, #catalogTabBatches").forEach((b) =>
      b.classList.remove("active")
    );
    if (tab === "batches") {
      el("catalogTabBatches")?.classList.add("active");
      if (masonry) masonry.style.display = "none";
      if (libTool) libTool.style.display = "none";
      if (batchPanel) batchPanel.style.display = "block";
      loadBatchRuns();
      return;
    }
    if (batchPanel) batchPanel.style.display = "none";
    if (masonry) masonry.style.display = "";
    if (tab === "listings") el("catalogTabListings")?.classList.add("active");
    if (tab === "library") el("catalogTabLibrary")?.classList.add("active");
  };

  async function loadBatchRuns() {
    const box = el("batchRunsContent");
    if (!box) return;
    try {
      const res = await fetch("/api/batches");
      const data = await res.json();
      const byDate = data.by_date || {};
      const dates = Object.keys(byDate).sort().reverse();
      if (!dates.length) {
        box.innerHTML = "<p>No batch runs yet. Create one in Artwork Studio → Batch Production.</p>";
        return;
      }
      const watching = window.__batchRetryWatch || {};
      box.innerHTML =
        '<div id="batchRunsStatus" class="batch-meta" style="margin-bottom:12px;"></div>' +
        dates
          .map((day) => {
            const batches = byDate[day] || [];
            return (
              "<h3 style='margin:18px 0 10px;color:#fff;font-family:Outfit;'>" +
              day +
              "</h3>" +
              batches
                .map((b) => {
                  const p = b.progress || {};
                  const pct = Math.max(0, Math.min(100, Number(p.percentage || 0)));
                  const status = p.status || b.status || "—";
                  const failed = Number(p.artworks_failed || b.failed_artworks || 0);
                  const completed = Number(p.artworks_completed || b.completed_artworks || 0);
                  const total = Number(p.artworks_total || b.artwork_total || 0);
                  const isWatching = !!watching[b.id];
                  const failedJobs = (b.jobs || []).filter((j) => j.status === "failed");
                  const errBlock = failedJobs.length
                    ? '<div style="margin-top:8px;padding:8px 10px;border:1px solid rgba(239,68,68,.35);border-radius:8px;font-size:0.72rem;color:#fca5a5;">' +
                      failedJobs
                        .slice(0, 4)
                        .map(
                          (j) =>
                            "<div><strong>" +
                            (j.artwork_id || j.id) +
                            "</strong> — " +
                            (j.error || j.message || "failed") +
                            "</div>"
                        )
                        .join("") +
                      "</div>"
                    : "";
                  const retryBtn = failed
                    ? '<button type="button" class="btn btn-outline" id="retryBtn-' +
                      b.id +
                      '" style="padding:6px 10px;font-size:0.72rem;" onclick="batchRetry(\'' +
                      b.id +
                      "')\" " +
                      (isWatching ? "disabled" : "") +
                      ">" +
                      (isWatching ? "Retrying…" : "Retry " + failed + " failed") +
                      "</button>"
                    : '<span style="font-size:0.72rem;opacity:.65;align-self:center;">No failed jobs</span>';
                  return (
                    '<div class="batch-run-card" data-batch-id="' +
                    b.id +
                    '">' +
                    "<strong style='color:#fff;'>Batch " +
                    b.id +
                    "</strong>" +
                    (b.dry_run ? ' <span style="opacity:.7;">· dry-run</span>' : " · live") +
                    ' <span style="opacity:.75;">· ' +
                    status +
                    "</span><br>" +
                    (p.listings_total || b.listing_total || 0) +
                    " listings · " +
                    total +
                    " artworks · " +
                    completed +
                    " completed · " +
                    failed +
                    " failed · " +
                    (p.etsy_drafts || b.etsy_drafts || 0) +
                    " Etsy drafts<br>" +
                    '<div class="fd-progress" style="margin:8px 0;"><div class="fd-progress__bar" style="width:' +
                    pct +
                    '%"></div></div>' +
                    "<div style='font-size:0.75rem;opacity:.8;'>Source: " +
                    (b.source_filename || "—") +
                    " · email: " +
                    (b.email_status || "—") +
                    "</div>" +
                    errBlock +
                    '<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">' +
                    retryBtn +
                    '<a class="btn btn-outline" style="padding:6px 10px;font-size:0.72rem;" href="/api/batches/' +
                    encodeURIComponent(b.id) +
                    '/report">Download report</a>' +
                    "</div></div>"
                  );
                })
                .join("")
            );
          })
          .join("");
      const statusEl = el("batchRunsStatus");
      const activeIds = Object.keys(watching);
      if (statusEl && activeIds.length) {
        statusEl.textContent = "Watching retry for: " + activeIds.join(", ") + " — refreshing…";
      }
    } catch (e) {
      box.textContent = "Could not load batches: " + e;
    }
  }

  window.batchRetry = async function (batchId) {
    const btn = el("retryBtn-" + batchId);
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Queuing retry…";
    }
    toast("Sending retry for batch " + batchId + "…");
    try {
      const res = await fetch("/api/batches/" + encodeURIComponent(batchId) + "/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        toast(data.error || "Retry request failed");
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Retry failed";
        }
        return;
      }
      const retried = Number(data.retried_count || 0);
      toast(data.message || (retried ? "Queued " + retried + " job(s)" : "Nothing to retry"));
      if (!retried) {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Retry failed";
        }
        loadBatchRuns();
        return;
      }
      window.__batchRetryWatch = window.__batchRetryWatch || {};
      window.__batchRetryWatch[batchId] = true;
      loadBatchRuns();
      watchBatchRetry(batchId);
    } catch (e) {
      toast("Retry network error: " + e);
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Retry failed";
      }
    }
  };

  async function watchBatchRetry(batchId) {
    const terminal = ["complete", "partial", "failed", "cancelled"];
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const res = await fetch("/api/batches/" + encodeURIComponent(batchId));
        const data = await res.json();
        const p = data.progress || {};
        const status = p.status || data.status;
        const failed = Number(p.artworks_failed || 0);
        const completed = Number(p.artworks_completed || 0);
        const total = Number(p.artworks_total || 0);
        const statusEl = el("batchRunsStatus");
        if (statusEl) {
          statusEl.textContent =
            "Retry " +
            batchId +
            ": " +
            completed +
            "/" +
            total +
            " complete · " +
            failed +
            " failed · status " +
            status;
        }
        if (i % 2 === 0) loadBatchRuns();
        if (terminal.includes(status)) {
          if (window.__batchRetryWatch) delete window.__batchRetryWatch[batchId];
          toast(
            failed
              ? "Retry finished with " + failed + " still failed (" + batchId + ")"
              : "Retry finished — all artworks complete (" + batchId + ")"
          );
          loadBatchRuns();
          return;
        }
      } catch (_) {}
    }
    if (window.__batchRetryWatch) delete window.__batchRetryWatch[batchId];
    toast("Stopped watching retry for " + batchId + " — refresh Batch Runs to check.");
    loadBatchRuns();
  }

  function ensureSettingsExtras() {
    const grid = document.querySelector("#view-settings .settings-grid");
    if (!grid || el("setEmailEnabled")) return;
    const block = document.createElement("div");
    block.className = "form-item";
    block.style.gridColumn = "span 2";
    block.innerHTML = `
      <label>Batch &amp; email notifications</label>
      <div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:12px;">
        SMTP password is read only from environment variable <code>AETHELGARD_SMTP_PASSWORD</code> — never stored in settings JSON.
      </div>
      <div id="settingsQuota" style="margin-bottom:12px;font-size:0.8rem;"></div>
      <div class="form-item" style="margin-bottom:10px;">
        <label for="setBatchConcurrency">Batch concurrency (1–4)</label>
        <input type="number" id="setBatchConcurrency" min="1" max="4" value="1">
      </div>
      <label style="display:flex;gap:8px;align-items:center;margin-bottom:10px;font-size:0.85rem;">
        <input type="checkbox" id="setEmailEnabled"> Enable email notifications
      </label>
      <div class="form-item" style="margin-bottom:8px;"><label>SMTP host</label><input type="text" id="setSmtpHost" placeholder="smtp.gmail.com"></div>
      <div class="form-item" style="margin-bottom:8px;"><label>SMTP port</label><input type="number" id="setSmtpPort" value="587"></div>
      <div class="form-item" style="margin-bottom:8px;"><label>SMTP username</label><input type="text" id="setSmtpUser"></div>
      <div class="form-item" style="margin-bottom:8px;"><label>Sender address</label><input type="text" id="setSmtpSender"></div>
      <div class="form-item" style="margin-bottom:8px;"><label>Recipient address</label><input type="text" id="setSmtpRecipient"></div>
      <div class="form-item" style="margin-bottom:8px;">
        <label>TLS mode</label>
        <select id="setSmtpTls"><option value="starttls">STARTTLS</option><option value="ssl">SSL</option><option value="off">Off</option></select>
      </div>
      <button type="button" class="btn btn-outline" style="padding:8px 12px;" onclick="testEmailSettings()">Send test email</button>
    `;
    grid.appendChild(block);
  }

  const prevLoadSettings = window.loadSettingsPanel;
  window.loadSettingsPanel = async function () {
    ensureSettingsExtras();
    if (typeof prevLoadSettings === "function") await prevLoadSettings();
    try {
      const res = await fetch("/api/suite_settings");
      const data = await res.json();
      const s = data.settings || {};
      if (el("setBatchConcurrency")) el("setBatchConcurrency").value = (s.batch || {}).concurrency || 1;
      const email = s.email || {};
      if (el("setEmailEnabled")) el("setEmailEnabled").checked = !!email.enabled;
      if (el("setSmtpHost")) el("setSmtpHost").value = email.host || "";
      if (el("setSmtpPort")) el("setSmtpPort").value = email.port || 587;
      if (el("setSmtpUser")) el("setSmtpUser").value = email.username || "";
      if (el("setSmtpSender")) el("setSmtpSender").value = email.sender || "";
      if (el("setSmtpRecipient")) el("setSmtpRecipient").value = email.recipient || "";
      if (el("setSmtpTls")) el("setSmtpTls").value = email.tls_mode || "starttls";
      const qRes = await fetch("/api/quota");
      const q = await qRes.json();
      if (el("settingsQuota")) {
        el("settingsQuota").textContent =
          "Daily generation: " + (q.label || "") + " · " + (q.remaining_label || "") + " · Resets at 00:00 local";
      }
    } catch (_) {}
  };

  const prevSaveSettings = window.savePresetSettings;
  window.savePresetSettings = async function () {
    ensureSettingsExtras();
    const elg = (id) => document.getElementById(id);
    // call original save with extended payload by monkeypatching fetch briefly is hard —
    // instead POST full payload here.
    const payload = {
      prices: {
        single: parseFloat(elg("setPriceSingle").value) || 2.99,
        graphic_poster: parseFloat(elg("setPricePoster").value) || 2.99,
        pd_bundle: parseFloat(elg("setPricePdPack").value) || 7.99,
        bundle: parseFloat(elg("setPriceBundle").value) || 12.99,
      },
      default_quantity: parseInt(elg("setDefaultQty").value, 10) || 999,
      thank_you_note: elg("setThankYou").value || "",
      batch: {
        concurrency: parseInt(elg("setBatchConcurrency")?.value || "1", 10) || 1,
      },
      email: {
        enabled: !!elg("setEmailEnabled")?.checked,
        host: elg("setSmtpHost")?.value || "",
        port: parseInt(elg("setSmtpPort")?.value || "587", 10) || 587,
        username: elg("setSmtpUser")?.value || "",
        sender: elg("setSmtpSender")?.value || "",
        recipient: elg("setSmtpRecipient")?.value || "",
        tls_mode: elg("setSmtpTls")?.value || "starttls",
      },
    };
    try {
      const response = await fetch("/api/suite_settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.success) toast("Presets settings saved!");
      else alert(data.error || "Failed to save settings.");
    } catch (e) {
      alert("Network error saving settings.");
    }
  };

  window.testEmailSettings = async function () {
    // save first
    await window.savePresetSettings();
    const res = await fetch("/api/settings/email/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    if (data.ok) toast("Test email sent to " + (data.recipient || "recipient"));
    else alert(data.error || "Email test failed");
  };

  // Hook switchView for dashboard live connect + generator batch
  const prevSwitch = window.switchView;
  window.switchView = function (viewName, opts) {
    if (typeof prevSwitch === "function") prevSwitch(viewName, opts);
    if (viewName === "dashboard" && typeof window.factoryDashConnect === "function") {
      window.factoryDashConnect();
    }
    if (viewName === "generator") ensureBatchPanel();
    if (viewName === "catalog") ensureBatchRunsTab();
    if (viewName === "settings") {
      ensureSettingsExtras();
      if (typeof loadSettingsPanel === "function") loadSettingsPanel();
    }
  };

  // Boot
  document.addEventListener("DOMContentLoaded", () => {
    ensureBatchPanel();
    ensureBatchRunsTab();
    ensureSettingsExtras();
  });
  // dashboard.html may already be loaded
  setTimeout(() => {
    ensureBatchPanel();
    ensureBatchRunsTab();
  }, 0);
})();
