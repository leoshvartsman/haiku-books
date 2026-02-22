const PER_PAGE = 25;
const DIMS = ["image_precision", "cut", "economy", "resonance", "originality", "musicality"];

let allPoems = [];
let filteredPoems = [];
let currentFilter = "all";
let currentPage = 1;
let totalMatches = 0;

// Chart state
const authorColors = {};
const authorVis    = {};
const poemById     = {};

async function init() {
    try {
        const res = await fetch("ratings.json");
        if (!res.ok) throw new Error("ratings.json not found");
        const data = await res.json();

        totalMatches = data.total_matches || 0;
        allPoems = data.poems || [];

        renderSummary(data.summary);
        setupFilters();
        applyFilter("all");
    } catch (e) {
        document.getElementById("leaderboard").innerHTML = `
            <div class="no-ratings">
                <p>No ratings yet.</p>
                <p style="font-size:0.85rem">Run <code>python rate_poems.py</code> to start rating.</p>
            </div>`;
        return;
    }

    // Chart rendering is isolated so any failure here doesn't wipe the leaderboard
    try {
        buildAuthorColors(allPoems);
        renderScatterChart(allPoems);
    } catch (e) {
        console.error("Chart rendering error:", e);
    }
}

function renderSummary(summary) {
    if (!summary || totalMatches === 0) return;

    document.getElementById("summary-bar").style.display = "flex";
    document.getElementById("elo-comparison").style.display = "block";

    document.getElementById("stat-total-matches").textContent = totalMatches.toLocaleString();
    document.getElementById("stat-total-poems").textContent = allPoems.length.toLocaleString();
    document.getElementById("stat-ai-count").textContent = (summary.ai_count || 0).toLocaleString();
    document.getElementById("stat-human-count").textContent = (summary.human_count || 0).toLocaleString();

    const aiElo = summary.ai_avg_elo || 1500;
    const humanElo = summary.human_avg_elo || 1500;
    const maxElo = Math.max(aiElo, humanElo, 1501);
    const minElo = Math.min(aiElo, humanElo, 1499);
    const range = Math.max(maxElo - minElo, 50);
    const baseline = minElo - range * 0.1;

    const aiFill = Math.min(100, ((aiElo - baseline) / (range * 1.2)) * 100);
    const humanFill = Math.min(100, ((humanElo - baseline) / (range * 1.2)) * 100);

    document.getElementById("bar-ai").style.width = aiFill + "%";
    document.getElementById("bar-human").style.width = humanFill + "%";
    document.getElementById("score-ai").textContent = aiElo;
    document.getElementById("score-human").textContent = humanElo;
}

function setupFilters() {
    const aiCount = allPoems.filter(p => p.source === "ai").length;
    const humanCount = allPoems.filter(p => p.source === "human").length;

    document.getElementById("badge-all").textContent = allPoems.length;
    document.getElementById("badge-ai").textContent = aiCount;
    document.getElementById("badge-human").textContent = humanCount;

    document.querySelectorAll(".filter-tab").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-tab").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentPage = 1;
            applyFilter(btn.dataset.filter);
        });
    });
}

function applyFilter(filter) {
    currentFilter = filter;
    if (filter === "all") {
        filteredPoems = [...allPoems];
    } else {
        filteredPoems = allPoems.filter(p => p.source === filter);
    }
    render();
}

