(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  var root = document.documentElement;

  // --- Giao diện sáng/tối ---
  function currentTheme() {
    return root.getAttribute("data-theme") ||
      (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  try {
    var saved = localStorage.getItem("dash-theme");
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) {}

  var themeBtn = $("theme-btn");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("dash-theme", next); } catch (e) {}
    });
  }

  // --- Thông báo theo tham số URL ---
  var params = new URLSearchParams(location.search);
  var alertBox = $("alert");
  function showAlert(type, msg) {
    if (!alertBox) return;
    alertBox.className = "alert show " + type;
    alertBox.textContent = msg;
  }
  var err = params.get("error");
  if (err === "rate") showAlert("warn", "Bạn thử sai quá nhiều lần. Vui lòng đợi một lúc rồi thử lại.");
  else if (err) showAlert("error", "Mật khẩu không đúng. Vui lòng thử lại.");
  else if (params.get("expired")) showAlert("warn", "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  else if (params.get("logout")) showAlert("warn", "Bạn đã đăng xuất.");
  if (err || params.get("expired") || params.get("logout")) {
    history.replaceState(null, "", location.pathname);
  }

  // --- Cảnh báo HTTP không mã hóa (trừ localhost) ---
  var isLocal = ["localhost", "127.0.0.1", "[::1]"].indexOf(location.hostname) !== -1;
  if (location.protocol === "http:" && !isLocal && $("insecure")) {
    $("insecure").classList.add("show");
  }

  // --- Hiện/ẩn mật khẩu ---
  var pw = $("password");
  var toggle = $("toggle-pw");
  if (pw && toggle) {
    toggle.addEventListener("click", function () {
      var show = pw.type === "password";
      pw.type = show ? "text" : "password";
      toggle.textContent = show ? "Ẩn" : "Hiện";
      toggle.setAttribute("aria-pressed", String(show));
      pw.focus();
    });
  }

  // --- Cảnh báo Caps Lock ---
  var hint = $("caps-hint");
  if (pw && hint) {
    var checkCaps = function (e) {
      if (e.getModifierState) {
        hint.textContent = e.getModifierState("CapsLock") ? "⚠️ Caps Lock đang bật" : "";
      }
    };
    pw.addEventListener("keydown", checkCaps);
    pw.addEventListener("keyup", checkCaps);
    pw.addEventListener("blur", function () { hint.textContent = ""; });
  }

  // --- Trạng thái đang gửi ---
  var form = $("login-form");
  var btn = $("submit-btn");
  var label = $("submit-label");
  if (form && btn && label) {
    form.addEventListener("submit", function () {
      btn.disabled = true;
      btn.classList.add("loading");
      label.textContent = "Đang đăng nhập…";
    });
    window.addEventListener("pageshow", function (e) {
      if (e.persisted) {
        btn.disabled = false;
        btn.classList.remove("loading");
        label.textContent = "Đăng nhập";
      }
    });
  }
})();
