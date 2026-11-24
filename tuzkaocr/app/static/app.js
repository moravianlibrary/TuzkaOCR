"use strict";

const KEY = new URLSearchParams(location.search).get("k") || "";

const STRINGS = {
  en: {
    places: "Places",
    drives: "Drives",
    home: "Home",
    desktop: "Desktop",
    documents: "Documents",
    downloads: "Downloads",
    pictures: "Pictures",
    up: "Parent folder",
    change: "Change…",
    outputDefault: "Results go to a TuzkaOCR folder inside the folder with the scans.",
    outputCustom: "You chose this folder, so results from every scan folder go here.",
    outputReset: "Go back to the default",
    pickerTitle: "Choose the results folder",
    pickerEmpty: "No folders inside this one.",
    newFolder: "New folder",
    newFolderName: "OCR results",
    create: "Create",
    cancel: "Cancel",
    chooseFolder: "Use this folder",
    errExists: "A folder with this name already exists.",
    errBadName: "Choose a different name.",
    errReadOnly: "You cannot save to this folder.",
    selectAll: "Select all",
    selectNone: "Clear selection",
    colName: "Name",
    colSize: "Size",
    colStatus: "Status",
    material: "Document type",
    m_print: ["Printed", "Books, newspapers, typescripts"],
    m_handwritten: ["Handwriting", "Letters, chronicles, registers; Latin script and Kurrent"],
    m_kramarky: ["Broadside ballads", "Only Czech kramářské tisky; use Printed for other prints"],
    m_custom: "Custom model",
    formats: "Save as",
    fTxt: "Plain text",
    fAltoSub: "Text with the position of every word, for digital libraries",
    output: "Results folder",
    outputFallback: "This folder is read-only, so the results go to your Documents folder.",
    start: n => n === 1 ? "Read 1 page" : `Read ${n} pages`,
    startNone: "Read pages",
    hintSelect: "Tick the pages you want to read, or choose Select all.",
    hintAllRead: "Every page here has been read already. Tick pages to read them again.",
    hintNoImages: "Open a folder that contains scans.",
    hintFormats: "Choose at least one format.",
    hintBusy: "Wait until the current pages are finished.",
    selected: (n, total) => `${n} of ${total} selected`,
    readEarlier: n => `${n} read earlier`,
    folders: n => n === 1 ? "1 folder" : `${n} folders`,
    scans: n => n === 1 ? "1 scan" : `${n} scans`,
    stLoading: "Preparing",
    stRunning: "Reading",
    stDone: "Finished",
    stStopped: "Stopped",
    stError: "Could not start",
    loadingDetail: "Loading the models. The first page takes a little longer.",
    etaUnknown: "Estimating the time left…",
    etaLess: "Less than a minute left",
    eta: m => m === 1 ? "About 1 minute left" : `About ${m} minutes left`,
    stopping: "Stopping after this page…",
    doneDetail: (n, time) => `${n === 1 ? "1 page" : `${n} pages`} in ${time}`,
    stoppedDetail: (n, total) => `${n} of ${total} pages read`,
    failedDetail: n => n === 1 ? "1 page could not be read" : `${n} pages could not be read`,
    inFolder: "In",
    show: "Show",
    stop: "Stop",
    openResults: "Open folder",
    showText: "Show text",
    sWaiting: "Waiting",
    sReading: "Reading…",
    sLines: n => n === 1 ? "1 line" : `${n} lines`,
    sEmpty: "No text found",
    sEarlier: "Read earlier",
    sFailed: "Failed",
    view: "View",
    prev: "Previous page",
    next: "Next page",
    close: "Close",
    copy: "Copy text",
    copied: "Copied",
    noText: "This page has no recognised text.",
    emptyTitle: "No scans in this folder",
    emptyBody: "TuzkaOCR reads JPG, PNG and TIFF images. Open a folder that contains them.",
    noAccessTitle: "This folder cannot be opened",
    noAccessBody: "Your account does not have permission to read it.",
    notFoundTitle: "This folder no longer exists",
    notFoundBody: "It may have been moved, renamed or disconnected.",
    offline: "TuzkaOCR has stopped. To continue, open a terminal, type <code>tuzkaocr app</code> and press Enter.",
    staleKey: "This page belongs to an earlier TuzkaOCR window. Use the link shown in the terminal, or start it again with <code>tuzkaocr app</code>.",
    errBusy: "Other pages are being read right now.",
    errWrite: "The results folder cannot be created. Choose a folder you can save to.",
    errGeneric: "Something went wrong.",
  },
  cs: {
    places: "Místa",
    drives: "Disky",
    home: "Domovská složka",
    desktop: "Plocha",
    documents: "Dokumenty",
    downloads: "Stažené soubory",
    pictures: "Obrázky",
    up: "O úroveň výš",
    change: "Změnit…",
    outputDefault: "Výsledky se ukládají do podsložky TuzkaOCR ve složce se skeny.",
    outputCustom: "Tuto složku jste vybrali sami, ukládají se do ní výsledky ze všech složek se skeny.",
    outputReset: "Vrátit výchozí",
    pickerTitle: "Vyberte složku pro výsledky",
    pickerEmpty: "V této složce nejsou žádné podsložky.",
    newFolder: "Nová složka",
    newFolderName: "Výsledky OCR",
    create: "Vytvořit",
    cancel: "Zrušit",
    chooseFolder: "Použít tuto složku",
    errExists: "Složka s tímto názvem už existuje.",
    errBadName: "Zvolte jiný název.",
    errReadOnly: "Do této složky nelze ukládat.",
    selectAll: "Vybrat vše",
    selectNone: "Zrušit výběr",
    colName: "Název",
    colSize: "Velikost",
    colStatus: "Stav",
    material: "Typ dokumentu",
    m_print: ["Tisk", "Knihy, noviny, strojopis"],
    m_handwritten: ["Rukopis", "Dopisy, kroniky, matriky; latinka i kurent"],
    m_kramarky: ["Kramářské tisky", "Jen kramářské tisky; jiné tisky čtěte jako Tisk"],
    m_custom: "Vlastní model",
    formats: "Uložit jako",
    fTxt: "Prostý text",
    fAltoSub: "Text s polohou každého slova, pro digitální knihovny",
    output: "Složka s výsledky",
    outputFallback: "Do této složky nelze zapisovat, výsledky se proto uloží do složky Dokumenty.",
    start: n => `Přečíst ${n} ${cs(n, "stranu", "strany", "stran")}`,
    startNone: "Přečíst strany",
    hintSelect: "Zaškrtněte strany, které chcete přečíst, nebo zvolte Vybrat vše.",
    hintAllRead: "Všechny strany v této složce už jsou přečtené. Chcete-li je přečíst znovu, zaškrtněte je.",
    hintNoImages: "Otevřete složku se skeny.",
    hintFormats: "Vyberte alespoň jeden formát.",
    hintBusy: "Počkejte, až se dočtou rozpracované strany.",
    selected: (n, total) => `Vybráno ${n} z ${total}`,
    readEarlier: n => `Dříve přečteno: ${n}`,
    folders: n => `${n} ${cs(n, "složka", "složky", "složek")}`,
    scans: n => `${n} ${cs(n, "sken", "skeny", "skenů")}`,
    stLoading: "Připravuji",
    stRunning: "Čtu",
    stDone: "Hotovo",
    stStopped: "Zastaveno",
    stError: "Nepodařilo se spustit",
    loadingDetail: "Načítám modely. První strana trvá o něco déle.",
    etaUnknown: "Odhaduji zbývající čas…",
    etaLess: "Zbývá méně než minuta",
    eta: m => `Zbývá asi ${m} ${cs(m, "minuta", "minuty", "minut")}`,
    stopping: "Zastavím po této straně…",
    doneDetail: (n, time) => `${n} ${cs(n, "strana", "strany", "stran")} za ${time}`,
    stoppedDetail: (n, total) => `Přečteno ${n} z ${total}`,
    failedDetail: n => `${n} ${cs(n, "stranu", "strany", "stran")} se nepodařilo přečíst`,
    inFolder: "Ve složce",
    show: "Zobrazit",
    stop: "Zastavit",
    openResults: "Otevřít složku",
    showText: "Zobrazit text",
    sWaiting: "Čeká",
    sReading: "Čtu…",
    sLines: n => `${n} ${cs(n, "řádek", "řádky", "řádků")}`,
    sEmpty: "Bez textu",
    sEarlier: "Přečteno",
    sFailed: "Chyba",
    view: "Zobrazit",
    prev: "Předchozí strana",
    next: "Další strana",
    close: "Zavřít",
    copy: "Kopírovat text",
    copied: "Zkopírováno",
    noText: "Na této straně nebyl rozpoznán žádný text.",
    emptyTitle: "V této složce nejsou žádné skeny",
    emptyBody: "TuzkaOCR čte obrázky JPG, PNG a TIFF. Otevřete složku, ve které jsou.",
    noAccessTitle: "Tuto složku nelze otevřít",
    noAccessBody: "Váš účet k ní nemá oprávnění.",
    notFoundTitle: "Tato složka už neexistuje",
    notFoundBody: "Mohla být přesunuta, přejmenována nebo odpojena.",
    offline: "TuzkaOCR už neběží. Chcete-li pokračovat, otevřete terminál, napište <code>tuzkaocr app</code> a stiskněte Enter.",
    staleKey: "Tato stránka patří k dřívějšímu spuštění TuzkaOCR. Použijte odkaz z terminálu, nebo program spusťte znovu příkazem <code>tuzkaocr app</code>.",
    errBusy: "Právě se čtou jiné strany.",
    errWrite: "Složku s výsledky nelze vytvořit. Vyberte složku, do které můžete ukládat.",
    errGeneric: "Něco se pokazilo.",
  },
};

