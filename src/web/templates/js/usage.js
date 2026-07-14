/* Copyright (c) 2024-present, Yumeow. Licensed under the MIT License. */
(function () {
    const metrics = {
        cpu: {
            totalKey: 'cpu_core_hours', peakKey: 'cpu_peak_cores',
            totalLabel: '累计用量', peakLabel: '并发峰值',
            totalUnit: 'Core·h', peakUnit: 'Core', color: '#4f7df3'
        },
        memory: {
            totalKey: 'memory_gib_hours', peakKey: 'memory_peak_gib',
            totalLabel: '累计用量', peakLabel: '并发峰值',
            totalUnit: 'GiB·h', peakUnit: 'GiB', color: '#21b7a8'
        },
        gpu: {
            totalKey: 'gpu_gib_hours', peakKey: 'gpu_peak_gib',
            totalLabel: '累计用量', peakLabel: '并发峰值',
            totalUnit: 'GiB·h', peakUnit: 'GiB', color: '#8b6ce0'
        }
    };
    const charts = {};
    let progressHideTimer = null;

    function formatNumber(value) {
        if (value >= 1000) return value.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
        if (value >= 10) return value.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
        return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
    }

    function selectedHosts() {
        return Array.from(document.querySelectorAll('.usage-host-checkbox:checked')).map(item => item.value);
    }

    function updateHostButton() {
        const hosts = selectedHosts();
        const button = document.getElementById('usage-host-button');
        if (!hosts.length) button.textContent = '请选择服务器';
        else if (hosts.length <= 3) button.textContent = hosts.join('、');
        else button.textContent = `已选择 ${hosts.length} 台服务器`;
    }

    function stateMarkup(kind, text) {
        if (kind === 'loading') {
            return `<div class="card-load-state"><span class="card-load-spinner" aria-hidden="true"></span><span class="card-load-title">${text}</span></div>`;
        }
        if (kind === 'error') {
            return `<div class="card-load-state is-error"><span class="card-load-error-icon">!</span><span class="card-load-title">统计失败</span><span class="card-load-detail"></span></div>`;
        }
        return `<div class="history-empty-state"><span class="history-empty-state-icon">⌁</span><span>${text}</span></div>`;
    }

    function showState(kind, text) {
        Object.keys(metrics).forEach(metric => {
            if (charts[metric]) {
                charts[metric].dispose();
                delete charts[metric];
            }
            const container = document.getElementById(`usage-${metric}-chart`);
            container.innerHTML = stateMarkup(kind, text);
            if (kind === 'error') container.querySelector('.card-load-detail').textContent = text;
        });
    }

    function chartOption(users, metric) {
        const config = metrics[metric];
        const rows = users
            .filter(item => item[config.totalKey] > 0 || item[config.peakKey] > 0)
            .sort((a, b) => b[config.totalKey] - a[config.totalKey]);
        const names = rows.map(item => item.user);
        const totals = rows.map(item => item[config.totalKey]);
        const peaks = rows.map(item => item[config.peakKey]);
        const zoomEnd = names.length > 12 ? 12 / names.length * 100 : 100;
        const commonSeries = {
            type: 'bar',
            barMaxWidth: 18,
            showBackground: true,
            backgroundStyle: { color: '#f1f4f8', borderRadius: 8 },
            itemStyle: { borderRadius: [0, 7, 7, 0] },
            emphasis: { focus: 'series' }
        };
        return {
            animationDuration: 450,
            color: [config.color],
            tooltip: {
                trigger: 'item',
                axisPointer: { type: 'shadow' },
                formatter: item => {
                    const unit = item.seriesIndex === 0 ? config.totalUnit : config.peakUnit;
                    return `${item.marker}${item.name}<br>${item.seriesName}：<strong>${formatNumber(item.value)} ${unit}</strong>`;
                }
            },
            title: [
                { text: `${config.totalLabel}（${config.totalUnit}）`, left: '23%', top: 4, textAlign: 'center', textStyle: { fontSize: 13, color: '#52606d', fontWeight: 600 } },
                { text: `${config.peakLabel}（${config.peakUnit}）`, left: '72%', top: 4, textAlign: 'center', textStyle: { fontSize: 13, color: '#52606d', fontWeight: 600 } }
            ],
            grid: [
                { left: 105, right: '54%', top: 42, bottom: 28, containLabel: false },
                { left: '55%', right: 35, top: 42, bottom: 28, containLabel: false }
            ],
            xAxis: [
                { type: 'value', gridIndex: 0, axisLabel: { formatter: value => formatNumber(value) }, splitLine: { lineStyle: { color: '#edf1f5' } } },
                { type: 'value', gridIndex: 1, axisLabel: { formatter: value => formatNumber(value) }, splitLine: { lineStyle: { color: '#edf1f5' } } }
            ],
            yAxis: [
                { type: 'category', gridIndex: 0, inverse: true, data: names, axisTick: { show: false }, axisLabel: { width: 92, overflow: 'truncate', color: '#435267' } },
                { type: 'category', gridIndex: 1, inverse: true, data: names, axisTick: { show: false }, axisLabel: { show: false } }
            ],
            dataZoom: names.length > 12 ? [
                { type: 'inside', yAxisIndex: [0, 1], start: 0, end: zoomEnd },
                { type: 'slider', yAxisIndex: [0, 1], right: 4, width: 10, start: 0, end: zoomEnd, showDetail: false }
            ] : [],
            series: [
                { ...commonSeries, name: config.totalLabel, xAxisIndex: 0, yAxisIndex: 0, data: totals },
                { ...commonSeries, name: config.peakLabel, xAxisIndex: 1, yAxisIndex: 1, data: peaks }
            ]
        };
    }

    function renderCharts(users) {
        Object.keys(metrics).forEach(metric => {
            const container = document.getElementById(`usage-${metric}-chart`);
            const hasData = users.some(item => item[metrics[metric].totalKey] > 0 || item[metrics[metric].peakKey] > 0);
            if (!hasData) {
                if (charts[metric]) {
                    charts[metric].dispose();
                    delete charts[metric];
                }
                container.innerHTML = stateMarkup('empty', '所选范围内没有该资源的用户用量记录');
                return;
            }
            if (!charts[metric]) {
                container.innerHTML = '';
                charts[metric] = echarts.init(container);
            }
            charts[metric].setOption(
                chartOption(users, metric),
                { notMerge: true, lazyUpdate: true }
            );
        });
    }

    function updateSummary(payload, hosts, startDate, endDate, complete) {
        const summary = document.getElementById('usage-query-summary');
        const progress = Math.min(100, Math.max(0, Number(payload.progress) || 0));
        summary.textContent = complete
            ? `${hosts.length} 台服务器 · ${startDate} 至 ${endDate} · 汇总 ${payload.sample_count.toLocaleString('zh-CN')} 条采样记录`
            : `正在统计 · ${progress.toFixed(progress < 10 ? 1 : 0)}% · 已处理 ${payload.sample_count.toLocaleString('zh-CN')} 条采样记录`;
        summary.classList.add('is-visible');
    }

    function updateProgress(percent, label, state = 'loading') {
        const progress = document.getElementById('usage-progress');
        const bar = document.getElementById('usage-progress-bar');
        const labelElement = document.getElementById('usage-progress-label');
        const value = Math.min(100, Math.max(0, Number(percent) || 0));
        progress.classList.add('is-visible');
        progress.classList.toggle('is-complete', state === 'complete');
        progress.classList.toggle('is-error', state === 'error');
        progress.setAttribute('aria-valuenow', value.toFixed(1));
        bar.style.width = `${value}%`;
        labelElement.textContent = `${label} · ${value.toFixed(value < 10 ? 1 : 0)}%`;
    }

    async function fetchUsageStats() {
        const hosts = selectedHosts();
        const startDate = document.getElementById('usage-start-date').value;
        const endDate = document.getElementById('usage-end-date').value;
        if (!hosts.length) {
            showState('error', '请至少选择一台服务器');
            return;
        }
        if (!startDate || !endDate || startDate > endDate) {
            showState('error', '请选择有效的日期范围');
            return;
        }
        const start = new Date(startDate).getTime() / 1000 - 8 * 3600;
        const end = new Date(endDate).getTime() / 1000 + 24 * 3600 - 8 * 3600;
        const params = new URLSearchParams({ start, end });
        hosts.forEach(host => params.append('hosts', host));
        const button = document.getElementById('fetch-usage-stats');
        document.querySelectorAll('.usage-stat-body').forEach(body => body.classList.add('is-active'));
        button.disabled = true;
        showState('loading', '正在汇总历史用量');
        if (progressHideTimer) clearTimeout(progressHideTimer);
        updateProgress(0, '正在连接');
        const summary = document.getElementById('usage-query-summary');
        summary.textContent = '正在连接统计服务…';
        summary.classList.add('is-visible');
        let renderTimer = null;
        try {
            const response = await fetch(`/api/usage_stats?${params}`);
            if (!response.ok) {
                const payload = await response.json();
                throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
            }
            if (!response.body) throw new Error('浏览器不支持流式响应');

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let latestPayload = null;
            let renderedPayload = null;

            const renderLatest = () => {
                if (!latestPayload || latestPayload === renderedPayload) return;
                renderCharts(latestPayload.users || []);
                updateSummary(latestPayload, hosts, startDate, endDate, false);
                updateProgress(latestPayload.progress, '正在统计');
                renderedPayload = latestPayload;
            };
            renderTimer = setInterval(renderLatest, 1000);

            while (true) {
                const { value, done } = await reader.read();
                buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.trim()) continue;
                    const payload = JSON.parse(line);
                    if (payload.type === 'error') throw new Error(payload.detail || '统计过程中发生错误');
                    if (payload.type === 'complete') {
                        latestPayload = payload;
                        renderCharts(payload.users || []);
                        updateSummary(payload, hosts, startDate, endDate, true);
                        updateProgress(100, '统计完成', 'complete');
                        renderedPayload = payload;
                    } else {
                        latestPayload = payload;
                    }
                }
                if (done) break;
            }
            if (buffer.trim()) {
                const payload = JSON.parse(buffer);
                if (payload.type === 'error') throw new Error(payload.detail || '统计过程中发生错误');
                renderCharts(payload.users || []);
                updateSummary(payload, hosts, startDate, endDate, payload.type === 'complete');
                updateProgress(payload.progress, payload.type === 'complete' ? '统计完成' : '正在统计', payload.type === 'complete' ? 'complete' : 'loading');
            }
            progressHideTimer = setTimeout(() => {
                document.getElementById('usage-progress').classList.remove('is-visible');
            }, 350);
        } catch (error) {
            showState('error', error.message || '用量统计请求失败');
            updateProgress(
                Number(document.getElementById('usage-progress').getAttribute('aria-valuenow')) || 0,
                '统计失败',
                'error'
            );
        } finally {
            if (renderTimer) clearInterval(renderTimer);
            button.disabled = false;
        }
    }

    async function initialize() {
        const startInput = document.getElementById('usage-start-date');
        const endInput = document.getElementById('usage-end-date');
        startInput.value = new Date(Date.now() - 6 * 86400000).toISOString().split('T')[0];
        endInput.value = new Date().toISOString().split('T')[0];
        showState('empty', '请选择服务器和日期范围，然后生成统计图表');
        try {
            const response = await fetch('/api/hosts');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const hosts = await response.json();
            document.getElementById('usage-host-list').innerHTML = hosts.map(host => `
                <label class="usage-host-option">
                    <input class="form-check-input usage-host-checkbox" type="checkbox" value="${host}">
                    <span>${host}</span>
                </label>`).join('');
            document.querySelectorAll('.usage-host-checkbox').forEach(input => input.addEventListener('change', updateHostButton));
        } catch (error) {
            document.getElementById('usage-host-list').innerHTML = '<div class="text-danger p-3">服务器列表加载失败</div>';
        }
        document.getElementById('usage-select-all').addEventListener('click', () => {
            document.querySelectorAll('.usage-host-checkbox').forEach(input => { input.checked = true; });
            updateHostButton();
        });
        document.getElementById('usage-clear-all').addEventListener('click', () => {
            document.querySelectorAll('.usage-host-checkbox').forEach(input => { input.checked = false; });
            updateHostButton();
        });
        document.getElementById('fetch-usage-stats').addEventListener('click', fetchUsageStats);
        window.addEventListener('resize', () => Object.values(charts).forEach(chart => chart.resize()));
    }

    initialize();
})();
