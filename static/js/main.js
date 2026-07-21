(function () {
  var modal = document.getElementById("orderModal");
  if (!modal) return;

  var productIdInput = document.getElementById("orderProductId");
  var backInput = document.getElementById("orderBackUrl");
  var productLabel = document.getElementById("orderModalProduct");

  function openModal(productId, productName) {
    productIdInput.value = productId || "";
    backInput.value = window.location.pathname + window.location.search;
    productLabel.textContent = productName ? "Sản phẩm: " + productName : "";
    modal.classList.add("open");
  }

  function closeModal() {
    modal.classList.remove("open");
  }

  document.querySelectorAll(".btn-order").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openModal(btn.dataset.productId, btn.dataset.productName);
    });
  });

  var closeBtn = document.getElementById("orderModalClose");
  if (closeBtn) closeBtn.addEventListener("click", closeModal);

  modal.addEventListener("click", function (e) {
    if (e.target === modal) closeModal();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeModal();
  });
})();

(function () {
  document.querySelectorAll("[data-tabs]").forEach(function (tabRow) {
    var grid = tabRow.closest("section").querySelector("[data-tab-grid]");
    if (!grid) return;
    var items = grid.querySelectorAll(".tab-item");

    tabRow.querySelectorAll(".catfilter-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        tabRow.querySelectorAll(".catfilter-btn").forEach(function (b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");

        var cat = btn.dataset.cat || "";
        items.forEach(function (item) {
          var show = !cat || item.dataset.cat === cat;
          item.classList.toggle("tab-hidden", !show);
        });
      });
    });
  });
})();