function cs(n, one, few, many) {
  if (n === 1) return one;
  if (n >= 2 && n <= 4) return few;
  return many;
}

const state = {
  lang: "en",
  info: null,
  folder: null,
  folderError: null,
  selected: new Set(),
  anchor: null,
  material: null,
  job: null,
  polling: null,
  stopping: false,
  viewer: { names: [], index: 0 },
  sort: { key: "name", dir: 1 },
  output: null,
  picker: null,
};

const $ = id => document.getElementById(id);

function t(key, ...args) {
  const table = STRINGS[state.lang] || STRINGS.en;
  const value = key in table ? table[key] : STRINGS.en[key];
  return typeof value === "function" ? value(...args) : value;
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function icon(name) {
  return `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) {
    return null;
  }
  return null;
}

function pickLang() {
  const saved = storage("tuzkaocr.lang");
  if (saved && STRINGS[saved]) return saved;
  const langs = navigator.languages || [navigator.language || "en"];
  return langs.some(l => /^(cs|sk)\b/i.test(l)) ? "cs" : "en";
}


class ApiError extends Error {
  constructor(code, detail, status) {
    super(code);
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

async function api(path, body) {
  let res;
  try {
    res = await fetch(`/api/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-TuzkaOCR-Key": KEY, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    showBanner("offline");
    throw new ApiError("offline");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const code = (data && data.error) || "internal";
    if (code === "forbidden") showBanner("staleKey");
    throw new ApiError(code, data && data.detail, res.status);
  }
  hideBanner();
  return data;
}

