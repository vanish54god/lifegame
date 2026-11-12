/* Тема и живое небо. Тема ставится до отрисовки, чтобы не мигало.
   auto — днём Vice City, вечером и ночью — ночной город. Небо плавно меняется по минутам. */
(function () {
  var KEY = "lg-theme", DAY_FROM = 6, DAY_TO = 20;
  var COLORS = { vice: "#fff6ef", night: "#0d0f11" };
  // [час, верх неба, середина, свечение у горизонта, звёзды 0..1]; цвета — [r, g, b, alpha]
  var SKY = {
    vice: [
      [0,  [90, 70, 150, .38], [150, 120, 210, .14], [130, 100, 210, .18], .5],
      [5,  [130, 100, 180, .32], [210, 160, 200, .16], [255, 170, 150, .26], .2],
      [7,  [255, 186, 165, .50], [255, 222, 200, .26], [255, 178, 140, .42], 0],
      [10, [165, 212, 240, .38], [255, 242, 232, .16], [255, 222, 192, .16], 0],
      [16, [175, 218, 242, .36], [255, 240, 230, .16], [255, 210, 180, .18], 0],
      [18.5, [255, 155, 150, .50], [255, 200, 170, .26], [255, 140, 115, .42], 0],
      [20, [190, 110, 175, .48], [245, 170, 195, .22], [255, 125, 130, .32], .12],
      [22, [110, 85, 160, .42], [180, 140, 210, .16], [150, 110, 200, .2], .4],
      [24, [90, 70, 150, .38], [150, 120, 210, .14], [130, 100, 210, .18], .5]],
    night: [
      [0,  [18, 28, 72, .85], [10, 14, 34, .50], [40, 50, 115, .26], 1],
      [4.5, [22, 30, 76, .85], [12, 16, 38, .50], [50, 55, 120, .26], .95],
      [6,  [75, 52, 95, .62], [40, 30, 50, .30], [240, 140, 90, .26], .3],
      [9,  [38, 66, 108, .45], [18, 28, 42, .20], [240, 165, 58, .10], 0],
      [16, [40, 64, 104, .45], [18, 28, 42, .20], [240, 165, 58, .12], 0],
      [18.5, [115, 52, 72, .56], [52, 26, 36, .30], [240, 118, 60, .32], .08],
      [20, [52, 40, 102, .70], [20, 18, 40, .40], [200, 90, 80, .22], .5],
      [22, [20, 30, 76, .85], [10, 14, 34, .50], [45, 50, 118, .26], .9],
      [24, [18, 28, 72, .85], [10, 14, 34, .50], [40, 50, 115, .26], 1]]
  };
  function get() { try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; } }
  function resolve(mode) {
    if (mode === "vice" || mode === "night") return mode;
    var h = new Date().getHours();
    return h >= DAY_FROM && h < DAY_TO ? "vice" : "night";
  }
  function mix(a, b, t) { return a.map(function (v, i) { return v + (b[i] - v) * t; }); }
  function rgba(c) { return "rgba(" + Math.round(c[0]) + "," + Math.round(c[1]) + "," + Math.round(c[2]) + "," + c[3].toFixed(3) + ")"; }
  function sky(theme) {
    var d = new Date(), h = d.getHours() + d.getMinutes() / 60, k = SKY[theme], i = 0;
    while (i < k.length - 2 && k[i + 1][0] <= h) i++;
    var a = k[i], b = k[i + 1], t = (h - a[0]) / (b[0] - a[0]);
    var st = document.documentElement.style;
    st.setProperty("--sky-top", rgba(mix(a[1], b[1], t)));
    st.setProperty("--sky-mid", rgba(mix(a[2], b[2], t)));
    st.setProperty("--sky-glow", rgba(mix(a[3], b[3], t)));
    st.setProperty("--stars", (a[4] + (b[4] - a[4]) * t).toFixed(2));
  }
  function apply() {
    var t = resolve(get());
    document.documentElement.setAttribute("data-theme", t);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", COLORS[t]);
    sky(t);
  }
  function set(mode) { try { localStorage.setItem(KEY, mode); } catch (e) { /* приватный режим — только на сеанс */ } apply(); }

  // звёзды: одно и то же небо при каждом открытии (псевдослучайные, но с фиксированным зерном)
  function build() {
    var el = document.createElement("div");
    el.className = "sky"; el.setAttribute("aria-hidden", "true");
    var stars = document.createElement("div"); stars.className = "stars";
    var seed = 47, rnd = function () { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    var html = "";
    for (var i = 0; i < 90; i++) {
      var s = rnd() < .85 ? 1.5 : 2.5;
      html += '<i style="left:' + (rnd() * 100).toFixed(2) + '%;top:' + (Math.pow(rnd(), 1.6) * 75).toFixed(2) +
        '%;width:' + s + 'px;height:' + s + 'px;--d:' + (3 + rnd() * 5).toFixed(1) + 's;--dl:-' + (rnd() * 6).toFixed(1) + 's"></i>';
    }
    stars.innerHTML = html;
    var moon = document.createElement("div"); moon.className = "moon";
    el.appendChild(stars); el.appendChild(moon);
    document.body.insertBefore(el, document.body.firstChild);
    // изредка — падающая звезда, если звёзды видны
    setInterval(function () {
      var o = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--stars")) || 0;
      if (o < .6 || document.hidden || Math.random() > .35) return;
      var sh = document.createElement("div"); sh.className = "shooting";
      sh.style.left = (40 + Math.random() * 55) + "%"; sh.style.top = (5 + Math.random() * 30) + "%";
      el.appendChild(sh); setTimeout(function () { sh.remove(); }, 1300);
    }, 20000);
  }
  apply();
  setInterval(apply, 2 * 60 * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) apply(); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
  window.LGTheme = { get: get, set: set, apply: apply };
})();