function render() {
    const start = (currentPage - 1) * PER_PAGE;
    const page = filteredPoems.slice(start, start + PER_PAGE);

    const leaderboard = document.getElementById("leaderboard");

    if (filteredPoems.length === 0) {
        leaderboard.innerHTML = `<div class="no-ratings"><p>No poems in this category yet.</p></div>`;
        document.getElementById("pagination").innerHTML = "";
        return;
    }

    const hasAnyRatings = allPoems.some(p => p.matches > 0);

    leaderboard.innerHTML = page.map((poem, i) => {
        const rank = start + i + 1;
        const rankClass = rank <= 3 ? "top3" : "";
        const rankDisplay = rank === 1 ? "🥇" : rank === 2 ? "🥈" : rank === 3 ? "🥉" : `#${rank}`;

        const lines = (poem.lines || []).map(l =>
            `<span>${escHtml(l)}</span>`
        ).join("<br>");

        const sourceLabel = poem.source === "ai" ? "AI" : "Human";
        const sourceClass = poem.source;

        let metaParts = [escHtml(poem.author || "")];
        if (poem.collection) metaParts.push(escHtml(poem.collection));
        if (poem.translator) metaParts.push(`trans. ${escHtml(poem.translator)}`);
        const meta = metaParts.join(" · ");

        const eloDisplay = poem.elo !== undefined ? Math.round(poem.elo) : "—";
        const record = poem.matches > 0
            ? `${poem.wins}W ${poem.losses}L ${poem.draws}D`
            : "unrated";

        // Mini dim bars (only if this poem has been rated)
        let dimBarsHtml = "";
        if (poem.matches > 0 && poem.dim_averages) {
            const bars = DIMS.map(dim => {
                const val = poem.dim_averages[dim];
                const pct = val != null ? (val / 5) * 100 : 0;
                const fillClass = poem.source === "human" ? "human-fill" : "";
                return `<div class="dim-bar"><div class="dim-bar-fill ${fillClass}" style="width:${pct}%"></div></div>`;
            }).join("");
            dimBarsHtml = `<div class="dim-bars" title="Avg scores: ${DIMS.map(d => (poem.dim_averages[d] || 0).toFixed(1)).join(', ')}">${bars}</div>`;
        } else if (poem.matches === 0 && hasAnyRatings) {
            dimBarsHtml = `<div class="dim-bars" title="Not yet rated">${DIMS.map(() => `<div class="dim-bar"><div class="dim-bar-fill" style="width:0%"></div></div>`).join("")}</div>`;
        }

        const reasoningHtml = poem.last_reasoning
            ? `<div class="poem-meta" style="margin-top:0.4rem;font-style:italic;">"${escHtml(poem.last_reasoning)}"</div>`
            : "";

        return `<div class="poem-row">
            <div class="poem-rank ${rankClass}">${rankDisplay}</div>
            <div class="poem-text">
                <div class="poem-lines">${lines}</div>
                <div class="poem-meta">${meta}</div>
                ${reasoningHtml}
            </div>
            <span class="poem-source ${sourceClass}">${sourceLabel}</span>
            ${dimBarsHtml}
            <div class="poem-stats">
                <div class="poem-elo">${eloDisplay}</div>
                <div class="poem-record">${record}</div>
            </div>
        </div>`;
    }).join("");

    renderPagination();
}

function renderPagination() {
    const totalPages = Math.ceil(filteredPoems.length / PER_PAGE);
    const pag = document.getElementById("pagination");

    if (totalPages <= 1) {
        pag.innerHTML = "";
        return;
    }

    let html = "";
    if (currentPage > 1) html += `<button data-page="${currentPage - 1}">&laquo;</button>`;

    let start = Math.max(1, currentPage - 3);
    let end = Math.min(totalPages, start + 6);
    if (end - start < 6) start = Math.max(1, end - 6);

    for (let i = start; i <= end; i++) {
        html += `<button data-page="${i}" class="${i === currentPage ? "active" : ""}">${i}</button>`;
    }
    if (currentPage < totalPages) html += `<button data-page="${currentPage + 1}">&raquo;</button>`;

    pag.innerHTML = html;
    pag.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", () => {
            currentPage = parseInt(btn.dataset.page);
            render();
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    });
}

// ── Scatter chart ─────────────────────────────────────────────────────────────

function buildAuthorColors(poems) {
    poems.forEach(p => { poemById[p.id] = p; });
    const allAuthors = [...new Set(poems.map(p => p.author))].sort();
    allAuthors.forEach((author, i) => {
        const hue = Math.round((i * 137.508) % 360);
        const sat = 58 + (i % 3) * 8;
        const lit = 40 + (i % 2) * 10;
        if (!authorColors[author]) authorColors[author] = `hsl(${hue},${sat}%,${lit}%)`;
        if (!(author in authorVis)) authorVis[author] = true;
    });
}

function renderScatterChart(poems) {
    const rated = poems.filter(p => p.matches > 0);
    if (rated.length < 2) return;
    document.getElementById("chart-section").style.display = "block";
    drawScatter(rated);
    buildChartLegend(poems);
}

