/* Contract Buddy - Admin dashboard
 * Usage stats and user activation. Admin-only; the API enforces this too.
 */

document.addEventListener('DOMContentLoaded', async function () {
    if (!api.accessToken) {
        window.location.href = 'index.html';
        return;
    }

    var searchInput = document.getElementById('user-search-input');
    var tableBody = document.getElementById('user-table-body');
    var chart = document.getElementById('queries-chart');

    // Client-side check for UX only — /api/admin/* returns 403 regardless.
    try {
        var me = await api.getMe();
        if (me.role !== 'admin') {
            window.location.href = 'app.html';
            return;
        }
    } catch (err) {
        api.clearTokens();
        window.location.href = 'index.html';
        return;
    }

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    async function loadStats() {
        try {
            var stats = await api.adminGetStats();
            document.getElementById('stat-users').textContent = stats.total_users;
            document.getElementById('stat-documents').textContent = stats.total_documents;
            document.getElementById('stat-conversations').textContent = stats.total_conversations;
            document.getElementById('stat-messages').textContent = stats.total_messages;
            renderChart(stats.queries_per_day || []);
        } catch (err) {
            console.error('Could not load stats:', err);
        }
    }

    function renderChart(series) {
        if (series.length === 0) {
            chart.innerHTML = '<p class="muted">No activity yet.</p>';
            return;
        }

        var peak = Math.max.apply(null, series.map(function (d) { return d.count; }));
        chart.innerHTML = '';

        series.forEach(function (day) {
            var height = peak > 0 ? Math.round((day.count / peak) * 100) : 0;
            var column = document.createElement('div');
            column.className = 'bar-column';
            column.title = day.date + ': ' + day.count +
                (day.count === 1 ? ' question' : ' questions');
            // Keep a sliver visible on zero days so the row reads as a timeline.
            column.innerHTML =
                '<div class="bar" style="height:' + Math.max(height, 2) + '%"></div>' +
                '<span class="bar-label">' + day.date.slice(5) + '</span>';
            chart.appendChild(column);
        });
    }

    async function loadUsers(query) {
        tableBody.innerHTML =
            '<tr><td colspan="6" class="table-message">Loading users…</td></tr>';
        try {
            renderUsers(await api.adminGetUsers(query));
        } catch (err) {
            tableBody.innerHTML =
                '<tr><td colspan="6" class="table-message error-text">' +
                'Could not load users.</td></tr>';
        }
    }

    function renderUsers(users) {
        if (users.length === 0) {
            tableBody.innerHTML =
                '<tr><td colspan="6" class="table-message">No matching users.</td></tr>';
            return;
        }

        tableBody.innerHTML = '';
        users.forEach(function (user) {
            var row = document.createElement('tr');
            row.innerHTML =
                '<td><strong>' + escapeHtml(user.full_name) + '</strong></td>' +
                '<td>' + escapeHtml(user.email) + '</td>' +
                '<td><span class="role-pill">' + escapeHtml(user.role) + '</span></td>' +
                '<td>' + (user.document_count || 0) + '</td>' +
                '<td>' + (user.query_count || 0) + '</td>' +
                '<td><label class="switch">' +
                '<input type="checkbox"' + (user.is_active ? ' checked' : '') + '>' +
                '<span class="slider"></span></label></td>';

            row.querySelector('input').addEventListener('change', async function (e) {
                var wanted = e.target.checked;
                try {
                    await api.adminSetUserActive(user.id, wanted);
                } catch (err) {
                    // Roll the switch back so it never shows a state the server rejected.
                    e.target.checked = !wanted;
                    alert(err.message || 'Could not change this account.');
                }
            });

            tableBody.appendChild(row);
        });
    }

    var searchTimer = null;
    searchInput.addEventListener('input', function () {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () {
            loadUsers(searchInput.value.trim());
        }, 350);
    });

    await loadStats();
    await loadUsers();
});
