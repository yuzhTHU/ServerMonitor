let dragSrcEl = null;
let placeholder = null;

function enableDragDrop() {
    // 给所有卡片绑定事件
    const dashboardCards = document.getElementById('dashboardCards');
    Array.from(dashboardCards.children).forEach(card => {
        card.setAttribute('draggable', 'true');
        card.addEventListener('dragstart', handleDragStart);
        card.addEventListener('dragover', handleDragOver);
        card.addEventListener('dragend', handleDragEnd);
    });

}

function disableDragDrop() {
    const dashboardCards = document.getElementById('dashboardCards');
    Array.from(dashboardCards.children).forEach(card => {
        card.removeAttribute('draggable');
        card.removeEventListener('dragstart', handleDragStart);
        card.removeEventListener('dragover', handleDragOver);
        card.removeEventListener('dragend', handleDragEnd);
    });
}

function handleDragStart(e) {
    dragSrcEl = this;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', '');

    placeholder = this.cloneNode(true);
    placeholder.classList.add('drag-placeholder');
    placeholder.style.opacity = '0.3';
    placeholder.style.pointerEvents = 'none';
    placeholder.id = '';
    placeholder.style.marginBottom = window.getComputedStyle(this).marginBottom;

    this.parentNode.insertBefore(placeholder, this.nextSibling);
    this.style.display = 'none';
}

function handleDragOver(e) {
    e.preventDefault(); // 必须阻止默认行为才能允许 drop
    e.dataTransfer.dropEffect = 'move';

    const target = e.target.closest('.col-md-4');
    if (target && target !== placeholder && target !== dragSrcEl) {
        const rect = target.getBoundingClientRect();
        const next = (e.clientX - rect.left) / rect.width > 0.5;
        target.parentNode.insertBefore(placeholder, next ? target.nextSibling : target);
    }
}

function handleDragEnd(e) {
    e.stopPropagation();
    if (dragSrcEl && placeholder) {
        placeholder.parentNode.insertBefore(dragSrcEl, placeholder);
        placeholder.remove();
        placeholder = null;
        dragSrcEl.style.display = '';
        dragSrcEl = null;
    }
    if (placeholder) {
        placeholder.remove();
        placeholder = null;
    }
    if (dragSrcEl) {
        dragSrcEl.style.display = '';
        dragSrcEl = null;
    }
}

// 保存顺序到 localStorage
function saveCardOrder() {
    const container = document.getElementById('dashboardCards');
    if (!container) return;
    const ids = Array.from(dashboardCards.querySelectorAll('.col-md-4 > .card')).map(card => card.id);
    localStorage.setItem('CardOrder', JSON.stringify(ids));
}

// 恢复顺序
function resumeDashboardCardOrder() {
    const container = document.getElementById('dashboardCards');
    if (!container) return;
    const saved = JSON.parse(localStorage.getItem('CardOrder') || '[]');
    if (!saved.length) return;

    saved.forEach(id => {
        const card = container.querySelector(`#${id}`);
        if (card && card.parentElement === container.querySelector(`#${id}`).parentElement) {
            container.appendChild(card.parentElement);
        }
    });
}

function resumeUserCardOrder() {
    const container = document.getElementById('user-summary');
    if (!container) return;
    const saved = JSON.parse(localStorage.getItem('CardOrder') || '[]');
    if (!saved.length) return;

    saved.forEach(id => {
        const card = container.querySelector(`#user-${id}`);
        if (card) { container.appendChild(card); }
    });
}

function resumeDiskCardOrder() {
    const container = document.getElementById('disk-container');
    if (!container) return;
    const saved = JSON.parse(localStorage.getItem('CardOrder') || '[]');
    if (!saved.length) return;

    saved.forEach(id => {
        const card = container.querySelector(`#disk-${id}`);
        if (card) { container.appendChild(card); }
    });
}