function mediaUrl(path, extra) {
  const q = new URLSearchParams({ path, k: KEY, ...(extra || {}) });
  return `/api/thumb?${q}`;
}

let bannerKind = null;

function showBanner(kind) {
  bannerKind = kind;
  const el = $("banner");
  el.innerHTML = t(kind);
  el.hidden = false;
  stopPolling();
}

function hideBanner() {
  if (!bannerKind) return;
  bannerKind = null;
  $("banner").hidden = true;
}


function number(n, digits = 0) {
  return new Intl.NumberFormat(state.lang, { maximumFractionDigits: digits }).format(n);
}

function fileSize(bytes) {
  if (bytes < 1024 * 1024) return `${number(Math.max(1, Math.round(bytes / 1024)))} kB`;
  return `${number(bytes / 1024 / 1024, 1)} MB`;
}

function duration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 ? `${m} min ${s % 60} s` : `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}

function etaText(eta) {
  if (eta === null || eta === undefined) return t("etaUnknown");
  if (eta < 55) return t("etaLess");
  return t("eta", Math.ceil(eta / 60));
}


function applyLang() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll("[data-t]").forEach(el => { el.textContent = t(el.dataset.t); });
  document.querySelectorAll("[data-tt]").forEach(el => {
    el.title = t(el.dataset.tt);
    el.setAttribute("aria-label", t(el.dataset.tt));
  });
  document.querySelectorAll(".lang button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
  if (bannerKind) $("banner").innerHTML = t(bannerKind);
  if (state.info) {
    renderPlaces();
    renderMaterials();
  }
  renderList();
  renderPanel();
}


function renderPlaces() {
  const current = state.folder ? state.folder.path : null;
  const item = (label, path, ico) =>
    `<li><button type="button" data-path="${esc(path)}" ${path === current ? 'aria-current="true"' : ""} title="${esc(path)}">${icon(ico)}<span class="label">${esc(label)}</span></button></li>`;
  $("places").innerHTML = state.info.places.map(p => item(t(p.key), p.path, p.key)).join("");
  $("drives").innerHTML = state.info.drives.map(d => item(d.name, d.path, "drive")).join("");
  $("drives-title").hidden = state.info.drives.length === 0;
}


function renderMaterials() {
  const html = state.info.materials.map(m => {
    let title, sub, tip = "";
    if (m.builtin) {
      [title, sub] = t(`m_${m.key}`);
    } else {
      const base = { print: "print", kramarky: "kramarky", handwritten: "handwritten" }[m.base];
      title = m.title || m.key;
      sub = m.description || (base ? `${t("m_custom")} · ${t(`m_${base}`)[0]}` : t("m_custom"));
      tip = `${t("m_custom")}: ${m.key} ${m.version || ""}`.trim();
    }
    const checked = m.key === state.material ? "checked" : "";
    return `<label class="option"${tip ? ` title="${esc(tip)}"` : ""}>
      <input type="radio" name="material" value="${esc(m.key)}" ${checked}>
      <span class="box"></span>
      <span class="option-text"><span class="option-title">${esc(title)}</span><span class="option-sub">${esc(sub)}</span></span>
    </label>`;
  }).join("");
  $("materials").innerHTML = html;
}


function listQuery(path) {
  return new URLSearchParams(state.output ? { path, output: state.output } : { path });
}

async function openFolder(path, push = true) {
  try {
    const data = await api(`list?${listQuery(path)}`);
    const previous = state.folder;
    state.folder = data;
    state.folderError = null;
    if (!previous || previous.path !== data.path) state.selected = new Set();
    const names = new Set(data.images.map(i => i.name));
    state.selected = new Set([...state.selected].filter(n => names.has(n)));
    state.anchor = null;
    storage("tuzkaocr.folder", data.path);
    if (push && decodeURIComponent(location.hash.slice(1)) !== data.path) {
      history.pushState(null, "", `#${encodeURIComponent(data.path)}`);
    }
  } catch (e) {
    if (e.code === "offline" || e.code === "forbidden") return;
    state.folderError = e.code === "no_access" ? "noAccess" : "notFound";
    state.folder = state.folder && e.code === "no_access"
      ? state.folder
      : { path, name: path, parent: null, crumbs: [], dirs: [], images: [], output: "", output_is_fallback: false };
    if (e.code !== "no_access") state.folder.images = [];
  }
  renderPlaces();
  renderList();
  renderPanel();
  $("list").scrollTop = 0;
}

