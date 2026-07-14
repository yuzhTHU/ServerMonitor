/* Copyright (c) 2024-present, Yumeow. Licensed under the MIT License. */
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

    const start = new Date(startDate).getTime() / 1000 - 8 * 3600;
    const end = new Date(endDate).getTime() / 1000 + 24 * 60 * 60 - 8 * 3600;

    const progress = document.getElementById('history-progress');
    const progressBar = document.getElementById('history-progress-bar');
    const progressLabel = document.getElementById('history-progress-label');
    const cardSpinners = document.querySelectorAll('#history .history-card-spinner');
    const fetchButton = document.getElementById('fetch-history');
    const renderIntervalMs = 750;

    document.getElementById('history-result-body').classList.add('is-active');

    function setCardLoading(loading) {
        cardSpinners.forEach(spinner => spinner.classList.toggle('is-active', loading));
    }

    function setProgress(percent, label, state = 'loading') {
        const value = Math.min(100, Math.max(0, percent));
        progress.classList.add('is-visible');
        progress.classList.toggle('is-complete', state === 'complete');
        progress.classList.toggle('is-error', state === 'error');
        progress.setAttribute('aria-valuenow', value.toFixed(1));
        progressBar.style.width = `${value}%`;
        progressLabel.textContent = `${label} · ${value.toFixed(value < 10 ? 1 : 0)}%`;
    }

    function updateStreamProgress(timestamp) {
        const range = end - start;
        const percent = range > 0 ? (timestamp - start) / range * 100 : 100;
        setProgress(percent, '正在接收');
    }

    setProgress(0, '正在连接');
    setCardLoading(true);
    fetchButton.disabled = true;

    const historyContainer = document.getElementById('history-chart');
    if (historyContainer.historyResizeObserver) {
        historyContainer.historyResizeObserver.disconnect();
    }
    if (historyContainer.historyChart) {
        historyContainer.historyChart.dispose();
    }
    historyContainer.innerHTML = '<div class="history-chart-canvas"></div>';
    const historyChartElement = historyContainer.querySelector('.history-chart-canvas');
    const historyChart = echarts.init(historyChartElement);
    historyContainer.historyChart = historyChart;

    const resizeCharts = () => {
        historyChart.resize({
            width: historyContainer.clientWidth,
            height: historyContainer.clientHeight
        });
    };
    if ('ResizeObserver' in window) {
        const resizeObserver = new ResizeObserver(resizeCharts);
        resizeObserver.observe(historyContainer);
        historyContainer.historyResizeObserver = resizeObserver;
    }
    requestAnimationFrame(resizeCharts);

    const labels = [];
    const cpuData = [];
    const memData = [];
    const cudaData = [];
    const cudaCapacity = [];
    let latestTimestamp = null;
    let lastRender = 0;

    function formatHistoryLabel(timestamp) {
        return new Date(timestamp * 1000).toLocaleString('zh-CN', {
            hour12: false,
            timeZone: 'Asia/Shanghai',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function consumeRecord(record) {
        normalizeRecord(record);
        labels.push(formatHistoryLabel(record.timestamp));
        cpuData.push(record.cpu);
        memData.push(record.memory);

        while (cudaData.length < record.cuda.length) {
            cudaData.push(new Array(labels.length - 1).fill(0));
            cudaCapacity.push(0);
        }
        const gpuIds = Object.keys(record.gpu_total_bytes || {}).sort((a, b) =>
            parseInt(a.split(':')[1]) - parseInt(b.split(':')[1])
        );
        for (let i = 0; i < cudaData.length; i++) {
            if (record.cuda[i] === undefined) {
                cudaData[i].push(0);
                continue;
            }
            const gpuId = gpuIds[i];
            cudaData[i].push(((record.gpu_usage_bytes || {})[gpuId] || 0) / 1073741824);
            cudaCapacity[i] = Math.max(cudaCapacity[i], (record.gpu_total_bytes[gpuId] || 0) / 1073741824);
        }

        latestTimestamp = record.timestamp;
    }

    function renderHistory() {
        const cudaSeries = cudaData.map((values, i) => ({
            name: `cuda:${i}`,
            type: 'line',
            stack: 'CUDA',
            areaStyle: {},
            emphasis: { focus: 'series' },
            xAxisIndex: 1,
            yAxisIndex: 1,
            showSymbol: false,
            data: values
        }));
        historyChart.setOption({
            animation: false,
            tooltip: {
                trigger: 'axis',
                axisPointer: { animation: false },
                formatter: function (params) {
                    if (!params.length) return '';
                    const lines = [params[0].axisValueLabel];
                    params.forEach(item => {
                        const value = Number(Array.isArray(item.value) ? item.value.at(-1) : item.value);
                        const isGpu = item.seriesName.startsWith('cuda:');
                        const formatted = Number.isFinite(value)
                            ? value.toFixed(isGpu ? 2 : 1)
                            : '-';
                        lines.push(`${item.marker}${item.seriesName}: <strong>${formatted} ${isGpu ? 'GiB' : '%'}</strong>`);
                    });
                    return lines.join('<br>');
                }
            },
            legend: {
                type: 'scroll',
                data: ['CPU', 'Memory', ...cudaSeries.map(s => s.name)],
                top: 8,
                left: 60,
                right: 180
            },
            toolbox: {
                top: 4,
                right: 45,
                feature: { dataZoom: { yAxisIndex: 'none' }, restore: {}, saveAsImage: {} }
            },
            axisPointer: { link: [{ xAxisIndex: 'all' }] },
            dataZoom: [
                {
                    type: 'slider',
                    show: true,
                    realtime: true,
                    start: 0,
                    end: 100,
                    xAxisIndex: [0, 1],
                    bottom: 10,
                    height: 22,
                    showDataShadow: false,
                    brushSelect: false,
                    borderColor: '#d9e2f2',
                    backgroundColor: '#f5f8fc',
                    fillerColor: 'rgba(79, 140, 255, .18)',
                    handleStyle: {
                        color: '#fff',
                        borderColor: '#4f8cff',
                        borderWidth: 2
                    },
                    moveHandleStyle: { color: '#4f8cff' }
                },
                { type: 'inside', realtime: true, start: 0, end: 100, xAxisIndex: [0, 1] }
            ],
            grid: [
                { left: 60, right: 50, height: '35%' },
                { left: 60, right: 50, top: '55%', height: '35%' }
            ],
            xAxis: [
                { type: 'category', boundaryGap: false, axisLine: { onZero: true }, data: labels },
                { gridIndex: 1, type: 'category', boundaryGap: false, axisLine: { onZero: true }, data: labels }
            ],
            yAxis: [
                { name: '%', type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
                {
                    gridIndex: 1,
                    name: 'GiB',
                    type: 'value',
                    max: Math.max(10, Math.ceil(cudaCapacity.reduce((a, b) => a + b, 0))),
                    axisLabel: { formatter: '{value} GiB' }
                }
            ],
            series: [
                { name: 'CPU', type: 'line', showSymbol: false, data: cpuData },
                { name: 'Memory', type: 'line', showSymbol: false, data: memData },
                ...cudaSeries
            ]
        });
    }

    function render(force = false) {
        const now = performance.now();
        if (!force && lastRender && now - lastRender < renderIntervalMs) return;
        renderHistory();
        lastRender = now;
    }

    try {
        const response = await fetch(`/api/history?host=${host}&start=${start}&end=${end}`);
        if (!response.ok || !response.body) throw new Error(`History request failed: ${response.status}`);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { value, done } = await reader.read();
            buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (line) consumeRecord(JSON.parse(line));
            }
            if (latestTimestamp !== null) updateStreamProgress(latestTimestamp);
            render(done);
            if (done) break;
        }
        if (buffer.trim()) {
            consumeRecord(JSON.parse(buffer));
            updateStreamProgress(latestTimestamp);
            render(true);
        }
        setProgress(100, '加载完成', 'complete');
        setTimeout(() => progress.classList.remove('is-visible'), 300);
    } catch (error) {
        setProgress(Number(progress.getAttribute('aria-valuenow')) || 0, '加载失败', 'error');
        console.error(error);
    } finally {
        setCardLoading(false);
        fetchButton.disabled = false;
    }
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
