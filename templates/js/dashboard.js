const timers = {}; // Object to store timer IDs for each card
async function fetchDashboardData() {
    const response = await fetch('/api/dashboard');
    const data = await response.json();
    const dashboardCards = document.getElementById('dashboardCards');
    dashboardCards.innerHTML = '';

    data.forEach(record => {
        const cardId = record.host.replace(/[^a-z0-9]/gi, '_').toLowerCase();
        const card = document.createElement('div');
        card.className = 'col-md-4';
        const formattedTimestamp = formatTimestamp(record.timestamp);
        const timeAgo = getTimeAgo(record.timestamp);

        const mean_cuda = record.cuda ? record.cuda.reduce((s, i) => s + i, 0) / record.cuda.length : 0;
        const sum_cuda = record.cuda_free ? record.cuda_free.reduce((s, i) => s + i, 0) : 0;
        const max_cuda = record.cuda_free ? Math.max(...record.cuda_free) : 0;
        const max_idx = record.cuda_free ? record.cuda_free.indexOf(max_cuda) : 0;

        card.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h5 class="card-title">${record.host}</h5>
                </div>
                <div class="card-body">
                    <div>
                        <small>CPU: ${record.cpu.toFixed(0)}%</small>
                        <span style="color: #b2bec3"><small>(${(record.cpu_free ? record.cpu_free : 0).toFixed(0)}Cores free)</small></span>
                        <div class="hbar" style="background-color: ${colorInterpolate(record.cpu/100)}; width: ${record.cpu}%;"></div>
                    </div>
                    <div>
                        <small>MEM: ${record.memory.toFixed(0)}%</small>
                        <span style="color: #b2bec3"><small>(${(record.memory_free ? record.memory_free/1024 : 0).toFixed(0)}GiB free)</small></span>
                        <div class="hbar" style="background-color: ${colorInterpolate(record.memory/100)}; width: ${record.memory}%;"></div>
                    </div>
                    <div>
                        <!--<small>GPU: ${mean_cuda.toFixed(0)}% (${(max_cuda/1024).toFixed(0)}GiB free in cuda:${max_idx}, ${(sum_cuda/1024).toFixed(0)}GiB free in total)</small>-->
                        <small>GPU: ${mean_cuda.toFixed(0)}%</small>
                        <span style="color: #b2bec3"><small>(${(sum_cuda/1024).toFixed(0)}GiB free)</small></span>
                        <div class="cuda-container">
                            ${record.cuda ? record.cuda.map((cuda, index) => {
                                const suffix = record.cuda.length <= 4 ? '' : '';
                                const color = colorInterpolate(cuda/100);
                                const text = (record.cuda_free[index]/1024).toFixed(0);
                                return `<div class="cuda-box" style="background-color: ${color};">
                                    <span class="cuda-text" style="color: ${autoContrast(color)}">${text}${suffix}</span>
                                </div>`}
                            ).join('') : ''}
                        </div>
                    </div>
                    <div class="timestamp">
                        Last Update: ${formattedTimestamp} (<span id="time-ago-${cardId}">${timeAgo}</span>)
                    </div>
                </div>
            </div>
        `;
        dashboardCards.appendChild(card);
 
        if (timers[cardId]) { clearTimeout(timers[cardId]); }

        let count = 0; // 计数器
        const updateTimeAgo = () => {
            const lastUpdateElement = document.getElementById(`time-ago-${cardId}`);
            lastUpdateElement.innerHTML = getTimeAgo(record.timestamp);

            // 根据计数器决定下一个间隔
            count++;
            let delay = count < 60 ? 1000 : count < 120 ? 60000 : 3600000;
            timers[cardId] = setTimeout(updateTimeAgo, delay);
            
            // 超过5分钟未更新则标记为红色
            const dt = Math.floor((Date.now() - record.timestamp * 1000) / 1000);
            if (dt >= 5 * 60) {
                card.getElementsByClassName('card')[0].style.borderColor = 'rgba(255, 0, 0, 1.0)';
                card.getElementsByClassName('timestamp')[0].style.color = 'rgba(255, 0, 0, 1.0)';
            } else {
                card.getElementsByClassName('card')[0].style.borderColor = 'rgba(0, 0, 0, 0.1)';
                card.getElementsByClassName('timestamp')[0].style.color = 'rgba(178, 190, 195, 1.0)';
            }
        };
        updateTimeAgo();
    });
}

function formatTimestamp(timestamp) {
    const date = new Date(timestamp * 1000); // 转换为毫秒
    return date.toLocaleString('zh-CN', { hour12: false });
}

function getTimeAgo(timestamp) {
    const now = Date.now();
    const seconds = Math.floor((now - timestamp * 1000) / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (seconds < 60) return `${seconds}s ago`;
    if (minutes < 60) return `${minutes}min ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days} days ago`;
}

function colorInterpolate(value) {
    // return chroma.scale(['green', 'red']).mode('lab').colors(1, ratio)[0];
    const color1 = '#00b894';
    const color2 = '#d63031';
    const ratio = Math.max(0, Math.min(1, value));
    const r = Math.round((1 - ratio) * parseInt(color1.slice(1, 3), 16) + ratio * parseInt(color2.slice(1, 3), 16));
    const g = Math.round((1 - ratio) * parseInt(color1.slice(3, 5), 16) + ratio * parseInt(color2.slice(3, 5), 16));
    const b = Math.round((1 - ratio) * parseInt(color1.slice(5, 7), 16) + ratio * parseInt(color2.slice(5, 7), 16));
    return `rgb(${r}, ${g}, ${b})`;
}
// 自动反白
function autoContrast(bg_color) {
    const [r, g, b] = bg_color.match(/\d+/g).map(Number);
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;;
    return luminance > 128 ? '#000' : '#fff';
}

// 初始化时加载仪表盘数据
fetchDashboardData();
setInterval(fetchDashboardData, 60000);
