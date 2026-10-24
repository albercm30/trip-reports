/* Small progressive enhancements. Every form also works without JavaScript. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  var T = {};
  try { T = JSON.parse((document.getElementById("i18n") || {}).textContent || "{}"); } catch (e) { T = {}; }
  var t = function (k) { return T[k] || k; };

  /* ---------- toast */
  var toastEl = $("#toast"), toastTimer;
  function toast(msg, ms) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.hidden = true; }, ms || 5000);
  }
  if (toastEl && !toastEl.hidden) toastTimer = setTimeout(function () { toastEl.hidden = true; }, 6000);

  /* ---------- save indicator */
  var stateEl = $("#save-state");
  function setState(s) { if (stateEl) stateEl.textContent = s ? t(s) : ""; }

  /* ---------- autosave */
  $$("form[data-autosave]").forEach(function (form) {
    var url = form.getAttribute("data-autosave") || form.action;
    var timer = null, busy = false, again = false, dirty = false;

    function send(keepalive) {
      if (busy) { again = true; return; }
      busy = true; dirty = false; setState("Saving…");
      var body = new FormData(form);
      body.delete("files");
      return fetch(url, {
        method: "POST", body: body, credentials: "same-origin", keepalive: !!keepalive,
        headers: { "X-Requested-With": "fetch", "X-CSRF-Token": csrf }
      }).then(function (r) {
        if (r.status === 401) { setState("Not saved"); toast(t("Your session ended. Log in again to keep saving.")); return; }
        if (r.status === 402) { setState("Not saved"); toast(t("Your trial has ended. Choose a plan to keep editing.")); return; }
        if (!r.ok) throw new Error(r.status);
        setState("Saved");
        return r.json().then(function (j) {
          if (j && typeof j.approved === "boolean") {
            var a = form.querySelector('input[name="approved"]');
            if (a && a.checked !== j.approved) { a.checked = j.approved; if (!j.approved) toast(t("Write the day report before approving it.")); }
          }
        });
      }).catch(function () { setState("Not saved"); dirty = true; })
        .then(function () { busy = false; if (again) { again = false; send(); } });
    }
    function schedule(ms) { dirty = true; setState("Unsaved changes"); clearTimeout(timer); timer = setTimeout(send, ms); }
    form.addEventListener("input", function (e) { if (e.target.type !== "file") schedule(900); });
    form.addEventListener("change", function (e) {
      if (e.target.type === "checkbox" || e.target.tagName === "SELECT" || e.target.type === "date" || e.target.type === "color") schedule(50);
    });
    form.addEventListener("submit", function () { clearTimeout(timer); dirty = false; });
    window.addEventListener("pagehide", function () { if (dirty) { clearTimeout(timer); send(true); } });
    document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden" && dirty) { clearTimeout(timer); send(true); } });
  });

  /* ---------- busy overlay for slow actions (drafting) and confirmations */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-confirm]");
    if (b && !window.confirm(b.getAttribute("data-confirm"))) { e.preventDefault(); e.stopImmediatePropagation(); return; }
    var p = e.target.closest("[data-print]");
    if (p) { e.preventDefault(); window.print(); return; }
    var c = e.target.closest("[data-copy]");
    if (c) {
      e.preventDefault();
      var src = document.getElementById(c.getAttribute("data-copy"));
      var text = src ? (src.value != null ? src.value : src.textContent) : c.getAttribute("data-text");
      copy(text);
    }
  }, true);
  document.addEventListener("submit", function (e) {
    var btn = e.submitter;
    if (btn && btn.hasAttribute("data-busy")) {
      var o = document.createElement("div");
      o.className = "busy";
      o.innerHTML = '<div role="status"><span class="spin" aria-hidden="true"></span><span></span></div>';
      o.querySelector("span:last-child").textContent = btn.getAttribute("data-busy");
      document.body.appendChild(o);
      setTimeout(function () { btn.setAttribute("aria-busy", "true"); }, 0);
      window.addEventListener("pageshow", function () { o.remove(); btn.removeAttribute("aria-busy"); }, { once: true });
    }
  });

  function copy(text) {
    if (!text) return;
    var done = function () { toast(t("Copied.")); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else fallback();
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (err) { toast(t("Couldn't copy. Select the text and copy it yourself.")); }
      ta.remove();
    }
  }

  /* ---------- species row highlight follows the "confirmed" box */
  document.addEventListener("change", function (e) {
    if (e.target.matches('input[data-sure]')) {
      var row = e.target.closest(".sp");
      if (row) row.classList.toggle("unsure", !e.target.checked);
    }
    if (e.target.matches("select[data-nav]")) {
      window.location.href = e.target.value;
    }
  });

  /* ---------- open the day named in the URL */
  var m = location.hash.match(/^#(?:day|sp|narr)-([\w-]+)/);
  if (m) {
    var el = document.getElementById(location.hash.slice(1));
    var det = el && el.closest("details");
    if (det) det.open = true;
    if (el) setTimeout(function () { el.scrollIntoView({ block: "start" }); }, 30);
  }

  /* ---------- long text boxes grow with their content */
  function grow(el) { el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight + 4, 1400) + "px"; }
  $$("textarea.prose").forEach(function (el) { grow(el); el.addEventListener("input", function () { grow(el); }); });

  /* ---------- season summary on the insights page */
  var sb = $("#season-btn");
  if (sb) sb.addEventListener("click", function () {
    var box = $("#season-box"), note = $("#season-note");
    sb.disabled = true; note.textContent = t("Writing…");
    fetch(sb.getAttribute("data-url"), { method: "POST", credentials: "same-origin",
      headers: { "X-Requested-With": "fetch", "X-CSRF-Token": csrf } })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.ok) { note.textContent = t(res.j && res.j.error === "readonly" ? "Your trial has ended. Choose a plan to keep editing." : "Something went wrong. Try again."); return; }
        box.value = res.j.text; grow(box);
        note.textContent = t(res.j.engine === "ai" ? "Drafted with Claude. Edit before you publish it." : "Draft ready, built from your numbers. Edit before you publish it.");
      })
      .catch(function () { note.textContent = t("Something went wrong. Try again."); })
      .then(function () { sb.disabled = false; });
  });
})();
