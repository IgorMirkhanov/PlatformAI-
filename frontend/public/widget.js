/**
 * MoonAI embeddable site chat widget.
 * Usage: <script src="https://app.example.com/widget.js?id=<BOT_UUID>" async></script>
 */
(function () {
  "use strict";

  var script =
    document.currentScript ||
    (function () {
      var list = document.getElementsByTagName("script");
      return list[list.length - 1];
    })();

  var src = (script && script.src) || "";
  var params = new URL(src, window.location.href).searchParams;
  var botId = params.get("id") || params.get("bot_id");
  if (!botId) {
    console.warn("[MoonAI widget] missing ?id=<bot_uuid>");
    return;
  }

  var apiBase =
    params.get("api") ||
    (window.MOONAI_API_BASE ||
      (src.indexOf("localhost") >= 0
        ? "http://127.0.0.1:8000"
        : window.location.origin));

  var sessionKey = "moonai_widget_session_" + botId;
  var sessionId = localStorage.getItem(sessionKey);
  if (!sessionId) {
    sessionId =
      "web-" +
      Math.random().toString(36).slice(2) +
      Date.now().toString(36);
    localStorage.setItem(sessionKey, sessionId);
  }

  var root = document.createElement("div");
  root.id = "moonai-widget-root";
  root.innerHTML =
    '<button id="moonai-launcher" aria-label="Open chat" ' +
    'style="position:fixed;right:20px;bottom:20px;z-index:2147483000;width:56px;height:56px;' +
    "border:none;border-radius:50%;background:#5b4bff;color:#fff;font-size:22px;cursor:pointer;" +
    'box-shadow:0 8px 24px rgba(91,75,255,.35);">💬</button>' +
    '<div id="moonai-panel" style="display:none;position:fixed;right:20px;bottom:88px;z-index:2147483000;' +
    "width:340px;max-width:calc(100vw - 24px);height:460px;background:#0f0f12;color:#f4f4f5;" +
    "border:1px solid #27272a;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.45);" +
    'overflow:hidden;font-family:Inter,system-ui,sans-serif;">' +
    '<div style="padding:14px 16px;background:#18181b;border-bottom:1px solid #27272a;font-weight:600;">MoonAI</div>' +
    '<div id="moonai-messages" style="height:340px;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:8px;"></div>' +
    '<form id="moonai-form" style="display:flex;gap:8px;padding:12px;border-top:1px solid #27272a;">' +
    '<input id="moonai-input" type="text" placeholder="Напишите сообщение…" ' +
    'style="flex:1;border-radius:10px;border:1px solid #3f3f46;background:#09090b;color:#fff;padding:10px 12px;outline:none;" />' +
    '<button type="submit" style="border:none;border-radius:10px;background:#5b4bff;color:#fff;padding:0 14px;cursor:pointer;">➤</button>' +
    "</form></div>";
  document.body.appendChild(root);

  var panel = document.getElementById("moonai-panel");
  var launcher = document.getElementById("moonai-launcher");
  var messages = document.getElementById("moonai-messages");
  var form = document.getElementById("moonai-form");
  var input = document.getElementById("moonai-input");

  function addBubble(text, from) {
    var el = document.createElement("div");
    el.textContent = text;
    el.style.maxWidth = "85%";
    el.style.padding = "8px 12px";
    el.style.borderRadius = "12px";
    el.style.fontSize = "14px";
    el.style.lineHeight = "1.4";
    el.style.whiteSpace = "pre-wrap";
    el.style.alignSelf = from === "user" ? "flex-end" : "flex-start";
    el.style.background = from === "user" ? "#5b4bff" : "#27272a";
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  }

  launcher.addEventListener("click", function () {
    panel.style.display = panel.style.display === "none" ? "block" : "none";
  });

  async function poll() {
    try {
      var res = await fetch(
        apiBase +
          "/api/v1/webhooks/widget/" +
          encodeURIComponent(botId) +
          "/poll/" +
          encodeURIComponent(sessionId)
      );
      if (!res.ok) return;
      var data = await res.json();
      (data.messages || []).forEach(function (msg) {
        addBubble(String(msg), "bot");
      });
    } catch (e) {
      /* ignore network blips */
    }
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    addBubble(text, "user");
    try {
      await fetch(
        apiBase + "/api/v1/webhooks/widget/" + encodeURIComponent(botId),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            message_text: text,
            username: "web-visitor",
          }),
        }
      );
      setTimeout(poll, 1200);
      setTimeout(poll, 3000);
    } catch (e) {
      addBubble("Не удалось отправить сообщение. Попробуйте ещё раз.", "bot");
    }
  });

  setInterval(poll, 4000);
})();

