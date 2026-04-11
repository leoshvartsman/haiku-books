let allBooks = [];
let filteredBooks = [];

function slugify(str) {
    return str.normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
}

async function init() {
    const res = await fetch('catalog.json');
    allBooks = await res.json();
    filteredBooks = [...allBooks];

    document.getElementById('search').addEventListener('input', onFilter);
    document.getElementById('sort').addEventListener('change', onFilter);

    document.querySelectorAll('.shelf-arrow').forEach(btn => {
        btn.addEventListener('click', () => {
            const shelf = btn.dataset.shelf;
            const grid = document.getElementById(`grid-${shelf}`);
            const step = grid.clientWidth * 0.8;
            grid.scrollBy({ left: btn.classList.contains('shelf-arrow-left') ? -step : step, behavior: 'smooth' });
        });
    });

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
        return b.date.localeCompare(a.date);
    });

    render();
}

function bookCard(book) {
    const coverHtml = book.cover_url
        ? `<img src="${book.cover_url}" alt="${book.title}" loading="lazy">`
        : `<div class="no-cover">&#x2727;</div>`;
    const slug = book.slug || book.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const pageUrl = `books/${slug}.html`;
    return `<div class="card">
        <a href="${pageUrl}" class="card-link">
            <div class="card-cover">${coverHtml}</div>
        </a>
    </div>`;
}

function render() {
    const countEl = document.getElementById('book-count');
    countEl.textContent = filteredBooks.length === allBooks.length
        ? `${allBooks.length} books`
        : `${filteredBooks.length} of ${allBooks.length} books`;

    const classic = filteredBooks.filter(b => (b.cover_style || 'classic') !== 'modern');
    const modern  = filteredBooks.filter(b => b.cover_style === 'modern');

    document.getElementById('grid-classic').innerHTML = classic.map(bookCard).join('');
    document.getElementById('grid-modern').innerHTML  = modern.map(bookCard).join('');

    // Hide empty shelves
    document.querySelectorAll('.shelf-section').forEach(section => {
        const shelf = section.querySelector('.grid');
        section.style.display = shelf && shelf.children.length > 0 ? '' : 'none';
    });
}

init();
