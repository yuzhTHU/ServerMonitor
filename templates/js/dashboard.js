const timers = {}; // Object to store timer IDs for each card
async function fetchDashboardData(init=false) {
    const records = await fetch('/api/dashboard').then(response => response.json());
    const dashboardCards = document.getElementById('dashboardCards');
    if (init) { dashboardCards.innerHTML = ''; }

    records.forEach(record => {
        const cardId = record.host.replace(/[^a-z0-9]/gi, '_').toLowerCase();
        const formattedTimestamp = formatTimestamp(record.timestamp);
        const timeAgo = getTimeAgo(record.timestamp);

        const mean_cuda = record.cuda ? record.cuda.reduce((s, i) => s + i, 0) / record.cuda.length : 0;
        const sum_cuda = record.cuda_free ? record.cuda_free.reduce((s, i) => s + i, 0) : 0;

        if (init) {
            const card = document.createElement('div');
            card.className = 'col-md-4';
            card.innerHTML = `
                <div class="card" id="card-${cardId}">
                    <div class="card-header">
                        <h5 class="card-title">${record.host}</h5>
                    </div>
                    <div class="card-body">
                        <div class="cpu">
                            <small><span>CPU: ${record.cpu.toFixed(0)}%</span></small>
                            <small><span style="color: #b2bec3">(${(record.cpu_free ? record.cpu_free : 0).toFixed(0)} Cores free)</span></small>
                            <div id="card-CPU-hbar-${cardId}" class="hbar" style="background-color: ${colorInterpolate(record.cpu/100)}; width: ${record.cpu}%;"></div>
                        </div>
                        <div class="mem">
                            <small><span>MEM: ${record.memory.toFixed(0)}%</span></small>
                            <small><span style="color: #b2bec3">(${(record.memory_free ? record.memory_free/1024 : 0).toFixed(0)} GiB free)</span></small>
                            <div id="card-MEM-hbar-${cardId}" class="hbar" style="background-color: ${colorInterpolate(record.memory/100)}; width: ${record.memory}%;"></div>
                        </div>
                        <div class="cuda">
                            <small><span>GPU: ${mean_cuda.toFixed(0)}%</span></small>
                            <small><span style="color: #b2bec3">(${(sum_cuda/1024).toFixed(0)} GiB free)</span></small>
                            <div class="cuda-container">
                                ${record.cuda ? record.cuda.map((usage, index) => {
                                    const color = colorInterpolate(usage/100);
                                    return `
                                        <div class="cuda-box" style="background-color: ${color};">
                                            <span class="cuda-text" style="color: ${autoContrast(color)}">${(record.cuda_free[index]/1024).toFixed(0)}</span>
                                        </div>
                                    `}
                                ).join('') : ''}
                            </div>
                        </div>
                        <div class="timestamp">
                            <span>Last Update: ${formattedTimestamp}</span> (<span>${timeAgo}</span>)
                        </div>
                    </div>
                </div>
            `;
            dashboardCards.appendChild(card);
        } else {
            const card = document.getElementById(`card-${cardId}`);

            const cpu = card.getElementsByClassName('cpu')[0];
            cpu.children[0].textContent.text = `CPU: ${record.cpu.toFixed(0)}%`;
            cpu.children[1].textContent.text = `(${(record.cpu_free ? record.cpu_free : 0).toFixed(0)} Cores free)`;
            cpu.children[2].style.width = `${record.cpu}%`;
            cpu.children[2].style.backgroundColor = colorInterpolate(record.cpu/100);
            
            const mem = card.getElementsByClassName('mem')[0];
            mem.children[0].textContent.text = `MEM: ${record.memory.toFixed(0)}%`;
            mem.children[1].textContent.text = `(${(record.memory_free ? record.memory_free/1024 : 0).toFixed(0)} GiB free)`;
            mem.children[2].style.width = `${record.memory}%`;
            mem.children[2].style.backgroundColor = colorInterpolate(record.memory/100);

            const cuda = card.getElementsByClassName('cuda')[0];
            cuda.children[0].textContent.text = `GPU: ${mean_cuda.toFixed(0)}%`;
            cuda.children[1].textContent.text = `(${(sum_cuda/1024).toFixed(0)} GiB free)`;
            record.cuda.forEach((usage, index) => {
                const box = cuda.children[2].children[index];
                const text = box.getElementsByTagName('span')[0];
                const color = colorInterpolate(usage/100);
                box.style.backgroundColor = color;
                text.textContent.text = (record.cuda_free[index]/1024).toFixed(0);
                text.style.color = autoContrast(color);
            });
            
            const timestamp = card.getElementsByClassName('timestamp')[0];
            timestamp.children[0].textContent.text = `Last Update: ${formattedTimestamp}`;
            timestamp.children[1].textContent.text = timeAgo;
        }
 
        if (timers[cardId]) { clearTimeout(timers[cardId]); }

        let count = 0; // 计数器
        const updateTimeAgo = () => {
            const card = document.getElementById(`card-${cardId}`);
            card.getElementsByClassName('timestamp')[0].children[1].innerHTML = getTimeAgo(record.timestamp);

            // 根据计数器决定下一个间隔
            count++;
            let delay = count < 60 ? 1000 : count < 120 ? 60000 : 3600000;
            timers[cardId] = setTimeout(updateTimeAgo, delay);
            
            // 超过5分钟未更新则标记为红色
            const dt = Math.floor((Date.now() - record.timestamp * 1000) / 1000);
            if (dt >= 5 * 60) {
                card.style.borderColor = 'rgba(255, 0, 0, 1.0)';
                card.getElementsByClassName('timestamp')[0].style.color = 'rgba(255, 0, 0, 1.0)';
            } else {
                card.style.borderColor = 'rgba(0, 0, 0, 0.1)';
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
    if (value >= 0.85) return '#d63031';
    else value = value / 0.85;
    const mixed = Color.mix('#00b894', '#b2bec3', value, {space: "lch", outspace: "srgb"});
    const r = Math.min(255, Math.max(0, Math.round(mixed.srgb.r * 255)));
    const g = Math.min(255, Math.max(0, Math.round(mixed.srgb.g * 255)));
    const b = Math.min(255, Math.max(0, Math.round(mixed.srgb.b * 255)));
    const a = `rgb(${r}, ${g}, ${b})`;
    return a;
}
// 自动反白
function autoContrast(bg_color) {
    const [r, g, b] = bg_color.match(/\d+/g).map(Number);
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;;
    return luminance > 128 ? '#000' : '#fff';
}

// 初始化时加载仪表盘数据
fetchDashboardData(true);
setInterval(fetchDashboardData, 60000);
