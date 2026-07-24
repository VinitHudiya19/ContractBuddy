/* 
 * DocuIntel - API Client Library
 * Handles authentication, documents, conversations, SSE streaming, and admin stats.
 * Written in simple, easy to read code with student-developer comments.
 */

const API_BASE = window.location.origin;

class ApiClient {
    constructor() {
        this.accessToken = localStorage.getItem('access_token');
        this.refreshToken = localStorage.getItem('refresh_token');
    }

    // Save JWT tokens in localStorage
    saveTokens(access, refresh) {
        this.accessToken = access;
        this.refreshToken = refresh;
        localStorage.setItem('access_token', access);
        localStorage.setItem('refresh_token', refresh);
    }

    // Clear tokens on logout
    clearTokens() {
        this.accessToken = null;
        this.refreshToken = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }

    // Generic fetch request with auto-refresh token retry logic
    async request(path, options = {}) {
        options.headers = options.headers || {};
        
        if (this.accessToken) {
            options.headers['Authorization'] = `Bearer ${this.accessToken}`;
        }
        
        // Add random request ID header
        const requestId = Math.random().toString(36).substring(2, 10);
        options.headers['X-Request-ID'] = requestId;

        let response = await fetch(`${API_BASE}${path}`, options);

        // Auto refresh access token on 401
        if (response.status === 401 && this.refreshToken) {
            try {
                const refreshed = await this.rotateTokens();
                if (refreshed) {
                    options.headers['Authorization'] = `Bearer ${this.accessToken}`;
                    response = await fetch(`${API_BASE}${path}`, options);
                }
            } catch (err) {
                this.clearTokens();
                window.location.href = 'index.html';
                throw err;
            }
        }

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            const errMsg = errData.error?.message || `Request failed with status ${response.status}`;
            const errCode = errData.error?.code || 'HTTP_ERROR';
            const error = new Error(errMsg);
            error.code = errCode;
            error.status = response.status;
            throw error;
        }

        if (response.status === 204) return null;
        return response.json();
    }

    // Call refresh token rotation endpoint
    async rotateTokens() {
        if (!this.refreshToken) return false;
        
        const res = await fetch(`${API_BASE}/api/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: this.refreshToken })
        });

        if (!res.ok) {
            this.clearTokens();
            return false;
        }

        const data = await res.json();
        this.saveTokens(data.access_token, data.refresh_token);
        return true;
    }

    // --- Authentication Actions ---
    async login(email, password) {
        const data = await this.request('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        this.saveTokens(data.access_token, data.refresh_token);
        return data;
    }

    async register(email, password, fullName) {
        return this.request('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, full_name: fullName })
        });
    }

    async logout() {
        try {
            await this.request('/api/auth/logout', { method: 'POST' });
        } catch (e) {
            console.warn('Logout request failed, cleaning local state anyway', e);
        }
        this.clearTokens();
    }

    async getMe() {
        return this.request('/api/me');
    }

    async updateProfile(fullName) {
        return this.request('/api/profile', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ full_name: fullName })
        });
    }

    // --- Document Actions ---
    async getDocuments() {
        return this.request('/api/documents');
    }

    async getDocumentStatus(docId) {
        return this.request(`/api/documents/${docId}/status`);
    }

    async deleteDocument(docId) {
        return this.request(`/api/documents/${docId}`, { method: 'DELETE' });
    }

    async summarizeDocument(docId, extraIds = []) {
        return this.request(`/api/documents/${docId}/summarize`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ extra_document_ids: extraIds })
        });
    }

    async reindexDocument(docId) {
        return this.request('/api/reindex', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ document_id: docId })
        });
    }

    // --- Contract Actions ---
    async getContracts() {
        return this.request('/api/contracts');
    }

    async uploadContract(title, file) {
        const formData = new FormData();
        formData.append('title', title);
        formData.append('file', file);

        const headers = {};
        if (this.accessToken) {
            headers['Authorization'] = `Bearer ${this.accessToken}`;
        }
        const res = await fetch(`${API_BASE}/api/contracts/`, {
            method: 'POST',
            headers: headers,
            body: formData
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Contract upload failed');
        }
        return res.json();
    }

    async analyzeContract(contractId) {
        return this.request(`/api/contracts/${contractId}/analyze`, { method: 'POST' });
    }

    // --- Conversation Actions ---
    async getConversations() {
        return this.request('/api/conversations');
    }

    async createConversation(title = null, documentScope = null) {
        return this.request('/api/conversations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, document_scope: documentScope })
        });
    }

    async getMessages(convoId) {
        return this.request(`/api/conversations/${convoId}/messages`);
    }

    async deleteConversation(convoId) {
        return this.request(`/api/conversations/${convoId}`, { method: 'DELETE' });
    }

    // Custom fetch call for SSE streaming responses
    async askStream(convoId, question, stream = true, onMeta, onToken, onDone, onError) {
        const url = `${API_BASE}/api/conversations/${convoId}/messages`;
        const headers = {
            'Content-Type': 'application/json',
            'X-Request-ID': Math.random().toString(36).substring(2, 10)
        };
        if (this.accessToken) {
            headers['Authorization'] = `Bearer ${this.accessToken}`;
        }

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ question, stream })
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.error?.message || 'Chat generation request failed');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                let currentEvent = '';
                for (const line of lines) {
                    const cleanLine = line.trim();
                    if (!cleanLine) continue;

                    if (cleanLine.startsWith('event:')) {
                        currentEvent = cleanLine.substring(6).trim();
                    } else if (cleanLine.startsWith('data:')) {
                        const rawData = cleanLine.substring(5).trim();
                        try {
                            const parsed = JSON.parse(rawData);
                            if (currentEvent === 'meta' && onMeta) {
                                onMeta(parsed);
                            } else if (currentEvent === 'token' && onToken) {
                                onToken(parsed.t);
                            } else if (currentEvent === 'done' && onDone) {
                                onDone(parsed);
                            } else if (currentEvent === 'error' && onError) {
                                onError(parsed);
                            }
                        } catch (e) {
                            console.error('Error parsing SSE packet', e, rawData);
                        }
                    }
                }
            }
        } catch (err) {
            if (onError) onError({ message: err.message });
            else console.error('SSE connection error:', err);
        }
    }

    // --- Admin Dashboard Actions ---
    async adminGetUsers(searchQuery = null) {
        let path = '/api/admin/users';
        if (searchQuery) path += `?search=${encodeURIComponent(searchQuery)}`;
        return this.request(path);
    }

    async adminSetUserActive(userId, isActive) {
        return this.request(`/api/admin/users/${userId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: isActive })
        });
    }

    async adminGetStats() {
        return this.request('/api/admin/stats');
    }
}

const api = new ApiClient();
