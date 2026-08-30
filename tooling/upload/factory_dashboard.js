/**
 * Factory Dashboard — live projection of application state.
 * Source of truth: GET /api/dashboard + SSE /api/events (polling fallback).
 */
(function () {
  "use strict";

  const QUICK_VIEWS = {
    newProduct: "generator",
    continueDraft: "catalog",
    mockups: "studio",
    research: "research",
    openDraft: "catalog",
    uploadBatch: "generator",
    downloadTemplate: "generator",
    reviewBatch: "catalog",
    retryFailed: "catalog",
  };

  const PIPELINE_VIEWS = {
    research: "research",
    acquire: "generator",
    select: "generator",
    master: "generator",
    print: "catalog",
    mockups: "studio",
    seo: "catalog",
    package: "catalog",
    draft: "catalog",
    review: "catalog",
  };

  let es = null;
  let pollTimer = null;
  let lastDashboard = null;

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null ? "—" : String(value);
  }

  function goView(view) {
    try {
      if (typeof window.switchView === "function") window.switchView(view);
    } catch (_) {}
  }

  function openPiece(runIdx, pieceIdx) {
    goView("catalog");
    try {
      if (typeof window.selectCatalogPiece === "function") {
        window.selectCatalogPiece(runIdx, pieceIdx);
      }
    } catch (_) {}
  }

  function formatRelative(ts) {
    if (!ts) return "";
    const ms = ts > 1e12 ? ts : ts * 1000;
    const diff = Date.now() - ms;
    if (diff < 0) return "just now";
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return "just now";
    const min = Math.floor(sec / 60);
    if (min < 60) return min + "m ago";
    const hr = Math.floor(min / 60);
    if (hr < 24) return hr + "h ago";
    const day = Math.floor(hr / 24);
    if (day < 14) return day + "d ago";
    try {
      return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    } catch (_) {
      return "";
    }
  }

  function badge(status) {
    const map = {
      draft: ["draft", "Draft"],
      pending_review: ["review", "Review"],
      in_progress: ["progress", "In progress"],
      error: ["error", "Error"],
      queue: ["queue", "Queued"],
      stale: ["warn", "Stale"],
    };
    const pair = map[status] || ["queue", "—"];
    return '<span class="fd-badge fd-badge--' + pair[0] + '">' + escapeHtml(pair[1]) + "</span>";
  }

  function deriveStatus(piece) {
    const st = piece && piece.upload_status;
    const ust =
      !st ? "" : typeof st === "string" ? st.toLowerCase() : String(st.status || "").toLowerCase();
    if (ust === "failed" || ust === "error") return "error";
    if (["done", "uploaded", "success", "succeeded", "draft"].includes(ust) || piece.uploaded_at)
      return "draft";
    if (piece.stale_artifacts && piece.stale_artifacts.length) return "stale";
    if (piece.has_pdf && (piece.mockups || []).length && piece.seo_title) return "pending_review";
    if ((piece.master_image || piece.master_preview) && (!(piece.mockups || []).length || !piece.has_pdf || !piece.seo_title))
      return "in_progress";
    return "queue";
  }

  function thumbUrl(piece) {
    const thumb =
      (piece && piece.mockups && piece.mockups[0]) ||
      (piece && piece.master_preview) ||
      (piece && piece.master_image) ||
      "";
    if (!thumb) return "";
    const rel = String(thumb).replace(/^\/+/, "");
    return "/" + rel + "?t=" + Math.floor(piece.mtime || 0);
  }

  function renderProviders(preflight, auth, etsyApi) {
    const el = document.getElementById("fd-providers");
    if (!el) return;
    const pf = preflight || {};
    const api = etsyApi || {};
    const pills = [
      ["Cloudflare", !!pf.cloudflare_ready, "ready", "not configured"],
      ["Gemini", !!pf.gemini_key_set, "ready", "not configured"],
      ["OpenAI", !!pf.openai_key_set, "ready", "not configured"],
      ["Etsy API", !!api.oauth_connected, "connected", "not connected"],
      ["Local server", true, "active :8080", "down"],
    ];
    el.innerHTML = pills
      .map(([name, online, onLab, offLab]) => {
        const cls = online ? "fd-pill--online" : "fd-pill--offline";
        return (
          '<div class="fd-pill ' +
          cls +
          '"><span class="fd-pill__dot"></span><span class="fd-pill__name">' +
          escapeHtml(name) +
          '</span><span class="fd-pill__state">' +
          escapeHtml(online ? onLab : offLab) +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderPipeline(stages) {
    const el = document.getElementById("fd-pipeline");
    if (!el) return;
    el.innerHTML = (stages || [])
      .map((s) => {
        const countLabel = s.count == null ? "—" : String(s.count);
        const active = s.count != null && s.count > 0;
        const mods = [
          active ? "fd-stage--active" : "",
          s.tone === "warn" ? "fd-stage--warn" : "",
          s.tone === "ok" ? "fd-stage--ok" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          '<button type="button" class="fd-stage ' +
          mods +
          '" data-stage="' +
          escapeHtml(s.id) +
          '"><div class="fd-stage__name">' +
          escapeHtml(s.name) +
          '</div><div class="fd-stage__count">' +
          escapeHtml(countLabel) +
          '</div><div class="fd-stage__status">' +
          escapeHtml(s.status || (active ? "active" : "idle")) +
          "</div></button>"
        );
      })
      .join("");
    el.querySelectorAll(".fd-stage").forEach((btn) => {
      btn.addEventListener("click", () => goView(PIPELINE_VIEWS[btn.getAttribute("data-stage")] || "catalog"));
    });
  }

  function renderRows(id, pieces, emptyHtml) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!pieces.length) {
      el.innerHTML = emptyHtml;
      return;
    }
    el.innerHTML = pieces
      .map((p) => {
        const status = deriveStatus(p);
        const src = thumbUrl(p);
        const title = p.title || p.slug || "Untitled";
        return (
          '<button type="button" class="fd-row" data-run-idx="' +
          p.runIdx +
          '" data-piece-idx="' +
          p.pieceIdx +
          '">' +
          (src
            ? '<img class="fd-row__thumb" src="' + escapeHtml(src) + '" alt="" loading="lazy">'
            : '<div class="fd-row__thumb"></div>') +
          '<div><p class="fd-row__title">' +
          escapeHtml(title) +
          '</p><div class="fd-row__meta">' +
          badge(status) +
          "<span>" +
          escapeHtml(formatRelative(p.mtime) || "—") +
          "</span></div></div></button>"
        );
      })
      .join("");
    el.querySelectorAll(".fd-row").forEach((btn) => {
      btn.addEventListener("click", () =>
        openPiece(parseInt(btn.getAttribute("data-run-idx"), 10), parseInt(btn.getAttribute("data-piece-idx"), 10))
      );
    });
  }

  function renderProjects(pieces) {
    const el = document.getElementById("fd-projects");
    if (!el) return;
    const recent = pieces.slice(0, 8);
    if (!recent.length) {
      el.innerHTML =
        '<div class="fd-empty"><strong>No products yet</strong>Start a product or upload a batch.' +
        '<button type="button" onclick="factoryDashQuick(\'newProduct\')">New Product</button></div>';
      return;
    }
    el.innerHTML = recent
      .map((p) => {
        const src = thumbUrl(p);
        return (
          '<button type="button" class="fd-project" data-run-idx="' +
          p.runIdx +
          '" data-piece-idx="' +
          p.pieceIdx +
          '">' +
          (src
            ? '<img class="fd-project__thumb" src="' + escapeHtml(src) + '" alt="" loading="lazy">'
            : '<div class="fd-project__thumb"></div>') +
          '<div class="fd-project__body"><p class="fd-project__title">' +
          escapeHtml(p.title || p.slug || "Untitled") +
          '</p><div class="fd-project__meta">' +
          badge(deriveStatus(p)) +
          "<span>" +
          escapeHtml(formatRelative(p.mtime) || "") +
          "</span></div></div></button>"
        );
      })
      .join("");
    el.querySelectorAll(".fd-project").forEach((btn) => {
      btn.addEventListener("click", () =>
        openPiece(parseInt(btn.getAttribute("data-run-idx"), 10), parseInt(btn.getAttribute("data-piece-idx"), 10))
      );
    });
  }

  function renderActivity(items) {
    const el = document.getElementById("fd-activity");
    if (!el) return;
    if (!items || !items.length) {
      el.innerHTML = '<div class="fd-empty"><strong>No recent activity</strong></div>';
      return;
    }
    el.innerHTML = items
      .slice(0, 12)
      .map((it) => {
        return (
          '<div class="fd-activity__item"><span class="fd-activity__mark fd-activity__mark--' +
          escapeHtml(it.mark || "idle") +
          '"></span><div><p class="fd-activity__text">' +
          escapeHtml(it.text) +
          "</p>" +
          (it.sub ? '<p class="fd-activity__sub">' + escapeHtml(it.sub) + "</p>" : "") +
          '</div><span class="fd-activity__time">' +
          escapeHtml(formatRelative(it.time) || "") +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderBatchWidget(active) {
    let el = document.getElementById("fd-batch-widget");
    if (!el) {
      const grid = document.querySelector(".factory-dash__grid--primary");
      if (!grid) return;
      el = document.createElement("section");
      el.className = "fd-panel fd-panel--primary";
      el.id = "fd-batch-widget";
      el.setAttribute("aria-label", "Batch progress");
      grid.parentNode.insertBefore(el, grid.nextSibling);
    }
    if (!active || !active.id) {
      el.innerHTML =
        '<div class="fd-panel__head"><h4 class="fd-panel__title">Batch production</h4></div>' +
        '<div class="fd-empty"><strong>No active batch</strong>Upload a spreadsheet in Artwork Studio → Batch Production.' +
        '<button type="button" onclick="factoryDashQuick(\'uploadBatch\')">Upload Batch</button></div>';
      return;
    }
    const p = active.progress || {};
    const pct = Math.max(0, Math.min(100, Number(p.percentage || 0)));
    el.innerHTML =
      '<div class="fd-panel__head"><h4 class="fd-panel__title">Batch ' +
      escapeHtml(active.id) +
      '</h4><span class="fd-panel__meta">' +
      escapeHtml(active.status || "") +
      (active.dry_run ? " · dry-run" : "") +
      "</span></div>" +
      '<p style="margin:0 0 8px;font-size:0.9rem;">' +
      escapeHtml((p.artworks_completed || 0) + " / " + (p.artworks_total || 0) + " artworks") +
      " · " +
      escapeHtml((p.listings_ready || 0) + " / " + (p.listings_total || 0) + " listings ready") +
      "</p>" +
      '<div class="fd-progress" aria-valuenow="' +
      pct +
      '" aria-valuemin="0" aria-valuemax="100" role="progressbar">' +
      '<div class="fd-progress__bar" style="width:' +
      pct +
      '%"></div></div>' +
      '<p style="margin:8px 0 0;font-size:0.75rem;color:var(--ink-muted)">' +
      pct +
      "% · " +
      escapeHtml((p.listings_processing || 0) + " processing · " + (p.listings_attention || 0) + " need attention") +
      "</p>";
  }

  function renderQuota(q) {
    const el = document.getElementById("fd-quota");
    if (!el || !q) return;
    el.hidden = false;
    el.textContent = "Daily generation: " + (q.label || "") + " · " + (q.remaining_label || "");
  }

  function renderActions(actions) {
    const wrap = document.querySelector(".fd-actions");
    if (!wrap || !actions) return;
    wrap.innerHTML = actions
      .map((a) => {
        const cls = a.primary ? "fd-action fd-action--primary" : "fd-action";
        return (
          '<button type="button" class="' +
          cls +
          '" onclick="factoryDashQuick(\'' +
          escapeHtml(a.id) +
          "')\">" +
          escapeHtml(a.label) +
          "</button>"
        );
      })
      .join("");
  }

  function applyDashboard(data) {
    lastDashboard = data;
    const k = data.kpis || {};
    setText("fd-kpi-products", k.products);
    setText("fd-kpi-queue", k.queue);
    setText("fd-kpi-drafts", k.drafts);
    setText("fd-kpi-review", k.review);
    setText("fd-kpi-errors", k.errors);

    const attentionEl = document.getElementById("fd-attention");
    if (attentionEl) {
      if (data.attention) {
        attentionEl.hidden = false;
        attentionEl.textContent = data.attention;
      } else {
        attentionEl.hidden = true;
        attentionEl.textContent = "";
      }
    }

    const errEl = document.getElementById("fd-kpi-errors");
    if (errEl) errEl.closest(".fd-kpi")?.classList.toggle("fd-kpi--danger", (k.errors || 0) > 0);
    const revEl = document.getElementById("fd-kpi-review");
    if (revEl) revEl.closest(".fd-kpi")?.classList.toggle("fd-kpi--warn", (k.review || 0) > 0);

    renderPipeline(data.pipeline || []);
    renderQuota(data.quota);
    renderBatchWidget(data.active_batch);
    renderActions(data.quick_actions);

    const pieces = data.pieces || [];
    const reviewItems = pieces
      .filter((p) => ["pending_review", "error", "draft", "stale"].includes(deriveStatus(p)))
      .slice(0, 6);
    renderRows(
      "fd-review",
      reviewItems,
      '<div class="fd-empty"><strong>Nothing needs attention</strong></div>'
    );
    const active = pieces
      .filter((p) => ["in_progress", "queue"].includes(deriveStatus(p)))
      .slice(0, 6);
    renderRows(
      "fd-active",
      active.length ? active : pieces.filter((p) => deriveStatus(p) !== "draft").slice(0, 6),
      '<div class="fd-empty"><strong>No active products</strong></div>'
    );
    renderProjects(pieces);
    renderActivity(data.activity || []);
    renderProviders(data.preflight, data.auth, data.etsy_api);

    const stats = data.stats || {};
    setText("fd-stat-runs", stats.runs);
    setText("fd-stat-mockups", stats.mockups);
    setText("fd-stat-prints", stats.prints);
    setText("fd-stat-pdfs", stats.pdfs);
    setText("fd-stat-drafts", stats.drafts);

    const updated = document.getElementById("fd-updated");
    if (updated) {
      updated.dataset.live = "1";
      updated.textContent =
        "Updated " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
  }

  async function loadFactoryDashboard() {
    const root = document.getElementById("factory-dash-root");
    if (root) root.dataset.loading = "1";
    try {
      const res = await fetch("/api/dashboard");
      if (!res.ok) throw new Error("dashboard " + res.status);
      const data = await res.json();
      applyDashboard(data);
    } catch (err) {
      console.warn("loadFactoryDashboard failed", err);
      const updated = document.getElementById("fd-updated");
      if (updated) {
        updated.dataset.live = "0";
        updated.textContent = "Could not refresh";
      }
    } finally {
      if (root) root.dataset.loading = "0";
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(() => {
      if (document.getElementById("view-dashboard")?.classList.contains("active")) {
        loadFactoryDashboard();
      }
    }, 8000);
  }

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  function connectEvents() {
    if (es) {
      try {
        es.close();
      } catch (_) {}
    }
    try {
      es = new EventSource("/api/events");
      es.onmessage = () => {
        if (document.getElementById("view-dashboard")?.classList.contains("active")) {
          loadFactoryDashboard();
        }
      };
      es.addEventListener("dashboard.invalidate", () => loadFactoryDashboard());
      es.addEventListener("batch.progress", () => loadFactoryDashboard());
      es.addEventListener("job.progress", () => loadFactoryDashboard());
      es.addEventListener("quota.changed", () => loadFactoryDashboard());
      es.onerror = () => {
        try {
          es.close();
        } catch (_) {}
        es = null;
        startPolling();
      };
      stopPolling();
    } catch (_) {
      startPolling();
    }
  }

  function factoryDashQuick(action) {
    if (action === "downloadTemplate") {
      window.open("/api/templates/batch.xlsx", "_blank");
      return;
    }
    if (action === "uploadBatch" || action === "reviewBatch") {
      goView("generator");
      setTimeout(() => {
        if (typeof window.setGeneratorMode === "function") window.setGeneratorMode("batch");
        if (action === "reviewBatch" && typeof window.switchCatalogTab === "function") {
          goView("catalog");
          window.switchCatalogTab("batches");
        }
      }, 50);
      return;
    }
    if (action === "retryFailed") {
      goView("catalog");
      setTimeout(() => {
        if (typeof window.switchCatalogTab === "function") window.switchCatalogTab("batches");
      }, 50);
      return;
    }
    const view = QUICK_VIEWS[action];
    if (view) goView(view);
  }

  window.loadFactoryDashboard = loadFactoryDashboard;
  window.factoryDashQuick = factoryDashQuick;
  window.factoryDashConnect = connectEvents;

  if (document.getElementById("view-dashboard")?.classList.contains("active")) {
    loadFactoryDashboard();
    connectEvents();
  }
})();
