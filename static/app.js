"use strict";

const $ = (id) => document.getElementById(id);

/* ---------- タブ切り替え ---------- */

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("is-active"));
    tab.classList.add("is-active");
    $("panel-" + tab.dataset.panel).classList.add("is-active");
  });
});

/* ---------- モデル情報 ---------- */

fetch("/api/config")
  .then((r) => r.json())
  .then((c) => {
    $("footer").textContent =
      `画像: ${c.image_model} ／ コーディング: ${c.code_model} ／ チャット: ${c.chat_model}`;
  })
  .catch(() => {
    $("footer").textContent = "モデル情報を取得できませんでした。";
  });

/* ---------- 画像生成 ---------- */

const imageStatus = $("image-status");

function setStatus(message, isError) {
  imageStatus.hidden = !message;
  imageStatus.textContent = message || "";
  imageStatus.classList.toggle("is-error", Boolean(isError));
}

$("image-go").addEventListener("click", async () => {
  const prompt = $("image-prompt").value.trim();
  if (!prompt) {
    setStatus("プロンプトを入力してください。", true);
    return;
  }

  const button = $("image-go");
  button.disabled = true;
  setStatus("生成しています… 30秒ほどかかることがあります。", false);

  try {
    const response = await fetch("/api/image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        size: $("image-size").value,
        n: Number($("image-n").value),
      }),
    });
    const result = await response.json();

    if (result.error) {
      setStatus("エラー: " + result.error, true);
      return;
    }

    setStatus(`${result.images.length} 枚できました。`, false);
    const gallery = $("image-gallery");
    result.images.forEach((image, index) => {
      const figure = document.createElement("figure");
      figure.className = "shot";

      const img = document.createElement("img");
      img.src = image.data_url;
      img.alt = prompt;

      const meta = document.createElement("div");
      meta.className = "meta";
      const label = document.createElement("span");
      label.textContent = image.saved_as;
      label.title = image.revised_prompt || prompt;
      const link = document.createElement("a");
      link.href = image.data_url;
      link.download = `image-${Date.now()}-${index + 1}.png`;
      link.textContent = "保存";
      meta.append(label, link);

      figure.append(img, meta);
      gallery.prepend(figure);
    });
  } catch (error) {
    setStatus("通信に失敗しました: " + error.message, true);
  } finally {
    button.disabled = false;
  }
});

/* ---------- Markdown もどきの整形 ---------- */

function escapeHtml(text) {
  return text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
}

/** ```fence``` と `inline` だけを扱う、最小限のレンダラ。 */
function render(text) {
  const parts = text.split(/```/);
  return parts
    .map((part, index) => {
      if (index % 2 === 1) {
        const body = part.replace(/^[\w+-]*\n?/, "");
        return `<pre><code>${escapeHtml(body)}</code></pre>`;
      }
      return escapeHtml(part).replace(/`([^`\n]+)`/g, "<code>$1</code>");
    })
    .join("");
}

/* ---------- 会話（チャット／コーディング共通） ---------- */

function createConversation(name, endpoint) {
  const thread = $(name + "-thread");
  const input = $(name + "-input");
  const form = $(name + "-form");
  const button = $(name + "-go");
  const history = [];

  function bubble(role, who) {
    const element = document.createElement("div");
    element.className = "bubble " + role;
    const label = document.createElement("span");
    label.className = "who";
    label.textContent = who;
    element.append(label);
    thread.append(element);
    thread.scrollTop = thread.scrollHeight;
    return element;
  }

  async function send(prompt) {
    history.push({ role: "user", content: prompt });

    const userBubble = bubble("user", "あなた");
    userBubble.append(document.createTextNode(prompt));

    const replyBubble = bubble("assistant", name === "code" ? "アシスタント（コード）" : "アシスタント");
    const thinkBox = document.createElement("details");
    thinkBox.className = "think";
    thinkBox.hidden = true;
    const thinkSummary = document.createElement("summary");
    thinkSummary.textContent = "考えている内容を見る";
    const thinkBody = document.createElement("div");
    thinkBox.append(thinkSummary, thinkBody);

    const body = document.createElement("div");
    body.className = "cursor";
    replyBubble.append(thinkBox, body);

    button.disabled = true;
    let answer = "";
    let thinking = "";

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let cut;
        while ((cut = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);

          const event = /^event: (.*)$/m.exec(frame)?.[1];
          const raw = /^data: (.*)$/m.exec(frame)?.[1];
          if (!event || !raw) continue;
          const payload = JSON.parse(raw);

          if (event === "text") {
            answer += payload.text;
            body.innerHTML = render(answer);
          } else if (event === "thinking") {
            thinking += payload.text;
            thinkBox.hidden = false;
            thinkBody.textContent = thinking;
          } else if (event === "error") {
            replyBubble.classList.add("error");
            body.textContent = "エラー: " + payload.message;
          }
          thread.scrollTop = thread.scrollHeight;
        }
      }

      if (answer) history.push({ role: "assistant", content: answer });
      else history.pop();
    } catch (error) {
      replyBubble.classList.add("error");
      body.textContent = "通信に失敗しました: " + error.message;
      history.pop();
    } finally {
      body.classList.remove("cursor");
      button.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = input.value.trim();
    if (!prompt || button.disabled) return;
    input.value = "";
    send(prompt);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.querySelector("[data-clear]").addEventListener("click", () => {
    history.length = 0;
    thread.innerHTML = "";
    input.focus();
  });
}

createConversation("chat", "/api/chat");
createConversation("code", "/api/code");
