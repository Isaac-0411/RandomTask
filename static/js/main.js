'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
let toastTimer;
function toast(message, error = false) {
    const element = $('#toast');
    element.textContent = message;
    element.classList.toggle('error', error);
    element.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => element.classList.add('hidden'), error ? 7000 : 3500);
}

async function postJSON(url, payload) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
        const message = response.status === 401
            ? 'Your session has ended. Sign in again to save your changes.'
            : data.error || 'Could not save. Check your connection and try again.';
        throw new Error(message);
    }
    return data;
}

function initTheme() {
    const button = $('#theme-toggle');
    if (!button) return;
    const moon = '<path d="M20.7 13A9 9 0 0 1 11 3.3 9 9 0 1 0 20.7 13Z"/>';
    const sun = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>';
    function updateButton() {
        const dark = document.documentElement.dataset.theme === 'dark';
        button.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${dark ? sun : moon}</svg>`;
        button.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
    }
    updateButton();
    button.addEventListener('click', () => {
        const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = theme;
        try { localStorage.setItem('theme', theme); } catch (_) { /* Theme still works without storage. */ }
        updateButton();
    });
}

function initAvatarDropdown() {
    const button = $('#avatar-btn');
    const menu = $('#avatar-menu');
    if (!button || !menu) return;
    const initial = $('.profile-avatar')?.textContent.trim() || 'R';
    function close() {
        menu.hidden = true;
        menu.classList.remove('show');
        button.setAttribute('aria-expanded', 'false');
    }
    button.addEventListener('click', () => {
        const opening = menu.hidden;
        menu.hidden = !opening;
        menu.classList.toggle('show', opening);
        button.setAttribute('aria-expanded', String(opening));
    });
    document.addEventListener('click', event => {
        if (!event.target.closest('.avatar-dropdown')) close();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !menu.hidden) { close(); button.focus(); }
    });
    const avatarOptions = Array.from(menu.querySelectorAll('[data-avatar]'));
    avatarOptions.forEach(option => {
        option.addEventListener('click', async () => {
            const avatar = option.dataset.avatar;
            avatarOptions.forEach(item => { item.disabled = true; });
            try {
                await postJSON('/profile', { avatar });
                const element = $('.avatar-icon');
                element.textContent = { male: '👨', female: '👩', anonymous: initial }[avatar];
                element.className = `avatar-icon ${avatar}`;
                close();
                button.focus();
                toast('Avatar updated');
            } catch (error) { toast(error.message, true); }
            finally { avatarOptions.forEach(item => { item.disabled = false; }); }
        });
    });
}

function initPasswordToggles() {
    document.querySelectorAll('.password-toggle').forEach(button => {
        button.addEventListener('click', () => {
            const input = $('input', button.parentElement);
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            button.setAttribute('aria-pressed', String(show));
            button.setAttribute('aria-label', `${show ? 'Hide' : 'Show'} password`);
        });
    });
}

function initTaskHandlers() {
    const container = $('#tasks-container');
    if (!container) return;
    const states = Array.from(container.querySelectorAll('.task-card'), card => ({
        id: Number(card.dataset.taskId), card,
        input: $('.task-input', card), checkbox: $('.task-checkbox', card),
        retry: $('.task-retry', card),
        timer: null, revision: 0, savedRevision: 0,
        savedCompleted: $('.task-checkbox', card).checked,
        queued: false, saving: false, error: null, retryCompleted: null,
    }));
    let queue = Promise.resolve();
    let filter = 'all';
    const status = $('#save-status');

    function refresh() {
        let completed = 0;
        let visible = 0;
        for (const state of states) {
            const checked = state.checkbox.checked && Boolean(state.input.value.trim());
            if (checked) completed++;
            state.card.classList.toggle('completed', checked);
            state.card.classList.toggle('is-saving', state.saving);
            state.card.classList.toggle('save-error', Boolean(state.error));
            state.retry.hidden = !state.error;
            state.card.hidden = filter === 'completed' ? !checked : filter === 'active' ? checked : false;
            if (!state.card.hidden) visible++;
        }
        const total = states.length;
        const percent = total ? Math.round(completed / total * 100) : 0;
        $('#progress-fill').style.width = `${percent}%`;
        $('#progress-arc').setAttribute('stroke-dashoffset', String(100 - percent));
        $('#progress-percent').innerHTML = `${percent}<small>%</small>`;
        $('#progress-text').textContent = `${completed} of ${total} tasks completed`;
        $('.progress-bar').setAttribute('aria-valuenow', String(completed));
        $('#legend-completed').textContent = `${completed} done`;
        $('#legend-remaining').textContent = `${total - completed} to go`;
        $('#active-filter-count').textContent = total - completed;
        $('#completed-filter-count').textContent = completed;
        $('#visible-count').textContent = `${visible} ${visible === 1 ? 'task' : 'tasks'}`;
        $('#filter-empty').hidden = visible !== 0;
        $('.motivation-text').textContent = completed === total
            ? 'Everything done. Enjoy a little breathing room.'
            : completed ? 'Every little step counts. Keep going.' : 'Your first small win is waiting.';
        const errors = states.some(state => state.error);
        const dirty = states.some(state => state.revision !== state.savedRevision || state.saving || state.queued);
        status.dataset.state = errors ? 'error' : dirty ? 'saving' : 'saved';
        $('span:last-child', status).textContent = errors ? 'Not saved · Retry' : dirty ? 'Saving changes…' : 'All changes saved';
        status.title = errors ? 'Retry saving your changes' : 'Your changes save automatically';
    }

    function save(state) {
        clearTimeout(state.timer);
        if (state.error || state.queued || state.saving || state.revision === state.savedRevision) return;
        state.queued = true;
        refresh();
        // Serialize writes so a slow response cannot overwrite a newer edit.
        queue = queue.then(async () => {
            state.queued = false;
            state.saving = true;
            state.error = null;
            const revision = state.revision;
            const payload = {
                task_id: state.id,
                content: state.input.value,
                completed: state.checkbox.checked && Boolean(state.input.value.trim()),
            };
            refresh();
            try {
                const data = await postJSON('/update_task', payload);
                state.savedRevision = revision;
                state.savedCompleted = data.task.completed;
                state.retryCompleted = null;
                if (state.revision === revision) {
                    state.input.value = data.task.content;
                    state.checkbox.checked = data.task.completed;
                }
            } catch (error) {
                state.error = error.message;
                // Keep the task text available to retry, and undo unconfirmed completion.
                if (state.revision === revision) {
                    state.retryCompleted = payload.completed;
                    state.checkbox.checked = state.savedCompleted && Boolean(state.input.value.trim());
                }
                toast(error.message, true);
            } finally {
                state.saving = false;
                refresh();
                // An edit typed while the previous request was pending still needs saving.
                if (!state.error && state.revision !== state.savedRevision) save(state);
            }
        });
    }

    function retry(state) {
        // A failed completion is visually undone; retry the user's intended state.
        if (state.retryCompleted !== null) {
            state.checkbox.checked = state.retryCompleted && Boolean(state.input.value.trim());
            state.retryCompleted = null;
        }
        state.error = null;
        save(state);
    }

    for (const state of states) {
        state.input.addEventListener('input', () => {
            state.revision++;
            state.error = null;
            state.retryCompleted = null;
            if (!state.input.value.trim()) state.checkbox.checked = false;
            clearTimeout(state.timer);
            state.timer = setTimeout(() => save(state), 350);
            refresh();
        });
        state.input.addEventListener('blur', () => save(state));
        state.input.addEventListener('keydown', event => {
            if (event.key === 'Enter') {
                event.preventDefault();
                save(state);
                const next = states.slice(states.indexOf(state) + 1).find(item => !item.card.hidden);
                (next?.input || state.checkbox).focus();
            }
        });
        state.checkbox.addEventListener('change', () => {
            if (state.checkbox.checked && !state.input.value.trim()) {
                state.checkbox.checked = false;
                state.input.focus();
                toast('Write a task before marking it complete.', true);
                return;
            }
            state.revision++;
            state.error = null;
            state.retryCompleted = null;
            refresh();
            save(state);
        });
        state.retry.addEventListener('click', () => retry(state));
    }
    status.addEventListener('click', () => states.filter(state => state.error).forEach(retry));
    document.querySelectorAll('[data-filter]').forEach(button => {
        button.addEventListener('click', () => {
            filter = button.dataset.filter;
            document.querySelectorAll('[data-filter]').forEach(item => {
                const active = item === button;
                item.classList.toggle('active', active);
                item.setAttribute('aria-pressed', String(active));
            });
            refresh();
        });
    });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') states.forEach(save);
    });
    window.addEventListener('beforeunload', event => {
        if (states.some(state => state.revision !== state.savedRevision || state.queued || state.saving)) {
            states.forEach(save);
            event.preventDefault();
            event.returnValue = '';
        }
    });
    refresh();
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initAvatarDropdown();
    initPasswordToggles();
    initTaskHandlers();
});
