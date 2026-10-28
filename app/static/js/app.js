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


  /* ---------- dictation (browser speech recognition, free; hidden where unsupported) */
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var DICT_LANGS = [["es-ES", "ES"], ["en-GB", "EN"], ["de-DE", "DE"], ["fr-FR", "FR"]];
  var isAndroid = /Android/i.test(navigator.userAgent);
  var active = null; // {stop: fn}
  function stopDictation() { if (active) active.stop(); }
  function getDictLang() {
    var v = null;
    try { v = localStorage.getItem("dictLang"); } catch (e) {}
    if (v && DICT_LANGS.some(function (l) { return l[0] === v; })) return v;
    return (document.documentElement.lang || "en").slice(0, 2) === "es" ? "es-ES" : "en-GB";
  }
  function setDictLang(v) {
    try { localStorage.setItem("dictLang", v); } catch (e) {}
    $$("select.dictate-lang").forEach(function (s) { s.value = v; });
  }
  if (SR) $$("textarea[data-dictate]").forEach(function (box) {
    if (box.disabled || box.closest("fieldset[disabled]")) return;
    var bar = document.createElement("div");
    bar.className = "dictate-bar";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small dictate";
    btn.setAttribute("aria-pressed", "false");
    var label = t("Dictate"), stopLabel = t("Stop dictating");
    btn.innerHTML = '<span class="mic" aria-hidden="true"></span><span class="lbl"></span>';
    btn.querySelector(".lbl").textContent = label;
    var sel = document.createElement("select");
    sel.className = "dictate-lang";
    sel.setAttribute("aria-label", t("Language you will speak"));
    DICT_LANGS.forEach(function (l) { var o = document.createElement("option"); o.value = l[0]; o.textContent = l[1]; sel.appendChild(o); });
    sel.value = getDictLang();
    sel.addEventListener("change", function () { setDictLang(sel.value); if (session) { session.stop(); setTimeout(function () { btn.click(); }, 300); } });
    var live = document.createElement("span");
    live.className = "hint dictate-live";
    live.setAttribute("aria-live", "polite");
    bar.appendChild(btn); bar.appendChild(sel); bar.appendChild(live);
    box.insertAdjacentElement("afterend", bar);
    var sep = box.getAttribute("data-dictate-sep") || " ";
    var session = null;

    function insert(text) {
      text = text.trim();
      if (!text) return;
      var v = box.value, start = box.selectionStart, end = box.selectionEnd;
      if (document.activeElement !== box || start == null) { start = end = v.length; }
      var before = v.slice(0, start), after = v.slice(end);
      var glue = !before || /[\s\n]$/.test(before) ? "" : (sep === " " ? " " : sep);
      if (sep === " " && (!before.trim() || /[.!?]\s*$/.test(before))) text = text.charAt(0).toUpperCase() + text.slice(1);
      box.value = before + glue + text + after;
      var pos = (before + glue + text).length;
      try { box.setSelectionRange(pos, pos); } catch (e) {}
      box.dispatchEvent(new Event("input", { bubbles: true }));
    }
    function setOn(on) {
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("on", on);
      btn.querySelector(".lbl").textContent = on ? stopLabel : label;
      if (!on) live.textContent = "";
    }
    btn.addEventListener("click", function () {
      if (session) { session.stop(); return; }
      stopDictation();
      // One session = keep listening until the guide presses Stop. Browsers end recognition after a
      // pause (phones after every sentence), so it restarts by itself while the session is on.
      var wanted = true, rec = null, quiet = 0, lastFinal = "";
      session = active = {
        stop: function () { wanted = false; if (rec) { try { rec.stop(); } catch (e) {} } else finish(); }
      };
      function finish() { setOn(false); if (active === session) active = null; session = null; }
      function startOnce() {
        rec = new SR();
        rec.lang = sel.value;
        rec.continuous = !isAndroid;   // Android repeats words in continuous mode
        rec.interimResults = true;
        rec.maxAlternatives = 1;
        rec.onresult = function (ev) {
          var interim = "";
          quiet = 0;
          for (var i = ev.resultIndex; i < ev.results.length; i++) {
            var r = ev.results[i], tr = r[0].transcript;
            if (r.isFinal) {
              if (tr.trim() && tr.trim() !== lastFinal) insert(tr);
              lastFinal = tr.trim();
            } else interim += tr;
          }
          live.textContent = interim ? "… " + interim : t("Listening…");
        };
        rec.onerror = function (ev) {
          if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
            wanted = false; toast(t("Allow microphone access in your browser to dictate."));
          } else if (ev.error === "language-not-supported") {
            wanted = false; toast(t("This browser can't dictate in that language. Try Chrome, or another language."));
          } else if (ev.error === "network") {
            wanted = false; toast(t("Dictation needs an internet connection."));
          } else if (ev.error === "no-speech") {
            if (++quiet >= 3) { wanted = false; toast(t("Didn't hear anything. Try again closer to the microphone.")); }
          } else if (ev.error !== "aborted") {
            wanted = false; toast(t("Dictation stopped. Try again."));
          }
        };
        rec.onend = function () {
          rec = null;
          if (wanted) setTimeout(function () { if (wanted) { try { startOnce(); } catch (e) { finish(); } } else finish(); }, 150);
          else finish();
        };
        rec.start();
      }
      try { startOnce(); setOn(true); live.textContent = t("Listening…"); box.focus(); }
      catch (e) { finish(); toast(t("Dictation stopped. Try again.")); }
    });
  });
  // stop listening before a form is sent or the page is left
  document.addEventListener("submit", stopDictation, true);
  window.addEventListener("pagehide", stopDictation);

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
        note.textContent = t(res.j.engine === "ai" ? "Drafted with AI. Edit before you publish it." : "Draft ready, built from your numbers. Edit before you publish it.");
      })
      .catch(function () { note.textContent = t("Something went wrong. Try again."); })
      .then(function () { sb.disabled = false; });
  });
})();