function visibleCrumbs(folder) {
  const crumbs = folder ? folder.crumbs.slice() : [];
  const home = state.info ? state.info.home : null;
  const at = crumbs.findIndex(c => c.path === home);
  let items = at >= 0 ? [{ ...crumbs[at], name: t("home") }, ...crumbs.slice(at + 1)] : crumbs;
  if (items.length > 5) {
    items = [items[0], { gap: true, path: items[items.length - 4].path }, ...items.slice(-3)];
  }
  return items;
}

function renderCrumbs() {
  $("crumbs").innerHTML = visibleCrumbs(state.folder).map((c, i) =>
    `<li>${i ? icon("chev") : ""}<button type="button" data-path="${esc(c.path)}" title="${esc(c.path)}">${c.gap ? "…" : esc(c.name)}</button></li>`
  ).join("");
  $("up").disabled = !(state.folder && state.folder.parent);
}

function jobForFolder() {
  const job = state.job;
  return job && state.folder && job.folder === state.folder.path ? job : null;
}

function statusOf(image) {
  const job = jobForFolder();
  if (job) {
    const r = job.results[image.name];
    if (r) {
      if (!r.ok) return { kind: "failed", error: r.error };
      return { kind: "done", lines: r.lines, empty: r.empty };
    }
    if (job.current === image.name && (job.state === "running" || job.state === "loading")) return { kind: "reading" };
    if ((job.state === "running" || job.state === "loading") && job.files.includes(image.name)) return { kind: "waiting" };
  }
  if (image.done) return { kind: "earlier" };
  return { kind: "none" };
}

function statusHtml(s) {
  switch (s.kind) {
    case "reading": return `<span class="status reading"><span class="dot"></span>${t("sReading")}</span>`;
    case "waiting": return `<span class="status"><span class="dot"></span>${t("sWaiting")}</span>`;
    case "done": return `<span class="status done">${icon("check")}${s.empty ? t("sEmpty") : t("sLines", s.lines)}<button type="button" class="view">${t("view")}</button></span>`;
    case "earlier": return `<span class="status earlier">${icon("check")}${t("sEarlier")}<button type="button" class="view">${t("view")}</button></span>`;
    case "failed": return `<span class="status failed" title="${esc(s.error || "")}">${icon("alert")}${t("sFailed")}</span>`;
    default: return `<span class="status"></span>`;
  }
}

function collator() {
  return new Intl.Collator(state.lang, { numeric: true, sensitivity: "base" });
}

const STATUS_RANK = { none: 0, waiting: 1, reading: 2, failed: 3, earlier: 4, done: 5 };

function sortedImages() {
  if (!state.folder) return [];
  const byName = collator().compare;
  const { key, dir } = state.sort;
  const value = img => key === "size" ? img.size : STATUS_RANK[statusOf(img).kind];
  return state.folder.images.slice().sort((a, b) => {
    if (key !== "name") {
      const diff = value(a) - value(b);
      if (diff) return diff * dir;
      return byName(a.name, b.name);
    }
    return byName(a.name, b.name) * dir;
  });
}

function sortedDirs() {
  const byName = collator().compare;
  const dir = state.sort.key === "name" ? state.sort.dir : 1;
  return state.folder.dirs.slice().sort((a, b) => byName(a.name, b.name) * dir);
}

function renderSortHeaders() {
  document.querySelectorAll(".listhead .sort").forEach(b => {
    if (b.dataset.sort === state.sort.key) {
      b.setAttribute("aria-sort", state.sort.dir === 1 ? "ascending" : "descending");
    } else {
      b.removeAttribute("aria-sort");
    }
  });
}

function renderList() {
  renderSortHeaders();
  renderCrumbs();
  const list = $("list");
  const folder = state.folder;
  if (!folder) {
    list.innerHTML = "";
    $("listhead").hidden = true;
    $("listfoot").textContent = "";
    return;
  }
  if (state.folderError) {
    const k = state.folderError;
    list.innerHTML = `<div class="empty"><strong>${t(k + "Title")}</strong>${t(k + "Body")}</div>`;
    $("listhead").hidden = true;
    $("listfoot").textContent = "";
    return;
  }
  const dirs = sortedDirs().map(d =>
    `<div class="row dir" data-path="${esc(d.path)}" role="button" tabindex="0">
      <span></span><span class="dir-icon">${icon("folder")}</span><span class="name">${esc(d.name)}</span>
    </div>`).join("");
  const images = sortedImages().map(img => {
    const sel = state.selected.has(img.name);
    return `<div class="row image${sel ? " selected" : ""}" data-name="${esc(img.name)}">
      <label class="check"><input type="checkbox" ${sel ? "checked" : ""} aria-label="${esc(img.name)}"><span></span></label>
      <img class="thumb" loading="lazy" decoding="async" alt="" src="${mediaUrl(img.path, { m: img.mtime })}" onerror="this.onerror=null;this.classList.add('broken');this.src='data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=='">
      <span class="name" title="${esc(img.name)}">${esc(img.name)}</span>
      <span class="size">${fileSize(img.size)}</span>
      ${statusHtml(statusOf(img))}
    </div>`;
  }).join("");
  if (!dirs && !images) {
    list.innerHTML = `<div class="empty"><strong>${t("emptyTitle")}</strong>${t("emptyBody")}</div>`;
  } else {
    list.innerHTML = dirs + images;
  }
  $("listhead").hidden = folder.images.length === 0;
  updateSelectionUi();
}

