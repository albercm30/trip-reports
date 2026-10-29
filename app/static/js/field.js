/* Field tools that work with no coverage: voice notes and GPS positions.
   Everything is kept on the phone (IndexedDB) first, then sent when there's a connection:
   voice notes are turned into text and added to the day's notes, positions go on the map. */
(function () {
  "use strict";
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || "";
  var T = {};
  try { T = JSON.parse((document.getElementById("i18n") || {}).textContent || "{}"); } catch (e) { T = {}; }
  var t = function (k) { return T[k] || k; };
  var canSend = !!csrf && !document.body.hasAttribute("data-offline-page");

  function toast(msg) {
    var el = document.getElementById("toast");
    if (!el) { var s = document.querySelector("[data-field-msg]"); if (s) s.textContent = msg; return; }
    el.textContent = msg; el.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(function () { el.hidden = true; }, 5000);
  }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
  // positions and notes keep the guide's wall-clock time (no time zone), as it was on the boat
  function localIso(d) {
    var p = function (n) { return ("0" + n).slice(-2); };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }
  function hhmm(d) { return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2); }

  /* ---------- storage on the phone */
  var dbp = null;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise(function (ok, bad) {
      if (!window.indexedDB) return bad(new Error("no idb"));
      var r = indexedDB.open("field", 1);
      r.onupgradeneeded = function () { r.result.createObjectStore("items", { keyPath: "id" }); };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { bad(r.error); };
    });
    return dbp;
  }
  function tx(mode, fn) {
    return db().then(function (d) {
      return new Promise(function (ok, bad) {
        var x = d.transaction("items", mode), st = x.objectStore("items"), res;
        res = fn(st);
        x.oncomplete = function () { ok(res && res.result !== undefined ? res.result : res); };
        x.onerror = function () { bad(x.error); };
      });
    });
  }
  var put = function (it) { return tx("readwrite", function (s) { s.put(it); }).then(refresh); };
  var del = function (id) { return tx("readwrite", function (s) { s.delete(id); }).then(refresh); };
  var all = function () { return tx("readonly", function (s) { return s.getAll(); }).then(function (r) { return r || []; }); };
  if (navigator.storage && navigator.storage.persist) { try { navigator.storage.persist(); } catch (e) {} }

  /* ---------- sending */
  var syncing = false;
  function dayForm(dayId) { return dayId ? document.querySelector('form[data-day-id="' + dayId + '"]') : null; }
  function insertNotes(dayId, text) {
    var f = dayForm(dayId), box = f && f.querySelector('textarea[name="notes"]');
    if (!box || !text) return false;
    box.value = box.value.replace(/\s+$/, "") + (box.value.trim() ? "\n" : "") + text;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  }
  function sendOne(it) {
    var url, opts = { method: "POST", credentials: "same-origin", headers: { "X-Requested-With": "fetch", "X-CSRF-Token": csrf } };
    var open = it.dayId && dayForm(it.dayId);
    if (it.kind === "voice") {
      var fd = new FormData();
      var ext = /mp4|m4a|aac/.test(it.mime) ? "m4a" : (/ogg/.test(it.mime) ? "ogg" : "webm");
      fd.append("audio", it.blob, "note." + ext);
      fd.append("at", it.at); fd.append("lang", it.lang || "");
      fd.append("append", open ? "0" : "1");
      url = it.dayId ? "/app/trips/" + it.tripId + "/days/" + it.dayId + "/voice" : "/app/field/voice";
      opts.body = fd;
    } else {
      url = it.dayId ? "/app/trips/" + it.tripId + "/days/" + it.dayId + "/points" : "/app/field/points";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify({ id: it.id, lat: it.lat, lon: it.lon, acc: it.acc, label: it.label, at: it.at });
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { status: r.status, j: j }; });
    }).then(function (res) {
      if (res.status === 200 && res.j.ok) {
        if (it.kind === "voice") {
          if (open) insertNotes(it.dayId, res.j.text);
          toast(res.j.text ? t("Voice note added to your notes.") : t("The voice note was empty."));
        } else {
          addPointRow(it.dayId || res.j.day, res.j.point);
        }
        return del(it.id);
      }
      it.tries = (it.tries || 0) + 1;
      it.error = res.j.error || String(res.status);
      if (res.status === 400 || res.status === 413 || it.tries > 20) it.failed = true;
      return put(it);
    });
  }
  function sync() {
    if (!canSend || syncing || navigator.onLine === false) return Promise.resolve();
    syncing = true;
    return all().then(function (items) {
      items = items.filter(function (i) { return !i.failed && i.error !== "no_day"; })
        .sort(function (a, b) { return a.at < b.at ? -1 : 1; });
      return items.reduce(function (p, it) { return p.then(function () { return sendOne(it); }); }, Promise.resolve());
    }).catch(function () {}).then(function () { syncing = false; refresh(); });
  }
  window.addEventListener("online", function () { setTimeout(sync, 1500); });
  setInterval(function () { sync(); }, 90000);

  /* ---------- the "waiting to send" panel */
  var urls = {};
  function refresh() {
    var box = document.getElementById("field-pending");
    if (!box) return;
    all().then(function (items) {
      box.hidden = !items.length;
      if (!items.length) return;
      var v = items.filter(function (i) { return i.kind === "voice"; }).length, p = items.length - v;
      var list = box.querySelector("ul"); list.innerHTML = "";
      box.querySelector("[data-count]").textContent =
        t("Saved on this phone, waiting to be sent:") + " " + [v ? v + " " + t("voice note(s)") : "", p ? p + " " + t("position(s)") : ""].filter(Boolean).join(", ");
      var openDay = document.querySelector("details.day[open] form[data-day-id]");
      items.sort(function (a, b) { return a.at < b.at ? -1 : 1; }).forEach(function (it) {
        var li = document.createElement("li");
        var when = new Date(it.at);
        var what = it.kind === "voice" ? "🎙 " + hhmm(when) : "📍 " + hhmm(when) + (it.label ? " · " + it.label : "");
        var s = document.createElement("span"); s.textContent = what; li.appendChild(s);
        if (it.kind === "voice" && it.blob && window.URL) {
          var a = document.createElement("audio"); a.controls = true; a.preload = "none";
          a.src = urls[it.id] || (urls[it.id] = URL.createObjectURL(it.blob)); li.appendChild(a);
        }
        var note = document.createElement("small");
        note.textContent = it.failed ? t("Couldn't be sent.") :
          (it.error === "no_day" ? t("No outing on that date. Open the right one and press “Add here”.") :
          (it.error === "unavailable" ? t("Speech-to-text isn't available right now. It will try again.") : ""));
        li.appendChild(note);
        if ((it.error === "no_day" || !it.dayId) && openDay && canSend) {
          var add = document.createElement("button"); add.type = "button"; add.className = "btn small";
          add.textContent = t("Add here");
          add.addEventListener("click", function () {
            it.dayId = openDay.getAttribute("data-day-id"); it.tripId = openDay.getAttribute("data-trip-id");
            it.error = null; it.failed = false; it.tries = 0;
            put(it).then(sync);
          });
          li.appendChild(add);
        }
        var rm = document.createElement("button"); rm.type = "button"; rm.className = "btn small ghost danger";
        rm.textContent = t("Delete");
        rm.addEventListener("click", function () { if (window.confirm(t("Delete this from the phone? It hasn't been sent."))) del(it.id); });
        li.appendChild(rm);
        list.appendChild(li);
      });
    }).catch(function () { box.hidden = true; });
  }
  var sendNow = document.getElementById("field-send");
  if (sendNow) sendNow.addEventListener("click", function () {
    all().then(function (items) {
      return Promise.all(items.map(function (i) { if (i.failed || i.error) { i.failed = false; i.error = null; i.tries = 0; return put(i); } }));
    }).then(sync);
  });

  /* ---------- voice notes */
  function pickMime() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    var c = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"];
    for (var i = 0; i < c.length; i++) if (MediaRecorder.isTypeSupported(c[i])) return c[i];
    return "";
  }
  function speakLang() {
    var v = null;
    try { v = localStorage.getItem("dictLang"); } catch (e) {}
    return (v || document.documentElement.lang || "es").slice(0, 2);
  }
  $$("[data-voice]").forEach(function (box) {
    var btn = box.querySelector("button"), state = box.querySelector("[data-voice-state]");
    if (!window.MediaRecorder || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      box.hidden = true; return;
    }
    box.hidden = false;
    var rec = null, chunks = [], started = 0, tick = null, limit = null, lbl = btn.querySelector(".lbl"), idle = lbl.textContent;
    function stopUi() {
      clearInterval(tick); clearTimeout(limit);
      btn.classList.remove("on"); btn.setAttribute("aria-pressed", "false"); lbl.textContent = idle;
    }
    btn.addEventListener("click", function () {
      if (rec && rec.state === "recording") { rec.stop(); return; }
      navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }).then(function (stream) {
        var mime = pickMime();
        try { rec = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined); }
        catch (e) { rec = new MediaRecorder(stream); }
        chunks = []; started = Date.now();
        rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
        rec.onstop = function () {
          stream.getTracks().forEach(function (tr) { tr.stop(); });
          stopUi();
          var type = rec.mimeType || mime || "audio/webm";
          var blob = new Blob(chunks, { type: type });
          if (Date.now() - started < 800 || !blob.size) { state.textContent = ""; return; }
          var it = { id: uid(), kind: "voice", blob: blob, mime: type, at: localIso(new Date(started)), lang: speakLang(),
                     dayId: box.getAttribute("data-day") || null, tripId: box.getAttribute("data-trip") || null };
          put(it).then(function () {
            state.textContent = navigator.onLine === false || !canSend ? t("Saved on the phone. It will be turned into text when you have signal.") : t("Turning it into text…");
            return sync();
          }).then(function () { state.textContent = ""; }).catch(function () { toast(t("Couldn't save the voice note on this phone.")); });
        };
        rec.start(1000);
        btn.classList.add("on"); btn.setAttribute("aria-pressed", "true");
        tick = setInterval(function () {
          var s = Math.floor((Date.now() - started) / 1000);
          lbl.textContent = t("Stop") + " · " + Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
        }, 500);
        lbl.textContent = t("Stop") + " · 0:00";
        limit = setTimeout(function () { if (rec && rec.state === "recording") rec.stop(); }, 5 * 60 * 1000);
      }).catch(function () { toast(t("Allow microphone access in your browser to record.")); });
    });
    window.addEventListener("pagehide", function () { if (rec && rec.state === "recording") rec.stop(); });
  });

  /* ---------- GPS positions */
  function addPointRow(dayId, p) {
    var list = dayId && document.querySelector('[data-points-list="' + dayId + '"]');
    if (!list || !p) return;
    if (list.querySelector('[data-point-id="' + p.id + '"]')) return;
    var li = document.createElement("li"); li.setAttribute("data-point-id", p.id);
    var d = p.at ? new Date(p.at) : null;
    li.textContent = "📍 " + (d ? hhmm(d) + " · " : "") + (p.label || "—") + "  (" + p.lat.toFixed(4) + ", " + p.lon.toFixed(4) + ")";
    list.appendChild(li);
    var empty = list.parentNode.querySelector("[data-points-empty]"); if (empty) empty.hidden = true;
  }
  $$("[data-gps]").forEach(function (box) {
    var btn = box.querySelector("button"), input = box.querySelector("input"), state = box.querySelector("[data-gps-state]");
    if (!navigator.geolocation) { box.hidden = true; return; }
    box.hidden = false;
    btn.addEventListener("click", function () {
      btn.disabled = true; state.textContent = t("Getting your position…");
      navigator.geolocation.getCurrentPosition(function (pos) {
        var it = { id: uid(), kind: "point", lat: pos.coords.latitude, lon: pos.coords.longitude,
                   acc: Math.round(pos.coords.accuracy || 0), label: (input && input.value.trim()) || "",
                   at: localIso(new Date(pos.timestamp || Date.now())),
                   dayId: box.getAttribute("data-day") || null, tripId: box.getAttribute("data-trip") || null };
        put(it).then(function () {
          btn.disabled = false; if (input) input.value = "";
          state.textContent = t("Position saved") + " (±" + it.acc + " m)" + (navigator.onLine === false || !canSend ? ". " + t("It will be sent when you have signal.") : ".");
          sync();
        });
      }, function (err) {
        btn.disabled = false;
        state.textContent = err && err.code === 1 ? t("Allow location access in your browser to save positions.") : t("Couldn't get a GPS fix. Try again in the open.");
      }, { enableHighAccuracy: true, timeout: 30000, maximumAge: 15000 });
    });
  });

  refresh();
  setTimeout(sync, 800);
})();