/* ---------- admin: AI accuracy tests, one case at a time (free AI plans have per-minute limits) */
(function () {
  var box = document.getElementById("accuracy");
  if (!box) return;
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  var run = document.getElementById("acc-run"), status = document.getElementById("acc-status");
  var out = document.getElementById("acc-json"), summary = document.getElementById("acc-summary");
  function cell(s) {
    if (!s) return "—";
    return (s.ok ? "✅ " : "❌ ") + s.found + "/" + s.expected;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  run.addEventListener("click", function () {
    var rows = Array.prototype.slice.call(box.querySelectorAll("tr[data-case]"));
    var draft = document.getElementById("acc-draft").checked;
    var results = [], i = 0;
    run.disabled = true;
    function next() {
      if (i >= rows.length) {
        var ok = results.filter(function (r) { return r.ai ? r.ai.ok : r.free.ok; }).length;
        var clean = results.filter(function (r) { return r.draft && !r.draft.problems.length; }).length;
        var drafted = results.filter(function (r) { return r.draft; }).length;
        summary.textContent = ok + " / " + results.length + " ✅" + (drafted ? " · " + clean + " / " + drafted + " 📝" : "");
        out.value = JSON.stringify(results, null, 1);
        status.textContent = ""; run.disabled = false;
        return;
      }
      var tr = rows[i], id = tr.getAttribute("data-case");
      status.textContent = (i + 1) + " / " + rows.length + "…";
      tr.querySelector(".c-ai").textContent = "…";
      fetch(box.getAttribute("data-url") + id + (draft ? "?draft=1" : ""), { method: "POST", credentials: "same-origin",
        headers: { "X-Requested-With": "fetch", "X-CSRF-Token": csrf } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          results.push(j);
          tr.querySelector(".c-free").textContent = cell(j.free);
          tr.querySelector(".c-raw").textContent = j.ai_error ? "⚠️ " + j.ai_error : cell(j.ai_raw);
          tr.querySelector(".c-ai").textContent = j.ai_error ? "⚠️ " + j.ai_error : cell(j.ai);
          tr.querySelector(".c-draft").textContent = j.draft ? (j.draft.problems.length ? "❌ " + j.draft.problems.length : "✅") : (j.draft_error ? "⚠️ " + j.draft_error : "—");
          var probs = (j.ai || j.free).problems.concat(j.draft ? j.draft.problems.map(function (p) { return p.kind + ": " + p.what; }) : []);
          tr.querySelector(".acc-detail").innerHTML = probs.map(esc).join("<br>") +
            (j.draft ? "<details><summary>📝</summary>" + esc(j.draft.text) + "</details>" : "");
        })
        .catch(function () { tr.querySelector(".c-ai").textContent = "⚠️"; results.push({ id: id, error: "request" }); })
        .then(function () { i++; next(); });
    }
    next();
  });
})();