function drawScatter(poems) {
    const vis = poems.filter(p => authorVis[p.author] !== false);

    const VW = 760, VH = 310;
    const P = { l: 48, r: 16, t: 18, b: 38 };
    const W = VW - P.l - P.r, H = VH - P.t - P.b;

    const elos = poems.map(p => p.elo);
    const minE = Math.min(...elos), maxE = Math.max(...elos);
    const ep = (maxE - minE) * 0.06 || 50;

    const xp = elo => P.l + (elo - (minE - ep)) / ((maxE + ep) - (minE - ep)) * W;
    const yp = p   => P.t + (1 - p.wins / p.matches) * H;

    let s = `<svg viewBox="0 0 ${VW} ${VH}" style="width:100%;height:auto;display:block" xmlns="http://www.w3.org/2000/svg">`;

    // Y grid
    [0, 25, 50, 75, 100].forEach(pct => {
        const yy = P.t + (1 - pct / 100) * H;
        s += `<line x1="${P.l}" y1="${yy}" x2="${VW - P.r}" y2="${yy}" stroke="#f0ede8" stroke-width="${pct === 50 ? 1.5 : 1}"/>`;
        s += `<text x="${P.l - 5}" y="${yy + 4}" text-anchor="end" font-size="10" fill="#ccc">${pct}%</text>`;
    });

    // X grid + ticks
    const span = maxE - minE || 200;
    const step = span < 300 ? 50 : span < 600 ? 100 : 200;
    const first = Math.ceil((minE - ep) / step) * step;
    for (let t = first; t <= maxE + ep; t += step) {
        const xx = xp(t);
        s += `<line x1="${xx}" y1="${P.t}" x2="${xx}" y2="${P.t + H}" stroke="#f5f2ee" stroke-width="1"/>`;
        s += `<text x="${xx}" y="${P.t + H + 14}" text-anchor="middle" font-size="10" fill="#ccc">${t}</text>`;
    }

    // Axis labels
    s += `<text x="${P.l + W / 2}" y="${VH - 1}" text-anchor="middle" font-size="11" fill="#bbb">ELO Rating</text>`;
    s += `<text x="10" y="${P.t + H / 2}" text-anchor="middle" font-size="11" fill="#bbb" transform="rotate(-90 10 ${P.t + H / 2})">Win Rate</text>`;

    // Shape legend (top-right corner of chart)
    const lx = VW - P.r - 4;
    s += `<circle cx="${lx - 68}" cy="12" r="4.5" fill="#aaa" fill-opacity="0.6"/>`;
    s += `<text x="${lx - 60}" y="16" font-size="10" fill="#aaa">AI</text>`;
    s += `<polygon points="${lx - 41},7 ${lx - 35},12 ${lx - 41},17 ${lx - 47},12" fill="#aaa" fill-opacity="0.6"/>`;
    s += `<text x="${lx - 33}" y="16" font-size="10" fill="#aaa">Human</text>`;

    // Points (dimmed first, visible on top)
    const dimmed = poems.filter(p => authorVis[p.author] === false);
    const drawPoint = (p, opacity) => {
        const cx = xp(p.elo), cy = yp(p);
        const col = authorColors[p.author] || "#999";
        const attr = `fill="${col}" fill-opacity="${opacity}" stroke="none" class="cp" data-pid="${escHtml(p.id)}" style="cursor:pointer"`;
        if (p.source === "ai") {
            return `<circle cx="${cx}" cy="${cy}" r="5" ${attr}/>`;
        } else {
            const r = 6;
            return `<polygon points="${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}" ${attr}/>`;
        }
    };
    s += `<g>`;
    dimmed.forEach(p => { s += drawPoint(p, 0.12); });
    vis.forEach(p  => { s += drawPoint(p, 0.82); });
    s += `</g>`;

    // Axes
    s += `<line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${P.t + H + 1}" stroke="#ddd" stroke-width="1.5"/>`;
    s += `<line x1="${P.l - 1}" y1="${P.t + H}" x2="${VW - P.r}" y2="${P.t + H}" stroke="#ddd" stroke-width="1.5"/>`;

    s += `</svg>`;

    document.getElementById("chart-inner").innerHTML = s;

    // Tooltip
    const tooltip = document.getElementById("chart-tooltip");
    document.querySelectorAll(".cp").forEach(el => {
        el.addEventListener("mouseenter", function(e) {
            const p = poemById[this.dataset.pid];
            if (!p) return;
            const lines = (p.lines || []).map(l => escHtml(l)).join("<br>");
            const pct = p.matches > 0 ? Math.round(p.wins / p.matches * 100) : 0;
            tooltip.innerHTML = `<div style="font-style:italic;margin-bottom:0.25rem">${lines}</div>`
                + `<div style="color:#ccc;font-size:0.76rem">${escHtml(p.author)}</div>`
                + `<div style="color:#999;font-size:0.74rem;margin-top:0.15rem">ELO ${Math.round(p.elo)} &nbsp;·&nbsp; ${p.wins}W ${p.losses}L &nbsp;·&nbsp; ${pct}% wins</div>`;
            tooltip.style.display = "block";
            positionTooltip(e);
        });
        el.addEventListener("mousemove", positionTooltip);
        el.addEventListener("mouseleave", () => { tooltip.style.display = "none"; });
    });
}

