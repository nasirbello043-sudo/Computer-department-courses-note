/* Learning Hub menu: the hamburger opens and closes the menu, Departments folds open and shut,
   and a More section holds Contact us, About us, White paper and Sign in. */
(function () {
  var $ = function (s) { return document.querySelector(s); };
  var sb = $('#sb'), bd = $('#bd'), mt = $('#mt'), list = $('#dl');
  if (!sb || !mt || !bd || !list) return;

  var css = document.createElement('style');
  css.textContent =
    '#mt{position:relative;z-index:60}' +
    '#sb .lh-acc{display:flex;width:100%;align-items:center;justify-content:space-between;background:none;border:0;' +
    'color:#e8c96a;font:600 .72rem/1 Inter,system-ui,Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;padding:14px 4px 10px;cursor:pointer;text-align:left}' +
    '#sb .lh-acc span{font-size:.9rem;letter-spacing:0}' +
    '#sb .lh-item{display:block;width:100%;background:#ffffff0d;border:1px solid #ffffff1a;border-radius:10px;color:#fff;' +
    'padding:12px 14px;margin:0 0 8px;font:600 .95rem Inter,system-ui,Arial,sans-serif;text-align:left;cursor:pointer;text-decoration:none}' +
    '#sb .lh-panel{background:#ffffff0d;border-radius:10px;padding:8px 14px;margin:0 0 8px}' +
    '#sb .lh-panel a{display:block;color:#fff;padding:9px 0;border-bottom:1px solid #ffffff14;text-decoration:none;font-size:.9rem}' +
    '#sb .lh-panel a:last-child{border-bottom:0}' +
    '#sb .lh-panel small{display:block;color:#c9d9cf;font-size:.72rem;margin-top:2px}' +
    '#sb .lh-note{color:#e8c96a;font-size:.82rem;margin:4px 2px 10px}';
  document.head.appendChild(css);

  function setOpen(open) {
    sb.classList.toggle('o', open);
    bd.classList.toggle('o', open);
  }
  mt.onclick = function (e) {
    e.stopPropagation();
    setOpen(!sb.classList.contains('o'));
  };
  bd.onclick = function () { setOpen(false); };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setOpen(false); });

  // Departments: hidden until pressed
  var label = sb.querySelector('.l');
  list.style.display = 'none';
  var deptBtn = document.createElement('button');
  deptBtn.type = 'button';
  deptBtn.className = 'lh-acc';
  deptBtn.innerHTML = 'Departments <span>&#9662;</span>';
  if (label) label.replaceWith(deptBtn); else sb.insertBefore(deptBtn, list);
  deptBtn.onclick = function () {
    var open = list.style.display === 'none';
    list.style.display = open ? '' : 'none';
    deptBtn.querySelector('span').innerHTML = open ? '&#9652;' : '&#9662;';
  };

  // More section
  var more = document.createElement('div');
  more.innerHTML =
    '<div class="lh-acc" style="cursor:default;padding-bottom:8px">More</div>' +
    '<button type="button" class="lh-item" id="lh-contact-btn">Contact us</button>' +
    '<div class="lh-panel" id="lh-contact" style="display:none">' +
      '<a href="https://wa.me/2348111553893" target="_blank" rel="noopener">WhatsApp<small>0811 155 3893</small></a>' +
      '<a href="tel:+2348111553893">Phone<small>0811 155 3893</small></a>' +
      '<a href="mailto:fueklearninghub@gmail.com">Email<small>fueklearninghub@gmail.com</small></a>' +
    '</div>' +
    '<a class="lh-item" href="tools/about.html">About us</a>' +
    '<a class="lh-item" href="tools/whitepaper.html">White paper</a>' +
    '<button type="button" class="lh-item" id="lh-auth">Sign in</button>' +
    '<div class="lh-note" id="lh-note" style="display:none">Sign in is coming soon.</div>';
  sb.appendChild(more);

  var contactBtn = $('#lh-contact-btn'), contact = $('#lh-contact');
  contactBtn.onclick = function () {
    contact.style.display = contact.style.display === 'none' ? '' : 'none';
  };
  var auth = $('#lh-auth'), note = $('#lh-note');
  auth.onclick = function () { note.style.display = ''; };
})();
