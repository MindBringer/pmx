window.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("prompt-form");
  const resultDiv = document.getElementById("result");
  const spinner = document.getElementById("spinner");

  if (!form || !resultDiv || !spinner) {
    console.error("❌ UI-Elemente nicht gefunden");
    return;
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    const prompt = document.getElementById("prompt").value.trim();
    const model = document.getElementById("model").value;
    const system = document.getElementById('system').value.trim();

    if (!prompt) {
      resultDiv.textContent = "⚠️ Bitte gib einen Prompt ein.";
      return;
    }

    resultDiv.textContent = "";
    spinner.style.display = "block";

    try {
      const response = await fetch("/webhook/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, model })
      });

      if (!response.ok) {
        throw new Error(`Fehler ${response.status}`);
      }

      const data = await response.json();
      const output =
        data?.raw_response?.response ||
        data?.result ||
        JSON.stringify(data, null, 2);

      resultDiv.textContent = output;
    } catch (error) {
      resultDiv.textContent = `❌ Fehler: ${error.message}`;
    } finally {
      spinner.style.display = "none";
    }
  });
});