function positionTooltip(e) {
    const t = document.getElementById("chart-tooltip");
    const tw = t.offsetWidth || 220;
    const left = e.clientX + 14 + tw > window.innerWidth ? e.clientX - tw - 14 : e.clientX + 14;
    t.style.left = left + "px";
    t.style.top  = (e.clientY - 10) + "px";
}

function buildChartLegend(poems) {
    const rated = poems.filter(p => p.matches > 0);

    const poetAvgElo = {};
    [...new Set(poems.map(p => p.author))].forEach(a => {
        const pp = rated.filter(x => x.author === a);
        poetAvgElo[a] = pp.length ? pp.reduce((s, x) => s + x.elo, 0) / pp.length : 1500;
    });
    const byEloDesc = (a, b) => poetAvgElo[b] - poetAvgElo[a];

    const humanAuthors = [...new Set(poems.filter(p => p.source === "human").map(p => p.author))].sort(byEloDesc);
    const aiAuthors    = [...new Set(poems.filter(p => p.source === "ai").map(p => p.author))].sort(byEloDesc);

    const chip = (author, cls) => {
        const col = authorColors[author] || "#999";
        const on  = authorVis[author] !== false;
        return `<div class="legend-chip ${cls}${on ? "" : " off"}" data-author="${escHtml(author)}" title="${escHtml(author)}"><span class="cdot" style="background:${col}"></span><span>${escHtml(author)}</span></div>`;
    };

    const toggleAllBtn = (source, label) =>
        `<button class="legend-toggle-all" data-source="${source}">${label}</button>`;

    document.getElementById("chart-legend").innerHTML = `
        <div class="legend-group">
            <div class="legend-group-header">
                <span class="legend-group-title">◆ Human Poets</span>
                ${toggleAllBtn("human", "all")} / ${toggleAllBtn("human-off", "none")}
            </div>
            <div class="legend-chips">${humanAuthors.map(a => chip(a, "human")).join("")}</div>
        </div>
        <div class="legend-group">
            <div class="legend-group-header">
                <span class="legend-group-title">● AI Poets</span>
                ${toggleAllBtn("ai", "all")} / ${toggleAllBtn("ai-off", "none")}
            </div>
            <div class="legend-ai-wrap"><div class="legend-chips">${aiAuthors.map(a => chip(a, "ai")).join("")}</div></div>
        </div>`;

    document.querySelectorAll(".legend-chip").forEach(el => {
        el.addEventListener("click", function() {
            const author = this.dataset.author;
            authorVis[author] = !authorVis[author];
            this.classList.toggle("off", !authorVis[author]);
            drawScatter(rated);
        });
    });

    document.querySelectorAll(".legend-toggle-all").forEach(btn => {
        btn.addEventListener("click", function() {
            const src = this.dataset.source;
            const source = src.replace("-off", "");
            const on = !src.includes("-off");
            poems.filter(p => p.source === source && p.matches > 0).forEach(p => { authorVis[p.author] = on; });
            document.querySelectorAll(`.legend-chip.${source}`).forEach(c => c.classList.toggle("off", !on));
            drawScatter(rated);
        });
    });
}

function escHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

init();