function updateStatuses() {
  if (!state.folder || state.folderError) return;
  const byName = new Map(state.folder.images.map(i => [i.name, i]));
  document.querySelectorAll(".row.image").forEach(row => {
    const img = byName.get(row.dataset.name);
    if (!img) return;
    const html = statusHtml(statusOf(img));
    const old = row.querySelector(".status");
    if (old.outerHTML !== html) old.outerHTML = html;
  });
}

function updateSelectionUi() {
  const folder = state.folder;
  if (!folder) return;
  const total = folder.images.length;
  const n = state.selected.size;
  const all = $("select-all");
  all.checked = total > 0 && n === total;
  all.indeterminate = n > 0 && n < total;
  const toggle = $("toggle-all");
  toggle.hidden = total === 0;
  toggle.textContent = total > 0 && n === total ? t("selectNone") : t("selectAll");
  document.querySelectorAll(".row.image").forEach(row => {
    const sel = state.selected.has(row.dataset.name);
    row.classList.toggle("selected", sel);
    row.querySelector("input").checked = sel;
  });
  const parts = [];
  if (folder.dirs.length) parts.push(t("folders", folder.dirs.length));
  if (total) {
    parts.push(t("scans", total));
    parts.push(t("selected", n, total));
    const earlier = folder.images.filter(i => i.done).length;
    if (earlier) parts.push(t("readEarlier", earlier));
  }
  $("listfoot").innerHTML = parts.map(p => `<span>${esc(p)}</span>`).join("");
  renderPanel();
}

function toggleImage(name, shift) {
  const names = sortedImages().map(i => i.name);
  if (shift && state.anchor && names.includes(state.anchor)) {
    const a = names.indexOf(state.anchor);
    const b = names.indexOf(name);
    const on = !state.selected.has(name);
    names.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(n => on ? state.selected.add(n) : state.selected.delete(n));
  } else if (state.selected.has(name)) {
    state.selected.delete(name);
  } else {
    state.selected.add(name);
  }
  state.anchor = name;
  updateSelectionUi();
}


function formats() {
  return [...document.querySelectorAll('input[name="format"]:checked')].map(i => i.value);
}

function active(job) {
  return job && (job.state === "running" || job.state === "loading");
}

function renderPanel() {
  const folder = state.folder;
  const job = state.job;
  const out = $("output-path");
  const outPath = folder && !state.folderError ? folder.output : "";
  out.textContent = outPath ? `\u200e${outPath}\u200e` : "—";
  out.title = outPath;
  $("output-note").hidden = !(folder && folder.output_is_fallback);
  $("output-custom").hidden = !state.output;
  $("output-default").hidden = Boolean(state.output || !folder || state.folderError || folder.output_is_fallback);

  const n = state.selected.size;
  const busy = active(job);
  const start = $("start");
  start.textContent = n ? t("start", n) : t("startNone");
  let hint = "";
  if (busy) hint = t("hintBusy");
  else if (!folder || state.folderError || folder.images.length === 0) hint = t("hintNoImages");
  else if (!formats().length) hint = t("hintFormats");
  else if (!n) hint = folder.images.every(i => i.done) ? t("hintAllRead") : t("hintSelect");
  start.disabled = Boolean(hint);
  $("start-hint").textContent = hint;
  $("idle").hidden = busy;
  document.querySelectorAll('.panel input, #output-change, #output-reset').forEach(i => { i.disabled = busy; });

  renderProgress();
}

