/* Learning Hub updates badge: shows how many updates (lessons, courses, news) the student has not seen,
   on every Updates link (bottom bar and home page). The Updates page marks everything as seen.
   The seen list is stored on the phone only. Nothing is sent anywhere. */
(function () {
  var script = document.currentScript;
  var base = (script && script.getAttribute('data-base')) || '';
  var KEY = 'lh-seen-updates';
  var LINK = 'a[href$="tools/updates.html"]';

  function getSeen() {
    try { var v = JSON.parse(localStorage.getItem(KEY)); return Array.isArray(v) ? v : null; } catch (e) { return null; }
  }
  function setSeen(ids) {
    try { localStorage.setItem(KEY, JSON.stringify(ids)); } catch (e) {}
  }
  function addStyle() {
    var style = document.createElement('style');
    style.textContent =
      LINK + '{position:relative}' +
      '.lh-badge{position:absolute;top:4px;left:calc(50% + 6px);min-width:19px;height:19px;padding:0 5px;border-radius:10px;' +
      'background:#e8c96a;color:#1b4332;font:700 11px/19px Arial,sans-serif;text-align:center;display:none;' +
      'box-shadow:0 0 0 2px var(--green,#1b4332);pointer-events:none}';
    document.head.appendChild(style);
  }
  function showCount(count) {
    if (count <= 0) return;
    var label = count > 9 ? '9+' : String(count);
    document.querySelectorAll(LINK).forEach(function (a) {
      var badge = document.createElement('span');
      badge.className = 'lh-badge';
      badge.textContent = label;
      badge.style.display = 'block';
      a.appendChild(badge);
    });
  }

  var marking = document.body && document.body.hasAttribute('data-mark-seen');
  if (!marking) addStyle();
  fetch(base + 'courses/updates/index.json', { cache: 'no-cache' })
    .then(function (r) { return r.ok ? r.json() : []; })
    .then(function (items) {
      var ids = items.map(function (i) { return i.id; });
      var seen = getSeen();
      if (seen === null) { seen = ids; setSeen(seen); }   // first visit: start at zero, no flood
      if (marking) { setSeen(ids); return; }             // the Updates page: everything is now seen
      var unseen = ids.filter(function (id) { return seen.indexOf(id) < 0; }).length;
      showCount(unseen);
    })
    .catch(function () {});
})();
