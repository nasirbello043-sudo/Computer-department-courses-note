/* Nova premium: /code (early-user access) and /image (picture creation).
   Handles only messages that start with /code or /image. Everything else goes to the normal chat untouched. */
(function () {
  var TOKEN_KEY = 'lh-premium-token';
  var cfg = window.STUDY_CONFIG || {};
  var base = (typeof cfg.worker === 'string' && /^(https:\/\/|http:\/\/localhost)/.test(cfg.worker)) ? cfg.worker.replace(/\/$/, '') : '';

  function token() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } }
  function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch (e) {} }

  var css = document.createElement('style');
  css.textContent =
    '.lh-premium .top{background:#0f1a14;border-bottom-color:#e8c96a}' +
    '.lh-premium .ai .bub{border:1px solid #e8c96a;background:#fffdf5}' +
    '.lh-badge-pro{display:inline-block;margin-left:8px;background:#e8c96a;color:#1b4332;font:700 10px Inter,sans-serif;' +
    'letter-spacing:.12em;padding:3px 7px;border-radius:9px;vertical-align:middle}' +
    '.lh-img{display:block;max-width:100%;border-radius:12px;margin-top:6px;border:2px solid #e8c96a}' +
    '#lh-plus{flex:0 0 44px;height:44px;border-radius:50%;border:2px solid #e8c96a;background:#0f1a14;color:#e8c96a;' +
    'font:700 24px Inter,sans-serif;cursor:pointer}';
  document.head.appendChild(css);

  function chatEl() { return document.getElementById('chat'); }
  function addMsg(role, text, opts) {
    var c = chatEl();
    var m = document.createElement('div');
    m.className = 'msg ' + role;
    if (role === 'ai') {
      var av = document.createElement('div');
      av.className = 'av';
      av.textContent = 'NV';
      m.appendChild(av);
    }
    var b = document.createElement('div');
    b.className = 'bub';
    if (opts && opts.typing) {
      b.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
    } else {
      var p = document.createElement('div');
      p.textContent = text;
      b.appendChild(p);
    }
    m.appendChild(b);
    c.appendChild(m);
    c.scrollTop = c.scrollHeight;
    return b;
  }
  function showImage(b, src, remaining) {
    var img = document.createElement('img');
    img.className = 'lh-img';
    img.alt = 'Picture made by Nova';
    img.src = src;
    b.appendChild(img);
    var note = document.createElement('div');
    note.style.cssText = 'font:500 12px Inter,sans-serif;color:#8a6d1f;margin-top:6px';
    note.textContent = 'Pictures left today: ' + remaining;
    b.appendChild(note);
  }
  function clearInput() {
    var q = document.getElementById('q');
    if (q) { q.value = ''; q.dispatchEvent(new Event('input')); }
  }
  function post(path, body) {
    return fetch(base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    });
  }
  function setPremiumLook(on) {
    document.body.classList.toggle('lh-premium', !!on);
    var ttl = document.querySelector('.top .ttl');
    if (on && ttl && !document.querySelector('.lh-badge-pro')) {
      var tag = document.createElement('span');
      tag.className = 'lh-badge-pro';
      tag.textContent = 'PREMIUM';
      ttl.appendChild(tag);
    }
    if (on) addPlusButton();
  }
  var picker = null;
  function addPlusButton() {
    if (document.getElementById('lh-plus')) return;
    var bar = document.querySelector('.inp');
    if (!bar) return;
    picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/jpeg,image/png,image/webp';
    picker.style.display = 'none';
    picker.id = 'lh-picker';
    picker.onchange = function () {
      var f = picker.files && picker.files[0];
      picker.value = '';
      if (f) sendPicture(f);
    };
    document.body.appendChild(picker);
    var plus = document.createElement('button');
    plus.id = 'lh-plus';
    plus.type = 'button';
    plus.textContent = '+';
    plus.setAttribute('aria-label', 'Choose a picture to ask about');
    plus.onclick = function () { picker.click(); };
    bar.insertBefore(plus, bar.firstChild);
  }

  // Makes the picture small enough to send (phone photos can be several megabytes).
  function shrink(file, max) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      var url = URL.createObjectURL(file);
      img.onload = function () {
        var scale = Math.min(1, max / Math.max(img.width, img.height));
        var w = Math.max(1, Math.round(img.width * scale));
        var h = Math.max(1, Math.round(img.height * scale));
        var c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        c.getContext('2d').drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL('image/jpeg', 0.85));
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('picture')); };
      img.src = url;
    });
  }

  function sendPicture(file) {
    if (!file || !/^image\//.test(file.type)) { addMsg('ai', 'Please choose a picture file.'); return; }
    var t = token();
    if (!t) { addMsg('ai', 'Enter your access code first. Type /code followed by your code.'); return; }
    if (!base) { addMsg('ai', 'Nova is not connected yet.'); return; }
    var q = document.getElementById('q');
    var question = q ? q.value.trim() : '';
    clearInput();
    shrink(file, 1024).then(function (dataUrl) {
      var userBub = addMsg('user', question || 'Describe this picture.');
      var thumb = document.createElement('img');
      thumb.className = 'lh-img';
      thumb.alt = 'Your picture';
      thumb.src = dataUrl;
      userBub.appendChild(thumb);
      var b = addMsg('ai', '', { typing: true });
      post('/vision', { token: t, question: question, image: dataUrl }).then(function (res) {
        b.parentNode.remove();
        if (res.ok && res.json.answer) {
          addMsg('ai', res.json.answer + '\n\nPicture questions left today: ' + res.json.remaining);
        } else {
          if (res.status === 401) { try { localStorage.removeItem(TOKEN_KEY); } catch (e) {} setPremiumLook(false); }
          addMsg('ai', (res.json && res.json.error) || 'Nova could not look at that picture. Please try again.');
        }
      }).catch(function () {
        b.parentNode.remove();
        addMsg('ai', 'No internet connection, or Nova is unreachable. Please try again.');
      });
    }).catch(function () {
      addMsg('ai', 'That picture could not be opened. Please try another one.');
    });
  }

  function handleCode(arg) {
    addMsg('user', '/code ' + arg);
    var code = String(arg || '').trim();
    if (!code) { addMsg('ai', 'Type /code followed by your access code, for example /code ABC12345'); return; }
    if (!base) { addMsg('ai', 'Nova is not connected yet.'); return; }
    var b = addMsg('ai', '', { typing: true });
    post('/code', { code: code }).then(function (res) {
      b.parentNode.remove();
      if (res.ok && res.json.token) {
        setToken(res.json.token);
        setPremiumLook(true);
        addMsg('ai', 'Access granted. Premium is on. Type /image followed by a description to make a picture. You can make ' +
          res.json.limits.images + ' pictures a day.');
      } else {
        addMsg('ai', (res.json && res.json.error) || 'That code did not work. Please try again.');
      }
    }).catch(function () {
      b.parentNode.remove();
      addMsg('ai', 'No internet connection, or Nova is unreachable. Please try again.');
    });
  }

  function handleImage(arg) {
    addMsg('user', '/image ' + arg);
    var prompt = String(arg || '').trim();
    var t = token();
    if (!t) { addMsg('ai', 'Enter your access code first. Type /code followed by your code.'); return; }
    if (prompt.length < 3) { addMsg('ai', 'Describe the picture after /image, for example: /image a diagram of an ellipse with its foci.'); return; }
    if (!base) { addMsg('ai', 'Nova is not connected yet.'); return; }
    var b = addMsg('ai', '', { typing: true });
    post('/image', { token: t, prompt: prompt }).then(function (res) {
      b.parentNode.remove();
      if (res.ok && res.json.image) {
        var box = addMsg('ai', 'Here is your picture.');
        showImage(box, res.json.image, res.json.remaining);
      } else {
        if (res.status === 401) { try { localStorage.removeItem(TOKEN_KEY); } catch (e) {} setPremiumLook(false); }
        addMsg('ai', (res.json && res.json.error) || 'Nova could not make that picture. Please try again.');
      }
    }).catch(function () {
      b.parentNode.remove();
      addMsg('ai', 'No internet connection, or Nova is unreachable. Please try again.');
    });
  }

  // Returns true if the text was a premium command and has been handled.
  function runCommand(text) {
    var m = /^\s*\/(code|image)(?:\s+([\s\S]*))?$/i.exec(text || '');
    if (!m) return false;
    clearInput();
    var arg = m[2] || '';
    if (m[1].toLowerCase() === 'code') handleCode(arg); else handleImage(arg);
    return true;
  }

  // Catch the send button and the Enter key before the normal chat does (capture phase).
  document.addEventListener('click', function (e) {
    var send = e.target.closest && e.target.closest('#send');
    if (!send || send.classList.contains('stop')) return;
    var q = document.getElementById('q');
    if (q && runCommand(q.value)) { e.stopImmediatePropagation(); e.preventDefault(); }
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || e.shiftKey || !e.target || e.target.id !== 'q') return;
    if (runCommand(e.target.value)) { e.stopImmediatePropagation(); e.preventDefault(); }
  }, true);

  // Turn premium on for a returning early user (the token is remembered on the phone).
  if (token()) setPremiumLook(true);
})();
