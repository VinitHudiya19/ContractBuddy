/* Contract Buddy - API Client
 * Handles all HTTP requests to the backend REST API.
 * Manages JWT tokens, auto-refresh, and SSE streaming.
 */

var API_BASE = (window.location.protocol === 'file:' || !window.location.port || window.location.port !== '8000')
    ? 'http://127.0.0.1:8000'
    : window.location.origin;

class ApiClient {
    constructor() {
        // load tokens from local storage on startup
        this.accessToken = localStorage.getItem('access_token');
        this.refreshToken = localStorage.getItem('refresh_token');
    }

    saveTokens(access, refresh) {
        this.accessToken = access;
        this.refreshToken = refresh;
        if (access) localStorage.setItem('access_token', access);
        if (refresh) localStorage.setItem('refresh_token', refresh);
    }

    clearTokens() {
        this.accessToken = null;
        this.refreshToken = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }

    // generic fetch with auth header and auto-retry on 401
    async request(path, options) {
        options = options || {};
        options.headers = options.headers || {};

        if (this.accessToken) {
            options.headers['Authorization'] = 'Bearer ' + this.accessToken;
        }

        // default to JSON content type if body is a string and not already set
        if (options.body && typeof options.body === 'string' && !options.headers['Content-Type']) {
            options.headers['Content-Type'] = 'application/json';
        }

        var res = await fetch(API_BASE + path, options);

        // auto refresh on 401 ONLY for protected routes (not auth login/register/refresh)
        var isAuthPath = path.indexOf('/api/auth/login') !== -1 || 
                         path.indexOf('/api/auth/register') !== -1 || 
                         path.indexOf('/api/auth/refresh') !== -1;

        if (res.status === 401 && !isAuthPath && this.refreshToken) {
            var refreshed = await this.rotateTokens();
            if (refreshed) {
                options.headers['Authorization'] = 'Bearer ' + this.accessToken;
                res = await fetch(API_BASE + path, options);
            } else {
                this.clearTokens();
                window.location.href = 'index.html';
                throw new Error('Session expired');
            }
        }

        if (!res.ok) {
            var errorMsg = 'Request failed (status ' + res.status + ')';
            try {
                var errData = await res.json();
                if (errData.detail) {
                    errorMsg = typeof errData.detail === 'string'
                        ? errData.detail
                        : JSON.stringify(errData.detail);
                } else if (errData.error && errData.error.message) {
                    errorMsg = errData.error.message;
                } else if (errData.message) {
                    errorMsg = errData.message;
                }
            } catch (e) { /* response was not json */ }
            var error = new Error(errorMsg);
            error.status = res.status;
            throw error;
        }

        if (res.status === 204) return null;
        return res.json();
    }

    // refresh token rotation
    async rotateTokens() {
        if (!this.refreshToken) return false;
        try {
            var res = await fetch(API_BASE + '/api/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: this.refreshToken })
            });
            if (!res.ok) {
                this.clearTokens();
                return false;
            }
            var data = await res.json();
            this.saveTokens(data.access_token, data.refresh_token);
            return true;
        } catch (e) {
            this.clearTokens();
            return false;
        }
    }

    // --- Auth endpoints ---

    async login(email, password) {
        // clear old tokens before trying to log in
        this.clearTokens();
        var data = await this.request('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, password: password })
        });
        this.saveTokens(data.access_token, data.refresh_token);
        return data;
    }

    async register(email, password, fullName) {
        return this.request('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, password: password, full_name: fullName })
        });
    }

    async logout() {
        try {
            await this.request('/api/auth/logout', { method: 'POST' });
        } catch (e) {
            // ignore
        }
        this.clearTokens();
    }

    async getMe() {
        return this.request('/api/me');
    }

    // The list endpoints are capped server-side. The sidebars show everything,
    // so walk the pages here; a short page means we reached the end. The page
    // ceiling is a guard against looping forever if a page ever comes back full
    // but unchanged.
    async _fetchAllPages(path, pageSize = 100, maxPages = 50) {
        const items = [];
        for (let page = 0; page < maxPages; page++) {
            const batch = await this.request(
                path + '?limit=' + pageSize + '&offset=' + page * pageSize
            );
            if (!Array.isArray(batch)) return batch;
            items.push(...batch);
            if (batch.length < pageSize) break;
        }
        return items;
    }

    // --- Document endpoints ---

    async getDocuments() {
        return this._fetchAllPages('/api/documents');
    }

    async getDocumentStatus(docId) {
        return this.request('/api/documents/' + docId + '/status');
    }

    async deleteDocument(docId) {
        return this.request('/api/documents/' + docId, { method: 'DELETE' });
    }

    async summarizeDocument(docId, extraIds) {
        return this.request('/api/documents/' + docId + '/summarize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ extra_document_ids: extraIds || [] })
        });
    }

    // --- Conversation endpoints ---

    async getConversations() {
        return this._fetchAllPages('/api/conversations');
    }

    async createConversation(title, documentScope) {
        return this.request('/api/conversations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title, document_scope: documentScope || null })
        });
    }

    async getMessages(convoId) {
        return this.request('/api/conversations/' + convoId + '/messages');
    }

    async deleteConversation(convoId) {
        return this.request('/api/conversations/' + convoId, { method: 'DELETE' });
    }

    // update title and/or which documents this conversation searches
    async updateConversation(convoId, changes) {
        return this.request('/api/conversations/' + convoId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(changes)
        });
    }

    // --- Contract endpoints ---

    async getContracts() {
        return this.request('/api/contracts');
    }

    async uploadContract(title, file) {
        var form = new FormData();
        form.append('title', title);
        form.append('file', file);
        // no Content-Type header: the browser sets the multipart boundary
        return this.request('/api/contracts', { method: 'POST', body: form });
    }

    async analyzeContract(contractId) {
        return this.request('/api/contracts/' + contractId + '/analyze', {
            method: 'POST'
        });
    }

    async deleteContract(contractId) {
        return this.request('/api/contracts/' + contractId, { method: 'DELETE' });
    }

    async getHealth() {
        return this.request('/health');
    }

    // SSE streaming for chat - backend sends event: + data: format
    async askStream(convoId, question, stream, onMeta, onToken, onDone, onError) {
        var url = API_BASE + '/api/conversations/' + convoId + '/messages';
        var headers = {
            'Content-Type': 'application/json'
        };
        if (this.accessToken) {
            headers['Authorization'] = 'Bearer ' + this.accessToken;
        }

        try {
            var response = await fetch(url, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ question: question, stream: stream })
            });

            if (!response.ok) {
                var errMsg = 'Chat request failed';
                try {
                    var errData = await response.json();
                    if (errData.detail) errMsg = errData.detail;
                    else if (errData.error && errData.error.message) errMsg = errData.error.message;
                } catch (e) {}
                throw new Error(errMsg);
            }

            var reader = response.body.getReader();
            var decoder = new TextDecoder('utf-8');
            var buffer = '';
            var currentEvent = '';

            while (true) {
                var result = await reader.read();
                if (result.done) break;

                buffer += decoder.decode(result.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop(); // keep the partial last line

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line) continue;

                    if (line.indexOf('event:') === 0) {
                        currentEvent = line.substring(6).trim();
                    } else if (line.indexOf('data:') === 0) {
                        var rawData = line.substring(5).trim();
                        try {
                            var parsed = JSON.parse(rawData);
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
                            // skip unparseable lines
                        }
                    }
                }
            }
        } catch (err) {
            if (onError) onError({ message: err.message });
        }
    }

}

var api = new ApiClient();
