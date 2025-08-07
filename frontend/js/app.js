// Main Application Logic
class AIPromptApp {
    constructor() {
        this.currentTab = 'chat';
        this.init();
    }

    init() {
        this.initTabNavigation();
        this.initChatForm();
        this.bindEvents();
        console.log('✅ AI Prompt App initialized');
    }

    // Tab Navigation
    initTabNavigation() {
        const tabBtns = document.querySelectorAll('.tab-btn');
        const tabContents = document.querySelectorAll('.tab-content');

        tabBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const targetTab = e.target.getAttribute('data-tab');
                this.switchTab(targetTab);
            });
        });
    }

    switchTab(tabName) {
        // Update tab buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.getAttribute('data-tab') === tabName) {
                btn.classList.add('active');
            }
        });

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        
        const targetContent = document.getElementById(`${tabName}-tab`);
        if (targetContent) {
            targetContent.classList.add('active');
        }

        this.currentTab = tabName;
        console.log(`🔄 Switched to tab: ${tabName}`);
    }

    // Chat Form Logic (Original functionality)
    initChatForm() {
        const form = document.getElementById("prompt-form");
        const resultDiv = document.getElementById("result");
        const spinner = document.getElementById("spinner");
        const submitBtn = document.getElementById("submit-btn");

        if (!form || !resultDiv || !spinner) {
            console.error("❌ Chat UI elements not found");
            return;
        }

        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            await this.handleChatSubmit(e);
        });
    }

    async handleChatSubmit(e) {
        const prompt = document.getElementById("prompt").value.trim();
        const model = document.getElementById("model").value;
        const system = document.getElementById("system").value.trim();
        const resultDiv = document.getElementById("result");
        const spinner = document.getElementById("spinner");
        const submitBtn = document.getElementById("submit-btn");

        if (!prompt) {
            this.showError("⚠️ Bitte gib einen Prompt ein.", resultDiv);
            return;
        }

        // Reset UI
        resultDiv.textContent = "";
        resultDiv.className = "response-container";
        spinner.classList.add("active");
        submitBtn.disabled = true;

        try {
            const response = await fetch("/webhook/llm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt, system, model })
            });

            if (!response.ok) {
                throw new Error(`HTTP Error: ${response.status}`);
            }

            const data = await response.json();
            const output =
                data?.raw_response?.response ||
                data?.result ||
                JSON.stringify(data, null, 2);

            resultDiv.textContent = output;
            resultDiv.classList.add("success");
            this.showNotification("✅ Antwort erhalten!", "success");
        } catch (error) {
            this.showError(`❌ Fehler: ${error.message}`, resultDiv);
            this.showNotification("❌ Fehler beim Senden!", "error");
        } finally {
            spinner.classList.remove("active");
            submitBtn.disabled = false;
        }
    }

    // Utility Methods
    showError(message, container) {
        if (container) {
            container.textContent = message;
            container.className = "response-container error";
        }
    }

    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        // Show notification
        setTimeout(() => notification.classList.add('show'), 100);
        
        // Hide and remove notification
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => document.body.removeChild(notification), 300);
        }, 3000);
    }

    // Event Bindings
    bindEvents() {
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + Enter to submit chat form
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && this.currentTab === 'chat') {
                e.preventDefault();
                const form = document.getElementById('prompt-form');
                if (form) form.dispatchEvent(new Event('submit'));
            }
            
            // Tab shortcuts (Ctrl/Cmd + 1, 2, 3)
            if (e.ctrlKey || e.metaKey) {
                switch(e.key) {
                    case '1':
                        e.preventDefault();
                        this.switchTab('chat');
                        break;
                    case '2':
                        e.preventDefault();
                        this.switchTab('upload');
                        break;
                    case '3':
                        e.preventDefault();
                        this.switchTab('agents');
                        break;
                }
            }
        });

        // Handle window resize
        window.addEventListener('resize', () => {
            this.handleResize();
        });
    }

    handleResize() {
        // Add responsive behavior if needed
        console.log('📱 Window resized');
    }
}

// Initialize app when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
    window.aiApp = new AIPromptApp();
});