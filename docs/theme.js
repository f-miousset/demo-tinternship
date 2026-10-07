// System / Light / Dark, remembered per browser. Runs before paint (it is the
// first script in <head>), so a returning reader who chose dark never sees a
// white flash. `data-theme` on <html> is the one thing the stylesheet reads.
(function () {
  var KEY = "tinternship-guide-theme";
  function read() {
    try { return localStorage.getItem(KEY) || "system"; } catch (e) { return "system"; }
  }
  function apply(choice) {
    var dark = choice === "dark" || (choice === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    document.documentElement.setAttribute("data-choice", choice);
  }
  apply(read());
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { apply(read()); });
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-set-theme]").forEach(function (button) {
      button.addEventListener("click", function () {
        var choice = button.getAttribute("data-set-theme");
        try { localStorage.setItem(KEY, choice); } catch (e) { /* private mode */ }
        apply(choice);
      });
    });
  });
})();
