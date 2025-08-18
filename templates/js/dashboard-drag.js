const editBtn = document.getElementById("editLayoutBtn");
const dashboardCards = document.getElementById('dashboardCards');
let editMode = false;
let dragSrcEl = null;
let placeholder = null;

// 切换编辑模式
let _oldContext = "<oldContent>";
let tipBar;

editBtn.addEventListener("click", () => {
    editMode = !editMode;

    if (editMode) {
        _oldContext = editBtn.textContent;
        editBtn.textContent = "完成编辑";

        dashboardCards.classList.add("editable");
        enableDragDrop();

        // 创建提示条
        tipBar = document.createElement('div');
        tipBar.className = 'edit-tip-bar';
        tipBar.textContent = "拖动卡片以排序";
        tipBar.style.cssText = `
      padding: 8px;
      background: #fffae6;
      color: #333;
      font-weight: bold;
      text-align: center;
      border-bottom: 1px solid #ffd700;
    `;
        dashboardCards.prepend(tipBar);

    } else {
        editBtn.textContent = _oldContext;
        dashboardCards.classList.remove("editable");
        disableDragDrop();
        saveCardOrder();

        // 移除提示条
        if (tipBar) {
            tipBar.remove();
            tipBar = null;
        }
    }
});


function enableDragDrop() {
    // 给所有卡片绑定事件
    Array.from(dashboardCards.children).forEach(card => {
        card.setAttribute('draggable', 'true');
        card.addEventListener('dragstart', handleDragStart);
        card.addEventListener('dragover', handleDragOver);
        card.addEventListener('dragend', handleDragEnd);
    });

}

function disableDragDrop() {
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
    if (!dashboardCards) return;
    const ids = Array.from(dashboardCards.querySelectorAll('.col-md-4 > .card')).map(card => card.id);
    localStorage.setItem('dashboardCardOrder', JSON.stringify(ids));
}

// 恢复顺序
function resumeCardOrder() {
    if (!dashboardCards) return;
    const saved = JSON.parse(localStorage.getItem('dashboardCardOrder') || '[]');
    if (!saved.length) return;

    saved.forEach(id => {
        const card = dashboardCards.querySelector(`#${id}`);
        if (card && card.parentElement === dashboardCards.querySelector(`#${id}`).parentElement) {
            dashboardCards.appendChild(card.parentElement);
        }
    });
}