async function initUserData() {
    const hosts = await fetch('/api/hosts').then(response => response.json());
    const summary = document.getElementById('user-summary');
    summary.innerHTML = '';
    hosts.forEach(host => {
        const container = `
            <div class="user-data-table-container" id="user-card-${host}">
                <div class="card-header card-header-layout">
                    <h5>${host}</h5>
                    <small class="card-header-timestamp">
                        <span id="summary-time-${host}"></span>
                        <span id="summary-time-ago-${host}"></span>
                    </small>
                </div>
                <div class="card-body">
                    <div class="card-load-state" id="user-state-${host}" role="status">
                        <span class="card-load-spinner" aria-hidden="true"></span>
                        <span class="card-load-title">正在加载用户数据</span>
                    </div>
                    <div id="user-content-${host}" class="d-none">
                        <div class="table-responsive" style="position: relative;">
                            <table class="table table-bordered user-data-table" id="user-data-table-${host}">
                                <thead id="table-head-${host}"></thead>
                                <tbody id="table-body-${host}"></tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        `;
        summary.innerHTML += container;
    });

    resumeUserCardOrder();
    await fetchUserData(hosts);
};

const summary_timers = {}; // Object to store timer IDs for each card
function setUserCardState(host, state, detail = '') {
    const status = document.getElementById(`user-state-${host}`);
    const content = document.getElementById(`user-content-${host}`);
    if (!status || !content) return;
    if (state === 'success') {
        status.classList.add('d-none');
        content.classList.remove('d-none');
        return;
    }
    if (summary_timers[host]) clearTimeout(summary_timers[host]);
    document.getElementById(`summary-time-${host}`).textContent = '';
    document.getElementById(`summary-time-ago-${host}`).textContent = '';
    content.classList.add('d-none');
    status.className = `card-load-state${state === 'error' ? ' is-error' : ''}`;
    status.innerHTML = state === 'error'
        ? `<span class="card-load-error-icon">!</span><span class="card-load-title">用户数据加载失败</span><span class="card-load-detail">${detail}</span>`
        : '<span class="card-load-spinner" aria-hidden="true"></span><span class="card-load-title">正在加载用户数据</span>';
}

async function fetchUserData(existingHosts = null) {
    const hosts = existingHosts || await fetch('/api/hosts').then(response => response.json());
    const sortBy = document.getElementById('sort-select').value;  // 获取下拉框的值

    await Promise.all(hosts.map(async host => {
      setUserCardState(host, 'loading');
      try {
        const response = await fetch(`/api/summary?host=${host}`);
        if (!response.ok) throw new Error(`服务器返回 HTTP ${response.status}`);
        let data = await response.json();
        if (!data.length) throw new Error('没有可显示的用户数据');
        data.forEach(normalizeRecord);

        const timestamp = data[0].timestamp;
        const time = document.getElementById(`summary-time-${host}`);
        time.textContent = `Last Update: ${formatTimestamp(timestamp)}`;
        if (summary_timers[host]) { clearTimeout(summary_timers[host]); }
        let count = 0; // 计数器
        const updateTimeAgo = () => {
            const lastUpdateElement = document.getElementById(`summary-time-ago-${host}`);
            lastUpdateElement.textContent = `(${getTimeAgo(timestamp)})`;
            count++;
            let delay = count < 60 ? 1000 : count < 120 ? 60000 : 3600000;
            summary_timers[host] = setTimeout(updateTimeAgo, delay);
        };
        updateTimeAgo();

        // 排除 data 中 cpu = 0, memory = 0, cuda = [0, 0, 0, 0] 的记录
        data = data.filter(record => record.cpu > 0 || record.memory > 0 || record.cuda.some(i => i > 0));
        
        if (sortBy === 'cuda') {
            data.sort((a, b) => b.cuda.reduce((s, i) => s + i, 0) - a.cuda.reduce((s, i) => s + i, 0));
        } else if (sortBy === 'memory') {
            data.sort((a, b) => b.memory - a.memory);
        } else if (sortBy === 'cpu') {
            data.sort((a, b) => b.cpu - a.cpu);
        }

        const tableHead = document.getElementById(`table-head-${host}`);
        const tableBody = document.getElementById(`table-body-${host}`);
        
        // 构建表头
        tableHead.innerHTML = '';
        let headerRow = '<tr><th>资源</th>';
        data.forEach(record => {
            headerRow += `<th>${record.user}</th>`;
        });
        headerRow += '</tr>';
        tableHead.innerHTML = headerRow;

        // 构建表体
        tableBody.innerHTML = '';
        const resources = ['cpu', 'memory', 'cuda'];
        resources.forEach(resource => {
            let name = 'N/A';
            if (resource === 'cpu') name = 'CPU';
            if (resource === 'memory') name = '内存';
            if (resource === 'cuda') name = 'GPU';
            let row = `<tr><td>${name}</td>`;
            data.forEach(record => {
                let value = 0;
                let item = '-';
                if (resource === 'cuda') {
                    value = record['cuda'].reduce((a, b) => a + b, 0) / 1024;
                    if (value > 0) 
                        item = `${value.toFixed(1)} GiB`;
                } else if (resource === 'cpu') {
                    value = record['cpu'];
                    if (value > 100)
                        item = `${(value/100).toFixed(1)} Cores`;
                    else if (value > 0)
                        item = `${value.toFixed(1)}%`;
                } else if (resource === 'memory') {
                    value = record['memory'];
                    if (value > 0)
                        item = `${value.toFixed(1)}%`;
                }
                row += `<td>${item}</td>`;
            });
            row += '</tr>';
            tableBody.innerHTML += row;
        });
        setUserCardState(host, 'success');
      } catch (error) {
        console.error(`加载 ${host} 用户数据时出错：`, error);
        setUserCardState(host, 'error', error.message || '请稍后重试');
      }
    }));
}
document.getElementById('fetch-user-data').addEventListener('click', () => fetchUserData());
initUserData().catch(error => console.error('初始化用户数据时出错：', error));
