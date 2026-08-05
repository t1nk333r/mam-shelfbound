// ---------- DOM lookups ----------
const form = document.getElementById('searchForm');
const q = document.getElementById('q');
const mediaTypeInputs = Array.from(document.querySelectorAll('input[name="mediaType"]'));
const kindleToggle = document.getElementById('kindleToggle');
const sendToKindleInput = document.getElementById('sendToKindle');
const perpageSel = document.getElementById('perpage');
const accountStatusEl = document.getElementById('accountStatus');
const statusEl = document.getElementById('status');
const table = document.getElementById('results');
const tbody = table.querySelector('tbody');
const showHistoryBtn = document.getElementById('showHistoryBtn');
const historyCard = document.getElementById('historyCard');
const historyTable = document.getElementById('history');
const historyBody = historyTable.querySelector('tbody');
const historyColumnCount = historyTable.querySelector('thead tr').children.length;
const filterRow = document.getElementById('filterRow');
const filterFormatInput = document.getElementById('filterFormat');
const filterMinSeedersInput = document.getElementById('filterMinSeeders');
const filterFreeleechInput = document.getElementById('filterFreeleech');
const clearFiltersBtn = document.getElementById('clearFilters');

let lastResults = [];              // raw results from the most recent search
let historyMamIds = new Map();     // mam_id -> torrent_status, for the "in history" badge
let sortKey = null;   // null = original API order; otherwise a data-sort-key value
let sortDir = null;   // 'asc' | 'desc'

function showHistoryCard() {
  historyCard.style.display = 'block';
}

function getSelectedMediaType() {
  const selected = document.querySelector('input[name="mediaType"]:checked')?.value;
  return selected === 'ebook' ? 'ebook' : 'audiobook';
}

function normalizeMediaType(value) {
  return value === 'ebook' ? 'ebook' : 'audiobook';
}

function mediaTypeLabel(value) {
  return normalizeMediaType(value) === 'ebook' ? 'Ebook' : 'Audiobook';
}

function getSendToKindle() {
  return sendToKindleInput ? sendToKindleInput.checked : false;
}

function renderMediaTypeBadge(value, sendToKindle = true) {
  const mediaType = normalizeMediaType(value);
  const badges = [`<span class="type-badge">${escapeHtml(mediaTypeLabel(mediaType))}</span>`];
  if (mediaType === 'ebook' && !sendToKindle) {
    badges.push('<span class="type-badge type-badge-nosend">No Kindle</span>');
  }
  return badges.join(' ');
}

function updateSearchPlaceholder() {
  if (!q) return;
  const isEbook = getSelectedMediaType() === 'ebook';
  q.placeholder = isEbook
    ? 'Search title/author'
    : 'Search title/author/narrator';
  if (kindleToggle) kindleToggle.hidden = !isEbook;
}

mediaTypeInputs.forEach((input) => input.addEventListener('change', updateSearchPlaceholder));
updateSearchPlaceholder();
initSortHeaders();

refreshAccountStatus();

// Focus the search box on devices where it will not pop open a touch keyboard.
if (q && window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches) q.focus();

// ---------- Show History (even without searching) ----------
if (showHistoryBtn) {
  showHistoryBtn.addEventListener('click', async () => {
    showHistoryCard();
    await loadHistory();
    historyCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

// ---------- Submit handler (Enter or button) ----------
if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await runSearch();
  });
}

// ---------- Filter controls ----------
[filterFormatInput, filterMinSeedersInput, filterFreeleechInput].forEach((el) => {
  if (el) el.addEventListener('input', () => { if (lastResults.length) renderResults(); });
});

if (clearFiltersBtn) {
  clearFiltersBtn.addEventListener('click', () => {
    if (filterFormatInput) filterFormatInput.value = '';
    if (filterMinSeedersInput) filterMinSeedersInput.value = '';
    if (filterFreeleechInput) filterFreeleechInput.checked = false;
    if (lastResults.length) renderResults();
  });
}

// ---------- Search flow ----------
async function runSearch() {
  const text = (q?.value || '').trim();
  const mediaType = getSelectedMediaType();
  const perpage = parseInt(perpageSel?.value || '25', 10);

  statusEl.textContent = 'Searching...';
  table.style.display = 'none';
  tbody.innerHTML = '';

  try {
    const data = await fetchJson('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ media_type: mediaType, tor: { text }, perpage })
    });

    setAccountStatus(data?.freeleech_wedges);

    lastResults = data.results || [];
    if (!lastResults.length) {
      filterRow.hidden = true;
      statusEl.textContent = 'No results.';
      return;
    }

    // Load history first so the "in history" badge can be rendered in one pass.
    await loadHistory();

    filterRow.hidden = false;
    renderResults();
  } catch (e) {
    console.error(e);
    statusEl.textContent = 'Search failed.';
  }
}

