document.getElementById('prompt-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const model = document.getElementById('model').value;
  const prompt = document.getElementById('prompt').value;
  const responseBox = document.getElementById('response');
  responseBox.textContent = "⏳ Anfrage wird gesendet...";

  try {
    const res = await fetch('/webhook/prompt', {
      method: 'POST',
      headers: {
        'Authorization': 'Basic ' + btoa('admin:supersecure'),
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ prompt, model })
    });
    const data = await res.json();
    responseBox.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    responseBox.textContent = "❌ Fehler: " + err.message;
  }
});