/* Sighting map in reports (Leaflet + OpenStreetMap). Numbered pins match the list under the map. */
(function () {
  "use strict";
  function init() {
    if (!window.L) return;
    Array.prototype.forEach.call(document.querySelectorAll(".r-map[data-points]"), function (el) {
      if (el._map) return;
      var pts = [];
      try { pts = JSON.parse(el.getAttribute("data-points")) || []; } catch (e) { return; }
      if (!pts.length) return;
      var map = L.map(el, { scrollWheelZoom: false, attributionControl: true, tap: false });
      el._map = map;
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18, referrerPolicy: "strict-origin-when-cross-origin",
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'
      }).addTo(map);
      var ll = [];
      pts.forEach(function (p) {
        var icon = L.divIcon({ className: "", html: '<span class="r-mk">' + p.n + "</span>", iconSize: [24, 24], iconAnchor: [12, 12] });
        var m = L.marker([p.lat, p.lon], { icon: icon, keyboard: false }).addTo(map);
        var tip = (p.label || "") + (p.time ? " · " + p.time : "");
        if (tip) m.bindTooltip(tip.replace(/[<>&]/g, ""), { direction: "top", offset: [0, -10] });
        ll.push([p.lat, p.lon]);
      });
      if (ll.length === 1) map.setView(ll[0], 12);
      else map.fitBounds(ll, { padding: [28, 28], maxZoom: 13 });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  window.addEventListener("load", init);
  window.addEventListener("beforeprint", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".r-map"), function (el) { if (el._map) el._map.invalidateSize(); });
  });
})();
