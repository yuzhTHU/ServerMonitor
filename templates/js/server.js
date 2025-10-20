(function () {
    function getQueryParam(name) {
        const params = new URLSearchParams(window.location.search);
        return params.get(name);
    }

    const host = getQueryParam('host');
    const titleEl = document.getElementById('server-title');
    const preEl = document.getElementById('server-info');

    if (!host) {
        titleEl.textContent = '服务器详情';
        preEl.textContent = '缺少 host 参数';
        return;
    }

    titleEl.textContent = `服务器详情：${host}`;
    preEl.textContent = '加载中...';

    fetch(`/api/server_info?host=${encodeURIComponent(host)}`)
        .then(resp => {
            if (!resp.ok) return resp.text().then(t => { throw new Error(t || resp.statusText); });
            return resp.text();
        })
        .then(text => {
            preEl.textContent = text || '无返回内容';
        })
        .catch(err => {
            preEl.textContent = `加载失败：${err.message}`;
        });
})();



