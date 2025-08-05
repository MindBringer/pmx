window.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("prompt-form");
  const resultDiv = document.getElementById("result");

  if (!form || !resultDiv) {
    console.error("❌ Form oder Ergebnis-DIV nicht gefunden!");
    return;
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    const prompt = document.getElementById("prompt").value.trim();
    const model = document.getElementById("model").value;

    if (!prompt) {
      resultDiv.textContent = "⚠️ Bitte gib einen Prompt ein.";
      return;
    }

    resultDiv.textContent = "⏳ Anfrage wird verarbeitet...";

    try {
      const response = await fetch("/webhook/llm", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ prompt, model })
      });

      if (!response.ok) {
        throw new Error(`Fehler ${response.status}`);
      }

      const data = await response.json();

      // Versuche sinnvoll zu parsen
      const output =
        data?.raw_response?.response ||
        data?.result ||
        JSON.stringify(data, null, 2);

      resultDiv.textContent = output;
    } catch (error) {
      resultDiv.textContent = `❌ Fehler: ${error.message}`;
    }
  });
});
