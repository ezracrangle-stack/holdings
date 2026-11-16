(function () {
  var box = document.getElementById('results'), input = document.getElementById('q');
  if (!box || !input) return;
  var root = box.dataset.root, data = null;
  function norm(s) { return (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }
  function section(title, items, render) {
    if (!items.length) return;
    box.appendChild(el('p', 'cta-kicker', title));
    var ul = el('ul', 'sresults');
    items.forEach(function (x) { ul.appendChild(render(x)); });
    box.appendChild(ul);
  }
  function link(href, text, meta) {
    var li = el('li'), a = el('a', null, text); a.href = root + href; li.appendChild(a);
    if (meta) li.appendChild(el('span', 'smeta', meta));
    return li;
  }
  function run() {
    var raw = input.value.trim(), q = norm(raw);
    box.innerHTML = '';
    if (history.replaceState) history.replaceState(null, '', q ? '?q=' + encodeURIComponent(raw) : location.pathname);
    if (!q || !data) return;
    var words = q.split(/\s+/);
    function hit(s) { s = norm(s); return words.every(function (w) { return s.indexOf(w) !== -1; }); }
    var ms = data.managers.filter(function (m) { return hit(m.n + ' ' + m.f + ' ' + m.s); });
    var cs = data.companies.filter(function (c) { return hit(c.n + ' ' + c.t); });
    // an exact ticker match goes first
    cs.sort(function (a, b) { return (norm(b.t).split(' ').indexOf(q) !== -1) - (norm(a.t).split(' ').indexOf(q) !== -1) || b.h - a.h; });
    section('Managers', ms, function (m) { return link(m.u, m.n + ', ' + m.f, m.s); });
    section('Companies', cs.slice(0, 40), function (c) {
      var who = c.h ? c.h + (c.h === 1 ? ' manager holds it now' : ' managers hold it now') : 'No manager holds it now';
      return link(c.u, c.n, (c.t ? c.t + ' · ' : '') + who);
    });
    if (cs.length > 40) box.appendChild(el('p', 'small', (cs.length - 40) + ' more companies match. Add a word to narrow it down.'));
    if (!ms.length && !cs.length) box.appendChild(el('p', 'small', 'Nothing found. The site only covers the managers on the Managers page and what their 13Fs have held.'));
  }
  fetch(box.dataset.index).then(function (r) { return r.json(); }).then(function (d) {
    data = d;
    var p = new URLSearchParams(location.search).get('q');
    if (p) input.value = p;
    run();
  });
  input.addEventListener('input', run);
})();
