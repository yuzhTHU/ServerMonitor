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

// 自动反白
function autoContrast(bg_color) {
    const [r, g, b] = bg_color.match(/\d+/g).map(Number);
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;;
    return luminance > 128 ? '#000' : '#fff';
}
