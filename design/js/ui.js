/* Small shared helpers for the static screens (no framework). */
(function () {
  /* Deterministic pseudo-waveform heights (same shape as the reference). */
  function heights(n, scale) {
    var out = [];
    for (var i = 0; i < n; i++) {
      var h = 8 + Math.abs(Math.sin(i * 0.7) * 18 + Math.sin(i * 1.9) * 10 + Math.sin(i * 0.23) * 6);
      out.push((h * (scale || 1)).toFixed(1));
    }
    return out;
  }

  /* Render bars into el. classFor(i) returns "", "in", "done" or "todo". */
  function wave(el, n, classFor, scale) {
    el.innerHTML = heights(n, scale).map(function (h, i) {
      return '<i class="' + (classFor ? classFor(i) : "") + '" style="--h:' + h + '"></i>';
    }).join("");
    return el;
  }

  var toastTimer;
  function toast(text, actionLabel) {
    var t = document.getElementById("toast");
    if (!t) {
      t = document.createElement("div");
      t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); t.setAttribute("aria-live", "polite");
      document.body.appendChild(t);
    }
    t.innerHTML = "<span></span>" + (actionLabel ? '<button class="btn btn--ghost" type="button">' + actionLabel + "</button>" : "");
    t.firstChild.textContent = text;
    t.classList.add("is-open");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("is-open"); }, 3200);
  }

  /* Modal: <div class="scrim" id="..."> with [data-close] buttons. Returns focus on close. */
  function openModal(id, opener) {
    var scrim = document.getElementById(id);
    scrim.classList.add("is-open");
    scrim.setAttribute("aria-hidden", "false");
    var first = scrim.querySelector("button");
    if (first) first.focus();
    function close() {
      scrim.classList.remove("is-open");
      scrim.setAttribute("aria-hidden", "true");
      document.removeEventListener("keydown", onKey);
      if (opener) opener.focus();
    }
    function onKey(e) { if (e.key === "Escape") close(); }
    document.addEventListener("keydown", onKey);
    scrim.querySelectorAll("[data-close]").forEach(function (b) { b.onclick = close; });
    scrim.onclick = function (e) { if (e.target === scrim) close(); };
    return close;
  }

  /* Segmented controls: [data-seg] containers with buttons using aria-pressed. */
  function bindSegs(root) {
    (root || document).querySelectorAll("[data-seg]").forEach(function (seg) {
      seg.addEventListener("click", function (e) {
        var b = e.target.closest("button");
        if (!b || !seg.contains(b)) return;
        seg.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        seg.dispatchEvent(new CustomEvent("segchange", { detail: b.dataset.value || b.textContent.trim() }));
      });
    });
  }

  window.UI = { heights: heights, wave: wave, toast: toast, openModal: openModal, bindSegs: bindSegs };
})();
