export default {
    convList: [],
    activeConvId: null,
    providers: [],
    prompts: [],
    currentProvider: '',
    currentModel: '',
    currentPrompt: 'default',
    abortController: null,
    streaming: false,
    currentAssistantEl: null,
    currentAssistantText: '',

    async onExtensionPageLoad(ctx) {
        this.ctx = ctx;
        this.initDom();
        this.wireEvents();
        await Promise.all([
            this.loadConversations(),
            this.loadProviders(),
            this.loadPrompts(),
        ]);
    },

    initDom() {
        this.el = {
            messages: document.getElementById('chat-messages'),
            input: document.getElementById('chat-input'),
            sendBtn: document.getElementById('send-btn'),
            stopBtn: document.getElementById('stop-btn'),
            convList: document.getElementById('conversation-list'),
            newConvBtn: document.getElementById('new-conversation-btn'),
            providerStatus: document.getElementById('provider-status'),
            providerName: document.getElementById('provider-name'),
            providerSelect: document.getElementById('provider-select'),
            modelSelect: document.getElementById('model-select'),
            promptSelect: document.getElementById('prompt-select'),
            exportBtn: document.getElementById('export-btn'),
            panel: document.getElementById('fava-ai-panel'),
            panelTabs: document.querySelectorAll('.panel-tab'),
            panelContents: document.querySelectorAll('.panel-content'),
            panelTools: document.getElementById('panel-tools'),
            panelConfig: document.getElementById('panel-config'),
            panelProviders: document.getElementById('panel-providers'),
        };
    },

    wireEvents() {
        // Track whether the user is at the bottom. Measuring on each append is
        // wrong (a big chunk shifts the distance below the threshold even when
        // the user was pinned), so the pinned state is maintained here.
        this._atBottom = true;
        this.el.messages.addEventListener('scroll', () => {
            const el = this.el.messages;
            this._atBottom =
                el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        });

        this.el.sendBtn.addEventListener('click', () => this.sendMessage());
        this.el.input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        this.el.newConvBtn.addEventListener('click', () => this.newConversation());

        if (this.el.stopBtn) {
            this.el.stopBtn.addEventListener('click', () => this.stopStreaming());
        }
        if (this.el.providerSelect) {
            this.el.providerSelect.addEventListener('change', async () => {
                this.currentProvider = this.el.providerSelect.value;
                await this.loadModels(this.currentProvider);
            });
        }
        if (this.el.modelSelect) {
            this.el.modelSelect.addEventListener('change', () => {
                this.currentModel = this.el.modelSelect.value;
            });
        }
        if (this.el.promptSelect) {
            this.el.promptSelect.addEventListener('change', () => {
                this.currentPrompt = this.el.promptSelect.value;
            });
        }
        if (this.el.exportBtn) {
            this.el.exportBtn.addEventListener('click', () => this.exportConversation());
        }

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

    bindWelcomeLinks() {
        document.querySelectorAll('.fava-ai-welcome li').forEach(li => {
            li.addEventListener('click', () => {
                this.el.input.value = li.textContent;
                this.sendMessage();
            });
        });
    },

    // ── API helpers ───────────────────────────────────────────────

    api(method, path, body, params) {
        return this.ctx.api.request(path, method, params, body);
    },

    extensionBaseUrl() {
        const path = window.location.pathname;
        const marker = '/extension/';
        let idx = path.indexOf(marker);
        if (idx >= 0) {
            const rest = path.slice(idx + marker.length);
            const name = rest.split('/')[0];
            return path.slice(0, idx) + marker + name + '/';
        }
        idx = path.indexOf('extension/');
        if (idx >= 0) {
            const rest = path.slice(idx + 'extension/'.length);
            const name = rest.split('/')[0];
            return path.slice(0, idx) + 'extension/' + name + '/';
        }
        return 'extension/FavaAI/';
    },

    streamUrl(endpoint) {
        return this.extensionBaseUrl() + endpoint;
    },

    // ── conversations ─────────────────────────────────────────────

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
            div.dataset.id = conv.id;

            const title = document.createElement('span');
            title.className = 'conv-title';
            title.title = conv.title || '';
            title.textContent = conv.title || '';
            title.addEventListener('click', () => this.loadConversation(conv.id));
            title.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                this.beginRename(div, conv);
            });

            const del = document.createElement('span');
            del.className = 'conv-delete';
            del.textContent = '\u00d7';
            del.title = 'Delete';
            del.addEventListener('click', (e) => {
                e.stopPropagation();
                this.requestDelete(div, conv);
            });

            div.appendChild(title);
            div.appendChild(del);
            this.el.convList.appendChild(div);
        }
    },

    // Inline rename — native prompt() blocks the page (and hangs automation).
    beginRename(div, conv) {
        if (div.querySelector('.conv-rename')) return;
        const titleEl = div.querySelector('.conv-title');
        if (!titleEl) return;

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'conv-rename';
        input.value = conv.title || '';
        titleEl.replaceWith(input);
        input.focus();
        input.select();

        let settled = false;
        const commit = async () => {
            if (settled) return;
            settled = true;
            const value = input.value.trim();
            if (value && value !== conv.title) {
                try {
                    await this.api('PUT', 'conversations', { id: conv.id, title: value });
                } catch (e) {
                    console.error('Failed to rename:', e);
                }
            }
            await this.loadConversations();
        };
        const cancel = () => {
            if (settled) return;
            settled = true;
            this.renderConvList();
        };

        input.addEventListener('click', (e) => e.stopPropagation());
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); commit(); }
            else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
        });
        input.addEventListener('blur', commit);
    },

    // Two-step inline delete confirmation — native confirm() blocks the page.
    requestDelete(div, conv) {
        if (div.dataset.confirm === '1') {
            delete div.dataset.confirm;
            this.deleteConversation(conv.id);
            return;
        }
        this._resetDeleteConfirms();
        div.dataset.confirm = '1';
        div.classList.add('confirming');
        const del = div.querySelector('.conv-delete');
        if (del) del.textContent = 'Delete?';
        setTimeout(() => {
            if (div.dataset.confirm === '1') {
                delete div.dataset.confirm;
                div.classList.remove('confirming');
                const d = div.querySelector('.conv-delete');
                if (d) d.textContent = '\u00d7';
            }
        }, 4000);
    },

    _resetDeleteConfirms() {
        this.el.convList.querySelectorAll('.fava-ai-conv-item.confirming').forEach(el => {
            delete el.dataset.confirm;
            el.classList.remove('confirming');
            const d = el.querySelector('.conv-delete');
            if (d) d.textContent = '\u00d7';
        });
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

    async renameConversation(id, currentTitle) {
        // Kept for programmatic use; the UI uses inline editing (beginRename).
        const title = currentTitle;
        if (title === null || title === undefined) return;
        try {
            await this.api('PUT', 'conversations', { id, title });
            await this.loadConversations();
        } catch (e) {
            console.error('Failed to rename:', e);
        }
    },

    async deleteConversation(id) {
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

    async exportConversation() {
        if (!this.activeConvId) return;
        try {
            const conv = await this.api('GET', 'conversations', null, { id: this.activeConvId });
            const lines = [`# ${conv.title || 'Conversation'}`, ''];
            for (const msg of conv.messages || []) {
                if (msg.role === 'system' || msg.role === 'tool') continue;
                if (msg.role === 'assistant' && this.hasToolCalls(msg)) continue;
                lines.push(`## ${msg.role === 'user' ? 'You' : 'Assistant'}`, '', msg.content || '', '');
            }
            const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${(conv.title || 'conversation').replace(/[^\w.-]+/g, '_')}.md`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            console.error('Failed to export:', e);
        }
    },

    newConversation() {
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
        this.bindWelcomeLinks();
        this.el.input.focus();
    },

    // ── sending / streaming ───────────────────────────────────────

    async sendMessage() {
        const message = this.el.input.value.trim();
        if (!message || this.streaming) return;

        this.el.input.value = '';
        this.setStreaming(true);

        this.addMessage('user', message);
        const assistantEl = this.addMessage('assistant', '');
        this.scrollToBottom(true);  // a new turn always jumps to the latest
        assistantEl.classList.add('streaming');
        this.currentAssistantEl = assistantEl;
        this.currentAssistantText = '';

        const body = { message };
        if (this.activeConvId) body.conversation_id = this.activeConvId;
        if (this.currentProvider) body.provider = this.currentProvider;
        if (this.currentModel) body.model = this.currentModel;
        if (this.currentPrompt) body.prompt_id = this.currentPrompt;

        this.abortController = new AbortController();
        try {
            const response = await fetch(this.streamUrl('chat_stream'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: this.abortController.signal,
            });
            if (!response.ok || !response.body) {
                const text = await response.text().catch(() => '');
                throw new Error(text || `Request failed (${response.status})`);
            }
            await this.consumeStream(response.body);
            await this.loadConversations();
        } catch (e) {
            if (e.name === 'AbortError') {
                this.appendNote(assistantEl, 'Stopped.');
            } else {
                this.renderAssistantError(assistantEl, e.message);
            }
            // An interrupted run may still have been persisted server-side.
            await this.loadConversations();
        } finally {
            assistantEl.classList.remove('streaming');
            this.currentAssistantEl = null;
            this.abortController = null;
            this.setStreaming(false);
        }
    },

    async consumeStream(body) {
        const reader = body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let sep;
            while ((sep = buffer.indexOf('\n\n')) >= 0) {
                const frame = buffer.slice(0, sep);
                buffer = buffer.slice(sep + 2);
                this.handleFrame(frame);
            }
        }
    },

    handleFrame(frame) {
        const line = frame.split('\n').find(l => l.startsWith('data:'));
        if (!line) return;
        let event;
        try {
            event = JSON.parse(line.slice('data:'.length).trim());
        } catch {
            return;
        }

        if (event.type === 'reasoning_delta') {
            this.appendReasoning(this.currentAssistantEl, event.content || '');
        } else if (event.type === 'content_delta') {
            this.currentAssistantText += event.content || '';
            this.setAssistantContent(this.currentAssistantEl, this.currentAssistantText);
        } else if (event.type === 'tool_call_start') {
            this.addToolChip(this.currentAssistantEl, event.tool_name);
        } else if (event.type === 'tool_call') {
            this.addToolStep(this.currentAssistantEl, event.step);
        } else if (event.type === 'done') {
            if (event.content != null) {
                this.currentAssistantText = event.content;
                this.setAssistantContent(this.currentAssistantEl, event.content);
            }
            if (event.message_id) this.currentAssistantEl.dataset.messageId = event.message_id;
            this.activeConvId = event.conversation_id;
            this.appendNote(this.currentAssistantEl, event.provenance_summary || '');
            // Everything is final now: fold the tool trail away.
            const activity = this.currentAssistantEl.querySelector('.tool-activity');
            if (activity) activity.removeAttribute('open');
            if (event.partial) {
                this.appendPartial(this.currentAssistantEl, event.stop_reason);
            }
        } else if (event.type === 'error') {
            this.renderAssistantError(this.currentAssistantEl, event.error);
        }
    },

    stopStreaming() {
        if (this.abortController) this.abortController.abort();
    },

    setStreaming(value) {
        this.streaming = value;
        this.el.sendBtn.disabled = value;
        this.el.input.disabled = value;
        if (this.el.stopBtn) this.el.stopBtn.style.display = value ? 'inline-block' : 'none';
        if (!value) this.el.input.focus();
    },

    setAssistantContent(el, text) {
        // Collapse the reasoning block once the actual answer starts.
        const reasoning = el.querySelector('.reasoning');
        if (reasoning) reasoning.removeAttribute('open');

        let content = el.querySelector('.content');
        if (!content) {
            content = document.createElement('div');
            content.className = 'content';
            el.prepend(content);
        }
        content.innerHTML = this.md(text);
        this.scrollToBottom();
    },

    appendReasoning(el, text) {
        if (!text) return;
        let details = el.querySelector('.reasoning');
        if (!details) {
            details = document.createElement('details');
            details.className = 'reasoning';
            details.setAttribute('open', '');
            details.innerHTML = '<summary>Thinking\u2026</summary><div class="reasoning-text"></div>';
            el.prepend(details);
        }
        // textContent: never interpret model output as HTML.
        details.querySelector('.reasoning-text').textContent += text;
        this.scrollToBottom();
    },

    addToolChip(el, name) {
        // Only one live indicator at a time.
        const existing = el.querySelector('.tool-chip.running');
        if (existing) existing.remove();
        const chip = document.createElement('div');
        chip.className = 'tool-chip running';
        chip.innerHTML = `<span class="spinner"></span> Running ${this.esc(name)}\u2026`;
        el.appendChild(chip);
        this.scrollToBottom();
    },

    addToolStep(el, step) {
        const chip = el.querySelector('.tool-chip.running');
        if (chip) chip.remove();
        if (!el._toolSteps) el._toolSteps = [];
        el._toolSteps.push(step);
        this.upsertToolActivity(el, el._toolSteps);
    },

    appendNote(el, text) {
        if (!text) return;
        const note = document.createElement('div');
        note.className = 'assistant-note';
        note.innerHTML = this.md(text);
        el.appendChild(note);
        this.scrollToBottom();
    },

    appendPartial(el, stopReason) {
        const note = document.createElement('div');
        note.className = 'partial-note';
        note.textContent = `\u26a0\ufe0f Partial answer \u2014 stopped: ${stopReason || 'execution limit reached'}`;
        el.appendChild(note);
        this.scrollToBottom();
    },

    renderAssistantError(el, message) {
        const error = document.createElement('div');
        error.className = 'assistant-error';
        error.textContent = `Error: ${message}`;
        el.appendChild(error);
        this.scrollToBottom();
    },

    // ── message rendering ─────────────────────────────────────────

    renderToolSteps(toolSteps) {
        // Inner content of the collapsed "Tool activity" block.
        if (!toolSteps || toolSteps.length === 0) return '';
        let html = '';
        for (const step of toolSteps) {
            let inputDisplay = '';
            try {
                inputDisplay = JSON.stringify(JSON.parse(step.tool_input || '{}'), null, 2);
            } catch {
                inputDisplay = step.tool_input || '';
            }
            html += `
                <div class="tool-call">
                    <div class="tool-call-name">${this.esc(step.tool_name)}</div>
                    <pre>${this.esc(inputDisplay)}</pre>
                    ${step.error ? `<pre class="tool-call-error">${this.esc(step.error)}</pre>` : ''}
                </div>`;
        }
        return html;
    },

    upsertToolActivity(el, toolSteps) {
        // One collapsed block for the whole audit trail, hidden by default so
        // the answer stays readable (issue #15).
        if (!toolSteps || toolSteps.length === 0) return;
        let block = el.querySelector('.tool-activity');
        if (!block) {
            block = document.createElement('details');
            block.className = 'tool-activity';
            const note = el.querySelector('.assistant-note, .partial-note');
            if (note) el.insertBefore(block, note);
            else el.appendChild(block);
        }
        const wasOpen = block.hasAttribute('open');
        block.innerHTML =
            `<summary>Tool activity (${toolSteps.length})</summary>` +
            `<div class="tool-activity-body">${this.renderToolSteps(toolSteps)}</div>`;
        if (wasOpen) block.setAttribute('open', '');
        this.scrollToBottom();
    },

    addMessage(role, content, messageId) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        if (messageId) div.dataset.messageId = messageId;
        div.innerHTML = `<div class="content">${this.md(content)}</div>`;
        this.el.messages.appendChild(div);
        this.scrollToBottom();
        return div;
    },

    async loadTraces(messageId, messageEl) {
        try {
            const steps = await this.api('GET', 'traces', null, { message_id: messageId });
            const toolSteps = (steps || []).filter(s => s.step_type === 'tool_call');
            this.upsertToolActivity(messageEl, toolSteps);
        } catch (e) {
            console.error('Failed to load traces:', e);
        }
    },

    renderMessages(messages) {
        this.el.messages.innerHTML = '';
        for (const msg of messages) {
            if (msg.role === 'system' || msg.role === 'tool') continue;
            if (msg.role === 'assistant' && this.hasToolCalls(msg)) continue;

            const el = this.addMessage(msg.role, msg.content, msg.id);
            if (msg.role === 'assistant' && msg.id) {
                this.loadTraces(msg.id, el);
            }
        }
        this.scrollToBottom(true);
    },

    hasToolCalls(msg) {
        if (!msg.tool_calls) return false;
        try {
            const tcs = JSON.parse(msg.tool_calls);
            return Array.isArray(tcs) && tcs.length > 0;
        } catch {
            return false;
        }
    },

    scrollToBottom(force = false) {
        const el = this.el.messages;
        if (!el) return;
        // Follow new output only while the user is pinned to the bottom, so
        // scrolling up to read earlier content is not fought by auto-scroll.
        if (force || this._atBottom !== false) {
            el.scrollTop = el.scrollHeight;
            this._atBottom = true;
        }
    },

    // ── providers / prompts / panels ──────────────────────────────

    async loadProviders() {
        try {
            this.providers = (await this.api('GET', 'providers')) || [];
        } catch (e) {
            console.error('Failed to load providers:', e);
            this.providers = [];
        }

        if (this.providers.length > 0) {
            const def = this.providers.find(p => p.is_default) || this.providers[0];
            this.el.providerName.textContent = `${def.name} ${def.connected ? '\u2713' : '\u2717'}`;
            this.el.providerStatus.className = 'status-dot ' + (def.connected ? 'connected' : 'disconnected');
        } else {
            this.el.providerName.textContent = 'No provider';
            this.el.providerStatus.className = 'status-dot disconnected';
        }

        if (this.el.providerSelect) {
            this.el.providerSelect.innerHTML = this.providers
                .map(p => `<option value="${this.esc(p.name)}"${p.is_default ? ' selected' : ''}>${this.esc(p.name)}${p.connected ? '' : ' (offline)'}</option>`)
                .join('');
            const def = this.providers.find(p => p.is_default) || this.providers[0];
            this.currentProvider = def ? def.name : '';
            if (this.currentProvider) await this.loadModels(this.currentProvider);
        }
    },

    async loadModels(name) {
        if (!this.el.modelSelect) return;
        if (!name) {
            this.el.modelSelect.innerHTML = '';
            this.currentModel = '';
            return;
        }
        try {
            const data = await this.api('GET', 'providers_models', null, { name });
            const models = (data && data.models) || [];
            this.el.modelSelect.innerHTML = models
                .map(m => `<option value="${this.esc(m)}">${this.esc(m)}</option>`)
                .join('');
            this.currentModel = models[0] || '';
        } catch (e) {
            this.el.modelSelect.innerHTML = '';
            this.currentModel = '';
        }
    },

    async loadPrompts() {
        if (!this.el.promptSelect) return;
        try {
            this.prompts = (await this.api('GET', 'prompts')) || [];
        } catch (e) {
            this.prompts = [];
        }
        this.el.promptSelect.innerHTML = this.prompts
            .map(p => `<option value="${this.esc(p.id)}">${this.esc(p.name)}</option>`)
            .join('');
        this.currentPrompt = this.prompts.length ? this.prompts[0].id : 'default';
        this.el.promptSelect.value = this.currentPrompt;
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
            this._configDoc = config || {};
            const providers = config.providers || {};
            const names = Object.keys(providers);
            const agent = config.agent || {};
            const selected = names.includes(this.currentProvider)
                ? this.currentProvider : (names[0] || '');

            let html = '<h4>Configuration</h4>';
            html += '<div class="config-form">';
            html += '<label>Default provider</label>';
            html += '<select id="cfg-provider">' + names.map(n =>
                `<option value="${this.esc(n)}"${n === selected ? ' selected' : ''}>${this.esc(n)}</option>`
            ).join('') + '</select>';
            html += '<div id="cfg-provider-fields"></div>';
            html += '<label>max_iterations</label>';
            html += `<input id="cfg-max-iterations" type="number" min="1" value="${this.esc(agent.max_iterations ?? '')}">`;
            html += '<label>max_tool_calls</label>';
            html += `<input id="cfg-max-tool-calls" type="number" min="1" value="${this.esc(agent.max_tool_calls ?? '')}">`;
            html += '<label>timeout_seconds</label>';
            html += `<input id="cfg-timeout" type="number" min="1" value="${this.esc(agent.timeout_seconds ?? '')}">`;
            html += '<button id="cfg-save" class="btn btn-sm">Save</button>';
            html += '<div id="cfg-status" class="config-status"></div>';
            html += '</div>';
            html += '<p class="config-hint">Secrets are shown masked as <code>***</code>; leaving them unchanged keeps the stored value. Prefer editing the beancount directive for anything that belongs in version control.</p>';

            this.el.panelConfig.innerHTML = html;

            const renderProviderFields = () => {
                const name = document.getElementById('cfg-provider').value;
                const p = providers[name] || {};
                document.getElementById('cfg-provider-fields').innerHTML =
                    '<label>base_url</label>' +
                    `<input id="cfg-base-url" type="text" value="${this.esc(p.base_url || '')}" placeholder="https://.../v1">` +
                    '<label>model</label>' +
                    `<input id="cfg-model" type="text" value="${this.esc(p.model || '')}">` +
                    '<label>api_key</label>' +
                    `<input id="cfg-api-key" type="text" value="${this.esc(p.api_key || '')}" placeholder="***">`;
            };
            document.getElementById('cfg-provider').addEventListener('change', renderProviderFields);
            renderProviderFields();
            document.getElementById('cfg-save').addEventListener('click', () => this.saveConfig());
        } catch (e) {
            this.el.panelConfig.innerHTML = '<p style="color:red;">Failed to load config</p>';
        }
    },

    async saveConfig() {
        const status = document.getElementById('cfg-status');
        const name = document.getElementById('cfg-provider').value;
        const doc = JSON.parse(JSON.stringify(this._configDoc || {}));
        delete doc.config_dir;  // not part of the writable schema
        doc.providers = doc.providers || {};
        doc.providers[name] = doc.providers[name] || {};
        doc.providers[name].base_url = document.getElementById('cfg-base-url').value.trim();
        doc.providers[name].model = document.getElementById('cfg-model').value.trim();
        const apiKey = document.getElementById('cfg-api-key').value;
        if (apiKey) doc.providers[name].api_key = apiKey;

        doc.agent = doc.agent || {};
        for (const [id, field] of [
            ['cfg-max-iterations', 'max_iterations'],
            ['cfg-max-tool-calls', 'max_tool_calls'],
            ['cfg-timeout', 'timeout_seconds'],
        ]) {
            const value = parseInt(document.getElementById(id).value, 10);
            if (!Number.isNaN(value)) doc.agent[field] = value;
        }

        try {
            await this.api('PUT', 'config', doc);
            status.textContent = 'Saved.';
            status.className = 'config-status ok';
            await this.loadProviders();
        } catch (e) {
            status.textContent = 'Error: ' + (e.message || e);
            status.className = 'config-status err';
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

    // ── markdown ──────────────────────────────────────────────────

    esc(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },

    inline(text) {
        let s = this.esc(text);
        const codes = [];
        s = s.replace(/`([^`]+)`/g, (m, c) => {
            codes.push(c);
            return `\u0000${codes.length - 1}\u0000`;
        });
        s = s.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            (m, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
        );
        s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
        s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
        s = s.replace(/\u0000(\d+)\u0000/g, (m, i) => `<code>${codes[Number(i)]}</code>`);
        return s;
    },

    isBlockStart(line, next) {
        if (line.trim() === '') return true;
        if (/^```/.test(line)) return true;
        if (/^#{1,6}\s+/.test(line)) return true;
        if (/^>\s?/.test(line)) return true;
        if (/^\s*([-*+]|\d+\.)\s+/.test(line)) return true;
        if (line.includes('|') && next && /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(next)) return true;
        return false;
    },

    splitTableRow(line) {
        let s = line.trim();
        if (s.startsWith('|')) s = s.slice(1);
        if (s.endsWith('|')) s = s.slice(0, -1);
        return s.split('|').map(c => c.trim());
    },

    md(text) {
        if (!text) return '';
        const lines = String(text).replace(/\r\n/g, '\n').split('\n');
        let html = '';
        let i = 0;
        while (i < lines.length) {
            const line = lines[i];

            const fence = line.match(/^```(\w*)\s*$/);
            if (fence) {
                const lang = fence[1];
                const buf = [];
                i++;
                while (i < lines.length && !/^```\s*$/.test(lines[i])) {
                    buf.push(lines[i]);
                    i++;
                }
                i++;
                html += `<pre><code class="language-${this.esc(lang)}">${this.esc(buf.join('\n'))}</code></pre>`;
                continue;
            }

            if (
                line.includes('|') && i + 1 < lines.length &&
                /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1])
            ) {
                const header = this.splitTableRow(line);
                const rows = [];
                i += 2;
                while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
                    rows.push(this.splitTableRow(lines[i]));
                    i++;
                }
                html += '<table><thead><tr>' +
                    header.map(c => `<th>${this.inline(c)}</th>`).join('') +
                    '</tr></thead><tbody>';
                for (const row of rows) {
                    html += '<tr>' + row.map(c => `<td>${this.inline(c)}</td>`).join('') + '</tr>';
                }
                html += '</tbody></table>';
                continue;
            }

            const heading = line.match(/^(#{1,6})\s+(.*)$/);
            if (heading) {
                const level = heading[1].length;
                html += `<h${level}>${this.inline(heading[2])}</h${level}>`;
                i++;
                continue;
            }

            if (/^>\s?/.test(line)) {
                const buf = [];
                while (i < lines.length && /^>\s?/.test(lines[i])) {
                    buf.push(lines[i].replace(/^>\s?/, ''));
                    i++;
                }
                html += `<blockquote>${this.md(buf.join('\n'))}</blockquote>`;
                continue;
            }

            if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
                const ordered = /^\s*\d+\./.test(line);
                const items = [];
                while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
                    items.push(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ''));
                    i++;
                }
                const tag = ordered ? 'ol' : 'ul';
                html += `<${tag}>` + items.map(it => `<li>${this.inline(it)}</li>`).join('') + `</${tag}>`;
                continue;
            }

            if (line.trim() === '') {
                i++;
                continue;
            }

            const buf = [];
            while (
                i < lines.length &&
                !this.isBlockStart(lines[i], lines[i + 1])
            ) {
                buf.push(lines[i]);
                i++;
            }
            if (buf.length) {
                html += `<p>${this.inline(buf.join(' '))}</p>`;
            } else {
                i++;
            }
        }
        return html;
    },
};
