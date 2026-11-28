/* Shared account code: sign-in, the course lists (Library, Favourite, My Courses),
   and the press-and-hold (phone) and right-click (computer) menu on course cards. */
(function () {
  var CFG = window.HUB_CONFIG || {};
  var ROOT = /\/(account|admin)\//.test(location.pathname) ? '../' : '';
  var READY = !!(CFG.supabaseUrl && CFG.supabaseAnonKey && CFG.supabaseUrl.indexOf('PASTE') < 0);
  var client = null;

  function loadLibrary() {
    return new Promise(function (resolve, reject) {
      if (window.supabase) return resolve(window.supabase);
      var s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';
      s.onload = function () { resolve(window.supabase); };
      s.onerror = function () { reject(new Error('Could not load the sign-in library.')); };
      document.head.appendChild(s);
    });
  }
  var ready = READY
    ? loadLibrary().then(function (sb) { client = sb.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey); return client; })
    : Promise.resolve(null);

  function user() {
    return ready.then(function (c) {
      if (!c) return null;
      return c.auth.getUser().then(function (r) { return r.data.user; });
    });
  }

  var HUB = (window.HUB = {
    root: ROOT,
    ready: READY,
    user: user,
    client: function () { return client; },
    ensureReady: function () { return ready; },
    requireLogin: function () {
      return user().then(function (u) {
        if (!u) location.href = ROOT + 'account/login.html?next=' + encodeURIComponent(location.pathname + location.search);
        return u;
      });
    },
    profile: function () {
      return user().then(function (u) {
        if (!u) return null;
        return client.from('profiles').select('*').eq('id', u.id).single().then(function (r) { return r.data; });
      });
    },
    addCourse: function (courseId, list) {
      return HUB.requireLogin().then(function (u) {
        if (!u) return null;
        return client.from('user_courses').upsert({ user_id: u.id, course_id: courseId, list: list },
          { onConflict: 'user_id,course_id,list' });
      });
    },
    removeCourse: function (courseId, list) {
      return user().then(function (u) {
        if (!u) return null;
        return client.from('user_courses').delete().eq('user_id', u.id).eq('course_id', courseId).eq('list', list);
      });
    },
    listCourses: function (list) {
      return user().then(function (u) {
        if (!u) return [];
        return client.from('user_courses').select('course_id').eq('user_id', u.id).eq('list', list)
          .order('created_at', { ascending: false })
          .then(function (r) { return (r.data || []).map(function (x) { return x.course_id; }); });
      });
    },
    catalogue: function () {
      var out = [];
      return fetch(ROOT + 'courses/index.json?t=' + Date.now(), { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : []; })
        .catch(function () { return []; })
        .then(function (idx) {
          idx.forEach(function (c) { out.push(c); });
          return fetch(ROOT + 'manual-upload.txt?t=' + Date.now(), { cache: 'no-store' }).then(function (r) { return r.ok ? r.text() : ''; })
            .catch(function () { return ''; })
            .then(function (txt) {
              txt.split('\n').forEach(function (raw) {
                var line = raw.trim(); if (!line || line.charAt(0) === '#') return;
                var flags = (line.match(/\[([^\]]+)\]/g) || []).map(function (m) { return m.slice(1, -1).trim().toLowerCase(); });
                var title = line.replace(/\[[^\]]+\]/g, '').trim();
                var kind = flags.indexOf('pdf') >= 0 ? 'pdf' : flags.indexOf('html') >= 0 ? 'html' : null;
                if (!kind || !title) return;
                var id = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
                var depts = flags.filter(function (f) { return f.indexOf('dept=') === 0; })
                  .reduce(function (a, f) { return a.concat(f.slice(5).split('+')); }, []).filter(Boolean);
                var code = ((flags.filter(function (f) { return f.indexOf('code=') === 0; })[0] || '').slice(5)).toUpperCase();
                if (!out.some(function (c) { return c.id === id; }))
                  out.push({ id: id, title: title, kind: kind, depts: depts, code: code, school: flags.indexOf('school') >= 0,
                             total: 1, ready: 1, manual: true, url: '../manual/' + kind + '/' + id + (kind === 'pdf' ? '.pdf' : '.html') });
              });
              return out;
            });
        });
    },
    openLink: function (c) {
      if (c.kind === 'pdf') return ROOT + (c.url || 'courses/pdf/' + c.id + '.pdf');
      return ROOT + 'reader.html#/c/' + c.id;
    },
    toast: function (msg) {
      var t = document.getElementById('hub-toast');
      if (!t) { t = document.createElement('div'); t.id = 'hub-toast'; document.body.appendChild(t); }
      t.textContent = msg; t.className = 'show';
      clearTimeout(t._h); t._h = setTimeout(function () { t.className = ''; }, 2200);
    }
  });

  /* ---- press and hold (phone) and right click (computer) on course cards ---- */
  var css = document.createElement('style');
  css.textContent =
    '#hub-menu{position:fixed;z-index:999;display:none;min-width:220px;background:#fff;border:1px solid #d8d2bf;border-radius:14px;' +
    'box-shadow:0 12px 30px rgba(0,0,0,.18);padding:6px;font:600 15px Inter,system-ui,sans-serif}' +
    '#hub-menu button{display:flex;width:100%;align-items:center;gap:10px;background:none;border:0;padding:12px 12px;border-radius:10px;' +
    'color:#14221c;text-align:left;cursor:pointer;font:inherit}#hub-menu button:hover{background:#f1efe6}' +
    '#hub-toast{position:fixed;left:50%;bottom:90px;transform:translateX(-50%) translateY(20px);background:#14221c;color:#fff;' +
    'padding:12px 18px;border-radius:12px;opacity:0;transition:.25s;z-index:1000;font:600 14px Inter,sans-serif;pointer-events:none}' +
    '#hub-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}';
  document.head.appendChild(css);

  var menu = document.createElement('div');
  menu.id = 'hub-menu';
  menu.innerHTML = '<button type="button" data-l="library">&#128278;&nbsp; Add to Library</button>' +
                   '<button type="button" data-l="favourite">&#10084;&nbsp; Add to Favourite</button>';
  document.body.appendChild(menu);
  var current = null, suppressClick = false;

  function showMenu(x, y, id) {
    current = id;
    menu.style.left = Math.min(x, window.innerWidth - 240) + 'px';
    menu.style.top = Math.min(y, window.innerHeight - 120) + 'px';
    menu.style.display = 'block';
  }
  function hideMenu() { menu.style.display = 'none'; current = null; }

  function courseIdFrom(el) {
    var n = el && el.closest && el.closest('[data-c]');
    return n ? n.getAttribute('data-c') : null;
  }
  document.addEventListener('contextmenu', function (e) {
    var id = courseIdFrom(e.target);
    if (!id) return;
    e.preventDefault();
    showMenu(e.clientX, e.clientY, id);
  });
  var pressTimer = null, startX = 0, startY = 0;
  document.addEventListener('touchstart', function (e) {
    var id = courseIdFrom(e.target);
    if (!id) return;
    startX = e.touches[0].clientX; startY = e.touches[0].clientY;
    pressTimer = setTimeout(function () {
      suppressClick = true;
      showMenu(startX, startY, id);
      if (navigator.vibrate) navigator.vibrate(20);
    }, 500);
  }, { passive: true });
  ['touchend', 'touchcancel'].forEach(function (ev) {
    document.addEventListener(ev, function () { clearTimeout(pressTimer); }, { passive: true });
  });
  document.addEventListener('touchmove', function (e) {
    var t = e.touches[0];
    if (Math.abs(t.clientX - startX) > 10 || Math.abs(t.clientY - startY) > 10) clearTimeout(pressTimer);
  }, { passive: true });
  document.addEventListener('click', function (e) {
    if (suppressClick) { e.preventDefault(); e.stopPropagation(); suppressClick = false; return; }
    if (menu.style.display === 'block' && !menu.contains(e.target)) hideMenu();
  }, true);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideMenu(); });

  menu.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-l]');
    if (!b || !current) return;
    var list = b.getAttribute('data-l'), id = current;
    hideMenu();
    HUB.addCourse(id, list).then(function (r) {
      if (r === null) return;
      if (r && r.error) return HUB.toast('Could not save: ' + r.error.message);
      HUB.toast(list === 'library' ? 'Added to Library' : 'Added to Favourite');
    });
  });
  if (!READY) document.addEventListener('DOMContentLoaded', function () { /* menu works once sign-in is connected */ });
})();
