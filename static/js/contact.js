/* AI Reality Simulator contact form */

(function () {
  const form = document.getElementById("form");
  const sent = document.getElementById("sent");
  const send = document.getElementById("send");
  const error = document.getElementById("error");
  const message = document.getElementById("message");
  const count = document.getElementById("count");

  const show = (text) => {
    error.textContent = text;
    error.hidden = false;
  };

  message.addEventListener("input", () => {
    count.textContent = message.value.length;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;

    const body = {
      name: document.getElementById("name").value.trim(),
      email: document.getElementById("email").value.trim(),
      message: message.value.trim(),
    };
    if (!body.message) {
      show("Write a message before sending it.");
      return;
    }

    send.disabled = true;
    send.textContent = "Sending…";

    let data;
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      data = await res.json();
    } catch {
      data = { ok: false, error: "Could not reach the company. Is the server running?" };
    }

    // The engine refuses a second run while one is in flight, and that refusal
    // is the honest answer to show: the message was not accepted.
    if (!data.ok) {
      show(data.error || "Something went wrong. Try again.");
      send.disabled = false;
      send.textContent = "Send message";
      return;
    }

    form.hidden = true;
    sent.hidden = false;
  });
})();
