/* Pages for long lists and tables. Mark the list or table with data-per-page="N".
   Without JavaScript every item stays visible, so nothing is lost for search engines.
   data-range="1" adds a line like "Q2 2026 to Q3 2024" from the first link of each row. */
document.querySelectorAll('[data-per-page]').forEach(function (box) {
  var items = box.tagName === 'TABLE' ? [].slice.call(box.tBodies[0].rows) : [].slice.call(box.children);
  var per = +box.dataset.perPage, n = Math.ceil(items.length / per);
  if (n < 2) return;
  var nav = document.createElement('nav');
  nav.className = 'pager';
  nav.setAttribute('aria-label', 'Pages');
  box.parentNode.insertBefore(nav, box.nextSibling);
  function label(item) {
    var a = item.querySelector('a');
    return a ? a.textContent.trim() : '';
  }
  function go(k, scroll) {
    items.forEach(function (r, i) { r.hidden = Math.floor(i / per) !== k; });
    var h = k > 0 ? '<a href="#" data-k="' + (k - 1) + '">&larr; Prev</a>' : '';
    h += '<span class="pager-nums">';
    for (var i = 0; i < n; i++) {
      if (n > 9 && i > 1 && i < n - 2 && Math.abs(i - k) > 1) {
        if (i === 2 || i === n - 3) h += '<span class="gap">&hellip;</span>';
        continue;
      }
      h += i === k ? '<span aria-current="page">' + (i + 1) + '</span>' : '<a href="#" data-k="' + i + '">' + (i + 1) + '</a>';
    }
    h += '</span>';
    h += k < n - 1 ? '<a href="#" data-k="' + (k + 1) + '">Next &rarr;</a>' : '';
    if (box.dataset.range) {
      h += '<span class="pager-note">' + label(items[k * per]) + ' to ' +
           label(items[Math.min((k + 1) * per, items.length) - 1]) + '</span>';
    } else {
      h += '<span class="pager-note">' + (k * per + 1) + '&ndash;' + Math.min((k + 1) * per, items.length) +
           ' of ' + items.length + '</span>';
    }
    nav.innerHTML = h;
    if (scroll) box.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }
  nav.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-k]');
    if (!a) return;
    e.preventDefault();
    go(+a.dataset.k, true);
  });
  go(0, false);
});