function currentFilters() {
  return {
    format: (filterFormatInput?.value || '').trim().toLowerCase(),
    minSeeders: parseInt(filterMinSeedersInput?.value || '', 10),
    freeleechOnly: !!filterFreeleechInput?.checked
  };
}

function matchesFilters(item, f) {
  if (f.format && !String(item.format || '').toLowerCase().includes(f.format)) return false;
  if (Number.isFinite(f.minSeeders) && Number(item.seeders ?? 0) < f.minSeeders) return false;
  if (f.freeleechOnly && !item.is_freeleech) return false;
  return true;
}

function renderResults() {
  const f = currentFilters();
  let shown = lastResults.filter((it) => matchesFilters(it, f));
  if (sortKey) shown = sortResults(shown, sortKey, sortDir);

  tbody.innerHTML = '';
  shown.forEach((it) => tbody.appendChild(buildResultRow(it)));

  table.style.display = shown.length ? '' : 'none';
  statusEl.textContent = shown.length === lastResults.length
    ? `${shown.length} results shown`
    : `${shown.length} of ${lastResults.length} results shown`;
  updateSortIndicators();
}

function updateSortIndicators() {
  table.querySelectorAll('thead th[data-sort-key]').forEach((th) => {
    let ind = th.querySelector('.sort-ind');
    if (!ind) { ind = document.createElement('span'); ind.className = 'sort-ind'; th.appendChild(ind); }
    ind.textContent = th.dataset.sortKey === sortKey ? (sortDir === 'desc' ? ' ▼' : ' ▲') : '';
  });
}

function initSortHeaders() {
  table.querySelectorAll('thead th[data-sort-key]').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.sortKey;
      if (sortKey !== key) { sortKey = key; sortDir = 'asc'; }        // 1st click: asc
      else if (sortDir === 'asc') { sortDir = 'desc'; }               // 2nd click: desc
      else { sortKey = null; sortDir = null; }                        // 3rd click: reset to API order
      renderResults();
    });
  });
}

function buildResultRow(it) {
  const mediaType = getSelectedMediaType();
  const tr = document.createElement('tr');
  const detailsURL = it.id ? `https://www.myanonamouse.net/t/${encodeURIComponent(it.id)}` : '';
  const addBtn = document.createElement('button');
  addBtn.textContent = 'Add';
  addBtn.disabled = !(it.dl || it.id);
  addBtn.addEventListener('click', async () => {
    addBtn.disabled = true;
    addBtn.textContent = 'Adding...';
    try {
      const result = await fetchJson('/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: String(it.id ?? ''),
          title: it.title || '',
          dl: it.dl || '',
          author: it.author_info || '',
          narrator: it.narrator_info || '',
          media_type: it.media_type || mediaType,
          send_to_kindle: normalizeMediaType(it.media_type || mediaType) !== 'ebook' || getSendToKindle()
        })
      });
      setAccountStatus(result?.freeleech_wedges);
      addBtn.textContent = 'Added';
      await loadHistory();
    } catch (e) {
      console.error(e);
      addBtn.textContent = 'Error';
      addBtn.disabled = false;
    }
  });

  tr.innerHTML = `
    <td>${renderResultTitleCell(it)}${renderInHistoryBadge(it)}${renderInLibraryBadge(it)}</td>
    <td>${escapeHtml(it.author_info || '')}</td>
    <td>${escapeHtml(it.narrator_info || '')}</td>
    <td>${escapeHtml(it.format || '')}</td>
    <td class="right">${formatSize(it.size)}</td>
    <td class="right">${escapeHtml(`${it.seeders ?? '-'} / ${it.leechers ?? '-'}`)}</td>
    <td>${escapeHtml(it.added || '')}</td>
    <td class="center">
      ${detailsURL ? `<a href="${detailsURL}" target="_blank" rel="noopener noreferrer" title="Open on MAM">🔗</a>` : ''}
    </td>
    <td></td>
  `;

  applyDataLabels(table, tr);
  const actionCell = tr.lastElementChild;
  actionCell.appendChild(addBtn);
  return tr;
}

function renderInHistoryBadge(item) {
  const status = historyMamIds.get(String(item?.id ?? ''));
  if (!status) return '';
  const label = status === 'import_failed' ? 'In history (failed)' : 'In history';
  return `<div class="result-flags"><span class="result-badge result-badge-history">${escapeHtml(label)}</span></div>`;
}

