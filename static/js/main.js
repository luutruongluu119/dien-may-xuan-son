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
