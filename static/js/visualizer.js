/* Stable SVG nodes; only the current delivery gets an animated route. */
const Visualizer = {
    nodes: new Map(),
    lastDeliveryKey: '',
    animationFrame: null,

    element(tag, attributes = {}, text) {
        const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
        if (text !== undefined) element.textContent = text;
        return element;
    },

    init() {
        this.svg = document.getElementById('network-svg');
        this.links = this.element('g', {'aria-hidden': 'true'});
        this.route = this.element('g', {'aria-hidden': 'true'});
        this.resource = this.element('g');
        this.processLayer = this.element('g');
        this.svg.append(this.links, this.route, this.resource, this.processLayer);
        this.resizeObserver = new ResizeObserver(() => {
            if (this.state) this.render(this.state, this.selectedPid, true);
        });
        this.resizeObserver.observe(this.svg.parentElement);
    },

    render(state, selectedPid, resizing = false) {
        this.state = state;
        this.selectedPid = selectedPid;
        if (this.animationFrame) cancelAnimationFrame(this.animationFrame);
        const width = this.svg.parentElement.clientWidth;
        const height = 320;
        this.svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
        const cx = width / 2, cy = height / 2;
        const rx = width / 2 - 62, ry = 112;
        const positions = new Map();
        state.processes.forEach((process, index) => {
            const angle = 2 * Math.PI * index / state.processes.length - Math.PI / 2;
            positions.set(process.pid, {x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle)});
        });
        if (this.nodes.size !== state.processes.length) {
            this.nodes.clear();
            this.processLayer.replaceChildren();
            state.processes.forEach(process => {
                const group = this.element('g', {class: 'svg-process', tabindex: 0, role: 'button'});
                const rect = this.element('rect', {x: -42, y: -23, width: 84, height: 46, rx: 8, 'stroke-width': 1.5});
                const label = this.element('text', {y: -3, 'text-anchor': 'middle', 'font-size': 15, 'font-weight': 600, fill: 'var(--text)'}, 'P' + process.pid);
                const clock = this.element('text', {y: 14, 'text-anchor': 'middle', 'font-size': 12, 'font-family': 'Consolas, monospace', fill: 'var(--muted)'});
                const status = this.element('text', {y: 38, 'text-anchor': 'middle', 'font-size': 12, fill: 'var(--muted)'});
                group.append(rect, label, clock, status);
                group.onclick = () => App.selectProcess(process.pid);
                group.onkeydown = event => {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); App.selectProcess(process.pid); }
                };
                this.processLayer.append(group);
                this.nodes.set(process.pid, {group, rect, clock, status});
            });
        }
        this.links.replaceChildren();
        const selected = positions.get(selectedPid);
        if (selected) positions.forEach((position, pid) => {
            if (pid !== selectedPid) this.links.append(this.element('line', {x1: selected.x, y1: selected.y, x2: position.x, y2: position.y, stroke: 'var(--border)', 'stroke-width': 1}));
        });
        state.processes.forEach(process => {
            const node = this.nodes.get(process.pid);
            const position = positions.get(process.pid);
            const kind = process.state === 'IN_CRITICAL_SECTION' ? 'release' : process.state === 'REQUESTING' ? 'request' : process.state === 'WAITING' ? 'reply' : null;
            node.group.setAttribute('transform', 'translate(' + position.x + ' ' + position.y + ')');
            node.group.setAttribute('aria-label', 'Inspect P' + process.pid + ', clock ' + process.clock + ', ' + process.state.replaceAll('_', ' ').toLowerCase());
            node.group.setAttribute('aria-pressed', String(process.pid === selectedPid));
            node.rect.setAttribute('fill', kind ? 'var(--' + kind + '-bg)' : 'var(--surface)');
            node.rect.setAttribute('stroke', process.pid === selectedPid ? 'var(--accent)' : kind ? 'var(--' + kind + ')' : 'var(--control)');
            node.rect.setAttribute('stroke-width', process.pid === selectedPid ? 2.5 : 1.5);
            node.clock.textContent = 'C = ' + process.clock;
            node.status.textContent = process.state === 'IN_CRITICAL_SECTION' ? 'In CS' : process.state === 'RELEASED' ? 'Idle' : process.state === 'WAITING' ? 'Waiting' : 'Requesting';
        });
        const inside = state.processes.find(process => process.state === 'IN_CRITICAL_SECTION');
        this.resource.replaceChildren();
        if (inside) {
            const position = positions.get(inside.pid);
            this.links.append(this.element('line', {x1: position.x, y1: position.y, x2: cx, y2: cy, stroke: 'var(--release)', 'stroke-width': 2}));
        }
        this.resource.append(
            this.element('rect', {x: cx - 74, y: cy - 31, width: 148, height: 62, rx: 9, fill: inside ? 'var(--release-bg)' : 'var(--raised)', stroke: inside ? 'var(--release)' : 'var(--border)'}),
            this.element('text', {x: cx, y: cy - 9, 'text-anchor': 'middle', 'font-size': 12, fill: 'var(--muted)'}, 'Critical section'),
            this.element('text', {x: cx, y: cy + 14, 'text-anchor': 'middle', 'font-size': 17, 'font-weight': 600, fill: inside ? 'var(--release)' : 'var(--text)'}, inside ? 'P' + inside.pid + ' inside' : 'Available')
        );
        this.route.replaceChildren();
        const delivery = [...(state.live_events || [])].reverse().find(event => event.details?.message);
        const message = delivery?.details.message;
        if (message) {
            const from = positions.get(message.sender_id), to = positions.get(message.receiver_id);
            const dx = to.x - from.x, dy = to.y - from.y, distance = Math.hypot(dx, dy);
            const midpoint = {x: (from.x + to.x) / 2, y: (from.y + to.y) / 2};
            const bend = Math.hypot(midpoint.x - cx, midpoint.y - cy) < 90 ? 130 : 25;
            const control = {x: midpoint.x - dy / distance * bend, y: midpoint.y + dx / distance * bend};
            const edge = (node, toward) => {
                const vx = toward.x - node.x, vy = toward.y - node.y;
                const scale = Math.min(46 / (Math.abs(vx) || 1), 27 / (Math.abs(vy) || 1));
                return {x: node.x + vx * scale, y: node.y + vy * scale};
            };
            const startPoint = edge(from, control), endPoint = edge(to, control);
            const d = 'M ' + startPoint.x + ' ' + startPoint.y + ' Q ' + control.x + ' ' + control.y + ' ' + endPoint.x + ' ' + endPoint.y;
            const colour = 'var(--' + message.msg_type.toLowerCase() + ')';
            const defs = this.element('defs');
            const marker = this.element('marker', {id: 'delivery-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto'});
            marker.append(this.element('path', {d: 'M 0 0 L 10 5 L 0 10 Z', fill: colour}));
            defs.append(marker);
            const path = this.element('path', {d, fill: 'none', stroke: colour, 'stroke-width': 2, 'marker-end': 'url(#delivery-arrow)'});
            const dot = this.element('circle', {r: 5, class: 'packet-dot', stroke: colour});
            this.route.append(defs, path, dot);
            const key = message.id + ':' + state.step;
            const animate = key !== this.lastDeliveryKey && !resizing && !matchMedia('(prefers-reduced-motion: reduce)').matches;
            this.lastDeliveryKey = key;
            const length = path.getTotalLength();
            const positionDot = progress => {
                const point = path.getPointAtLength(length * progress);
                dot.setAttribute('transform', 'translate(' + point.x + ' ' + point.y + ')');
            };
            if (animate) {
                const start = performance.now();
                const duration = Math.min(380, state.speed_ms * 0.45);
                const frame = now => {
                    const progress = Math.min(1, (now - start) / duration);
                    positionDot(progress);
                    if (progress < 1) this.animationFrame = requestAnimationFrame(frame);
                };
                positionDot(0);
                this.animationFrame = requestAnimationFrame(frame);
            } else positionDot(1);
            App.text('network-caption', 'Delivered ' + message.msg_type + ': P' + message.sender_id + ' → P' + message.receiver_id + ' · message timestamp ' + message.timestamp);
        } else if (inside) {
            App.text('network-caption', 'P' + inside.pid + ' has exclusive access · ' + inside.cs_ticks_remaining + ' CS ticks remaining.');
        } else if (state.in_transit_messages.length) {
            App.text('network-caption', state.in_transit_messages.length + ' messages waiting. Next step delivers the first one.');
        } else App.text('network-caption', 'Select a process to inspect it. Choose Request resource below to begin.');
    }
};
