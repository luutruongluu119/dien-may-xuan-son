(function () {
  var popup = document.getElementById("giftPopup");
  if (!popup) return;

  var STORAGE_KEY = "xs_gift_popup_seen";
  var closeBtn = document.getElementById("giftPopupClose");

  function closePopup() {
    popup.classList.remove("open");
  }

  if (closeBtn) closeBtn.addEventListener("click", closePopup);
  popup.addEventListener("click", function (e) {
    if (e.target === popup) closePopup();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closePopup();
  });

  try {
    if (localStorage.getItem(STORAGE_KEY)) return;
  } catch (e) {
    return; // localStorage bị chặn (chế độ ẩn danh nghiêm ngặt) — bỏ qua, không hiện popup
  }

  window.setTimeout(function () {
    popup.classList.add("open");
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch (e) {}
  }, 12000);
})();