function renderInLibraryBadge(item) {
  if (!item?.in_library) return '';
  return `<div class="result-flags"><span class="result-badge result-badge-library">In library</span></div>`;
}

let lastWedges = null;
let lastBonus = null;

function renderAccountStatus() {
  if (!accountStatusEl) return;
  const w = lastWedges ?? 'unknown';
  const b = (lastBonus == null) ? 'unknown' : Number(lastBonus).toLocaleString();
  accountStatusEl.textContent = `Freeleech wedges: ${w} · Bonus points: ${b}`;
}

function setAccountStatus(wedges, bonus) {
  if (wedges !== undefined) lastWedges = wedges;
  if (bonus !== undefined) lastBonus = bonus;
  renderAccountStatus();
}

async function refreshAccountStatus() {
  if (!accountStatusEl) return;
  accountStatusEl.textContent = 'Freeleech wedges: loading... · Bonus points: loading...';
  try {
    const data = await fetchJson('/account');
    setAccountStatus(data?.freeleech_wedges, data?.bonus_points);
  } catch (e) {
    console.error('account status failed', e);
    accountStatusEl.textContent = 'Freeleech wedges: unavailable · Bonus points: unavailable';
  }
}

// ---------- Helpers ----------
function escapeHtml(s) {
  return (s || '').toString()
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

function truncateText(text, maxLen = 140) {
  const value = (text || '').trim();
  if (!value || value.length <= maxLen) return value;
  return `${value.slice(0, maxLen - 1)}…`;
}

function renderResultTitleCell(item) {
  const badges = [];
  if (item?.is_freeleech) {
    badges.push('<span class="result-badge result-badge-free">Freeleech</span>');
  }
  if (item?.is_vip) {
    badges.push('<span class="result-badge result-badge-vip">VIP</span>');
  }

  const badgesHtml = badges.length
    ? `<div class="result-flags">${badges.join('')}</div>`
    : '';

  return `
    <div class="result-title-cell">
      <div class="result-title-main">${escapeHtml(item?.title || '')}</div>
      ${badgesHtml}
    </div>
  `;
}

function renderHistoryStatusCell(item) {
  const status = item?.torrent_status || '';
  const detail = item?.status_detail || '';
  const classes = [];
  if (status === 'import_failed') classes.push('history-status-failed');
  if (status === 'importing') classes.push('history-status-active');
  const labels = {
    added: 'Added',
    importing: 'Importing',
    imported: 'Imported',
    import_failed: 'Failure'
  };
  let label = labels[status] || status;
  const pct = item?.download_progress;
  if ((status === '' || status === 'added') && typeof pct === 'number') {
    label = `Downloading ${pct}%`;
    classes.push('history-status-active');
  }

  const statusHtml = classes.length
    ? `<span class="${classes.join(' ')}">${escapeHtml(label)}</span>`
    : escapeHtml(label);
  const detailHtml = detail
    ? `<div class="history-status-detail">${escapeHtml(truncateText(detail))}</div>`
    : '';

  return `${statusHtml}${detailHtml}`;
}

function buildRetryButton(item) {
  if (item?.torrent_status !== 'import_failed') return null;

  const retryBtn = document.createElement('button');
  retryBtn.type = 'button';
  retryBtn.textContent = 'Retry';
  retryBtn.addEventListener('click', async () => {
    retryBtn.disabled = true;
    retryBtn.textContent = 'Retrying...';
    try {
      await fetchJson(`/history/${encodeURIComponent(item.id)}/retry`, { method: 'POST' });
    } catch (e) {
      console.error('retry failed', e);
    }
    await loadHistory();
  });
  return retryBtn;
}

// Parse a size value (numeric bytes, or a string like "12.3 GiB" / "528.9 MiB"
// / "5.4 KiB" / "800 B") to a comparable byte count. Blank/unparseable -> -Infinity.
function sizeToBytes(v) {
  if (v == null || v === '') return -Infinity;
  if (typeof v === 'number') return Number.isFinite(v) ? v : -Infinity;
  const s = String(v).trim();
  const asNum = Number(s);
  if (Number.isFinite(asNum)) return asNum;            // pure numeric string = bytes
  const m = s.match(/([\d.]+)\s*([KMGT])?i?B/i);
  if (!m) return -Infinity;
  const val = parseFloat(m[1]);
  if (!Number.isFinite(val)) return -Infinity;
  const mult = { '': 1, K: 1024, M: 1024 ** 2, G: 1024 ** 3, T: 1024 ** 4 };
  return val * (mult[(m[2] || '').toUpperCase()] ?? 1);
}

// Parse the "Uploaded" value to a timestamp. Blank/unparseable -> -Infinity.
function parseUploaded(v) {
  if (!v) return -Infinity;
  const t = new Date(String(v).replace(' ', 'T')).getTime();
  return Number.isFinite(t) ? t : -Infinity;
}

const RESULT_SORTERS = {
  title:    { get: (it) => it.title || '',         type: 'str' },
  author:   { get: (it) => it.author_info || '',   type: 'str' },
  narrator: { get: (it) => it.narrator_info || '', type: 'str' },
  format:   { get: (it) => it.format || '',        type: 'str' },
  size:     { get: (it) => sizeToBytes(it.size),   type: 'num' },
  seeders:  { get: (it) => { const n = Number(it.seeders); return Number.isFinite(n) ? n : -Infinity; }, type: 'num' },
  added:    { get: (it) => parseUploaded(it.added), type: 'num' },
};

// Stable sort: decorate with original index and tie-break on it, so equal keys
// keep their filtered (API) order regardless of the engine's sort stability.
function sortResults(arr, key, dir) {
  const s = RESULT_SORTERS[key];
  if (!s) return arr;
  const sign = dir === 'desc' ? -1 : 1;
  return arr
    .map((it, i) => [it, i])
    .sort((a, b) => {
      const av = s.get(a[0]);
      const bv = s.get(b[0]);
      let c;
      if (s.type === 'str') c = String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' });
      else c = av < bv ? -1 : av > bv ? 1 : 0;
      return c !== 0 ? c * sign : a[1] - b[1];
    })
    .map((x) => x[0]);
}

function formatSize(sz) {
  if (sz == null || sz === '') return '';
  const n = Number(sz);
  if (!Number.isFinite(n)) return String(sz);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let x = n;
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024;
    i += 1;
  }
  return `${x.toFixed(1)} ${units[i]}`;
}