function renderProgress() {
  const job = state.job;
  const box = $("progress");
  const elsewhere = !state.folder || !job || job.folder !== state.folder.path;
  if (!job || (elsewhere && !active(job))) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.classList.toggle("done", job.state === "done");
  box.classList.toggle("loading", job.state === "loading");
  const titles = { loading: "stLoading", running: "stRunning", done: "stDone", stopped: "stStopped", error: "stError" };
  $("progress-title").textContent = t(titles[job.state]);
  $("progress-count").textContent = job.state === "error" ? "" : `${job.done} / ${job.total}`;
  $("bar-fill").style.width = `${job.total ? (job.done / job.total) * 100 : 0}%`;

  let detail = "";
  if (job.state === "loading") detail = esc(t("loadingDetail"));
  else if (job.state === "running") detail = esc(state.stopping ? t("stopping") : etaText(job.eta));
  else if (job.state === "done") detail = esc(t("doneDetail", job.done, duration(job.elapsed)));
  else if (job.state === "stopped") detail = esc(t("stoppedDetail", job.done, job.total));
  else if (job.state === "error") detail = esc(job.message || t("errGeneric"));
  if (job.failed && !active(job)) detail += `<br><span class="failed">${esc(t("failedDetail", job.failed))}</span>`;
  $("progress-detail").innerHTML = detail;

  const where = $("progress-where");
  where.hidden = !elsewhere;
  if (elsewhere) {
    const name = job.folder.split(/[\\/]/).filter(Boolean).pop() || job.folder;
    where.innerHTML = `${esc(t("inFolder"))} <strong>${esc(name)}</strong> · <button type="button" data-goto="${esc(job.folder)}">${esc(t("show"))}</button>`;
  }

  const actions = [];
  if (active(job)) {
    actions.push(`<button type="button" class="secondary" data-action="stop" ${state.stopping ? "disabled" : ""}>${esc(t("stop"))}</button>`);
  } else if (job.state !== "error" && job.done > job.failed) {
    actions.push(`<button type="button" class="secondary" data-action="open">${icon("open")}${esc(t("openResults"))}</button>`);
    if (!elsewhere) actions.push(`<button type="button" class="secondary" data-action="text">${esc(t("showText"))}</button>`);
  }
  $("progress-actions").innerHTML = actions.join("");
}


async function startJob() {
  const folder = state.folder;
  const files = sortedImages().map(i => i.name).filter(n => state.selected.has(n));
  try {
    state.stopping = false;
    state.job = await api("start", { folder: folder.path, files, material: state.material, formats: formats(), output: state.output });
    state.selected.clear();
    updateSelectionUi();
    updateStatuses();
    startPolling();
  } catch (e) {
    const messages = { busy: "errBusy", cannot_write: "errWrite" };
    $("start-hint").textContent = t(messages[e.code] || "errGeneric");
  }
}

async function poll() {
  try {
    const job = await api("job");
    const finished = active(state.job) && !active(job);
    state.job = job;
    if (!active(job)) {
      stopPolling();
      state.stopping = false;
    }
    if (finished && state.folder && job && job.folder === state.folder.path) {
      await openFolder(state.folder.path, false);
      return;
    }
    updateStatuses();
    renderPanel();
  } catch (e) {
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  state.polling = setInterval(poll, 700);
}

function stopPolling() {
  if (state.polling) clearInterval(state.polling);
  state.polling = null;
}


function readableNames() {
  return sortedImages().filter(i => {
    const s = statusOf(i);
    return s.kind === "done" || s.kind === "earlier";
  }).map(i => i.name);
}

function openViewer(name) {
  const names = readableNames();
  if (!names.length) return;
  state.viewer = { names, index: Math.max(0, names.indexOf(name)) };
  $("viewer").hidden = false;
  document.body.style.overflow = "hidden";
  showViewerPage();
  $("viewer-close").focus();
}

async function showViewerPage() {
  const { names, index } = state.viewer;
  const name = names[index];
  const image = state.folder.images.find(i => i.name === name);
  $("viewer-title").textContent = name;
  $("viewer-pos").textContent = `${index + 1} / ${names.length}`;
  $("viewer-prev").disabled = index === 0;
  $("viewer-next").disabled = index === names.length - 1;
  $("viewer-img").src = mediaUrl(image.path, { size: "large", m: image.mtime });
  const pre = $("viewer-text");
  pre.textContent = "";
  pre.classList.remove("placeholder");
  $("viewer-copy").textContent = t("copy");
  try {
    const data = await api(`text?${new URLSearchParams(state.output ? { path: image.path, output: state.output } : { path: image.path })}`);
    if (state.viewer.names[state.viewer.index] !== name) return;
    if (data.text.trim()) {
      pre.textContent = data.text;
    } else {
      pre.textContent = t("noText");
      pre.classList.add("placeholder");
    }
    $("viewer-copy").disabled = !data.text.trim();
  } catch (e) {
    pre.textContent = t("errGeneric");
    pre.classList.add("placeholder");
  }
}

function moveViewer(step) {
  const next = state.viewer.index + step;
  if (next < 0 || next >= state.viewer.names.length) return;
  state.viewer.index = next;
  showViewerPage();
}

function closeViewer() {
  $("viewer").hidden = true;
  document.body.style.overflow = "";
  $("viewer-img").removeAttribute("src");
}

async function copyText() {
  const text = $("viewer-text").textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const range = document.createRange();
    range.selectNodeContents($("viewer-text"));
    const sel = getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.execCommand("copy");
    sel.removeAllRanges();
  }
  const btn = $("viewer-copy");
  btn.textContent = t("copied");
  setTimeout(() => { btn.textContent = t("copy"); }, 1600);
}


async function openPicker() {
  const folder = state.folder;
  const candidates = [state.output, folder && folder.output, folder && folder.path, state.info.home].filter(Boolean);
  state.picker = { path: null, data: null };
  $("picker").hidden = false;
  hideNewFolder();
  for (const path of candidates) {
    if (await pickerLoad(path)) break;
  }
  $("picker-choose").focus();
}

