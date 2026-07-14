/* Copyright (c) 2024-present, Yumeow. Licensed under the MIT License. */
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

// ── 将后端原始数据 (millicores / bytes / dict) 映射为前端可直接使用的旧格式计算属性 ──
function normalizeRecord(r) {
    var GiB = 1073741824, MiB = 1048576;

    // CPU
    r.cpu = r.cpu_usage_millicores / r.cpu_total_millicores * 100;
    r.cpu_free = (r.cpu_total_millicores - r.cpu_usage_millicores) / 1000;

    // Memory
    r.memory = r.memory_usage_bytes / r.memory_total_bytes * 100;
    r.memory_free = (r.memory_total_bytes - r.memory_usage_bytes) / MiB;

    // GPU arrays
    var gids = Object.keys(r.gpu_total_bytes || {}).sort(function(a, b) {
        return parseInt(a.split(':')[1]) - parseInt(b.split(':')[1]);
    });
    r.cuda = gids.map(function(id) {
        var tb = r.gpu_total_bytes[id] || 0;
        var ub = (r.gpu_usage_bytes || {})[id] || 0;
        return tb > 0 ? ub / tb * 100 : 0;
    });
    r.cuda_free = gids.map(function(id) {
        var tb = r.gpu_total_bytes[id] || 0;
        var ub = (r.gpu_usage_bytes || {})[id] || 0;
        return (tb - ub) / MiB;
    });

    // cuda_per_user: {user: {gpu_id: bytes}} → [[gpu_id, user, mem_mib], ...]
    r.cuda_per_user = [];
    var gpuPerUser = r.gpu_per_user || {};
    for (var user in gpuPerUser) {
        var gpus = gpuPerUser[user];
        for (var gpuId in gpus) {
            r.cuda_per_user.push([gpuId, user, Math.round(gpus[gpuId] / MiB)]);
        }
    }

    return r;
}

// 自动反白
function autoContrast(bg_color) {
    const [r, g, b] = bg_color.match(/\d+/g).map(Number);
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;;
    return luminance > 128 ? '#000' : '#fff';
}
