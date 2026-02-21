const PER_PAGE = 25;
const DIMS = ["image_precision", "cut", "economy", "resonance", "originality", "musicality"];

let allPoems = [];
let filteredPoems = [];
let currentFilter = "all";
let currentPage = 1;
let totalMatches = 0;

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

function escHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

init();