function closePicker() {
  $("picker").hidden = true;
  state.picker = null;
}

async function pickerLoad(path) {
  try {
    const data = await api(`list?${new URLSearchParams({ path })}`);
    state.picker = { path: data.path, data };
  } catch (e) {
    return false;
  }
  $("picker-error").textContent = "";
  renderPicker();
  return true;
}

function renderPicker() {
  const { data } = state.picker;
  const current = data.path;
  const item = (label, path, ico) =>
    `<li><button type="button" data-path="${esc(path)}" ${path === current ? 'aria-current="true"' : ""} title="${esc(path)}">${icon(ico)}<span class="label">${esc(label)}</span></button></li>`;
  const drives = state.info.drives.map(d => item(d.name, d.path, "drive")).join("");
  $("picker-places").innerHTML = `<ul>${state.info.places.map(p => item(t(p.key), p.path, p.key)).join("")}</ul>${drives ? `<ul>${drives}</ul>` : ""}`;
  $("picker-crumbs").innerHTML = visibleCrumbs(data).map((c, i) =>
    `<li>${i ? icon("chev") : ""}<button type="button" data-path="${esc(c.path)}" title="${esc(c.path)}">${c.gap ? "…" : esc(c.name)}</button></li>`
  ).join("");
  $("picker-up").disabled = !data.parent;
  const byName = collator().compare;
  const dirs = data.dirs.slice().sort((a, b) => byName(a.name, b.name));
  $("picker-list").innerHTML = dirs.length
    ? dirs.map(d => `<div class="row dir" data-path="${esc(d.path)}" role="button" tabindex="0"><span class="dir-icon">${icon("folder")}</span><span class="name">${esc(d.name)}</span></div>`).join("")
    : `<div class="empty">${esc(t("pickerEmpty"))}</div>`;
  $("picker-list").scrollTop = 0;
  $("picker-choose").disabled = !data.writable;
  $("picker-error").textContent = data.writable ? "" : t("errReadOnly");
}

function hideNewFolder() {
  $("newfolder-form").hidden = true;
  $("newfolder-open").hidden = false;
}

async function createFolder(e) {
  e.preventDefault();
  const name = $("newfolder-name").value.trim();
  if (!name) return;
  try {
    const data = await api("mkdir", { parent: state.picker.path, name });
    hideNewFolder();
    await pickerLoad(data.path);
  } catch (err) {
    const messages = { exists: "errExists", bad_name: "errBadName", no_access: "errReadOnly" };
    $("picker-error").textContent = t(messages[err.code] || "errGeneric");
  }
}

async function setOutput(path) {
  state.output = path;
  storage("tuzkaocr.output", path || "");
  if (state.folder && !state.folderError) {
    const keep = state.selected;
    await openFolder(state.folder.path, false);
    state.selected = keep;
    updateSelectionUi();
  } else {
    renderPanel();
  }
}

function bindPicker() {
  $("output-change").addEventListener("click", openPicker);
  $("output-reset").addEventListener("click", () => setOutput(null));
  $("picker-close").addEventListener("click", closePicker);
  $("picker-cancel").addEventListener("click", closePicker);
  $("picker").addEventListener("mousedown", e => { if (e.target === $("picker")) closePicker(); });
  $("picker-up").addEventListener("click", () => { if (state.picker.data.parent) pickerLoad(state.picker.data.parent); });
  for (const id of ["picker-places", "picker-crumbs", "picker-list"]) {
    $(id).addEventListener("click", e => {
      const target = e.target.closest("[data-path]");
      if (target) pickerLoad(target.dataset.path);
    });
  }
  $("picker-list").addEventListener("keydown", e => {
    const target = e.target.closest("[data-path]");
    if (target && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      pickerLoad(target.dataset.path);
    }
  });
  $("picker-choose").addEventListener("click", async () => {
    const path = state.picker.path;
    closePicker();
    await setOutput(path);
  });
  $("newfolder-open").addEventListener("click", () => {
    $("newfolder-open").hidden = true;
    $("newfolder-form").hidden = false;
    const input = $("newfolder-name");
    input.value = t("newFolderName");
    input.focus();
    input.select();
  });
  $("newfolder-form").addEventListener("submit", createFolder);
  $("newfolder-name").addEventListener("keydown", e => {
    if (e.key === "Escape") {
      e.stopPropagation();
      hideNewFolder();
    }
  });
}

