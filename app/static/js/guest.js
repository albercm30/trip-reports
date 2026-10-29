/* Guests' QR page: show how many photos are picked, and stop double uploads. */
(function () {
  var f = document.querySelector(".g-file input");
  if (f) f.addEventListener("change", function () {
    var lbl = f.parentNode, n = f.files ? f.files.length : 0;
    lbl.classList.toggle("has", n > 0);
    var s = lbl.querySelector("span");
    if (!s.getAttribute("data-label")) s.setAttribute("data-label", s.textContent);
    s.textContent = n ? "📷 " + n + " ✓" : s.getAttribute("data-label");
  });
  Array.prototype.forEach.call(document.querySelectorAll(".g-form"), function (form) {
    form.addEventListener("submit", function () {
      var b = form.querySelector(".g-btn");
      if (b) setTimeout(function () { b.disabled = true; b.textContent = "…"; }, 0);
    });
  });
})();
