(function () {
  var toggle = document.getElementById("aiChatToggle");
  var panel = document.getElementById("aiChatPanel");
  if (!toggle || !panel) return;

  var closeBtn = document.getElementById("aiChatClose");
  var body = document.getElementById("aiChatBody");
  var form = document.getElementById("aiChatForm");
  var input = document.getElementById("aiChatInput");
  var suggestRow = document.getElementById("aiChatSuggest");

  var history = [];
  var sending = false;

  function scrollToBottom() {
    body.scrollTop = body.scrollHeight;
  }

  function addMessage(role, text) {
    var div = document.createElement("div");
    div.className = "ai-msg " + (role === "user" ? "ai-msg-user" : "ai-msg-bot");
    div.textContent = text;
    body.appendChild(div);
    scrollToBottom();
    return div;
  }

  function setOpen(open) {
    panel.classList.toggle("open", open);
    panel.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) input.focus();
  }

  toggle.addEventListener("click", function () {
    setOpen(!panel.classList.contains("open"));
  });
  if (closeBtn) closeBtn.addEventListener("click", function () { setOpen(false); });

  function send(text) {
    text = (text || "").trim();
    if (!text || sending) return;
    if (suggestRow) suggestRow.style.display = "none";
    addMessage("user", text);
    history.push({ role: "user", content: text });
    input.value = "";
    sending = true;
    var loading = document.createElement("div");
    loading.className = "ai-msg ai-msg-loading";
    loading.textContent = "Đang trả lời…";
    body.appendChild(loading);
    scrollToBottom();

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history: history }),
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (res) {
        loading.remove();
        if (!res.ok || res.data.error) {
          var errDiv = document.createElement("div");
          errDiv.className = "ai-msg ai-msg-error";
          errDiv.textContent = (res.data && res.data.error) || "Có lỗi xảy ra, vui lòng thử lại.";
          body.appendChild(errDiv);
          scrollToBottom();
          return;
        }
        addMessage("bot", res.data.reply);
        history.push({ role: "assistant", content: res.data.reply });
      })
      .catch(function () {
        loading.remove();
        var errDiv = document.createElement("div");
        errDiv.className = "ai-msg ai-msg-error";
        errDiv.textContent = "Không kết nối được, vui lòng thử lại hoặc gọi hotline.";
        body.appendChild(errDiv);
        scrollToBottom();
      })
      .finally(function () { sending = false; });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    send(input.value);
  });

  if (suggestRow) {
    suggestRow.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () { send(btn.dataset.q); });
    });
  }
})();
