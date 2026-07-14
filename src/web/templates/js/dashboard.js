/* Copyright (c) 2024-present, Yumeow. Licensed under the MIT License. */
const timers = {};
let dashboardHosts = [];

function dashboardCardId(host) {
    return host.replace(/[^a-z0-9]/gi, '_').toLowerCase();
}

function createDashboardCards(hosts) {
    const container = document.getElementById('dashboardCards');
    container.innerHTML = hosts.map(host => {
        const cardId = dashboardCardId(host);
        return `
            <div class="col-md-4 col-12 dashboard-card-column">
                <div class="card dashboard-card" id="card-${cardId}">
                    <div class="card-header card-header-layout">
                        <h5><a href="/server?host=${encodeURIComponent(host)}" class="text-decoration-none">${host}</a></h5>
                        <small class="card-header-timestamp" id="dashboard-time-wrap-${cardId}">
                            <span id="dashboard-time-${cardId}"></span>
                            <span id="dashboard-time-ago-${cardId}"></span>
                        </small>
                    </div>
                    <div class="card-body">
                        <div class="card-load-state" id="dashboard-state-${cardId}" role="status">
                            <span class="card-load-spinner" aria-hidden="true"></span>
                            <span class="card-load-title">正在加载服务器状态</span>
                        </div>
                        <div class="d-none" id="dashboard-content-${cardId}"></div>
                    </div>
                </div>
            </div>`;
    }).join('');
    resumeDashboardCardOrder();
}

function setDashboardState(host, state, detail = '') {
    const cardId = dashboardCardId(host);
    const status = document.getElementById(`dashboard-state-${cardId}`);
    const content = document.getElementById(`dashboard-content-${cardId}`);
    if (!status || !content) return;
    if (state === 'success') {
        status.classList.add('d-none');
        content.classList.remove('d-none');
        return;
    }
    content.classList.add('d-none');
    status.className = `card-load-state${state === 'error' ? ' is-error' : ''}`;
    status.innerHTML = state === 'error'
        ? `<span class="card-load-error-icon">!</span><span class="card-load-title">状态加载失败</span><span class="card-load-detail">${detail}</span>`
        : '<span class="card-load-spinner" aria-hidden="true"></span><span class="card-load-title">正在加载服务器状态</span>';
}

function renderDashboardRecord(record) {
    normalizeRecord(record);
    const cardId = dashboardCardId(record.host);
    const content = document.getElementById(`dashboard-content-${cardId}`);
    if (!content) return;
    const meanCuda = record.cuda.length ? record.cuda.reduce((sum, value) => sum + value, 0) / record.cuda.length : 0;
    const sumCudaFree = record.cuda_free.reduce((sum, value) => sum + value, 0);
    content.innerHTML = `
        <div class="cpu">
            <small>CPU: ${record.cpu.toFixed(0)}%</small>
            <small style="color:#b2bec3">(${record.cpu_free.toFixed(0)} Cores free)</small>
            <div class="hbar" style="background-color:${colorInterpolate(record.cpu / 100)};width:${record.cpu}%"></div>
        </div>
        <div class="mem">
            <small>MEM: ${record.memory.toFixed(0)}%</small>
            <small style="color:#b2bec3">(${(record.memory_free / 1024).toFixed(0)} GiB free)</small>
            <div class="hbar" style="background-color:${colorInterpolate(record.memory / 100)};width:${record.memory}%"></div>
        </div>
        <div class="cuda">
            <small>GPU: ${meanCuda.toFixed(0)}%</small>
            <small style="color:#b2bec3">(${(sumCudaFree / 1024).toFixed(0)} GiB free)</small>
            <div class="cuda-container">${record.cuda.map((usage, index) => {
                const color = colorInterpolate(usage / 100);
                const free = record.cuda_free[index] / 1024;
                return `<div class="cuda-box" title="cuda:${index} 剩余显存 ${free.toFixed(2)} GiB" style="background-color:${color}"><span class="cuda-text" style="color:${autoContrast(color)}">${free.toFixed(0)}</span></div>`;
            }).join('')}</div>
        </div>`;
    document.getElementById(`dashboard-time-${cardId}`).textContent = `Last Update: ${formatTimestamp(record.timestamp)}`;
    setDashboardState(record.host, 'success');

    if (timers[cardId]) clearTimeout(timers[cardId]);
    const updateTimeAgo = () => {
        const card = document.getElementById(`card-${cardId}`);
        const timeWrap = document.getElementById(`dashboard-time-wrap-${cardId}`);
        document.getElementById(`dashboard-time-ago-${cardId}`).textContent = `(${getTimeAgo(record.timestamp)})`;
        const age = Math.max(0, Date.now() / 1000 - record.timestamp);
        const stale = age >= 300;
        card.style.borderColor = stale ? '#dc3545' : 'rgba(0,0,0,.1)';
        timeWrap.style.color = stale ? '#dc3545' : '#8795a5';
        timers[cardId] = setTimeout(updateTimeAgo, age < 60 ? 1000 : age < 3600 ? 60000 : 3600000);
    };
    updateTimeAgo();
}

async function fetchDashboardData() {
    const response = await fetch('/api/dashboard');
    if (!response.ok) throw new Error(`服务器返回 HTTP ${response.status}`);
    const records = await response.json();
    const returnedHosts = new Set(records.map(record => record.host));
    records.forEach(renderDashboardRecord);
    dashboardHosts.filter(host => !returnedHosts.has(host)).forEach(host => {
        setDashboardState(host, 'error', '没有收到该服务器的监控数据');
    });
}

async function initDashboard() {
    const pageState = document.getElementById('dashboard-host-state');
    try {
        const response = await fetch('/api/hosts');
        if (!response.ok) throw new Error(`服务器列表返回 HTTP ${response.status}`);
        dashboardHosts = await response.json();
        createDashboardCards(dashboardHosts);
        pageState.classList.add('d-none');
    } catch (error) {
        pageState.className = 'card-load-state is-error';
        pageState.innerHTML = `<span class="card-load-error-icon">!</span><span class="card-load-title">仪表盘加载失败</span><span class="card-load-detail">${error.message}</span>`;
        return;
    }
    try {
        await fetchDashboardData();
    } catch (error) {
        dashboardHosts.forEach(host => setDashboardState(host, 'error', error.message));
    }
}

initDashboard();
setInterval(() => fetchDashboardData().catch(error => console.error('刷新仪表盘失败：', error)), 60000);


// 切换编辑模式
const editBtn = document.getElementById("editLayoutBtn");
let _tipBar;
let _editMode = false;
let _oldContext = "<oldContent>";
editBtn.addEventListener("click", () => {
    _editMode = !_editMode;

    if (_editMode) {
        _oldContext = editBtn.textContent;
        editBtn.textContent = "完成编辑";

        dashboardCards.classList.add("editable");
        enableDragDrop();

        // 创建提示条
        _tipBar = document.createElement('div');
        _tipBar.className = 'edit-tip-bar';
        _tipBar.textContent = "拖动卡片以排序";
        _tipBar.style.cssText = `
            padding: 8px;
            background: #fffae6;
            color: #333;
            font-weight: bold;
            text-align: center;
            border-bottom: 1px solid #ffd700;
        `;
        dashboardCards.prepend(_tipBar);

    } else {
        editBtn.textContent = _oldContext;
        dashboardCards.classList.remove("editable");
        disableDragDrop();
        saveCardOrder();

        // 移除提示条
        if (_tipBar) {
            _tipBar.remove();
            _tipBar = null;
        }
    }
});
