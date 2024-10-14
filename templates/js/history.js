let chartInstances = {};
// 设置默认日期为7天前和当前日期
document.getElementById('start-date').value = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
document.getElementById('end-date').value = new Date().toISOString().split('T')[0];


async function InitOption() {
    const hosts = await fetch('/api/hosts').then(response => response.json());
    const select = document.getElementById('host-select');
    hosts.forEach(host => {
        const option = document.createElement('option');
        option.value = host;
        option.innerHTML = host;
        select.appendChild(option);
    });
}
InitOption();

async function fetchHistoryData() {
    const host = document.getElementById('host-select').value;
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;

    document.getElementById('chart-title-cpu').innerHTML = `CPU (${host})`;
    document.getElementById('chart-title-mem').innerHTML = `Memory (${host})`;
    document.getElementById('chart-title-cuda').innerHTML = `CUDA (${host})`;
    
    // 将日期转换为时间戳
    const start = new Date(startDate).getTime() / 1000;
    const end = new Date(endDate).getTime() / 1000 + 24 * 60 * 60; // 结束日期加一天
    const response = await fetch(`/api/history?host=${host}&start=${start}&end=${end}`);
    const data = await response.json();

    // 对数据进行排序
    data.sort((a, b) => a.timestamp - b.timestamp);

    // 提取时间、cpu、memory、cuda 数据
    const labels = data.map(record => new Date(record.timestamp * 1000));
    const cpuData = data.map(record => record.cpu);
    const memData = data.map(record => record.memory);
    const cudaData = data.map(record => {
        // 取平均值作为展示
        return record.cuda.reduce((a, b) => a + b, 0) / record.cuda.length;
    });

    // 绘制图表
    renderChart('cpu-chart', labels, cpuData, 'CPU 使用率');
    renderChart('mem-chart', labels, memData, '内存使用率');
    renderChart('cuda-chart', labels, cudaData, '显存使用率');
}

document.getElementById('fetch-history').addEventListener('click', fetchHistoryData);

function renderChart(chartId, x, y, title) {
    const ctx = document.getElementById(chartId).getContext('2d');
    if (chartInstances[chartId]) { chartInstances[chartId].destroy(); }

    chartInstances[chartId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: x,
            datasets: [{
                label: title,
                data: y,
                borderColor: 'rgba(75, 192, 192, 1)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                fill: true,
            }]
        },
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time', // 使用时间类型
                    time: {
                        unit: 'hour',
                        displayFormats: {
                            hour: 'MM-dd HH:mm'
                        }
                    },
                    ticks: {
                        maxTicksLimit: 5  // 限制最多显示 5 个刻度
                    }
                },
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) { return value + '%'; }
                    }
                }
            }
        }
    });
}
fetchHistoryData();
