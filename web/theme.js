/* Тема: ставится до отрисовки, чтобы не мигало. auto — днём Vice City, вечером и ночью — ночной город. */
(function () {
  var KEY = "lg-theme", DAY_FROM = 6, DAY_TO = 20;
  var COLORS = { vice: "#fff6ef", night: "#0d0f11" };
  function get() { try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; } }
  function resolve(mode) {
    if (mode === "vice" || mode === "night") return mode;
    var h = new Date().getHours();
    return h >= DAY_FROM && h < DAY_TO ? "vice" : "night";
  }
  function apply() {
    var t = resolve(get());
    document.documentElement.setAttribute("data-theme", t);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", COLORS[t]);
  }
  function set(mode) { try { localStorage.setItem(KEY, mode); } catch (e) { /* приватный режим — только на сеанс */ } apply(); }
  apply();
  setInterval(apply, 5 * 60 * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) apply(); });
  window.LGTheme = { get: get, set: set, apply: apply };
})();
