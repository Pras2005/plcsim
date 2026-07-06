/* ================================================================
   PLC Simulator Dashboard — Application Logic
   ================================================================ */

(function () {
    'use strict';

    // ─── State ────────────────────────────────────────────────
    let tagConfig = [];          // tag metadata from config_data
    let currentMachines = [];    // last known machine list
    let isConnected = false;

    // ─── DOM References ───────────────────────────────────────
    const machineGrid       = document.getElementById('machine-grid');
    const connectionDot     = document.getElementById('connection-dot');
    const connectionLabel   = document.getElementById('connection-label');
    const settingsToggle    = document.getElementById('settings-toggle');
    const settingsPanel     = document.getElementById('settings-panel');
    const settingsOverlay   = document.getElementById('settings-overlay');
    const settingsClose     = document.getElementById('settings-close');
    const settingsForm      = document.getElementById('settings-form');
    const cfgMachineCount   = document.getElementById('cfg-machine-count');
    const cfgUpdateInterval = document.getElementById('cfg-update-interval');
    const cfgPlcEnabled     = document.getElementById('cfg-plc-enabled');
    const cfgPlcProfile     = document.getElementById('cfg-plc-profile');
    const cfgPlcIp          = document.getElementById('cfg-plc-ip');
    const cfgPlcPort        = document.getElementById('cfg-plc-port');
    const cfgPlcDeviceId    = document.getElementById('cfg-plc-device-id');
    const plcFields         = document.getElementById('plc-fields');

    // ─── Settings Panel ───────────────────────────────────────
    function openSettings() {
        settingsPanel.classList.add('is-open');
        settingsOverlay.hidden = false;
        requestAnimationFrame(() => settingsOverlay.classList.add('is-open'));
    }

    function closeSettings() {
        settingsPanel.classList.remove('is-open');
        settingsOverlay.classList.remove('is-open');
        setTimeout(() => { settingsOverlay.hidden = true; }, 300);
    }

    settingsToggle.addEventListener('click', openSettings);
    settingsClose.addEventListener('click', closeSettings);
    settingsOverlay.addEventListener('click', closeSettings);

    cfgPlcEnabled.addEventListener('change', () => {
        plcFields.hidden = !cfgPlcEnabled.checked;
    });

    cfgPlcProfile.addEventListener('change', () => {
        const val = cfgPlcProfile.value;
        if (val === 'localhost') {
            cfgPlcIp.value = '127.0.0.1';
            cfgPlcPort.value = 5020;
        } else if (val === 'router') {
            cfgPlcIp.value = '192.168.1.5';
            cfgPlcPort.value = 502;
        }
    });

    settingsForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const cfg = {
            machine_count:  parseInt(cfgMachineCount.value, 10),
            update_interval: parseFloat(cfgUpdateInterval.value),
            plc_enabled:    cfgPlcEnabled.checked,
            plc_ip:         cfgPlcIp.value,
            plc_port:       parseInt(cfgPlcPort.value, 10),
            plc_device_id:  parseInt(cfgPlcDeviceId.value, 10),
        };
        socket.emit('update_config', cfg);
        closeSettings();
    });

    // ─── SVG Gauge Helpers ────────────────────────────────────
    const GAUGE_RADIUS   = 46;
    const GAUGE_STROKE   = 8;
    const GAUGE_CX       = 60;
    const GAUGE_CY       = 60;
    // 270° sweep
    const SWEEP_ANGLE    = 270;
    const START_ANGLE    = 135; // degrees (bottom-left start)
    const CIRCUMFERENCE  = 2 * Math.PI * GAUGE_RADIUS;
    const ARC_LENGTH     = (SWEEP_ANGLE / 360) * CIRCUMFERENCE;

    /**
     * Convert a polar point to SVG cartesian coords.
     */
    function polarToCartesian(cx, cy, r, angleDeg) {
        const rad = (angleDeg - 90) * Math.PI / 180;
        return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
    }

    /**
     * Build an SVG arc path for a given sweep angle.
     */
    function describeArc(cx, cy, r, startAngle, sweepAngle) {
        const start = polarToCartesian(cx, cy, r, startAngle);
        const end   = polarToCartesian(cx, cy, r, startAngle + sweepAngle);
        const large = sweepAngle > 180 ? 1 : 0;
        return `M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 1 ${end.x} ${end.y}`;
    }

    /**
     * Determine gauge color based on thresholds.
     */
    function gaugeColor(value, warnHigh, alarmHigh) {
        if (alarmHigh != null && value >= alarmHigh) return 'var(--alarm)';
        if (warnHigh  != null && value >= warnHigh)  return 'var(--warning)';
        return 'var(--primary)';
    }

    /**
     * Create the static SVG gauge markup.
     */
    function createGaugeSVG(id) {
        const arcPath = describeArc(GAUGE_CX, GAUGE_CY, GAUGE_RADIUS, START_ANGLE, SWEEP_ANGLE);
        return `
        <svg class="gauge-svg" viewBox="0 0 120 120" id="${id}">
            <path class="gauge-bg"
                  d="${arcPath}"
                  stroke-width="${GAUGE_STROKE}" />
            <path class="gauge-fill"
                  d="${arcPath}"
                  stroke-width="${GAUGE_STROKE}"
                  stroke-dasharray="${ARC_LENGTH}"
                  stroke-dashoffset="${ARC_LENGTH}"
                  id="${id}-fill" />
            <text class="gauge-value" x="${GAUGE_CX}" y="${GAUGE_CY - 4}" id="${id}-val">0</text>
            <text class="gauge-unit"  x="${GAUGE_CX}" y="${GAUGE_CY + 14}" id="${id}-unit"></text>
        </svg>`;
    }

    /**
     * Update gauge with a new value.
     */
    function updateGauge(id, value, min, max, unit, warnHigh, alarmHigh) {
        const fill  = document.getElementById(`${id}-fill`);
        const valEl = document.getElementById(`${id}-val`);
        const unitEl = document.getElementById(`${id}-unit`);
        if (!fill) return;

        const ratio  = Math.max(0, Math.min(1, (value - min) / (max - min)));
        const offset = ARC_LENGTH - ratio * ARC_LENGTH;

        fill.style.strokeDashoffset = offset;
        fill.style.stroke = gaugeColor(value, warnHigh, alarmHigh);
        valEl.textContent = Math.round(value);
        unitEl.textContent = unit || '';
    }

    // ─── Machine Card Rendering ───────────────────────────────
    const STATUS_BITS = [
        { key: 'power',     label: 'PWR',   activeClass: 'led--pwr-on'   },
        { key: 'auto',      label: 'AUTO',  activeClass: 'led--auto-on'  },
        { key: 'running',   label: 'RUN',   activeClass: 'led--run-on'   },
        { key: 'estop',     label: 'E-STOP',activeClass: 'led--estop-on' },
        { key: 'alarm',     label: 'ALARM', activeClass: 'led--alarm-on' },
        { key: 'door_open', label: 'DOOR',  activeClass: 'led--door-on'  },
    ];

    const ANALOG_TAGS = ['speed', 'temperature', 'vibration', 'load'];

    /**
     * Build the HTML for a single machine card.
     */
    function buildCardHTML(machine) {
        const mid = machine.id;
        const statusBitsHTML = STATUS_BITS.map(bit => `
            <div class="status-bit">
                <span class="status-bit__led" id="led-${mid}-${bit.key}"></span>
                <span class="status-bit__label">${bit.label}</span>
            </div>
        `).join('');

        const gaugesHTML = ANALOG_TAGS.map(tag => {
            const meta = getTagMeta(tag);
            return `
            <div class="gauge-cell">
                <span class="gauge-label">${meta.label}</span>
                ${createGaugeSVG(`gauge-${mid}-${tag}`)}
            </div>`;
        }).join('');

        return `
        <article class="machine-card" id="card-${mid}">
            <div class="machine-card__header">
                <span class="machine-card__name">${machine.name}</span>
                <span class="machine-card__overall-led" id="overall-led-${mid}"></span>
            </div>
            <div style="padding: 0 16px 8px 16px;">
                <select class="machine-state-select" id="state-select-${mid}" data-mid="${mid}" style="width: 100%; background: #0c1424; color: #e2e8f0; border: 1px solid #1e293b; border-radius: 4px; padding: 6px; font-size: 11px; font-weight: bold; cursor: pointer; font-family: inherit;">
                    <option value="auto">Simulation (Auto)</option>
                    <option value="active">Force Active</option>
                    <option value="stopped">Force Stopped</option>
                    <option value="idle">Force Idle</option>
                </select>
            </div>
            <div class="status-bits">${statusBitsHTML}</div>
            <div class="gauges-grid">${gaugesHTML}</div>
            <div class="cycle-counter">
                <span class="cycle-counter__label">Cycle Count</span>
                <span class="cycle-counter__display" id="cycle-${mid}">0</span>
            </div>
        </article>`;
    }

    /**
     * Return tag metadata, falling back to sensible defaults.
     */
    function getTagMeta(tagName) {
        const found = tagConfig.find(t => t.name === tagName);
        if (found) return found;
        // defaults
        const defaults = {
            speed:       { name: 'speed',       label: 'Speed',       unit: 'RPM', min: 0, max: 100, warn_high: 85, alarm_high: 95 },
            temperature: { name: 'temperature', label: 'Temp',        unit: '°C',  min: 0, max: 100, warn_high: 80, alarm_high: 95 },
            vibration:   { name: 'vibration',   label: 'Vibration',   unit: 'mm/s',min: 0, max: 50,  warn_high: 35, alarm_high: 45 },
            load:        { name: 'load',        label: 'Load',        unit: '%',   min: 0, max: 100, warn_high: 85, alarm_high: 95 },
        };
        return defaults[tagName] || { name: tagName, label: tagName, unit: '', min: 0, max: 100 };
    }

    /**
     * Sync the DOM cards with the incoming machine array.
     */
    function syncCards(machines) {
        const existingIds = new Set();
        machines.forEach(m => existingIds.add(m.id));

        // remove cards for machines that no longer exist
        machineGrid.querySelectorAll('.machine-card').forEach(card => {
            const cardId = parseInt(card.id.replace('card-', ''), 10);
            if (!existingIds.has(cardId)) card.remove();
        });

        // add/update
        machines.forEach((machine, idx) => {
            let card = document.getElementById(`card-${machine.id}`);
            if (!card) {
                // insert in order
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = buildCardHTML(machine);
                const newCard = tempDiv.firstElementChild;
                newCard.style.animationDelay = `${idx * 0.06}s`;
                machineGrid.appendChild(newCard);

                // add event listener to the state selector
                const selectEl = document.getElementById(`state-select-${machine.id}`);
                if (selectEl) {
                    selectEl.addEventListener('change', (e) => {
                        const mid = parseInt(e.target.getAttribute('data-mid'), 10);
                        const state = e.target.value;
                        socket.emit('set_machine_state', { machine_id: mid, state: state });
                    });
                }
            }
            updateCard(machine);
        });
    }

    /**
     * Update an existing card with new data.
     */
    function updateCard(machine) {
        const mid = machine.id;
        const tags = machine.tags;
        const status = tags.status || {};

        // update dropdown selection if it's different from current
        const selectEl = document.getElementById(`state-select-${mid}`);
        if (selectEl && selectEl.value !== machine.override_state) {
            selectEl.value = machine.override_state || 'auto';
        }

        // Overall LED
        const overallLed = document.getElementById(`overall-led-${mid}`);
        if (overallLed) {
            overallLed.className = 'machine-card__overall-led';
            if (status.estop) {
                overallLed.classList.add('machine-card__overall-led--estop');
            } else if (status.alarm) {
                overallLed.classList.add('machine-card__overall-led--alarm');
            } else if (status.running) {
                overallLed.classList.add('machine-card__overall-led--running');
            } else {
                overallLed.classList.add('machine-card__overall-led--idle');
            }
        }

        // Breathing border
        const card = document.getElementById(`card-${mid}`);
        if (card) {
            card.classList.toggle('machine-card--running', !!status.running && !status.estop);
            card.classList.toggle('machine-card--disconnected', !isConnected);
        }

        // Status bit LEDs
        STATUS_BITS.forEach(bit => {
            const led = document.getElementById(`led-${mid}-${bit.key}`);
            if (led) {
                led.className = 'status-bit__led';
                if (status[bit.key]) {
                    led.classList.add(bit.activeClass);
                }
            }
        });

        // Analog gauges
        ANALOG_TAGS.forEach(tag => {
            const meta = getTagMeta(tag);
            const value = tags[tag] != null ? tags[tag] : 0;
            updateGauge(
                `gauge-${mid}-${tag}`,
                value,
                meta.min  ?? 0,
                meta.max  ?? 100,
                meta.unit ?? '',
                meta.warn_high,
                meta.alarm_high
            );
        });

        // Cycle counter
        const cycleEl = document.getElementById(`cycle-${mid}`);
        if (cycleEl) {
            const count = tags.cycle_count != null ? tags.cycle_count : (machine.cycle != null ? machine.cycle : 0);
            cycleEl.textContent = String(count).padStart(6, '0');
        }
    }

    /**
     * Gray-out all cards (on disconnect).
     */
    function setAllCardsDisconnected() {
        machineGrid.querySelectorAll('.machine-card').forEach(card => {
            card.classList.add('machine-card--disconnected');
            card.classList.remove('machine-card--running');
        });
    }

    // ─── Socket.IO ────────────────────────────────────────────
    const socket = io({ transports: ['websocket', 'polling'] });

    socket.on('connect', () => {
        isConnected = true;
        connectionDot.className  = 'status-dot status-dot--connected';
        connectionLabel.textContent = 'Connected';
        // remove disconnect styling
        machineGrid.querySelectorAll('.machine-card--disconnected').forEach(c =>
            c.classList.remove('machine-card--disconnected'));
        // request current config
        socket.emit('get_config');
    });

    socket.on('disconnect', () => {
        isConnected = false;
        connectionDot.className  = 'status-dot status-dot--disconnected';
        connectionLabel.textContent = 'Disconnected';
        setAllCardsDisconnected();
    });

    socket.on('config_data', (data) => {
        // store tag metadata
        if (data.tags && Array.isArray(data.tags)) {
            tagConfig = data.tags;
        }
        // populate settings
        cfgMachineCount.value   = data.machine_count  ?? 1;
        cfgUpdateInterval.value = data.update_interval ?? 1;
        cfgPlcEnabled.checked   = !!data.plc_enabled;
        cfgPlcIp.value          = data.plc_ip   ?? '192.168.1.5';
        cfgPlcPort.value        = data.plc_port  ?? 502;
        cfgPlcDeviceId.value    = data.plc_device_id ?? 1;
        plcFields.hidden        = !cfgPlcEnabled.checked;

        // update dropdown selection
        if (cfgPlcIp.value === '127.0.0.1' && cfgPlcPort.value == 5020) {
            cfgPlcProfile.value = 'localhost';
        } else if (cfgPlcIp.value === '192.168.1.5' && cfgPlcPort.value == 502) {
            cfgPlcProfile.value = 'router';
        } else {
            cfgPlcProfile.value = 'custom';
        }
    });

    socket.on('machine_data', (data) => {
        if (!data || !data.machines) return;
        currentMachines = data.machines;
        syncCards(data.machines);
    });

})();
