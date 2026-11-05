/* Apply the saved theme before first paint (load this synchronously in <head>).
   Stored value: "light" | "dark" | "system" (default). System = no data-theme attribute. */
(function () {
  var KEY = "snipscout.theme";
  function read() { try { return localStorage.getItem(KEY) || "system"; } catch (e) { return "system"; } }
  function apply(mode) {
    var root = document.documentElement;
    if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode);
    else root.removeAttribute("data-theme");
  }
  apply(read());
  /* index.html drives screens inside iframes: accept {type:"theme", mode} messages. */
  window.addEventListener("message", function (e) {
    if (e.data && e.data.type === "theme") apply(e.data.mode);
  });
  window.SnipScoutTheme = {
    get: read,
    set: function (mode) {
      try { localStorage.setItem(KEY, mode); } catch (e) { /* private mode: still apply for this page */ }
      apply(mode);
      document.dispatchEvent(new CustomEvent("themechange", { detail: mode }));
    },
    /* Wire every [data-theme-switch] segmented control on the page. */
    bind: function () {
      document.querySelectorAll("[data-theme-switch] button").forEach(function (b) {
        b.setAttribute("aria-pressed", String(b.dataset.mode === read()));
        b.addEventListener("click", function () {
          window.SnipScoutTheme.set(b.dataset.mode);
          document.querySelectorAll("[data-theme-switch] button").forEach(function (x) {
            x.setAttribute("aria-pressed", String(x.dataset.mode === b.dataset.mode));
          });
        });
      });
    },
  };
})();
