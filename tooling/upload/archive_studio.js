/* Aethelgard Archive Studio UI — dedicated bulk sourcing feature */
(function () {
  const TABS = [
    ["search", "Search / Import"],
    ["library", "Library"],
    ["collections", "Collections"],
    ["queue", "Processing Queue"],
    ["pipeline", "Listing Pipeline"],
    ["drive", "Drive Sync"],
    ["sources", "Sources"],
    ["rules", "Automation"],
  ];

  const state = {
    tab: "search",
    sources: [],
    enabledSources: [],
    results: [],
    searchMeta: null,
    selected: new Set(),
    library: [],
    libraryTotal: 0,
    libraryOffset: 0,
    collections: [],
    jobs: [],
    rules: [],
    stats: {},
    drive: {},
    settings: {},
    focus: null,
    q: "",
    libQ: "",
    rights: "public_domain,cc0",
    orientation: "",
    minWidth: "",
    artworkType: "",
    collectionId: "",
    packName: "",
    busy: false,
    mounted: false,
  };

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  async function api(path, opts) {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok && data && data.error) throw new Error(data.error);
    return data;
  }

  function toast(msg) {
    if (typeof showToast === "function") showToast(msg);
    else if (typeof window.toast === "function") window.toast(msg);
    else console.log("[archive]", msg);
  }

  function thumbUrl(rec) {
    if (rec.id) return `/api/archive/assets/${encodeURIComponent(rec.id)}/thumbnail`;
    const url = rec.thumbnail_url || rec.source_image_url || rec.image || rec.image_small;
    if (!url) return "";
    if (url.startsWith("/")) return url;
    return `/api/archive/proxy-image?url=${encodeURIComponent(url)}`;
  }

  function recordKey(rec) {
    return rec.id || `${rec.source}:${rec.source_object_id || rec.object_id}`;
  }

  function rightsClass(status) {
    if (status === "cc0" || status === "public_domain") return status === "cc0" ? "cc0" : "pd";
    if (status === "restricted") return "restricted";
    return "unclear";
  }

  function selectedRecords(fromLibrary) {
    const pool = fromLibrary ? state.library : state.results;
    return pool.filter((r) => state.selected.has(recordKey(r)));
  }

  function render() {
    const root = document.getElementById("archive-studio-root");
    if (!root) return;
    const stats = state.stats || {};
    root.innerHTML = `
      <div class="as-hero">
        <div>
          <h3>Archive Studio</h3>
          <p>Bulk public-domain acquisition engine. Search open-access museums, import metadata first, then download full-resolution files and hand selected works into the existing listing pipeline.</p>
        </div>
        <div class="as-kpis">
          <div class="as-kpi"><b>${stats.assets || 0}</b><span>Library</span></div>
          <div class="as-kpi"><b>${stats.fullres || 0}</b><span>Full-res</span></div>
          <div class="as-kpi"><b>${stats.clear_rights || 0}</b><span>Clear rights</span></div>
          <div class="as-kpi"><b>${stats.active_jobs || 0}</b><span>Jobs</span></div>
        </div>
      </div>
      <div class="as-tabs">
        ${TABS.map(([id, label]) => `<button type="button" class="as-tab ${state.tab === id ? "active" : ""}" data-tab="${id}">${label}</button>`).join("")}
      </div>
      <div id="as-body">${renderTab()}</div>
    `;
    bind(root);
  }

  function renderTab() {
    switch (state.tab) {
      case "sources":
        return renderSources();
      case "library":
        return renderLibrary();
      case "collections":
        return renderCollections();
      case "queue":
        return renderQueue();
      case "pipeline":
        return renderPipeline();
      case "drive":
        return renderDrive();
      case "rules":
        return renderRules();
      default:
        return renderSearch();
    }
  }

  function sourceChips() {
    return (state.sources || [])
      .map((s) => {
        const on = state.enabledSources.includes(s.id);
        return `<label class="as-chip ${on ? "on" : ""}"><input type="checkbox" data-source="${esc(s.id)}" ${on ? "checked" : ""}>${esc(s.short || s.name)}</label>`;
      })
      .join("");
  }

  function filterFields(prefix) {
    return `
      <label>Rights
        <select id="${prefix}Rights">
          <option value="public_domain,cc0" ${state.rights === "public_domain,cc0" ? "selected" : ""}>Public Domain + CC0</option>
          <option value="cc0" ${state.rights === "cc0" ? "selected" : ""}>CC0 only</option>
          <option value="public_domain" ${state.rights === "public_domain" ? "selected" : ""}>Public Domain only</option>
          <option value="" ${state.rights === "" ? "selected" : ""}>Any (includes unclear)</option>
        </select>
      </label>
      <label>Orientation
        <select id="${prefix}Ori">
          <option value="">Any</option>
          <option value="portrait" ${state.orientation === "portrait" ? "selected" : ""}>Portrait</option>
          <option value="landscape" ${state.orientation === "landscape" ? "selected" : ""}>Landscape</option>
          <option value="square" ${state.orientation === "square" ? "selected" : ""}>Square</option>
        </select>
      </label>
      <label>Min width
        <input type="number" id="${prefix}MinW" placeholder="1200" value="${esc(state.minWidth)}">
      </label>
      <label>Artwork type
        <input type="text" id="${prefix}Type" placeholder="Painting" value="${esc(state.artworkType)}">
      </label>
    `;
  }

  function cardGrid(items, { library } = {}) {
    if (!items.length) {
      return `<div class="as-empty">No artworks yet. Search open-access sources and import metadata first — full-resolution files download only when you ask.</div>`;
    }
    return `<div class="as-grid">${items
      .map((rec) => {
        const key = recordKey(rec);
        const sel = state.selected.has(key);
        const flags = rec.qc_flags || [];
        const src = thumbUrl(rec);
        return `<article class="as-card ${sel ? "selected" : ""}" data-key="${esc(key)}" data-lib="${library ? "1" : "0"}">
          <input class="as-check" type="checkbox" ${sel ? "checked" : ""} data-key="${esc(key)}">
          ${src ? `<img src="${esc(src)}" alt="" loading="lazy">` : `<div class="as-ph">No image</div>`}
          <div class="as-card-body">
            <h4 title="${esc(rec.title)}">${esc(rec.title || "Untitled")}</h4>
            <p>${esc(rec.artist || "")} ${rec.year ? "· " + esc(rec.year) : ""}</p>
            <div class="as-badges">
              <span class="as-badge">${esc(rec.source)}</span>
              <span class="as-badge ${rightsClass(rec.rights_status)}">${esc(rec.rights_status || "unclear")}</span>
              ${rec.processing_status ? `<span class="as-badge info">${esc(rec.processing_status)}</span>` : ""}
              ${flags.slice(0, 2).map((f) => `<span class="as-badge warn">${esc(f)}</span>`).join("")}
            </div>
          </div>
        </article>`;
      })
      .join("")}</div>`;
  }

  function sidePanel() {
    const rec = state.focus;
    if (!rec) {
      return `<aside class="as-side"><h4>Selection</h4><p class="as-muted">${state.selected.size} selected. Click a card for metadata, rights, and source URL.</p>
        <div class="as-actions" style="margin-top:12px">
          <button type="button" class="btn btn-outline" data-act="select-page">Select page</button>
          <button type="button" class="btn btn-outline" data-act="clear-sel">Clear</button>
        </div></aside>`;
    }
    const img = thumbUrl(rec);
    return `<aside class="as-side">
      ${img ? `<img class="as-preview" src="${esc(img)}" alt="">` : ""}
      <h4>${esc(rec.title || "Untitled")}</h4>
      <dl>
        <dt>Artist</dt><dd>${esc(rec.artist || "—")}</dd>
        <dt>Date</dt><dd>${esc(rec.date_display || rec.year || "—")}</dd>
        <dt>Source</dt><dd>${esc(rec.source)}</dd>
        <dt>Object</dt><dd>${esc(rec.source_object_id)}</dd>
        <dt>Rights</dt><dd>${esc(rec.licence_type || rec.rights_status || "—")}</dd>
        <dt>Medium</dt><dd>${esc(rec.medium || rec.media_type || "—")}</dd>
        <dt>Size</dt><dd>${rec.width && rec.height ? `${rec.width}×${rec.height}` : "unknown until full-res"}</dd>
        <dt>Status</dt><dd>${esc(rec.processing_status || "search hit")}</dd>
      </dl>
      ${rec.source_url ? `<p style="margin-top:8px"><a href="${esc(rec.source_url)}" target="_blank" rel="noopener">Open source page</a></p>` : ""}
      <p class="as-muted" style="margin-top:10px">Do not assume a reachable image is reusable. Prefer Public Domain / CC0 filters.</p>
    </aside>`;
  }

  function renderSearch() {
    return `
      <div class="as-toolbar">
        <label>Keyword
          <input type="search" id="asSearchQ" placeholder="still life fruit, botanical, art nouveau" value="${esc(state.q)}">
        </label>
        ${filterFields("as")}
        <button type="button" class="btn" data-act="search" ${state.busy ? "disabled" : ""}>Search sources</button>
        <button type="button" class="btn btn-outline" data-act="import-selected">Import selected metadata</button>
        <button type="button" class="btn btn-outline" data-act="ingest-job">Queue bulk ingest</button>
      </div>
      <div class="as-sources-row" style="margin:8px 0 12px">${sourceChips()}</div>
      <p class="as-muted">${state.searchMeta ? `${state.searchMeta.count || 0} results across ${(state.searchMeta.sources || []).join(", ")}` : "Metadata + thumbnails only. Full-resolution stays off until you queue a download."}</p>
      <div class="as-layout" style="margin-top:12px">
        <div>${cardGrid(state.results)}</div>
        ${sidePanel()}
      </div>
    `;
  }

  function renderLibrary() {
    return `
      <div class="as-toolbar">
        <label>Find in library
          <input type="search" id="asLibQ" value="${esc(state.libQ)}" placeholder="title, artist, id">
        </label>
        ${filterFields("asLib")}
        <label>Collection
          <select id="asLibCol">
            <option value="">All</option>
            ${(state.collections || []).map((c) => `<option value="${esc(c.id)}" ${state.collectionId === c.id ? "selected" : ""}>${esc(c.name)} (${c.asset_count || 0})</option>`).join("")}
          </select>
        </label>
        <button type="button" class="btn" data-act="lib-search">Filter</button>
      </div>
      <div class="as-actions" style="margin:10px 0">
        <button type="button" class="btn" data-act="bulk-download">Download full-res</button>
        <button type="button" class="btn btn-outline" data-act="bulk-collect">Add to collection</button>
        <button type="button" class="btn btn-outline" data-act="bulk-pipeline">Send to listing pipeline</button>
        <button type="button" class="btn btn-outline" data-act="bulk-drive">Sync to Drive</button>
        <button type="button" class="btn btn-outline" data-act="bulk-qc">Re-run QC</button>
        <button type="button" class="btn btn-outline" data-act="bulk-delete">Remove</button>
      </div>
      <p class="as-muted">${state.libraryTotal || 0} in library · ${state.selected.size} selected</p>
      <div class="as-layout" style="margin-top:12px">
        <div>${cardGrid(state.library, { library: true })}
          <div class="as-actions" style="margin-top:12px">
            <button type="button" class="btn btn-outline" data-act="lib-more" ${state.library.length >= state.libraryTotal ? "disabled" : ""}>Load more</button>
          </div>
        </div>
        ${sidePanel()}
      </div>
    `;
  }

  function renderCollections() {
    const rows = (state.collections || [])
      .map(
        (c) => `<tr>
          <td><strong>${esc(c.name)}</strong><div class="as-muted">${esc(c.description || "")}</div></td>
          <td>${c.asset_count || 0}</td>
          <td>${esc(c.drive_folder || "—")}</td>
          <td class="as-actions">
            <button type="button" class="btn btn-outline" data-act="open-col" data-id="${esc(c.id)}">Open</button>
            <button type="button" class="btn btn-outline" data-act="pipe-col" data-id="${esc(c.id)}">To pipeline</button>
            <button type="button" class="btn btn-outline" data-act="del-col" data-id="${esc(c.id)}">Delete</button>
          </td>
        </tr>`
      )
      .join("");
    return `
      <div class="as-toolbar">
        <label>New collection
          <input type="text" id="asColName" placeholder="French Country Kitchen">
        </label>
        <label>Description
          <input type="text" id="asColDesc" placeholder="optional theme notes">
        </label>
        <button type="button" class="btn" data-act="create-col">Create</button>
        <button type="button" class="btn btn-outline" data-act="bulk-collect">Assign selected library items</button>
      </div>
      <table class="as-table" style="margin-top:14px">
        <thead><tr><th>Collection</th><th>Assets</th><th>Drive folder</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="4" class="as-muted">No collections yet.</td></tr>`}</tbody>
      </table>
    `;
  }

  function renderQueue() {
    const rows = (state.jobs || [])
      .map((j) => {
        const pct = j.percentage || 0;
        return `<tr>
          <td><span class="as-badge info">${esc(j.kind)}</span></td>
          <td>${esc(j.status)}</td>
          <td><div class="as-bar"><i style="width:${pct}%"></i></div> ${j.done || 0}/${j.total || 0} · ${j.failed || 0} failed</td>
          <td>${esc(j.message || j.error || "")}</td>
          <td class="as-actions">
            <button type="button" class="btn btn-outline" data-act="retry-job" data-id="${esc(j.id)}">Retry</button>
            <button type="button" class="btn btn-outline" data-act="cancel-job" data-id="${esc(j.id)}">Cancel</button>
          </td>
        </tr>`;
      })
      .join("");
    return `
      <p class="as-muted">Jobs survive refresh. Metadata ingest, thumbnail sync, full-res download, Drive upload, and pipeline handoff all run here.</p>
      <table class="as-table" style="margin-top:12px">
        <thead><tr><th>Kind</th><th>Status</th><th>Progress</th><th>Note</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="5" class="as-muted">No jobs yet.</td></tr>`}</tbody>
      </table>
    `;
  }

  function renderPipeline() {
    return `
      <p class="as-muted">Hands selected library assets into the existing Artwork Studio public-domain pack importer (mockups, SEO, listing drafts, Drive packaging stay as they are).</p>
      <div class="as-toolbar" style="margin-top:12px">
        <label>Pack / listing name
          <input type="text" id="asPackName" placeholder="Vintage botanical prints" value="${esc(state.packName)}">
        </label>
        <label>Or collection
          <select id="asPipeCol">
            <option value="">Selected assets only</option>
            ${(state.collections || []).map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")}
          </select>
        </label>
        <button type="button" class="btn" data-act="run-pipeline">Create listing pack</button>
      </div>
      <div id="asPipeResult" style="margin-top:16px"></div>
    `;
  }

  function renderDrive() {
    const d = state.drive || {};
    const folders = (state.settings.drive_folders || {});
    return `
      <p class="as-muted">${d.connected ? `Connected${d.account_email ? " as " + esc(d.account_email) : ""}.` : "Connect Google Drive from the top bar first. Archive Studio reuses that OAuth session."}</p>
      <div class="as-toolbar" style="margin-top:12px">
        <label>Source archive <input type="text" id="asDrvSrc" value="${esc(folders.source_archive || "")}"></label>
        <label>Processed <input type="text" id="asDrvProc" value="${esc(folders.processed || "")}"></label>
        <label>Mockups <input type="text" id="asDrvMock" value="${esc(folders.mockups || "")}"></label>
        <label>SEO <input type="text" id="asDrvSeo" value="${esc(folders.seo || "")}"></label>
        <label>Listings <input type="text" id="asDrvList" value="${esc(folders.listings || "")}"></label>
        <button type="button" class="btn" data-act="save-folders">Save folder map</button>
        <button type="button" class="btn btn-outline" data-act="bulk-drive">Sync selected</button>
      </div>
    `;
  }

  function renderSources() {
    const cards = (state.sources || [])
      .map((s) => {
        const h = s.health || {};
        const cls = h.ok ? "ok" : h.needs_key ? "warn" : "bad";
        return `<article class="as-source">
          <h4><span class="as-dot ${cls}"></span>${esc(s.name)}</h4>
          <p>${esc(s.notes || "")}</p>
          <div class="as-badges">
            <span class="as-badge">${esc(s.auth)}</span>
            <span class="as-badge">${s.library_count || 0} in library</span>
            ${h.needs_key ? `<span class="as-badge warn">needs ${esc(s.env_key)}</span>` : ""}
          </div>
          <p class="as-muted" style="margin-top:8px">${esc(h.message || "")}${h.latency_ms ? " · " + h.latency_ms + "ms" : ""}</p>
        </article>`;
      })
      .join("");
    return `<div class="as-source-cards">${cards}</div>`;
  }

  function renderRules() {
    const items = (state.rules || [])
      .map(
        (r) => `<div class="as-rule">
          <strong>${esc(r.name)}</strong>
          <p class="as-muted">${esc(r.query)} · ${(r.sources || []).join(", ") || "all sources"}</p>
          <div class="as-actions">
            <button type="button" class="btn btn-outline" data-act="run-rule" data-id="${esc(r.id)}">Run</button>
            <button type="button" class="btn btn-outline" data-act="del-rule" data-id="${esc(r.id)}">Delete</button>
          </div>
        </div>`
      )
      .join("");
    return `
      <p class="as-muted">Example: import public-domain still lifes matching “fruit”, portrait orientation, then auto-tag and optionally queue full-res download.</p>
      <div class="as-toolbar">
        <label>Name <input type="text" id="asRuleName" placeholder="Rijks fruit still lifes"></label>
        <label>Query <input type="text" id="asRuleQ" placeholder="fruit still life"></label>
        <label>Sources <input type="text" id="asRuleSrc" placeholder="rijksmuseum,cleveland"></label>
        <button type="button" class="btn" data-act="create-rule">Save rule</button>
      </div>
      <div style="margin-top:14px">${items || `<div class="as-empty">No automation rules yet.</div>`}</div>
    `;
  }

  function readFilters(prefix) {
    const rights = $(`#${prefix}Rights`)?.value;
    const orientation = $(`#${prefix}Ori`)?.value;
    const minWidth = $(`#${prefix}MinW`)?.value;
    const artworkType = $(`#${prefix}Type`)?.value;
    if (rights !== undefined) state.rights = rights;
    if (orientation !== undefined) state.orientation = orientation;
    if (minWidth !== undefined) state.minWidth = minWidth;
    if (artworkType !== undefined) state.artworkType = artworkType;
    return {
      rights: state.rights,
      orientation: state.orientation,
      min_width: state.minWidth,
      media_type: state.artworkType,
      require_clear_rights: Boolean(state.rights && state.rights !== ""),
    };
  }

  function bind(root) {
    root.querySelectorAll(".as-tab").forEach((btn) => {
      btn.onclick = async () => {
        state.tab = btn.dataset.tab;
        if (state.tab === "library") await loadLibrary();
        if (state.tab === "collections") await loadCollections();
        if (state.tab === "queue") await loadJobs();
        if (state.tab === "sources") await loadSources(true);
        if (state.tab === "drive") await loadDrive();
        if (state.tab === "rules") await loadRules();
        if (state.tab === "pipeline") await loadCollections();
        render();
      };
    });
    root.querySelectorAll("[data-source]").forEach((box) => {
      box.onchange = () => {
        const id = box.dataset.source;
        if (box.checked) {
          if (!state.enabledSources.includes(id)) state.enabledSources.push(id);
        } else {
          state.enabledSources = state.enabledSources.filter((s) => s !== id);
        }
        render();
      };
    });
    root.querySelectorAll(".as-card").forEach((card) => {
      card.onclick = (ev) => {
        if (ev.target.classList.contains("as-check")) return;
        const key = card.dataset.key;
        const pool = card.dataset.lib === "1" ? state.library : state.results;
        state.focus = pool.find((r) => recordKey(r) === key) || null;
        render();
      };
    });
    root.querySelectorAll(".as-check").forEach((box) => {
      box.onclick = (ev) => ev.stopPropagation();
      box.onchange = () => {
        const key = box.dataset.key;
        if (box.checked) state.selected.add(key);
        else state.selected.delete(key);
        render();
      };
    });
    root.querySelectorAll("[data-act]").forEach((btn) => {
      btn.onclick = () => handleAction(btn.dataset.act, btn.dataset.id);
    });
    const q = $("#asSearchQ");
    if (q) q.addEventListener("keydown", (e) => {
      if (e.key === "Enter") handleAction("search");
    });
  }

  async function handleAction(act, id) {
    try {
      if (act === "search") return await doSearch();
      if (act === "import-selected") return await importSelected();
      if (act === "ingest-job") return await ingestJob();
      if (act === "select-page") {
        (state.tab === "library" ? state.library : state.results).forEach((r) => state.selected.add(recordKey(r)));
        render();
        return;
      }
      if (act === "clear-sel") {
        state.selected.clear();
        render();
        return;
      }
      if (act === "lib-search") return await loadLibrary(true);
      if (act === "lib-more") {
        state.libraryOffset += 48;
        return await loadLibrary();
      }
      if (act === "bulk-download") return await bulk("download");
      if (act === "bulk-pipeline") return await bulk("pipeline");
      if (act === "bulk-drive") return await bulk("drive");
      if (act === "bulk-qc") return await bulk("qc");
      if (act === "bulk-delete") return await bulk("delete");
      if (act === "bulk-collect") return await assignCollection();
      if (act === "create-col") return await createCollection();
      if (act === "open-col") {
        state.collectionId = id;
        state.tab = "library";
        await loadLibrary(true);
        render();
        return;
      }
      if (act === "pipe-col") return await runPipeline(id);
      if (act === "del-col") {
        await api(`/api/archive/collections/${id}/delete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        await loadCollections();
        render();
        return;
      }
      if (act === "retry-job") {
        await api(`/api/archive/jobs/${id}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        await loadJobs();
        render();
        return;
      }
      if (act === "cancel-job") {
        await api(`/api/archive/jobs/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        await loadJobs();
        render();
        return;
      }
      if (act === "run-pipeline") return await runPipeline($("#asPipeCol")?.value);
      if (act === "save-folders") return await saveFolders();
      if (act === "create-rule") return await createRule();
      if (act === "run-rule") {
        await api(`/api/archive/rules/${id}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        toast("Rule queued");
        state.tab = "queue";
        await loadJobs();
        render();
        return;
      }
      if (act === "del-rule") {
        await api(`/api/archive/rules/${id}/delete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        await loadRules();
        render();
      }
    } catch (e) {
      alert(e.message || String(e));
    }
  }

  async function doSearch() {
    state.q = $("#asSearchQ")?.value || state.q;
    const filters = readFilters("as");
    state.busy = true;
    render();
    try {
      const params = new URLSearchParams({
        q: state.q,
        sources: state.enabledSources.join(","),
        limit: "36",
        offset: "0",
        rights: filters.rights || "",
        orientation: filters.orientation || "",
        media_type: filters.media_type || "",
        min_width: filters.min_width || "",
        has_image: "true",
      });
      const data = await api(`/api/archive/search?${params}`);
      state.results = data.results || [];
      state.searchMeta = data;
      state.selected.clear();
      toast(`Found ${state.results.length} records`);
    } finally {
      state.busy = false;
      render();
    }
  }

  async function importSelected() {
    const recs = selectedRecords(false);
    if (!recs.length) {
      alert("Select search results first.");
      return;
    }
    const data = await api("/api/archive/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records: recs, skip_duplicates: true, sync_thumbs: true, require_clear_rights: Boolean(state.rights) }),
    });
    toast(`Imported ${data.created || 0} new · ${data.skipped || 0} already in library`);
    await loadStats();
  }

  async function ingestJob() {
    state.q = $("#asSearchQ")?.value || state.q;
    const filters = readFilters("as");
    const max = prompt("How many metadata records to ingest? (thumbnails, not full-res)", "120");
    if (!max) return;
    const data = await api("/api/archive/import/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: state.q,
        sources: state.enabledSources,
        filters,
        max_records: parseInt(max, 10) || 100,
        skip_duplicates: true,
        sync_thumbs: true,
      }),
    });
    toast("Bulk ingest queued");
    state.tab = "queue";
    await loadJobs();
    render();
    return data;
  }

  function selectedIds() {
    return state.library.filter((r) => state.selected.has(recordKey(r))).map((r) => r.id).filter(Boolean);
  }

  async function bulk(action) {
    const ids = selectedIds();
    if (!ids.length) {
      alert("Select library items first (Library tab).");
      return;
    }
    if (action === "delete" && !confirm(`Remove ${ids.length} assets from the archive library? Files on Drive are not deleted.`)) return;
    const body = { ids, action, concept: state.packName || state.q };
    const data = await api("/api/archive/assets/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    toast(data.job ? `Queued ${action}` : `${action} done`);
    if (data.job) {
      state.tab = "queue";
      await loadJobs();
    }
    await loadLibrary(true);
    render();
  }

  async function assignCollection() {
    const ids = selectedIds();
    if (!ids.length) {
      alert("Select library items first.");
      return;
    }
    await loadCollections();
    const name = prompt("Collection name (existing or new)", (state.collections[0] || {}).name || "New collection");
    if (!name) return;
    let col = (state.collections || []).find((c) => c.name.toLowerCase() === name.toLowerCase());
    if (!col) {
      const created = await api("/api/archive/collections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, asset_ids: ids }),
      });
      col = created.collection;
    } else {
      await api(`/api/archive/collections/${col.id}/assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_ids: ids }),
      });
    }
    toast(`Added to ${name}`);
    await loadCollections();
    render();
  }

  async function createCollection() {
    const name = $("#asColName")?.value?.trim();
    if (!name) return alert("Name required");
    await api("/api/archive/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: $("#asColDesc")?.value || "", asset_ids: selectedIds() }),
    });
    $("#asColName").value = "";
    await loadCollections();
    render();
  }

  async function runPipeline(collectionId) {
    state.packName = $("#asPackName")?.value || state.packName;
    const ids = selectedIds();
    const data = await api("/api/archive/pipeline/handoff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_ids: ids,
        collection_id: collectionId || "",
        concept: state.packName,
        download_missing: true,
      }),
    });
    const box = $("#asPipeResult");
    if (box) {
      box.innerHTML = data.ok
        ? `<div class="as-empty">Created pack <strong>${esc(data.pack_title)}</strong> with ${(data.candidates || []).length} files.<br>Open Artwork Studio / Catalog to generate mockups, SEO, and listing drafts. Run: <code>${esc(data.run_dir || "")}</code></div>`
        : `<div class="as-empty">${esc(data.error || "Handoff failed")}</div>`;
    }
    toast(data.ok ? "Pack created in Artwork Studio pipeline" : data.error || "Handoff failed");
  }

  async function saveFolders() {
    const drive_folders = {
      source_archive: $("#asDrvSrc")?.value,
      processed: $("#asDrvProc")?.value,
      mockups: $("#asDrvMock")?.value,
      seo: $("#asDrvSeo")?.value,
      listings: $("#asDrvList")?.value,
    };
    const data = await api("/api/archive/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ drive_folders }),
    });
    state.settings = data.settings || state.settings;
    toast("Folder map saved");
  }

  async function createRule() {
    const name = $("#asRuleName")?.value?.trim();
    const query = $("#asRuleQ")?.value?.trim();
    if (!name || !query) return alert("Name and query required");
    const sources = ($("#asRuleSrc")?.value || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    await api("/api/archive/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        query,
        sources,
        filters: { rights: ["public_domain", "cc0"], require_clear_rights: true, orientation: "portrait" },
        actions: [{ type: "tag", tags: [query] }, { type: "theme", theme: name }],
      }),
    });
    await loadRules();
    render();
  }

  async function loadSources(ping) {
    const data = await api(ping ? "/api/archive/sources?health=1" : "/api/archive/sources");
    state.sources = data.sources || [];
    if (!state.enabledSources.length) {
      state.enabledSources = state.sources.filter((s) => s.health && s.health.configured && !s.health.needs_key).map((s) => s.id);
      if (!state.enabledSources.length) state.enabledSources = state.sources.map((s) => s.id);
    }
  }

  async function loadStats() {
    const data = await api("/api/archive/stats");
    state.stats = data;
    state.settings = data.settings || state.settings;
  }

  async function loadLibrary(reset) {
    if (reset) {
      state.libraryOffset = 0;
      state.library = [];
    }
    readFilters("asLib");
    state.libQ = $("#asLibQ")?.value ?? state.libQ;
    state.collectionId = $("#asLibCol")?.value ?? state.collectionId;
    const params = new URLSearchParams({
      q: state.libQ || "",
      rights: state.rights || "",
      orientation: state.orientation || "",
      min_width: state.minWidth || "",
      collection_id: state.collectionId || "",
      limit: "48",
      offset: String(state.libraryOffset || 0),
    });
    const data = await api(`/api/archive/assets?${params}`);
    const items = data.items || [];
    state.library = state.libraryOffset ? state.library.concat(items) : items;
    state.libraryTotal = data.total || 0;
  }

  async function loadCollections() {
    const data = await api("/api/archive/collections");
    state.collections = data.collections || [];
  }

  async function loadJobs() {
    const data = await api("/api/archive/jobs");
    state.jobs = data.jobs || [];
  }

  async function loadDrive() {
    const data = await api("/api/archive/drive/status");
    state.drive = data;
    const settings = await api("/api/archive/settings");
    state.settings = settings.settings || {};
  }

  async function loadRules() {
    const data = await api("/api/archive/rules");
    state.rules = data.rules || [];
  }

  async function boot() {
    await Promise.all([loadSources(), loadStats(), loadCollections()]);
    render();
  }

  window.archiveStudioEnter = function () {
    const root = document.getElementById("archive-studio-root");
    if (!root) return;
    if (!state.mounted) {
      state.mounted = true;
      boot();
    } else {
      loadStats();
      if (state.tab === "queue") loadJobs().then(render);
      else render();
    }
  };

  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("view-archive")?.classList.contains("active")) {
      window.archiveStudioEnter();
    }
  });
})();
