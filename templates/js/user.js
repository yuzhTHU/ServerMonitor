async function initUserData() {
    const hosts = await fetch('/api/hosts').then(response => response.json());
    console.log(hosts);
    const summary = document.getElementById('user-summary');
    summary.innerHTML = '';
    hosts.forEach(async host => {
        const container = `
            <div class="user-data-table-container">
                <div class="card-header">
                    <h5 class="card-title">${host}</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive" style="position: relative;">
                        <table class="table table-bordered user-data-table" id="user-data-table-${host}">
                            <thead id="table-head-${host}"></thead>
                            <tbody id="table-body-${host}"></tbody>
                        </table>
                    </div>
                    <div class="timestamp">
                        <span id="summary-time-${host}">Last Update: ???</span> (<span id="summary-time-ago-${host}">- ago</span>)
                    </div>
                </div>
            </div>
        `;
        summary.innerHTML += container;
    });
};
initUserData();

const summary_timers = {}; // Object to store timer IDs for each card
async function fetchUserData() {
    const hosts = await fetch('/api/hosts').then(response => response.json());
    const sortBy = document.getElementById('sort-select').value;  // 获取下拉框的值

    hosts.forEach(async host => {
        const response = await fetch(`/api/summary?host=${host}`);
        let data = await response.json();
        
        const timestamp = data[0].timestamp;
        const time = document.getElementById(`summary-time-${host}`);
        time.innerHTML = `Last Update: ${formatTimestamp(timestamp)}`;
        if (summary_timers[host]) { clearTimeout(summary_timers[host]); }
        let count = 0; // 计数器
        const updateTimeAgo = () => {
            const lastUpdateElement = document.getElementById(`summary-time-ago-${host}`);
            lastUpdateElement.innerHTML = getTimeAgo(timestamp);
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
        let headerRow = '<tr><th>User</th>';
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
            if (resource === 'memory') name = 'MEM';
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
    });
}
document.getElementById('fetch-user-data').addEventListener('click', fetchUserData);
fetchUserData()
