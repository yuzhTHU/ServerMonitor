/* Copyright (c) 2024-present, Yumeow. Licensed under the MIT License. */
const filesystemResults = new Map();
const filesystemTimeTimers = new Map();
let filesystemHosts = [];
const TWO_TIB = 2 * 1024 ** 4;

function escapeFilesystemText(value) {
    return String(value).replace(/[&<>'"]/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);
}

function formatFilesystemBytes(bytes) {
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
    let value = Number(bytes) || 0;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    const digits = value >= 100 || unit === 0 ? 0 : value >= 10 ? 1 : 2;
    return `${value.toFixed(digits)} ${units[unit]}`;
}

function allLoadedFilesystems() {
    return [...filesystemResults.values()].flatMap(data => data.filesystems);
}

function normalizedRisk(value, min, max) {
    if (max <= min) return 0;
    return 1 - Math.min(1, Math.max(0, (value - min) / (max - min)));
}

function filesystemRiskGradient(risk) {
    const stops = [
        [0.00, [32, 201, 151]],
        [0.70, [247, 183, 49]],
        [0.85, [253, 150, 68]],
        [1.00, [235, 59, 90]]
    ];
    let left = stops[0];
    let right = stops.at(-1);
    for (let i = 1; i < stops.length; i++) {
        if (risk <= stops[i][0]) {
            left = stops[i - 1];
            right = stops[i];
            break;
        }
    }
    const span = right[0] - left[0];
    const ratio = span > 0 ? (risk - left[0]) / span : 0;
    const color = left[1].map((value, i) => Math.round(value + (right[1][i] - value) * ratio));
    const highlight = color.map(value => Math.round(value + (255 - value) * 0.16));
    return `linear-gradient(90deg, rgb(${color.join(',')}), rgb(${highlight.join(',')}))`;
}

function filesystemBarColor(host, filesystem) {
    const mode = document.getElementById('filesystem-color').value;
    let risk;
    if (mode === 'usage') {
        risk = filesystem.usage_percent / 100;
    } else if (mode === 'free-absolute') {
        risk = 1 - Math.min(1, Math.max(0, filesystem.available_bytes / TWO_TIB));
    } else {
        const filesystems = mode === 'free-host'
            ? filesystemResults.get(host).filesystems
            : allLoadedFilesystems();
        const freeValues = filesystems.map(item => item.available_bytes);
        risk = normalizedRisk(filesystem.available_bytes, Math.min(...freeValues), Math.max(...freeValues));
    }
    risk = Math.min(1, Math.max(0, risk));
    return filesystemRiskGradient(risk);
}

function filesystemTrackWidth(host, filesystem) {
    const mode = document.getElementById('filesystem-width').value;
    if (mode === 'uniform') return 100;
    const filesystems = mode === 'size-host'
        ? filesystemResults.get(host).filesystems
        : allLoadedFilesystems();
    const maxSize = Math.max(...filesystems.map(item => item.total_bytes));
    return maxSize > 0 ? filesystem.total_bytes / maxSize * 100 : 100;
}

function createFilesystemCards(hosts) {
    const container = document.getElementById('filesystem-cards');
    container.innerHTML = hosts.map(host => `
        <div class="col-xl-4 col-md-6 col-12">
            <article class="card filesystem-card shadow-sm" id="filesystem-card-${escapeFilesystemText(host)}">
                <div class="card-header">
                    <h5 class="card-title">${escapeFilesystemText(host)}</h5>
                    <small class="text-muted filesystem-time">
                        <span id="filesystem-time-${escapeFilesystemText(host)}"></span>
                        <span class="filesystem-time-ago" id="filesystem-time-ago-${escapeFilesystemText(host)}"></span>
                    </small>
                </div>
                <div class="card-body">
                    <div class="card-load-state" id="filesystem-state-${escapeFilesystemText(host)}" role="status">
                        <span class="card-load-spinner" aria-hidden="true"></span>
                        <span class="card-load-title">正在读取磁盘空间</span>
                    </div>
                    <div class="filesystem-list d-none" id="filesystem-content-${escapeFilesystemText(host)}"></div>
                </div>
            </article>
        </div>
    `).join('');
    resumeFilesystemCardOrder();
}

function setFilesystemState(host, state, detail = '') {
    const status = document.getElementById(`filesystem-state-${host}`);
    const content = document.getElementById(`filesystem-content-${host}`);
    const timestamp = document.getElementById(`filesystem-time-${host}`);
    const timeAgo = document.getElementById(`filesystem-time-ago-${host}`);
    if (!status || !content) return;
    if (state === 'success') {
        status.classList.add('d-none');
        content.classList.remove('d-none');
        return;
    }
    content.classList.add('d-none');
    if (filesystemTimeTimers.has(host)) {
        clearTimeout(filesystemTimeTimers.get(host));
        filesystemTimeTimers.delete(host);
    }
    timestamp.textContent = '';
    timeAgo.textContent = '';
    delete timestamp.dataset.value;
    status.className = `card-load-state${state === 'error' ? ' is-error' : ''}`;
    status.innerHTML = state === 'error'
        ? `<span class="card-load-error-icon">!</span><span class="card-load-title">磁盘空间读取失败</span><span class="card-load-detail">${escapeFilesystemText(detail)}</span>`
        : '<span class="card-load-spinner" aria-hidden="true"></span><span class="card-load-title">正在读取磁盘空间</span>';
}

function sortedFilesystems(filesystems) {
    const sortBy = document.getElementById('filesystem-sort').value;
    const result = [...filesystems];
    if (sortBy === 'free-desc') result.sort((a, b) => b.available_bytes - a.available_bytes);
    if (sortBy === 'free-asc') result.sort((a, b) => a.available_bytes - b.available_bytes);
    if (sortBy === 'usage-desc') result.sort((a, b) => b.usage_percent - a.usage_percent);
    if (sortBy === 'mount') result.sort((a, b) => a.mountpoint.localeCompare(b.mountpoint));
    return result;
}

function renderFilesystemCard(host) {
    const data = filesystemResults.get(host);
    if (!data) return;
    const container = document.getElementById(`filesystem-content-${host}`);
    const timestamp = document.getElementById(`filesystem-time-${host}`);
    container.innerHTML = sortedFilesystems(data.filesystems).map(filesystem => {
        const usage = Math.min(100, Math.max(0, filesystem.usage_percent));
        const trackWidth = filesystemTrackWidth(host, filesystem);
        const barColor = filesystemBarColor(host, filesystem);
        const mountpoint = escapeFilesystemText(filesystem.mountpoint);
        const device = escapeFilesystemText(filesystem.device);
        const fsType = escapeFilesystemText(filesystem.filesystem_type);
        return `
            <div class="filesystem-item" title="${device} · ${fsType}">
                <div class="filesystem-heading">
                    <span class="filesystem-mount">${mountpoint}</span>
                    <span class="filesystem-percent">${usage.toFixed(1)}% 已用</span>
                </div>
                <div class="filesystem-progress" style="width:${trackWidth}%" role="progressbar" aria-label="${mountpoint} 使用率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${usage.toFixed(1)}">
                    <div class="filesystem-progress-bar" style="width:${usage}%; background:${barColor}"></div>
                </div>
                <div class="filesystem-meta">
                    <span class="filesystem-device">${device} · ${fsType}</span>
                    <span class="filesystem-free">剩余 ${formatFilesystemBytes(filesystem.available_bytes)} / ${formatFilesystemBytes(filesystem.total_bytes)}</span>
                </div>
            </div>
        `;
    }).join('');
    updateFilesystemTime(host, data.timestamp);
    setFilesystemState(host, 'success');
}

function updateFilesystemTime(host, timestamp) {
    const time = document.getElementById(`filesystem-time-${host}`);
    const timeAgo = document.getElementById(`filesystem-time-ago-${host}`);
    if (time.dataset.value === String(timestamp) && time.textContent) return;
    if (filesystemTimeTimers.has(host)) clearTimeout(filesystemTimeTimers.get(host));
    time.dataset.value = String(timestamp);
    time.textContent = formatTimestamp(timestamp);

    const tick = () => {
        timeAgo.textContent = `(${getTimeAgo(timestamp)})`;
        const ageSeconds = Math.max(0, Date.now() / 1000 - timestamp);
        const delay = ageSeconds < 60 ? 1000 : ageSeconds < 3600 ? 60000 : 3600000;
        filesystemTimeTimers.set(host, setTimeout(tick, delay));
    };
    tick();
}

function renderAllFilesystemCards() {
    filesystemResults.forEach((_, host) => renderFilesystemCard(host));
}

async function fetchFilesystemHost(host, refresh) {
    setFilesystemState(host, 'loading');
    filesystemResults.delete(host);
    const query = new URLSearchParams({
        host,
        refresh: String(refresh)
    });
    try {
        const response = await fetch(`/api/filesystems?${query}`);
        if (!response.ok) {
            let detail = `服务器返回 HTTP ${response.status}`;
            try {
                const body = await response.json();
                if (body.detail) detail = body.detail;
            } catch (_) {}
            throw new Error(detail);
        }
        const data = await response.json();
        filesystemResults.set(host, data);
        renderAllFilesystemCards();
    } catch (error) {
        console.error(`读取 ${host} 磁盘空间时出错：`, error);
        filesystemResults.delete(host);
        setFilesystemState(host, 'error', error.message || '请稍后重试');
    }
}

async function loadFilesystems(refresh = false) {
    const button = document.getElementById('fetch-filesystems');
    button.disabled = true;
    try {
        if (!filesystemHosts.length) {
            const response = await fetch('/api/hosts');
            if (!response.ok) throw new Error(`服务器列表返回 HTTP ${response.status}`);
            filesystemHosts = await response.json();
            createFilesystemCards(filesystemHosts);
        }
        await Promise.all(filesystemHosts.map(host => fetchFilesystemHost(host, refresh)));
    } finally {
        button.disabled = false;
    }
}

document.getElementById('fetch-filesystems').addEventListener('click', () => loadFilesystems(true));
document.getElementById('filesystem-sort').addEventListener('change', () => {
    renderAllFilesystemCards();
});
document.getElementById('filesystem-color').addEventListener('change', renderAllFilesystemCards);
document.getElementById('filesystem-width').addEventListener('change', renderAllFilesystemCards);
loadFilesystems().catch(error => console.error('初始化磁盘空间时出错：', error));
