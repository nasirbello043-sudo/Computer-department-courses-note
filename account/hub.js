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
