/* Plain JavaScript controller. Polling reads state; only explicit controls mutate it. */
const App = {
    state: null,
    selectedPid: 1,
    currentFilter: 'ALL',
    busy: false,
    fetching: false,
    generation: 0,
    signature: '',
    connected: false,
    connectionError: false,
    cards: new Map(),

    init() {
        Visualizer.init();
        this.fetchState();
        this.pollingInterval = setInterval(() => this.fetchState(), 300);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) this.fetchState();
        });
    },

    text(id, value) {
        const element = document.getElementById(id);
        const text = String(value);
        if (element.textContent !== text) element.textContent = text;
    },

    escape(value) {
        return String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
    },

    showError(message) {
        this.text('error-banner', message);
        document.getElementById('error-banner').hidden = false;
    },

    async fetchState() {
        if (this.fetching || this.busy || document.hidden) return;
        this.fetching = true;
        const generation = this.generation;
        try {
            const response = await fetch('/api/state?filter=' + this.currentFilter + '&limit=60', {cache: 'no-store'});
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error('Could not read the simulation.');
            if (generation !== this.generation) return;
            this.connected = true;
            if (this.connectionError) document.getElementById('error-banner').hidden = true;
            this.connectionError = false;
            this.renderState(result.data);
        } catch (error) {
            if (generation !== this.generation) return;
            this.connected = false;
            this.connectionError = true;
            this.showError('Connection lost. Keep the Flask server running; the page will reconnect automatically.');
            this.syncControls();
        } finally {
            this.fetching = false;
        }
    },

    async action(path, body) {
        if (this.busy || !this.connected) return;
        this.busy = true;
        this.generation += 1; // Ignore a poll started before this action.
        document.getElementById('error-banner').hidden = true;
        this.syncControls();
        try {
            const options = {method: 'POST'};
            if (body !== undefined) {
                options.headers = {'Content-Type': 'application/json'};
                options.body = JSON.stringify(body);
            }
            const response = await fetch(path, options);
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || result.message || 'The action could not be completed.');
            if (result.data) this.renderState(result.data);
            else if (this.state && typeof result.is_running === 'boolean') {
                this.renderState({...this.state, is_running: result.is_running});
            }
        } catch (error) {
            this.showError(error.message || 'The action failed. Check the server and try again.');
        } finally {
            this.busy = false;
            this.syncControls();
            this.fetchState();
        }
    },

    syncControls() {
        const running = !!this.state?.is_running;
        const unavailable = this.busy || !this.connected;
        const status = document.getElementById('run-status');
        status.className = 'run-status' + (!this.connected ? ' disconnected' : running ? ' running' : '');
        status.textContent = !this.connected ? 'Connecting to server' : running ? 'Auto running' : 'Paused · step at your own pace';
        const idleCount = this.state?.processes.filter(p => p.state === 'RELEASED').length || 0;
        document.getElementById('btn-play').textContent = running ? 'Pause auto' : 'Start auto';
        document.getElementById('btn-step').disabled = unavailable || running;
        document.getElementById('btn-step').title = running ? 'Pause auto before stepping manually.' : 'Deliver one message or advance one CS tick.';
        document.getElementById('btn-play').disabled = unavailable;
        document.getElementById('btn-reset').disabled = unavailable;
        document.getElementById('btn-concurrent').disabled = unavailable || idleCount < 2;
        ['config-algorithm', 'config-processes', 'config-speed', 'config-cs-duration'].forEach(id => document.getElementById(id).disabled = unavailable);
        this.cards.forEach((card, pid) => {
            const process = this.state?.processes.find(p => p.pid === pid);
            card.querySelector('.request-button').disabled = unavailable || process?.state !== 'RELEASED';
        });
    },

    renderState(state) {
        const signature = JSON.stringify([state.algorithm, state.step, state.live_event?.id, state.process_count, state.is_running, state.speed_ms, state.cs_duration, state.stats.violations_count, this.currentFilter, state.events.map(event => event.id)]);
        this.state = state;
        this.syncControls();
        if (signature === this.signature) return;
        const algorithmChanged = state.algorithm !== this.lastAlgorithm;
        const reset = !!this.signature && (algorithmChanged || state.step < this.lastStep || state.process_count !== this.lastCount);
        if (reset) {
            this.logSignature = '';
            document.getElementById('event-log-list').replaceChildren();
            Visualizer.lastDeliveryKey = '';
        }
        this.signature = signature;
        this.lastStep = state.step;
        this.lastCount = state.process_count;
        if (algorithmChanged) this.renderAlgorithm(state);
        this.lastAlgorithm = state.algorithm;
        if (!state.processes.some(p => p.pid === this.selectedPid)) this.selectedPid = 1;
        this.syncSelect('config-processes', state.process_count, state.process_count + ' processes');
        this.syncSelect('config-speed', state.speed_ms, (state.speed_ms / 1000) + ' seconds');
        this.syncSelect('config-cs-duration', state.cs_duration, state.cs_duration + ' ticks');
        const violations = state.shared_resource.violations_count;
        this.text('safety-status', violations ? 'Safety violation detected' : 'Safety holds in this run');
        this.text('stat-violations', violations + ' violation' + (violations === 1 ? '' : 's'));
        document.getElementById('safety-dot').classList.toggle('unsafe', violations > 0);
        this.text('cs-occupancy', state.processes.filter(p => p.state === 'IN_CRITICAL_SECTION').length + ' / 1');
        this.text('stat-completed', state.stats.completed_requests);
        this.text('stat-total-messages', state.stats.total_messages);
        this.text('step-badge', 'Step #' + state.step);
        this.text('in-transit-count', state.in_transit_messages.length + ' pending');
        const factor = state.algorithm === 'ricart_agrawala' ? 2 : 3;
        this.text('bound-calc', factor + ' × (' + state.process_count + ' − 1) = ' + factor * (state.process_count - 1) + ' messages per completed request');
        this.renderExplanation(state);
        this.renderProcesses(state.processes);
        this.renderInspector();
        this.renderObserver(state);
        this.renderLog();
        this.renderTimeline(state.message_timeline);
        Visualizer.render(state, this.selectedPid);
        this.syncControls();
    },

    syncSelect(id, value, label) {
        const select = document.getElementById(id);
        if (![...select.options].some(option => Number(option.value) === value)) select.add(new Option(label, value));
        select.value = String(value);
    },

    renderAlgorithm(state) {
        const ricart = state.algorithm === 'ricart_agrawala';
        document.getElementById('config-algorithm').value = state.algorithm;
        this.text('algorithm-name', state.algorithm_name + ' Algorithm');
        document.title = 'Distributed Mutual Exclusion Simulator | ' + state.algorithm_name + ' Algorithm';
        document.getElementById('release-legend').hidden = ricart;
        document.querySelector('[data-filter="RELEASE"]').hidden = ricart;
        document.getElementById('condition-head').hidden = ricart;
        this.text('entry-title', ricart ? 'Local entry condition' : 'Local entry conditions');
        this.text('process-title', ricart ? 'Processes & deferred replies' : 'Processes & local queues');
        this.text('process-subtitle', ricart ? 'Deferred replies are held locally and sent on exit.' : 'Each process makes its own entry decision.');
        this.text('observer-description', ricart ? 'Active requests ordered by (timestamp, PID) for display. Each process enters after all peers reply.' : 'Combined view of local queues, sorted by (timestamp, PID). Each process checks its own queue and replies.');
        this.text('observer-detail-title', ricart ? 'Replies' : 'Seen in');
        this.text('complexity-description', ricart ? 'One REQUEST and one REPLY per peer. Deferred replies are sent on exit; no RELEASE broadcast. Reliable delivery and failure-free processes are assumed.' : 'One REQUEST, one REPLY, and one RELEASE per peer. Reliable FIFO delivery and failure-free processes are assumed.');
        document.querySelector('[data-phase="release"]').textContent = ricart ? 'Reply on exit' : 'Release';
        document.getElementById('algorithm-stages').innerHTML = state.algorithm_stages.map(stage => '<li><strong>' + this.escape(stage.title.replace(/^Stage \d+: /, '')) + '</strong><p>' + this.escape(stage.description) + '</p></li>').join('');
        if (ricart && this.currentFilter === 'RELEASE') this.setFilter('ALL');
    },

    renderExplanation(state) {
        const event = state.live_event;
        if (!event) return;
        const delivery = [...state.live_events].reverse().find(item => item.details?.message);
        const clockEvent = delivery || event;
        const details = clockEvent.details || {};
        const type = event.event_type;
        const phase = event.details?.deferred ? 'reply' : type === 'REQUEST' ? 'request' : type === 'REPLY' ? 'reply' : type === 'CS_EXIT' || type === 'RELEASE' ? 'release' : type.startsWith('CS_') ? 'cs' : '';
        document.querySelectorAll('[data-phase]').forEach(element => element.classList.toggle('active', element.dataset.phase === phase));
        this.text('event-kind', event.details?.deferred ? 'Reply deferred' : type.startsWith('CS_') ? 'Critical section' : type === 'SYSTEM' ? 'System' : type);
        this.text('edu-title', event.description);
        this.text('edu-rule', event.educational_note);
        if (details.message) {
            const message = details.message;
            this.text('clock-equation', 'P' + message.receiver_id + ': C = max(' + details.clock_before + ', ' + message.timestamp + ') + 1 = ' + details.clock_after);
        } else if (details.clock_before !== undefined) {
            this.text('clock-equation', 'P' + event.process_id + ': C = ' + details.clock_before + ' + 1 = ' + details.clock_after);
        } else {
            this.text('clock-equation', type.startsWith('CS_') ? (state.algorithm === 'ricart_agrawala' ? 'Entry requires: a REPLY from every other process.' : 'Entry requires: first in local queue AND all peer replies.') : 'Order: lower timestamp first; equal timestamps use lower PID.');
        }
        let next = 'Choose Request resource below, or try Concurrent requests.';
        if (state.in_transit_messages.length) {
            const message = state.in_transit_messages[0];
            next = 'Next step delivers ' + message.msg_type + ': P' + message.sender_id + ' → P' + message.receiver_id + '.';
        } else {
            const inside = state.processes.find(p => p.state === 'IN_CRITICAL_SECTION');
            if (inside) next = 'P' + inside.pid + ' continues for ' + inside.cs_ticks_remaining + ' tick' + (inside.cs_ticks_remaining === 1 ? '' : 's') + (state.algorithm === 'ricart_agrawala' ? ', then sends any deferred replies.' : ', then broadcasts RELEASE.');
        }
        this.text('edu-next', next);
    },

    renderProcesses(processes) {
        const container = document.getElementById('processes-container');
        if (this.cards.size !== processes.length) {
            this.cards.clear();
            container.replaceChildren();
            const select = document.getElementById('inspect-process');
            select.replaceChildren();
            processes.forEach(process => {
                const card = document.createElement('article');
                card.id = 'process-' + process.pid;
                card.innerHTML = '<div class="process-card-header"><button class="process-name" aria-label="Inspect P' + process.pid + '">Process P' + process.pid + '</button><span class="state-tag"></span></div><div class="process-values"><span>Clock <strong class="process-clock mono"></strong></span><span>Replies <strong class="replies-value mono"></strong></span></div><span class="local-queue-label"><span class="queue-label-text">Local queue</span> <span class="queue-hint"></span></span><div class="local-queue"></div><div class="process-footer"><span class="completed-value"></span><button class="request-button">Request resource</button></div>';
                card.querySelector('.process-name').onclick = () => this.selectProcess(process.pid);
                card.querySelector('.request-button').onclick = () => this.requestResource(process.pid);
                container.append(card);
                this.cards.set(process.pid, card);
                select.add(new Option('P' + process.pid, process.pid));
            });
        }
        processes.forEach(process => {
            const card = this.cards.get(process.pid);
            const ricart = this.state.algorithm === 'ricart_agrawala';
            const inside = process.state === 'IN_CRITICAL_SECTION';
            card.className = 'process-card' + (process.pid === this.selectedPid ? ' selected' : '') + (inside ? ' in-cs' : '');
            const state = card.querySelector('.state-tag');
            const stateClass = inside ? 'in-cs' : process.state === 'REQUESTING' ? 'requesting' : process.state === 'WAITING' ? 'waiting' : '';
            state.className = 'state-tag ' + stateClass;
            state.textContent = inside ? 'In CS · ' + process.cs_ticks_remaining + 't' : process.state === 'RELEASED' ? 'Idle' : process.state === 'WAITING' ? 'Waiting' : 'Requesting';
            card.querySelector('.process-clock').textContent = process.clock;
            card.querySelector('.replies-value').textContent = process.current_request ? process.replies_count + '/' + (processes.length - 1) : '—';
            card.querySelector('.completed-value').textContent = process.completed_requests + ' completed';
            card.querySelector('.request-button').textContent = inside ? 'Inside CS' : process.state === 'RELEASED' ? 'Request resource' : 'Request pending';
            card.querySelector('.queue-label-text').textContent = ricart ? 'Deferred replies' : 'Local queue';
            card.querySelector('.local-queue-label').title = ricart ? 'Requests this process will reply to after it exits the critical section.' : 'Requests ordered by timestamp, then process ID.';
            card.querySelector('.queue-hint').textContent = process.current_request ? (ricart ? '· own request T=' + process.current_request.timestamp : '· own request highlighted') : '';
            const queue = card.querySelector('.local-queue');
            const requests = ricart ? process.deferred_replies : process.request_queue;
            const queueMarkup = requests.map(request => '<span class="queue-token mono' + (!ricart && request.process_id === process.pid ? ' own' : '') + '">(' + request.timestamp + ', P' + request.process_id + ')</span>').join('') || '<span class="queue-empty">' + (ricart ? 'None held' : 'Empty') + '</span>';
            if (queue.innerHTML !== queueMarkup) queue.innerHTML = queueMarkup;
        });
        container.setAttribute('aria-busy', 'false');
        document.getElementById('inspect-process').value = String(this.selectedPid);
    },

    renderInspector() {
        const process = this.state.processes.find(item => item.pid === this.selectedPid);
        if (!process) return;
        const active = !!process.current_request;
        const head = process.request_queue[0];
        const first = active && head?.process_id === process.pid && head.timestamp === process.current_request.timestamp;
        const peers = this.state.processes.filter(item => item.pid !== process.pid).map(item => item.pid);
        const missing = peers.filter(pid => !process.replies_received.includes(pid));
        const allReplies = active && missing.length === 0;
        const ricart = this.state.algorithm === 'ricart_agrawala';
        [['condition-head', first], ['condition-replies', allReplies]].forEach(([id, met]) => {
            const element = document.getElementById(id);
            element.classList.toggle('met', !!met);
            element.querySelector('.condition-symbol').textContent = met ? 'Yes' : 'No';
            element.querySelector('.condition-symbol').setAttribute('aria-label', met ? 'Satisfied' : 'Not satisfied');
        });
        let reason = 'P' + process.pid + ' has no active request. ' + (ricart ? 'A request needs every peer\'s REPLY before entry.' : 'Both conditions are needed to enter.');
        if (process.state === 'IN_CRITICAL_SECTION') reason = (ricart ? 'Every peer replied. ' : 'Both conditions were met. ') + 'P' + process.pid + ' is inside the critical section.';
        else if (active) {
            const reasons = [];
            if (!ricart && !first) reasons.push('P' + head.process_id + ' is ahead in its local queue');
            if (missing.length) reasons.push('waiting for ' + missing.map(pid => 'P' + pid).join(', ') + ' to reply');
            reason = 'P' + process.pid + ': ' + (reasons.join('; ') || (ricart ? 'every peer has replied' : 'both entry conditions are satisfied')) + '.';
        }
        this.text('entry-reason', reason);
    },

    renderObserver(state) {
        const queue = state.global_request_queue;
        this.text('queue-length-badge', queue.length + ' request' + (queue.length === 1 ? '' : 's'));
        document.getElementById('global-queue-body').innerHTML = queue.length ? queue.map((request, index) => {
            const seen = state.processes.filter(process => process.request_queue.some(item => item.timestamp === request.timestamp && item.process_id === request.process_id)).map(process => 'P' + process.pid).join(', ');
            const owner = state.processes.find(process => process.pid === request.process_id);
            const detail = state.algorithm === 'ricart_agrawala' ? owner.replies_count + '/' + (state.process_count - 1) : seen;
            const status = request.is_in_cs ? 'Inside CS' : request.is_active ? (owner.state === 'WAITING' ? 'Waiting' : 'Requesting') : 'Release pending';
            const kind = request.is_in_cs ? 'executing' : request.is_active ? '' : 'cleanup';
            return '<tr><td class="mono">' + (index + 1) + '</td><td class="mono">(' + request.timestamp + ', P' + request.process_id + ')</td><td><span class="observer-status ' + kind + '">' + status + '</span></td><td>' + detail + '</td></tr>';
        }).join('') : '<tr><td colspan="4" class="empty-state">No outstanding requests. The resource is ready.</td></tr>';
    },

    renderLog() {
        const signature = this.currentFilter + ':' + this.state.events.map(event => event.id).join(',');
        if (signature === this.logSignature) return;
        this.logSignature = signature;
        const events = this.state.events.filter(event => this.currentFilter === 'ALL' || (this.currentFilter === 'CRITICAL_SECTION' ? event.event_type.startsWith('CS_') : event.event_type === this.currentFilter));
        const container = document.getElementById('event-log-list');
        const opened = new Set([...container.querySelectorAll('details[open]')].map(element => element.dataset.event));
        const scroll = container.scrollTop;
        container.innerHTML = events.map(event => '<details class="log-entry" data-event="' + event.id + '"' + (opened.has(String(event.id)) ? ' open' : '') + '><summary><span class="log-step mono">#' + event.step + '</span><span>' + this.escape(event.description) + '</span><span class="message-tag ' + event.event_type.toLowerCase() + '">' + event.event_type.replaceAll('_', ' ') + '</span></summary><p>' + this.escape(event.educational_note) + '</p></details>').join('') || '<p class="empty-state">No matching events in the loaded history.</p>';
        container.scrollTop = scroll;
    },

    renderTimeline(messages) {
        document.getElementById('timeline-body').innerHTML = messages.map(message => '<tr><td class="mono">P' + message.sender_id + ' → P' + message.receiver_id + '</td><td><span class="message-tag ' + message.msg_type.toLowerCase() + '">' + message.msg_type + '</span></td><td class="mono">' + message.timestamp + '</td><td>' + (message.status === 'delivered' ? 'Delivered · #' + message.step_delivered : 'Pending') + '</td></tr>').join('') || '<tr><td colspan="4" class="empty-state">No messages sent yet.</td></tr>';
    },

    selectProcess(pid) {
        this.selectedPid = pid;
        if (!this.state) return;
        this.renderProcesses(this.state.processes);
        this.renderInspector();
        Visualizer.render(this.state, pid);
        this.syncControls();
    },

    setFilter(filter) {
        this.generation += 1;
        this.currentFilter = filter;
        document.querySelectorAll('[data-filter]').forEach(button => {
            const active = button.dataset.filter === filter;
            button.classList.toggle('active', active);
            button.setAttribute('aria-pressed', String(active));
        });
        if (this.state) this.renderLog();
    },

    requestResource(pid) { this.selectProcess(pid); return this.action('/api/request', {pid}); },
    triggerConcurrent() { return this.action('/api/concurrent', {}); },
    stepSimulation() { if (!this.state?.is_running) return this.action('/api/step'); },
    togglePlayback() { return this.action(this.state?.is_running ? '/api/pause' : '/api/start'); },
    resetSimulation() { return this.action('/api/reset'); },
    updateConfig(key, value) { return this.action('/api/config', {[key]: key === 'algorithm' ? value : Number(value)}); }
};

document.addEventListener('DOMContentLoaded', () => App.init());
