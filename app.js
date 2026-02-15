const BOOKS_PER_PAGE = 24;
let allBooks = [];
let filteredBooks = [];
let currentPage = 1;

async function init() {
    const res = await fetch('catalog.json');
    allBooks = await res.json();
    filteredBooks = [...allBooks];

    document.getElementById('search').addEventListener('input', onFilter);
    document.getElementById('sort').addEventListener('change', onFilter);

    onFilter();
}

function onFilter() {
    const query = document.getElementById('search').value.toLowerCase().trim();
    const sortBy = document.getElementById('sort').value;

    filteredBooks = allBooks.filter(b =>
        !query ||
        b.title.toLowerCase().includes(query) ||
        b.author.toLowerCase().includes(query)
    );

    filteredBooks.sort((a, b) => {
        if (sortBy === 'title') return a.title.localeCompare(b.title);
        if (sortBy === 'author') return a.author.localeCompare(b.author);
        return b.date.localeCompare(a.date); // newest
    });

    currentPage = 1;
    render();
}

function render() {
    const totalPages = Math.max(1, Math.ceil(filteredBooks.length / BOOKS_PER_PAGE));
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * BOOKS_PER_PAGE;
    const page = filteredBooks.slice(start, start + BOOKS_PER_PAGE);

    // Book count
    const countEl = document.getElementById('book-count');
    countEl.textContent = filteredBooks.length === allBooks.length
        ? `${allBooks.length} books`
        : `${filteredBooks.length} of ${allBooks.length} books`;

    // Grid
    const grid = document.getElementById('grid');
    grid.innerHTML = page.map(book => {
        const coverHtml = book.cover_url
            ? `<img src="${book.cover_url}" alt="${book.title}" loading="lazy">`
            : `<div class="no-cover">&#x2727;</div>`;

        return `<div class="card">
            ${coverHtml}
            <div class="card-body">
                <div class="card-title">${book.title}</div>
                <div class="card-author">${book.author}</div>
                <div class="card-meta">${book.haiku_count} haiku</div>
                <div class="card-downloads">
                    ${book.pdf_url ? `<a href="${book.pdf_url}" class="btn-pdf" download>PDF</a>` : ''}
                    ${book.epub_url ? `<a href="${book.epub_url}" class="btn-epub" type="application/epub+zip">EPUB</a>` : ''}
                </div>
            </div>
        </div>`;
    }).join('');

    // Pagination
    const pag = document.getElementById('pagination');
    if (totalPages <= 1) {
        pag.innerHTML = '';
        return;
    }

    let buttons = '';
    if (currentPage > 1) {
        buttons += `<button data-page="${currentPage - 1}">&laquo; Prev</button>`;
    }

    // Show at most 7 page buttons around current
    let startPage = Math.max(1, currentPage - 3);
    let endPage = Math.min(totalPages, startPage + 6);
    if (endPage - startPage < 6) startPage = Math.max(1, endPage - 6);

    for (let i = startPage; i <= endPage; i++) {
        buttons += `<button data-page="${i}" class="${i === currentPage ? 'active' : ''}">${i}</button>`;
    }

    if (currentPage < totalPages) {
        buttons += `<button data-page="${currentPage + 1}">Next &raquo;</button>`;
    }

    pag.innerHTML = buttons;
    pag.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            currentPage = parseInt(btn.dataset.page);
            render();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    });
}

init();
