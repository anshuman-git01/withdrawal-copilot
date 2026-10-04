// Small progressive enhancements. Everything works without this file.
(function () {
  // Greeting in the user's local time.
  document.addEventListener("DOMContentLoaded", function () {
    var el = document.querySelector("[data-greeting]");
    if (el) {
      var h = new Date().getHours();
      el.textContent = h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
    }
  });

  // Indian digit grouping while typing: 170000 -> 1,70,000
  function groupIndian(digits) {
    if (!digits) return "";
    digits = digits.replace(/^0+(?=\d)/, "");
    if (digits.length <= 3) return digits;
    var tail = digits.slice(-3), head = digits.slice(0, -3);
    return head.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + tail;
  }
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!t.matches || !t.matches("[data-indian-number]")) return;
    var before = t.value, pos = t.selectionStart || before.length;
    var digitsLeft = before.slice(0, pos).replace(/\D/g, "").length;
    var formatted = groupIndian(before.replace(/\D/g, ""));
    if (formatted === before) return;
    t.value = formatted;
    var i = 0, seen = 0;
    while (i < formatted.length && seen < digitsLeft) { if (/\d/.test(formatted[i])) seen++; i++; }
    try { t.setSelectionRange(i, i); } catch (_) {}
  }, true);

  // "How is this calculated?" opens are a tracked event (why_opened).
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (d.tagName === "DETAILS" && d.open && d.dataset.why) {
      var body = new URLSearchParams({ topic: d.dataset.why });
      fetch("/events/why_opened", { method: "POST", body: body, keepalive: true }).catch(function () {});
    }
  }, true);

  // Clear the optional reason on the need screen.
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-clear-reason]");
    if (!b) return;
    var form = b.closest("form");
    form.querySelectorAll('input[name="reason"]').forEach(function (r) { r.checked = false; });
    form.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // Keep the newest Copilot answer in view.
  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.target.id === "copilot-thread") {
      var s = document.getElementById("copilot-scroll");
      if (s) s.scrollTop = s.scrollHeight;
    }
  });
})();