async function fetchJson(url, options) {
  const resp = await fetch(url, options);
  if (resp.ok) return resp.json();

  let msg = `HTTP ${resp.status}`;
  try {
    const j = await resp.json();
    if (j?.detail) msg += ` - ${j.detail}`;
  } catch {}
  throw new Error(msg);
}

function renderEmptyHistory() {
  const tr = document.createElement('tr');
  tr.className = 'empty';
  tr.innerHTML = `<td colspan="${historyColumnCount}" class="center muted">No items in history yet.</td>`;
  historyBody.appendChild(tr);
}

function applyDataLabels(sourceTable, row) {
  const labels = Array.from(sourceTable.querySelectorAll('thead th'))
    .map((th) => th.textContent.trim());

  Array.from(row.children).forEach((cell, index) => {
    if (labels[index]) cell.dataset.label = labels[index];
  });
}

async function loadHistory() {
  try {
    const j = await fetchJson('/history');
    historyBody.innerHTML = '';

    const items = j.items || [];
    historyMamIds = new Map(
      items
        .filter((it) => it.mam_id)
        .map((it) => [String(it.mam_id), it.torrent_status || 'added'])
    );
    if (!items.length) {
      renderEmptyHistory();
      showHistoryCard();
      return;
    }

    items.forEach((item) => {
      const tr = document.createElement('tr');
      const when = item.added_at ? new Date(item.added_at.replace(' ', 'T') + 'Z').toLocaleString() : '';
      const linkURL = item.mam_id ? `https://www.myanonamouse.net/t/${encodeURIComponent(item.mam_id)}` : '';
      const mediaType = normalizeMediaType(item.media_type);

      tr.innerHTML = `
        <td>${renderMediaTypeBadge(mediaType, item.send_to_kindle !== 0)}</td>
        <td>${escapeHtml(item.title || '')}</td>
        <td>${escapeHtml(item.author || '')}</td>
        <td>${escapeHtml(item.narrator || '')}</td>
        <td class="center">${linkURL ? `<a href="${linkURL}" target="_blank" rel="noopener noreferrer" title="Open on MAM">🔗</a>` : ''}</td>
        <td>${escapeHtml(when)}</td>
        <td>${renderHistoryStatusCell(item)}</td>
        <td></td>
      `;

      const retryBtn = buildRetryButton(item);
      if (retryBtn) tr.lastElementChild.appendChild(retryBtn);
      applyDataLabels(historyTable, tr);
      historyBody.appendChild(tr);
    });

    showHistoryCard();
  } catch (e) {
    console.error('history load failed', e);
  }
}
