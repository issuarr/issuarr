(function () {
  // Sidebar Service status: the download clients that are turned on (Usenet, torrent, JDownloader).
  var el = document.getElementById('client_status');
  if (!el || !window.jQuery) return;
  function icon(ok) {
    var img = document.createElement('img');
    img.src = ok ? 'images/success.png' : 'images/x_red.png';
    img.height = 8; img.width = 8; img.alt = ok ? 'up' : 'down';
    return img;
  }
  function load() {
    jQuery.getJSON('client_status', function (r) {
      el.textContent = '';
      var clients = (r && r.clients) || [];
      if (!clients.length) return;
      el.appendChild(document.createElement('br'));
      el.appendChild(document.createTextNode('Clients: '));
      clients.forEach(function (c, i) {
        el.appendChild(document.createTextNode((i ? ' · ' : '') + c.name + ' '));
        el.appendChild(icon(c.ok));
      });
    });
  }
  load();
  setInterval(load, 300000);
})();
