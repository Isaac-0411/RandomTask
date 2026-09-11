document.addEventListener('DOMContentLoaded', function() {
    initTheme();
    initAvatarDropdown();
    initTaskHandlers();
});

function initTheme() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    }
    
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.textContent = document.documentElement.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
        
        themeToggle.addEventListener('click', function() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            themeToggle.textContent = newTheme === 'dark' ? '☀️' : '🌙';
        });
    }
}

function initAvatarDropdown() {
    const avatarBtn = document.getElementById('avatar-btn');
    const avatarMenu = document.getElementById('avatar-menu');
    
    if (avatarBtn && avatarMenu) {
        avatarBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            avatarMenu.classList.toggle('show');
        });
        
        document.addEventListener('click', function() {
            avatarMenu.classList.remove('show');
        });
    }
    
    document.querySelectorAll('.avatar-option').forEach(option => {
        option.addEventListener('click', function() {
            const avatar = this.getAttribute('data-avatar');
            updateAvatar(avatar);
            avatarMenu.classList.remove('show');
        });
    });
}

function updateAvatar(avatar) {
    fetch('/profile', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ avatar: avatar })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const avatarIcon = document.querySelector('.avatar-icon');
            if (avatarIcon) {
                const emojiMap = {
                    'male': '👨',
                    'female': '👩',
                    'anonymous': '👤'
                };
                avatarIcon.textContent = emojiMap[avatar];
                avatarIcon.className = 'avatar-icon ' + avatar;
            }
        }
    });
}

function initTaskHandlers() {
    const tasksContainer = document.getElementById('tasks-container');
    if (tasksContainer) {
        useDebouncedInputs();
        initCheckboxes();
    }
}

function useDebouncedInputs() {
    document.querySelectorAll('.task-input').forEach(input => {
        let debounceTimer;
        
        input.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            const taskId = this.getAttribute('data-task-id');
            const content = this.value;
            
            debounceTimer = setTimeout(function() {
                updateTask(taskId, content, null);
            }, 300);
        });
    });
}

function initCheckboxes() {
    document.querySelectorAll('.task-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const taskId = this.getAttribute('data-task-id');
            const completed = this.checked;
            const taskCard = this.closest('.task-card');
            
            if (taskCard) {
                taskCard.classList.toggle('completed', completed);
            }
            
            updateTask(taskId, null, completed);
        });
    });
}

function updateTask(taskId, content, completed) {
    const payload = { task_id: parseInt(taskId) };
    if (content !== null) payload.content = content;
    if (completed !== null) payload.completed = completed;
    
    fetch('/update_task', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            updateProgress(data.completed_count, data.total);
            updateMotivation(data.completed_count, data.total);
        }
    });
}

function updateProgress(completed, total) {
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    
    if (progressFill && progressText) {
        const percent = total > 0 ? (completed / total * 100) : 0;
        progressFill.style.width = percent + '%';
        progressText.textContent = `${completed}/${total} completed`;
    }
}

function updateMotivation(completed, total) {
    const motivationEl = document.querySelector('.motivation-text');
    if (motivationEl && total > 0) {
        if (completed === total) {
            motivationEl.textContent = '🎉 Amazing! You completed all tasks today!';
        } else if (completed > 0) {
            motivationEl.textContent = '💪 Keep going! You\'re doing great!';
        } else {
            motivationEl.textContent = '🚀 Start completing your tasks!';
        }
    }
}