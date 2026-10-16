window.STUDY_CONFIG = {
  worker: 'https://nova-r1pl.onrender.com'
};

// Keeps the chat above the phone keyboard (no empty green gap).
(function () {
  function fitToScreen() {
    var height = (window.visualViewport && window.visualViewport.height) || window.innerHeight;
    var app = document.querySelector('.app');
    if (app) app.style.height = height + 'px';
    window.scrollTo(0, 0);
  }
  if (window.visualViewport) window.visualViewport.addEventListener('resize', fitToScreen);
  window.addEventListener('resize', fitToScreen);
  window.addEventListener('load', fitToScreen);
  fitToScreen();
})();
