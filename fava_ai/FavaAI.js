export default {
    convList: [],
    activeConvId: null,

    async onExtensionPageLoad(ctx) {
        this.ctx = ctx;
        this.initDom();
        await this.loadConversations();
        await this.loadProviders();
        this.wireEvents();
    },

    initDom() {
        this.el = {
            messages: document.getElementById('chat-messages'),
            input: document.getElementById('chat-input'),
            sendBtn: document.getElementById('send-btn'),
            convList: document.getElementById('conversation-list'),
            newConvBtn: document.getElementById('new-conversation-btn'),
            providerStatus: document.getElementById('provider-status'),
            providerName: document.getElementById('provider-name'),
            panel: document.getElementById('fava-ai-panel'),
            panelTabs: document.querySelectorAll('.panel-tab'),
            panelContents: document.querySelectorAll('.panel-content'),
            panelTools: document.getElementById('panel-tools'),
            panelConfig: document.getElementById('panel-config'),
            panelProviders: document.getElementById('panel-providers'),
        };
    },

    wireEvents() {
        this.el.sendBtn.addEventListener('click', () => this.sendMessage());
        this.el.input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        this.el.newConvBtn.addEventListener('click', () => this.newConversation());

        document.querySelectorAll('.fava-ai-welcome li').forEach(li => {
            li.addEventListener('click', () => {
                this.el.input.value = li.textContent;
                this.sendMessage();
            });
        });

        this.el.panelTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                this.el.panelTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.el.panelContents.forEach(c => c.classList.remove('active'));
                const target = document.getElementById('panel-' + tab.dataset.tab);
                if (target) target.classList.add('active');

                if (tab.dataset.tab === 'tools') this.loadTools();
                if (tab.dataset.tab === 'config') this.loadConfig();
                if (tab.dataset.tab === 'providers') this.loadProvidersPanel();
            });
        });
    },

    api(method, path, body, params) {
        return this.ctx.api.request(path, method, params, body);
    },

    async loadConversations() {
        try {
            this.convList = await this.api('GET', 'conversations');
            this.renderConvList();
        } catch (e) {
            console.error('Failed to load conversations:', e);
        }
    },

    renderConvList() {
        this.el.convList.innerHTML = '';
        for (const conv of this.convList) {
            const div = document.createElement('div');
            div.className = 'fava-ai-conv-item' + (conv.id === this.activeConvId ? ' active' : '');
            div.innerHTML = `
                <span class="conv-title" title="${this.esc(conv.title)}">${this.esc(conv.title)}</span>
                <span class="conv-delete" data-id="${conv.id}">&times;</span>
            `;

            div.querySelector('.conv-title').addEventListener('click', () => this.loadConversation(conv.id));
            div.querySelector('.conv-delete').addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteConversation(conv.id);
            });

            this.el.convList.appendChild(div);
        }
    },

    async loadConversation(id) {
        try {
            const conv = await this.api('GET', 'conversations', null, { id });
            this.activeConvId = id;
            this.renderConvList();
            this.renderMessages(conv.messages || []);
        } catch (e) {
            console.error('Failed to load conversation:', e);
        }
    },

    async newConversation() {
        this.activeConvId = null;
        this.el.messages.innerHTML = `
            <div class="fava-ai-welcome">
                <h2>Fava AI Assistant</h2>
                <p>Ask questions about your ledger data. Example:</p>
                <ul>
                    <li>"What is the operating currency and date range of this ledger?"</li>
                    <li>"What are my top 5 expenses by total amount?"</li>
                    <li>"What recurring payments do I have?"</li>
                    <li>"Show me my spending on food by month."</li>
                </ul>
            </div>`;
        this.renderConvList();
        this.el.input.focus();
    },

    async deleteConversation(id) {
        if (!confirm('Delete this conversation?')) return;
        try {
            await this.api('DELETE', 'conversations', null, { id });
            if (this.activeConvId === id) {
                this.activeConvId = null;
                this.el.messages.innerHTML = '';
            }
            await this.loadConversations();
        } catch (e) {
            console.error('Failed to delete:', e);
        }
    },

    async sendMessage() {
        const message = this.el.input.value.trim();
        if (!message) return;

        this.el.input.value = '';
        this.el.input.disabled = true;
        this.el.sendBtn.disabled = true;

        this.addMessage('user', message);

        const loadingEl = this.addLoading();

        try {
            const body = { message };
            if (this.activeConvId) body.conversation_id = this.activeConvId;

            const result = await this.api('POST', 'chat', body);

            loadingEl.remove();

            this.addMessage('assistant', result.content, result.provenance);

            this.activeConvId = result.conversation_id;
            await this.loadConversations();
        } catch (e) {
            loadingEl.remove();
            this.addMessage('assistant', `Error: ${e.message}`, null);
        } finally {
            this.el.input.disabled = false;
            this.el.sendBtn.disabled = false;
            this.el.input.focus();
        }
    },

    addMessage(role, content, provenance) {
        const div = document.createElement('div');
        div.className = `message ${role}`;

        let html = '';

        html += `<div class="content">${this.md(content)}</div>`;

        if (provenance && provenance.steps) {
            const toolSteps = provenance.steps.filter(s => s.step_type === 'tool_call');
            if (toolSteps.length > 0) {
                html += '<div class="provenance-footer">';
                for (const step of toolSteps) {
                    let inputDisplay = '';
                    try {
                        inputDisplay = JSON.stringify(JSON.parse(step.tool_input || '{}'), null, 2);
                    } catch {
                        inputDisplay = step.tool_input || '';
                    }
                    html += `
                        <div class="tool-call-card">
                            <details>
                                <summary>Tool: ${this.esc(step.tool_name)}</summary>
                                <div class="tool-detail">
                                    <strong>Input:</strong>
                                    <pre>${this.esc(inputDisplay)}</pre>
                                    ${step.error ? `<strong>Error:</strong> <pre>${this.esc(step.error)}</pre>` : ''}
                                </div>
                            </details>
                        </div>`;
                }
                html += '</div>';
            }
        }

        div.innerHTML = html;
        this.el.messages.appendChild(div);
        this.el.messages.scrollTop = this.el.messages.scrollHeight;
    },

    addLoading() {
        const div = document.createElement('div');
        div.className = 'loading';
        div.innerHTML = '<div class="spinner"></div> Thinking...';
        this.el.messages.appendChild(div);
        this.el.messages.scrollTop = this.el.messages.scrollHeight;
        return div;
    },

    renderMessages(messages) {
        this.el.messages.innerHTML = '';
        for (const msg of messages) {
            if (msg.role === 'system') continue;
            this.addMessage(msg.role, msg.content, null);
        }
        this.el.messages.scrollTop = this.el.messages.scrollHeight;
    },

    async loadProviders() {
        try {
            const providers = await this.api('GET', 'providers');
            if (providers.length > 0) {
                const def = providers.find(p => p.is_default) || providers[0];
                this.el.providerName.textContent = `${def.name} ${def.connected ? '\u2713' : '\u2717'}`;
                this.el.providerStatus.className = 'status-dot ' + (def.connected ? 'connected' : 'disconnected');
            }
        } catch (e) {
            console.error('Failed to load providers:', e);
        }
    },

    async loadTools() {
        try {
            const tools = await this.api('GET', 'tools');
            let html = '<h4>Available Tools</h4>';
            for (const tool of tools) {
                html += `
                    <details style="margin-bottom:6px;">
                        <summary><strong>${this.esc(tool.name)}</strong></summary>
                        <p style="font-size:12px;color:#666;">${this.esc(tool.description)}</p>
                    </details>`;
            }
            this.el.panelTools.innerHTML = html;
        } catch (e) {
            this.el.panelTools.innerHTML = '<p style="color:red;">Failed to load tools</p>';
        }
    },

    async loadConfig() {
        try {
            const config = await this.api('GET', 'config');
            this.el.panelConfig.innerHTML = `<pre style="font-size:11px;">${this.esc(JSON.stringify(config, null, 2))}</pre>`;
        } catch (e) {
            this.el.panelConfig.innerHTML = '<p style="color:red;">Failed to load config</p>';
        }
    },

    async loadProvidersPanel() {
        try {
            const providers = await this.api('GET', 'providers');
            let html = '<h4>Providers</h4>';
            for (const p of providers) {
                html += `
                    <div style="padding:4px 0;">
                        <span class="status-dot ${p.connected ? 'connected' : 'disconnected'}"></span>
                        ${this.esc(p.name)} ${p.is_default ? '(default)' : ''}
                    </div>`;
            }
            this.el.panelProviders.innerHTML = html;
        } catch (e) {
            this.el.panelProviders.innerHTML = '<p style="color:red;">Failed to load providers</p>';
        }
    },

    esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    md(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    },
};
