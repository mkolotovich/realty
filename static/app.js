/* ══════════════════════════════════════════════
   RealtyScan — Frontend Logic v2
   ══════════════════════════════════════════════ */

const API = "";

let currentJobId = null;
let pollTimer    = null;
let allListings  = [];

// ── Глобальный перехват ошибок ──────────────────
window.onerror = (msg, src, line, col, err) => {
  console.error("[RealtyScan] JS Error:", msg, "at", src, line, col, err);
};
window.addEventListener("unhandledrejection", e => {
  console.error("[RealtyScan] Unhandled promise rejection:", e.reason);
});

console.log("[RealtyScan] app.js v2 loaded");

// Явно выставляем дефолт, чтобы браузерное восстановление формы
// не игнорировало selected в HTML.
const propTypeEl = document.getElementById("prop-type");
if (propTypeEl) {
  propTypeEl.value = "house";
}

// ── Navigation ──────────────────────────────────
document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`view-${view}`).classList.add("active");
    if (view === "history") loadHistory();
  });
});

// ── Load parsers ────────────────────────────────
async function loadParsers() {
  try {
    console.log("[RealtyScan] Loading parsers...");
    const res  = await fetch(`${API}/api/parsers`);
    const list = await res.json();
    console.log("[RealtyScan] Parsers:", list);
    const container = document.getElementById("sources-list");
    container.innerHTML = "";
    list.forEach(p => {
      const label = document.createElement("label");
      label.className = "source-check";
      label.innerHTML = `
        <input type="checkbox" value="${p.key}" checked />
        <span class="source-check-name">${p.name}</span>
        <span class="source-check-url">${p.url.replace(/^https?:\/\//, "")}</span>
      `;
      container.appendChild(label);
    });
  } catch(e) {
    console.error("[RealtyScan] Failed to load parsers:", e);
  }
}
loadParsers();

// ── Parse button ────────────────────────────────
document.getElementById("parse-btn").addEventListener("click", startParsing);

async function startParsing() {
  try {
    clearPoll();
    allListings = [];
    document.getElementById("listings").innerHTML = "";
    document.getElementById("empty-state").style.display = "none";

    const sources = [...document.querySelectorAll(".source-check input:checked")]
      .map(i => i.value);
    console.log("[RealtyScan] Sources selected:", sources);

    if (!sources.length) { alert("Выберите хотя бы один источник"); return; }

    const selectedDistricts = [...document.querySelectorAll("input[name='district']:checked")]
      .map(i => i.value);

    const filters = {
      deal_type:     document.getElementById("deal-type").value,
      property_type: document.getElementById("prop-type").value || "house",
      city:          document.getElementById("city").value.trim() || "Луганск",
      districts:     selectedDistricts,
      rooms:         document.getElementById("rooms").value || null,
      price_min:     document.getElementById("price-min").value || null,
      price_max:     document.getElementById("price-max").value || null,
      area_min:      document.getElementById("area-min").value || null,
      area_max:      document.getElementById("area-max").value || null,
    };
    console.log("[RealtyScan] Filters:", filters);

    setStatus("Запуск парсинга…");
    document.getElementById("results-toolbar").classList.add("hidden");
    document.getElementById("parse-btn").disabled = true;

    const res = await fetch(`${API}/api/parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources, filters }),
    });

    if (!res.ok) {
      throw new Error(`/api/parse вернул ${res.status}: ${await res.text()}`);
    }

    const body = await res.json();
    console.log("[RealtyScan] Job started:", body);
    const job_id = body.job_id;

    if (!job_id) {
      throw new Error("Сервер не вернул job_id: " + JSON.stringify(body));
    }

    currentJobId = job_id;
    pollJob(job_id);

  } catch(e) {
    console.error("[RealtyScan] startParsing error:", e);
    setStatus("Ошибка: " + e.message);
    document.getElementById("parse-btn").disabled = false;
  }
}

// ── Polling ─────────────────────────────────────
function pollJob(jobId) {
  let attempts = 0;
  pollTimer = setInterval(async () => {
    try {
      attempts++;
      const res = await fetch(`${API}/api/jobs/${jobId}`);
      if (!res.ok) throw new Error(`/api/jobs вернул ${res.status}`);
      const job = await res.json();

      console.log(`[RealtyScan] Poll #${attempts} status=${job.status} total=${job.total}`);

      const prog = document.getElementById("source-progress");
      prog.innerHTML = Object.entries(job.progress || {}).map(([k, v]) =>
        `<span class="src-badge done">${k} (${v})</span>`
      ).join("");

      if (job.status === "running" || job.status === "pending") {
        setStatus(`Парсинг… собрано ${job.total || 0} объявлений`);
      }

      if (job.status === "done") {
        clearPoll();
        document.getElementById("status-bar").classList.add("hidden");
        document.getElementById("parse-btn").disabled = false;
        if (job.errors && job.errors.length) {
          console.warn("[RealtyScan] Job errors:", job.errors);
        }
        loadResults(jobId);
      }

      // Страховка: если polling идёт больше 5 минут
      if (attempts > 375) {
        clearPoll();
        setStatus("Таймаут — попробуйте снова");
        document.getElementById("parse-btn").disabled = false;
      }

    } catch(e) {
      console.error("[RealtyScan] Poll error:", e);
    }
  }, 800);
}

function clearPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ── Load results ────────────────────────────────
async function loadResults(jobId) {
  try {
    const sortBy  = document.getElementById("sort-by").value;
    const sortDir = document.getElementById("sort-dir").value;
    const url     = `${API}/api/results/${jobId}?sort_by=${sortBy}&sort_dir=${sortDir}`;
    console.log("[RealtyScan] Loading results from:", url);

    const res = await fetch(url);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`/api/results вернул ${res.status}: ${text}`);
    }

    const data = await res.json();
    console.log("[RealtyScan] Results:", data.total, "listings");

    allListings = data.listings || [];
    renderListings(allListings);
    document.getElementById("count").textContent = allListings.length;
    document.getElementById("results-toolbar").classList.remove("hidden");

    if (!allListings.length) {
      document.getElementById("empty-state").style.display = "flex";
      document.getElementById("empty-state").querySelector(".empty-title").textContent =
        "Ничего не найдено по заданным фильтрам";
    }
  } catch(e) {
    console.error("[RealtyScan] loadResults error:", e);
    setStatus("Ошибка загрузки результатов: " + e.message);
  }
}

// ── Render listings ─────────────────────────────
const tpl = document.getElementById("card-tpl");

function renderListings(listings) {
  const grid = document.getElementById("listings");
  grid.innerHTML = "";

  if (!tpl) {
    console.error("[RealtyScan] card-tpl template not found in DOM!");
    return;
  }

  listings.forEach((l, i) => {
    const clone = tpl.content.cloneNode(true);
    const card  = clone.querySelector(".listing-card");
    card.style.animationDelay = `${Math.min(i * 30, 300)}ms`;

    const img = clone.querySelector(".card-img");
    if (l.image) {
      img.src = l.image;
      img.alt = l.title;
    } else {
      img.parentElement.style.background = "#1c1c21";
      img.style.display = "none";
    }

    clone.querySelector(".card-source").textContent = l.source;
    clone.querySelector(".card-price").textContent  = formatPrice(l.price, l.currency);
    clone.querySelector(".card-title").textContent  = l.title;
    clone.querySelector(".card-addr").textContent   = l.address;

    const areaEl  = clone.querySelector(".card-area");
    const roomsEl = clone.querySelector(".card-rooms");
    if (l.area)  areaEl.textContent  = `${l.area} м²`;  else areaEl.remove();
    if (l.rooms !== null && l.rooms !== undefined) {
      roomsEl.textContent = l.rooms === 0 ? "Студия" : `${l.rooms} комн.`;
    } else roomsEl.remove();

    const link = clone.querySelector(".card-link");
    link.href = l.url || "#";

    grid.appendChild(clone);
  });
}

function formatPrice(price, currency) {
  if (!price) return "Цена не указана";
  const formatted = price.toLocaleString("ru-RU");
  if (currency && currency !== "RUB") return `${formatted} ${currency}`;
  return `${formatted} ₽`;
}

// ── Sort & view toggle ──────────────────────────
["sort-by", "sort-dir"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => {
    if (currentJobId) loadResults(currentJobId);
  });
});

document.getElementById("grid-btn").addEventListener("click", () => {
  document.getElementById("listings").classList.remove("list-mode");
  document.getElementById("grid-btn").classList.add("active");
  document.getElementById("list-btn").classList.remove("active");
});
document.getElementById("list-btn").addEventListener("click", () => {
  document.getElementById("listings").classList.add("list-mode");
  document.getElementById("list-btn").classList.add("active");
  document.getElementById("grid-btn").classList.remove("active");
});

// ── Status helper ───────────────────────────────
function setStatus(msg) {
  document.getElementById("status-bar").classList.remove("hidden");
  document.getElementById("status-text").textContent = msg;
}

// ── History ─────────────────────────────────────
async function loadHistory() {
  try {
    const res  = await fetch(`${API}/api/jobs`);
    const jobs = await res.json();
    const el   = document.getElementById("jobs-list");

    if (!jobs.length) {
      el.innerHTML = '<div style="color:var(--text3);padding:24px">Заданий пока нет</div>';
      return;
    }

    el.innerHTML = jobs.map(j => {
      const city    = j.filters?.city || "—";
      const deal    = j.filters?.deal_type === "rent" ? "Аренда" : "Продажа";
      const sources = (j.sources || []).join(", ");
      const ts      = j.created_at ? new Date(j.created_at).toLocaleString("ru-RU") : "";
      return `
        <div class="job-row" onclick="openJob('${j.id}')">
          <div class="job-id">${j.id}</div>
          <div class="job-info">
            <div class="job-city">${city} · ${deal}</div>
            <div class="job-meta">${sources} · ${ts}</div>
          </div>
          <span class="job-status ${j.status}">${j.status}</span>
          <div class="job-count">${j.total || 0} обяв.</div>
        </div>`;
    }).join("");
  } catch(e) {
    console.error("[RealtyScan] loadHistory error:", e);
  }
}

function openJob(jobId) {
  currentJobId = jobId;
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.querySelector('[data-view="search"]').classList.add("active");
  document.getElementById("view-search").classList.add("active");
  document.getElementById("empty-state").style.display = "none";
  document.getElementById("status-bar").classList.add("hidden");
  loadResults(jobId);
}