function bind() {
  bindPicker();
  document.querySelector(".listhead").addEventListener("click", e => {
    const b = e.target.closest("button[data-sort]");
    if (!b) return;
    const key = b.dataset.sort;
    state.sort = state.sort.key === key ? { key, dir: -state.sort.dir } : { key, dir: 1 };
    storage("tuzkaocr.sort", `${state.sort.key}:${state.sort.dir}`);
    renderList();
  });

  document.querySelector(".lang").addEventListener("click", e => {
    const b = e.target.closest("button[data-lang]");
    if (!b) return;
    state.lang = b.dataset.lang;
    storage("tuzkaocr.lang", state.lang);
    applyLang();
  });

  $("up").addEventListener("click", () => { if (state.folder && state.folder.parent) openFolder(state.folder.parent); });

  for (const id of ["places", "drives", "crumbs"]) {
    $(id).addEventListener("click", e => {
      const b = e.target.closest("button[data-path]");
      if (b && !(id === "crumbs" && b.parentElement === $("crumbs").lastElementChild)) openFolder(b.dataset.path);
    });
  }

  const list = $("list");
  list.addEventListener("click", e => {
    const dir = e.target.closest(".row.dir");
    if (dir) return openFolder(dir.dataset.path);
    const row = e.target.closest(".row.image");
    if (!row) return;
    if (e.target.closest(".view")) return openViewer(row.dataset.name);
    if (e.target.closest(".check") && e.target.tagName !== "INPUT") return;
    toggleImage(row.dataset.name, e.shiftKey);
  });
  list.addEventListener("keydown", e => {
    const dir = e.target.closest(".row.dir");
    if (dir && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openFolder(dir.dataset.path);
    }
  });
  list.addEventListener("dblclick", e => {
    const row = e.target.closest(".row.image");
    if (!row) return;
    const s = statusOf(state.folder.images.find(i => i.name === row.dataset.name));
    if (s.kind === "done" || s.kind === "earlier") openViewer(row.dataset.name);
  });

  $("toggle-all").addEventListener("click", () => {
    const all = state.selected.size === state.folder.images.length;
    state.selected = all ? new Set() : new Set(state.folder.images.map(i => i.name));
    updateSelectionUi();
  });

  $("select-all").addEventListener("change", e => {
    state.selected = e.target.checked ? new Set(state.folder.images.map(i => i.name)) : new Set();
    updateSelectionUi();
  });

  $("materials").addEventListener("change", e => {
    state.material = e.target.value;
    storage("tuzkaocr.material", state.material);
  });
  document.querySelectorAll('input[name="format"]').forEach(i => i.addEventListener("change", () => {
    storage("tuzkaocr.formats", formats().join(","));
    renderPanel();
  }));

  $("start").addEventListener("click", startJob);

  $("progress").addEventListener("click", async e => {
    const go = e.target.closest("[data-goto]");
    if (go) return openFolder(go.dataset.goto);
    const b = e.target.closest("[data-action]");
    if (!b) return;
    if (b.dataset.action === "stop") {
      state.stopping = true;
      renderProgress();
      try { await api("stop", {}); } catch (err) { state.stopping = false; }
    } else if (b.dataset.action === "open") {
      try { await api("open", { path: state.job.output }); } catch (err) { return; }
    } else if (b.dataset.action === "text") {
      const first = state.job.files.find(n => state.job.results[n] && state.job.results[n].ok);
      if (first) openViewer(first);
    }
  });

  $("viewer-close").addEventListener("click", closeViewer);
  $("viewer-prev").addEventListener("click", () => moveViewer(-1));
  $("viewer-next").addEventListener("click", () => moveViewer(1));
  $("viewer-copy").addEventListener("click", copyText);

  document.addEventListener("keydown", e => {
    if (!$("picker").hidden) {
      if (e.key === "Escape") closePicker();
      return;
    }
    if ($("viewer").hidden) {
      if (e.key === "Backspace" && !e.target.closest("input") && state.folder && state.folder.parent) {
        e.preventDefault();
        openFolder(state.folder.parent);
      }
      return;
    }
    if (e.key === "Escape") closeViewer();
    else if (e.key === "ArrowLeft") moveViewer(-1);
    else if (e.key === "ArrowRight") moveViewer(1);
  });

  window.addEventListener("popstate", () => {
    const path = decodeURIComponent(location.hash.slice(1));
    if (path) openFolder(path, false);
  });
}


async function boot() {
  state.lang = pickLang();
  const savedSort = (storage("tuzkaocr.sort") || "").split(":");
  if (["name", "size", "status"].includes(savedSort[0])) state.sort = { key: savedSort[0], dir: savedSort[1] === "-1" ? -1 : 1 };
  state.output = storage("tuzkaocr.output") || null;
  bind();
  applyLang();
  let info;
  try {
    info = await api("info");
  } catch (e) {
    return;
  }
  state.info = info;
  $("version").textContent = info.version;
  const savedMaterial = storage("tuzkaocr.material");
  state.material = info.materials.some(m => m.key === savedMaterial) ? savedMaterial : info.default_material;
  const savedFormats = storage("tuzkaocr.formats");
  if (savedFormats) {
    const wanted = savedFormats.split(",");
    document.querySelectorAll('input[name="format"]').forEach(i => { i.checked = wanted.includes(i.value); });
  }
  renderPlaces();
  renderMaterials();
  try {
    state.job = await api("job");
  } catch (e) {
    state.job = null;
  }
  if (active(state.job)) startPolling();
  const start = decodeURIComponent(location.hash.slice(1)) || storage("tuzkaocr.folder") || info.start;
  await openFolder(start, false);
  if (state.folderError && start !== info.start) await openFolder(info.start, false);
  history.replaceState(null, "", `#${encodeURIComponent(state.folder.path)}`);
}

boot();
