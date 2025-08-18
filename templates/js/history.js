async function InitOption() {
    // 设置默认日期为7天前和当前日期
    document.getElementById('start-date').value = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    document.getElementById('end-date').value = new Date().toISOString().split('T')[0];
    const hosts = await fetch('/api/hosts').then(response => response.json());
    const select = document.getElementById('host-select');
    hosts.forEach(host => {
        const option = document.createElement('option');
        option.value = host;
        option.innerHTML = host;
        select.appendChild(option);
    });
    select.selectedIndex = 0;
    document.getElementById('fetch-history').addEventListener('click', fetchHistoryData);
}
InitOption();

async function fetchHistoryData() {
    const host = document.getElementById('host-select').value;
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    document.getElementById('history-title').innerHTML = host;

    // 将日期转换为时间戳
    const start = new Date(startDate).getTime() / 1000 - 8 * 3600;
    const end = new Date(endDate).getTime() / 1000 + 24 * 60 * 60 - 8 * 3600; // 结束日期加一天
    const response = await fetch(`/api/history?host=${host}&start=${start}&end=${end}`);
    const data = await response.json();

    // 对数据进行排序
    data.sort((a, b) => a.timestamp - b.timestamp);

    // x轴时间标签
    const labels = data.map(record => {
        const d = new Date(record.timestamp * 1000);
        // return d.toISOString().slice(0, 16).replace('T', ' ');
        return d.toLocaleString('zh-CN', {
            hour12: false,
            timeZone: 'Asia/Shanghai',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        }); // .replace(/\//g, '-');
    });


    // CPU 和 Memory 数据
    const cpuData = data.map(record => record.cpu);
    const memData = data.map(record => record.memory);

    // CUDA 是二维数组，找最大 GPU 数目
    const maxCudaCount = Math.max(...data.map(record => record.cuda.length));

    // 准备每个 GPU 的堆叠数据，缺失补0
    let cudaSeries = [];
    let maxCudaMemory = 0;
    for (let i = 0; i < maxCudaCount; i++) {
        arr = data.map(record => (record.cuda[i] !== undefined ? (
            record.cuda[i] * record.cuda_free[i] / (100 - record.cuda[i]) / 1024
        ) : 0));
        maxCudaMemory += Math.max(...data.map(record => (record.cuda[i] !== undefined ? (
            100 * record.cuda_free[i] / (100 - record.cuda[i]) / 1024
        ) : 0)));
        cudaSeries[i] = {
            name: `cuda:${i + 1}`,
            type: 'line',
            stack: 'CUDA',
            areaStyle: {},
            emphasis: { focus: 'series' },
            data: arr
        }
    }

    const container = document.getElementById('history-chart');
    container.innerHTML = '';
    const colDiv = document.createElement('div');
    colDiv.className = 'col-md-12';
    container.appendChild(colDiv);
    const chartDiv = document.createElement('div');
    chartDiv.className = 'chart';
    colDiv.appendChild(chartDiv);
    const chart = echarts.init(chartDiv);
    chart.setOption({
        // title: { text: host, left: 'center' },
        tooltip: {
            trigger: 'axis',
            axisPointer: { animation: false },
        },
        legend: {
            data: ['CPU', 'Memory', ...cudaSeries.map(s => s.name)],
            left: 10,
        },
        toolbox: {
            feature: {
                dataZoom: { yAxisIndex: 'none' },
                restore: {},
                saveAsImage: {}
            }
        },
        axisPointer: {
            link: [ { xAxisIndex: 'all' } ]
        },
        dataZoom: [
            {
                show: true,
                realtime: true,
                start: 0,
                end: 100,
                xAxisIndex: [0, 1]
            },
            {
                type: 'inside',
                realtime: true,
                start: 0,
                end: 100,
                xAxisIndex: [0, 1]
            }
        ],
        grid: [
            {
                left: 60,
                right: 50,
                height: '35%'
            },
            {
                left: 60,
                right: 50,
                top: '55%',
                height: '35%'
            }
        ],
        xAxis: [
            {
                type: 'category',
                boundaryGap: false,
                axisLine: { onZero: true },
                data: labels
            },
            {
                gridIndex: 1,
                type: 'category',
                boundaryGap: false,
                axisLine: { onZero: true },
                data: labels,
            }
        ],
        yAxis: [
            {
                name: '%',
                type: 'value',
                max: 100
            },
            {
                gridIndex: 1,
                name: 'GiB',
                type: 'value',
                max: maxCudaMemory.toFixed(0),
            }
        ],
        series: [
            {
                name: 'CPU',
                type: 'line',
                symbolSize: 8,
                data: cpuData,
                
            },
            {
                name: 'Memory',
                type: 'line',
                xAxisIndex: 0,
                yAxisIndex: 0,
                data: memData
            },
            ...cudaSeries.map(s => ({
                ...s,
                xAxisIndex: 1,
                yAxisIndex: 1,
            }))

        ]
    });
}

// let chartInstances = {};
// async function fetchHistoryData() {
//     const host = document.getElementById('host-select').value;
//     const startDate = document.getElementById('start-date').value;
//     const endDate = document.getElementById('end-date').value;

//     document.getElementById('chart-title-cpu').innerHTML = `CPU (${host})`;
//     document.getElementById('chart-title-mem').innerHTML = `Memory (${host})`;
//     document.getElementById('chart-title-cuda').innerHTML = `CUDA (${host})`;
    
//     // 将日期转换为时间戳
//     const start = new Date(startDate).getTime() / 1000;
//     const end = new Date(endDate).getTime() / 1000 + 24 * 60 * 60; // 结束日期加一天
//     const response = await fetch(`/api/history?host=${host}&start=${start}&end=${end}`);
//     const data = await response.json();

//     // 对数据进行排序
//     data.sort((a, b) => a.timestamp - b.timestamp);

//     // 提取时间、cpu、memory、cuda 数据
//     const labels = data.map(record => new Date(record.timestamp * 1000));
//     const cpuData = data.map(record => record.cpu);
//     const memData = data.map(record => record.memory);
//     const cudaData = data.map(record => {
//         // 取平均值作为展示
//         return record.cuda.reduce((a, b) => a + b, 0) / record.cuda.length;
//     });

//     // 绘制图表
//     renderChart('cpu-chart', labels, cpuData, 'CPU 使用率');
//     renderChart('mem-chart', labels, memData, '内存使用率');
//     renderChart('cuda-chart', labels, cudaData, '显存使用率');
// }


// function renderChart(chartId, x, y, title) {
//     const ctx = document.getElementById(chartId).getContext('2d');
//     if (chartInstances[chartId]) { chartInstances[chartId].destroy(); }

//     chartInstances[chartId] = new Chart(ctx, {
//         type: 'line',
//         data: {
//             labels: x,
//             datasets: [{
//                 label: title,
//                 data: y,
//                 borderColor: 'rgba(75, 192, 192, 1)',
//                 backgroundColor: 'rgba(75, 192, 192, 0.2)',
//                 fill: true,
//             }]
//         },
//         options: {
//             responsive: true,
//             scales: {
//                 x: {
//                     type: 'time', // 使用时间类型
//                     time: {
//                         unit: 'hour',
//                         displayFormats: {
//                             hour: 'MM-dd HH:mm'
//                         }
//                     },
//                     ticks: {
//                         maxTicksLimit: 5  // 限制最多显示 5 个刻度
//                     }
//                 },
//                 y: {
//                     beginAtZero: true,
//                     ticks: {
//                         callback: function(value) { return value + '%'; }
//                     }
//                 }
//             }
//         }
//     });
// }
