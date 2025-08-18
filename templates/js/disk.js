async function InitContainer(hosts) {
    const container = document.getElementById('disk-container');
    container.innerHTML = '';
    hosts.forEach(host => {
        const card = document.createElement('div');
        card.className = "card mx-0 shadow-sm mb-4";
        card.innerHTML = `
            <div class="card-header">
                <h5 class="fw-bold">${host}</h5>
            </div>
            <div class="card-body">
                <div class="row justify-content-center" id="${host}-charts"></div>
                <div class="timestamp">
                    <span id="disk-time-${host}">Last Update: ???</span> (<span id="disk-time-ago-${host}">??? ago</span>)
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

async function DrawChart(host) {
    const data = await fetch(`/api/disk?host=${host}`).then(response => response.json());
    const container = document.getElementById(`${host}-charts`);
    container.innerHTML = '';
    const showDisk = document.getElementById('show-disk');
    const colorDisk = document.getElementById('color-disk');

    const aggregate  = {"host":host, "time": data[0]["time"], "disk":'Total', "total": 0, "free": 0, "usage": {}};
    data.forEach(disk => {
        aggregate.total += disk.total;
        aggregate.free += disk.free;
        for (const [user, size] of Object.entries(disk.usage)) {
            aggregate.usage[user] = (aggregate.usage[user] || 0) + size;
        }
    });
    data.unshift(aggregate); // 将 aggregate 添加到 data 的最开头

    function format_GB(value) {
        if (value > 1024) { return `${(value/1024).toFixed(0)}TB`; }
        else if (value > 1) { return `${(value).toFixed(0)}GB`; }
        else if (value > 1/1024) { return `${(value*1024).toFixed(0)}MB`; }
        else { return `${(value*1024*1024).toFixed(0)}KB`; }
    }
    function colorInterpolate(value, red=0.85) {
        if (value >= red) return '#d63031';
        else value = value / red;
        const mixed = Color.mix('#00b894', '#b2bec3', value, {space: "lch", outspace: "srgb"});
        const r = Math.min(255, Math.max(0, Math.round(mixed.srgb.r * 255)));
        const g = Math.min(255, Math.max(0, Math.round(mixed.srgb.g * 255)));
        const b = Math.min(255, Math.max(0, Math.round(mixed.srgb.b * 255)));
        const a = `rgb(${r}, ${g}, ${b})`;
        return a;
    }

    data.forEach((diskData, index) => {
        const colDiv = document.createElement('div');
        colDiv.className = 'chart-container col-md-4 mb-4';

        const chartDiv = document.createElement('div');
        chartDiv.className = 'chart';

        colDiv.appendChild(chartDiv);
        container.appendChild(colDiv);
        
        // 处理当前磁盘上的用户数据：添加颜色 & 大小排序 & 添加余量        
        let threshold;
        if (colorDisk.value == 'color-by-disk') {
            threshold = 0.2 * diskData.total;  // 超过 20% CurrentDiskTotal 即为红色
        } else {
            threshold = 0.2 * aggregate.total / (data.length - 1); // 超过 20% AllDiskMean 即为红色
        }
        let usageData = Object.entries(diskData.usage).map(([user, value]) => ({
            name: user,
            value: value,
            itemStyle: { color: colorInterpolate(value, threshold) },
        }));
        usageData = usageData.sort((a, b) => b.value - a.value);
        usageData.push({ 
            name: 'Free',
            value: diskData.free,
            itemStyle: { color: '#ffeaa7' },
        });

        // 绘图
        let angle;
        if (showDisk.value == 'norm-by-disk') {
            angle = 360;
        } else if (showDisk.value == 'norm-by-max') {
            angle = (diskData.total / data.slice(1).reduce((max, x) => x.total > max ? x.total : max, -Infinity)) * 360;
            if (index == 0) { angle = 360; }
            // angle = 360;
        } else {
            angle = (diskData.total / aggregate.total) * 360;
        }

        const chart = echarts.init(chartDiv);
        chart.setOption({
            title: { // 在中间显示加粗的标题（disk)
                text: `${diskData.disk}`, textStyle: {fontSize: 28},
                subtext: `${format_GB(diskData.free)} Free`, subtextStyle: {color: '#b2bec3'},
                left: 'center', top: 'center',
                target: 'blank', link: '/todo',
            },
            tooltip: { // 悬停时弹出气泡
              trigger: 'item',
              formatter: function (params) { return `${params.name} ${format_GB(params.value)} (${params.percent.toFixed(1)}%)`; }
            },
            legend: { show: false }, // 不显示 legend
            series: [{ // 饼图数据
              type: 'pie',
              data: usageData,
              name: diskData.disk,
              radius: ['50%', '70%'],
              padAngle: 0.3, // 饼瓣间隙
              startAngle: 135, // 从左上方开始
              endAngle: 135-angle, // 角度为 angle 度
              minShowLabelAngle: 360*0.05, // 不显示 <5% 的用户名称
              avoidLabelOverlap: true,
              itemStyle: { borderRadius: 99 }, // 圆角半径
              label: { 
                width: 99999, bleedMargin: 0, edgeDistance: 0, alignTo: 'labelLine',
                formatter: function (params) { return `${params.name}\n${format_GB(params.value)}\n(${params.percent.toFixed(1)}%)`; },
              },
              labelLayout: {hideOverlap: false, draggable: true}, // 可拖曳 label
              emphasis: { label: { fontSize: 14, fontWeight: 'bold', } }, // 悬停加粗
            }]
        });

        // 时间戳
        const timestamp = diskData.time;
        const time = document.getElementById(`disk-time-${host}`);
        time.innerHTML = `Last Update: ${formatTimestamp(timestamp)}`;
        if (time.timer) { clearTimeout(time.timer); }
        let count = 0; // 计数器
        const updateTimeAgo = () => {
            const lastUpdateElement = document.getElementById(`disk-time-ago-${host}`);
            lastUpdateElement.innerHTML = getTimeAgo(timestamp);
            count++;
            let delay = count < 60 ? 1000 : count < 120 ? 60000 : 3600000;
            time.timer = setTimeout(updateTimeAgo, delay);
        };
        updateTimeAgo();
    })
}

async function InitDiskUsage() {
    const hosts = await fetch('/api/hosts').then(response => response.json());
    await InitContainer(hosts);
    await Promise.all(hosts.map(
        host => DrawChart(host).catch(err => { console.error(`绘制 ${host.name} 时出错：`, err); })
    ));
}

InitDiskUsage()
document.getElementById('fetch-disk-data').addEventListener('click', InitDiskUsage)
