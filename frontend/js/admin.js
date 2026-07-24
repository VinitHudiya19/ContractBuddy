/* 
 * DocuIntel - Admin Dashboard Logic
 * Wires up User Table toggle switches and user searches.
 * Simple code with student comments.
 */

document.addEventListener('DOMContentLoaded', async () => {
    // Redirect if no tokens
    if (!api.accessToken) {
        window.location.href = 'index.html';
        return;
    }

    const userSearchInput = document.getElementById('user-search-input');
    const userTableBody = document.getElementById('user-table-body');

    // Check if user is actually admin
    try {
        const user = await api.getMe();
        if (user.role !== 'admin') {
            window.location.href = 'app.html';
            return;
        }
    } catch(e) {
        window.location.href = 'index.html';
        return;
    }

    // Load user list
    async function loadUsersData(searchQuery = null) {
        try {
            userTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center;"><i class="fa-solid fa-spinner fa-spin"></i> Loading users list...</td></tr>';
            const users = await api.adminGetUsers(searchQuery);
            renderUsersTable(users);
        } catch (e) {
            userTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--danger);">Failed to query users.</td></tr>';
        }
    }

    function renderUsersTable(users) {
        if (users.length === 0) {
            userTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center;">No matching users found.</td></tr>';
            return;
        }

        userTableBody.innerHTML = '';
        users.forEach(user => {
            const tr = document.createElement('tr');
            const checkedState = user.is_active ? 'checked' : '';
            
            tr.innerHTML = `
                <td><strong>${escapeHtml(user.full_name)}</strong></td>
                <td>${escapeHtml(user.email)}</td>
                <td><span style="text-transform: capitalize; background: rgba(255,255,255,0.04); padding: 2px 8px; border-radius: 6px; font-size: 0.8rem;">${user.role}</span></td>
                <td>${user.document_count || 0}</td>
                <td>${user.query_count || 0}</td>
                <td>
                    <label class="switch">
                        <input type="checkbox" class="toggle-user-active" data-id="${user.id}" ${checkedState}>
                        <span class="slider"></span>
                    </label>
                </td>
            `;

            // Active toggle handler
            tr.querySelector('.toggle-user-active').addEventListener('change', async (e) => {
                const targetState = e.target.checked;
                try {
                    await api.adminSetUserActive(user.id, targetState);
                } catch(err) {
                    alert(err.message || 'Could not change user activation state.');
                    e.target.checked = !targetState; // rollback switch state
                }
            });

            userTableBody.appendChild(tr);
        });
    }

    // Debounced search trigger
    let searchTimeout = null;
    userSearchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            loadUsersData(userSearchInput.value.trim());
        }, 400);
    });

    loadUsersData();
});

// HTML escaping helper
function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
