/* Contract Buddy - Workspace
 * Chat, documents and contract analysis for the signed-in user.
 */

document.addEventListener('DOMContentLoaded', async function () {
    if (!api.accessToken) {
        window.location.href = 'index.html';
        return;
    }

    // ---- state ----
    var currentUser = null;
    var conversations = [];
    var documents = [];
    var contracts = [];
    var activeConvoId = null;
    var activeConvoScope = null;
    var selectedContractId = null;
    var processingDocs = new Set();
    var pollTimer = null;

    // ---- elements ----
    var el = function (id) { return document.getElementById(id); };

    var listConvos = el('conversations-list');
    var btnNewConvo = el('btn-new-convo');
    var userInitials = el('user-avatar-initials');
    var userName = el('user-display-name');
    var userEmail = el('user-display-email');
    var btnLogout = el('btn-logout');

    var convoTitle = el('active-convo-title');
    var convoScopeInfo = el('active-convo-scope-info');
    var chatContainer = el('chat-messages-container');
    var chatTextarea = el('chat-textarea');
    var btnSend = el('btn-send');

    var btnToggleScope = el('btn-toggle-scope');
    var scopeDropdown = el('scope-dropdown-menu');
    var scopeDocsList = el('scope-documents-list');
    var btnClearScope = el('btn-clear-scope');

    var btnOpenDocs = el('btn-open-documents');
    var docsModal = el('documents-modal');
    var dropzone = el('upload-dropzone');
    var fileInput = el('file-input');
    var progressContainer = el('upload-progress-container');
    var uploadedDocsList = el('uploaded-documents-list');

    var citationsDrawer = el('citations-drawer');
    var citationsDrawerBody = el('citations-drawer-body');

    var btnOpenContracts = el('btn-open-contracts');
    var contractsModal = el('contracts-modal');
    var contractUploadForm = el('contract-upload-form');
    var contractTitleInput = el('contract-title-input');
    var contractFileInput = el('contract-file-input');
    var contractsListEl = el('contracts-list');
    var contractAnalysisViewEl = el('contract-analysis-view');

    // ---- helpers ----

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Renders the small subset of markdown the model actually produces.
    // Escaping happens first, so no user or model text can inject HTML.
    function renderAnswer(text) {
        if (!text) return '';
        var out = escapeHtml(text);
        out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/`(.+?)`/g, '<code>$1</code>');
        out = out.replace(/^\s*[-*]\s+(.*)$/gm, '<li>$1</li>');
        out = out.replace(/(<li>[\s\S]*<\/li>)/, '<ul>$1</ul>');
        // Match both [S1] and 【S1】 — models use either.
        out = out.replace(/[[【]\s*S(\d+)\s*[\]】]/g, '<span class="citation-ref">[S$1]</span>');
        out = out.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
        // The line-break pass above also puts <br> between list items, which
        // is invalid inside a <ul>. Strip those out.
        return out
            .replace(/(<\/li>)\s*(?:<br>\s*)+/g, '$1')
            .replace(/(<ul>)\s*(?:<br>\s*)+/g, '$1')
            .replace(/(?:<br>\s*)+(<\/ul>|<li>)/g, '$1');
    }

    // Shows a dash rather than an invented value when a field is absent.
    function orDash(value) {
        if (value === null || value === undefined || value === '') return '—';
        return escapeHtml(value);
    }

    function toast(message, kind) {
        var box = el('toast');
        if (!box) {
            box = document.createElement('div');
            box.id = 'toast';
            document.body.appendChild(box);
        }
        box.className = 'toast show ' + (kind || 'info');
        box.textContent = message;
        clearTimeout(box._timer);
        box._timer = setTimeout(function () { box.className = 'toast'; }, 4000);
    }

    function riskClass(score) {
        if (score === null || score === undefined) return 'low';
        if (score > 50) return 'high';
        if (score > 25) return 'medium';
        return 'low';
    }

    // ---- boot ----

    try {
        currentUser = await api.getMe();
        userName.textContent = currentUser.full_name;
        userEmail.textContent = currentUser.email;
        userInitials.textContent = currentUser.full_name
            .split(' ')
            .map(function (n) { return n[0]; })
            .join('')
            .substring(0, 2)
            .toUpperCase();

        await loadConversations();
        await loadDocuments();
    } catch (err) {
        console.error('Could not load profile:', err);
        api.clearTokens();
        window.location.href = 'index.html';
        return;
    }

    btnLogout.addEventListener('click', async function () {
        if (!confirm('Sign out of Contract Buddy?')) return;
        await api.logout();
        window.location.href = 'index.html';
    });

    // ---- conversations ----

    async function loadConversations() {
        try {
            conversations = await api.getConversations();
            renderConversations();
        } catch (err) {
            console.error('Could not load conversations:', err);
        }
    }

    function renderConversations() {
        listConvos.innerHTML = '';

        if (conversations.length === 0) {
            listConvos.innerHTML = '<div class="convo-empty-state">No conversations yet.</div>';
            return;
        }

        conversations.forEach(function (convo) {
            var item = document.createElement('div');
            item.className = 'convo-item' + (convo.id === activeConvoId ? ' active' : '');
            item.dataset.id = convo.id;
            item.innerHTML =
                '<div class="convo-item-left">' +
                '<i class="fa-regular fa-comment"></i>' +
                '<span class="convo-item-title">' + escapeHtml(convo.title) + '</span>' +
                '</div>' +
                '<button class="btn-delete-convo" title="Delete conversation">' +
                '<i class="fa-regular fa-trash-can"></i></button>';

            item.addEventListener('click', function (e) {
                if (e.target.closest('.btn-delete-convo')) return;
                selectConversation(convo.id);
            });

            item.querySelector('.btn-delete-convo').addEventListener('click', async function (e) {
                e.stopPropagation();
                if (!confirm('Delete "' + convo.title + '"?')) return;
                try {
                    await api.deleteConversation(convo.id);
                    if (activeConvoId === convo.id) resetChatPane();
                    await loadConversations();
                    toast('Conversation deleted.', 'success');
                } catch (err) {
                    toast(err.message || 'Could not delete conversation.', 'error');
                }
            });

            listConvos.appendChild(item);
        });
    }

    function resetChatPane() {
        activeConvoId = null;
        activeConvoScope = null;
        convoTitle.textContent = 'Select or start a chat';
        convoScopeInfo.textContent = 'Searching all documents';
        chatContainer.innerHTML =
            '<div class="chat-empty" id="chat-empty-state">' +
            '<i class="fa-regular fa-comments"></i>' +
            '<h3>Welcome to Contract Buddy</h3>' +
            '<p>Upload a PDF or DOCX, then ask questions about it. ' +
            'Every answer cites the page it came from.</p></div>';
        chatTextarea.disabled = true;
        btnSend.disabled = true;
    }

    btnNewConvo.addEventListener('click', async function () {
        try {
            var convo = await api.createConversation('New conversation', null);
            await loadConversations();
            await selectConversation(convo.id);
        } catch (err) {
            toast(err.message || 'Could not start a conversation.', 'error');
        }
    });

    async function selectConversation(convoId) {
        var convo = conversations.find(function (c) { return c.id === convoId; });
        if (!convo) return;

        activeConvoId = convoId;
        activeConvoScope = convo.document_scope;
        convoTitle.textContent = convo.title;
        updateScopeLabel();
        renderScopeList();

        chatTextarea.disabled = false;
        btnSend.disabled = false;
        chatTextarea.focus();

        document.querySelectorAll('.convo-item').forEach(function (node) {
            node.classList.toggle('active', node.dataset.id === convoId);
        });

        chatContainer.innerHTML =
            '<div class="chat-empty"><i class="fa-solid fa-spinner fa-spin"></i>' +
            '<p>Loading messages…</p></div>';
        try {
            renderMessages(await api.getMessages(convoId));
        } catch (err) {
            chatContainer.innerHTML =
                '<div class="chat-empty"><i class="fa-solid fa-triangle-exclamation"></i>' +
                '<p>Could not load this conversation.</p></div>';
        }
    }

    function renderMessages(messages) {
        if (messages.length === 0) {
            chatContainer.innerHTML =
                '<div class="chat-empty" id="chat-empty-state">' +
                '<i class="fa-regular fa-comments"></i><h3>Ask your first question</h3>' +
                '<p>Try “What are the payment terms?” or “When can this be terminated?”</p></div>';
            return;
        }
        chatContainer.innerHTML = '';
        messages.forEach(function (msg) {
            addMessage(msg.role, msg.content, msg.citations);
        });
        scrollToBottom();
    }

    function addMessage(role, content, citations) {
        var empty = el('chat-empty-state');
        if (empty) empty.remove();

        var wrapper = document.createElement('div');
        wrapper.className = 'message ' + role;

        var citationsHtml = '';
        if (role === 'assistant' && citations && citations.length > 0) {
            citationsHtml = '<div class="citations-container">';
            citations.forEach(function (cit) {
                citationsHtml +=
                    '<button class="citation-chip"' +
                    ' data-marker="' + escapeHtml(cit.marker) + '"' +
                    ' data-doc-id="' + escapeHtml(cit.document_id) + '"' +
                    ' data-filename="' + escapeHtml(cit.filename) + '"' +
                    ' data-page="' + escapeHtml(cit.page || '') + '"' +
                    ' data-snippet="' + escapeHtml(cit.snippet) + '">' +
                    '<i class="fa-solid fa-quote-left"></i><span>[' +
                    escapeHtml(cit.marker) + '] ' + escapeHtml(cit.filename) +
                    (cit.page ? ' · p.' + escapeHtml(cit.page) : '') +
                    '</span></button>';
            });
            citationsHtml += '</div>';
        }

        wrapper.innerHTML =
            '<div class="message-avatar"><i class="' +
            (role === 'user' ? 'fa-regular fa-user' : 'fa-solid fa-robot') +
            '"></i></div>' +
            '<div class="message-body">' +
            '<div class="message-bubble">' + renderAnswer(content) + '</div>' +
            citationsHtml +
            '</div>';

        chatContainer.appendChild(wrapper);
        scrollToBottom();
        return wrapper;
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // ---- asking ----

    async function sendQuestion() {
        var question = chatTextarea.value.trim();
        if (!question || !activeConvoId) return;

        addMessage('user', question, null);
        chatTextarea.value = '';
        chatTextarea.style.height = 'auto';
        setComposerEnabled(false);

        var pending = document.createElement('div');
        pending.className = 'message assistant';
        pending.innerHTML =
            '<div class="message-avatar"><i class="fa-solid fa-robot"></i></div>' +
            '<div class="message-body"><div class="message-bubble">' +
            '<div class="streaming-indicator"><span></span><span></span><span></span></div>' +
            '</div></div>';
        chatContainer.appendChild(pending);
        scrollToBottom();

        var bubble = pending.querySelector('.message-bubble');
        var answer = '';
        var citations = [];

        await api.askStream(
            activeConvoId,
            question,
            true,
            function onMeta(meta) {
                citations = meta.citations || [];
            },
            function onToken(token) {
                if (bubble.querySelector('.streaming-indicator')) bubble.innerHTML = '';
                answer += token;
                bubble.innerHTML = renderAnswer(answer);
                scrollToBottom();
            },
            async function onDone(done) {
                pending.remove();
                addMessage('assistant', answer, done.citations || citations);
                setComposerEnabled(true);
                await loadConversations();
                // Keep the active row highlighted after the list re-renders.
                document.querySelectorAll('.convo-item').forEach(function (node) {
                    node.classList.toggle('active', node.dataset.id === activeConvoId);
                });
                var convo = conversations.find(function (c) { return c.id === activeConvoId; });
                if (convo) convoTitle.textContent = convo.title;
            },
            function onError(err) {
                bubble.innerHTML =
                    '<span class="error-text"><i class="fa-solid fa-circle-exclamation"></i> ' +
                    escapeHtml(err.message || 'Generation failed. Please try again.') +
                    '</span>';
                setComposerEnabled(true);
            }
        );
    }

    function setComposerEnabled(enabled) {
        chatTextarea.disabled = !enabled;
        btnSend.disabled = !enabled;
        if (enabled) chatTextarea.focus();
    }

    btnSend.addEventListener('click', sendQuestion);

    chatTextarea.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendQuestion();
        }
    });

    chatTextarea.addEventListener('input', function () {
        chatTextarea.style.height = 'auto';
        chatTextarea.style.height = Math.min(chatTextarea.scrollHeight, 180) + 'px';
    });

    // ---- citations drawer ----

    chatContainer.addEventListener('click', function (e) {
        var chip = e.target.closest('.citation-chip');
        if (!chip) return;

        citationsDrawerBody.innerHTML =
            '<div class="citation-card">' +
            '<div class="citation-card-header"><i class="fa-regular fa-file-lines"></i>' +
            '<span>[' + escapeHtml(chip.dataset.marker) + '] ' +
            escapeHtml(chip.dataset.filename) + '</span></div>' +
            '<div class="citation-card-meta">Page ' +
            (chip.dataset.page || '—') + '</div>' +
            '<blockquote class="citation-snippet">' +
            escapeHtml(chip.dataset.snippet) + '</blockquote>' +
            '</div>' +
            '<button class="btn btn-secondary btn-block" id="btn-drawer-summarize">' +
            '<i class="fa-solid fa-wand-magic-sparkles"></i> Summarize this document</button>';

        el('btn-drawer-summarize').addEventListener('click', function () {
            citationsDrawer.classList.remove('open');
            summarizeDocument(chip.dataset.docId);
        });

        citationsDrawer.classList.add('open');
    });

    el('btn-close-drawer').addEventListener('click', function () {
        citationsDrawer.classList.remove('open');
    });

    // ---- document scope ----

    btnToggleScope.addEventListener('click', function (e) {
        e.stopPropagation();
        scopeDropdown.classList.toggle('hidden');
    });

    document.addEventListener('click', function (e) {
        if (!scopeDropdown.classList.contains('hidden') &&
            !e.target.closest('.scope-selector-wrapper')) {
            scopeDropdown.classList.add('hidden');
        }
    });

    function renderScopeList() {
        var ready = documents.filter(function (d) { return d.status === 'ready'; });

        if (ready.length === 0) {
            scopeDocsList.innerHTML =
                '<div class="empty-state">No indexed documents yet.</div>';
            return;
        }

        scopeDocsList.innerHTML = '';
        ready.forEach(function (doc) {
            var checked = activeConvoScope && activeConvoScope.indexOf(doc.id) !== -1;
            var label = document.createElement('label');
            label.className = 'scope-item';
            label.innerHTML =
                '<input type="checkbox" data-id="' + doc.id + '"' +
                (checked ? ' checked' : '') + '>' +
                '<span title="' + escapeHtml(doc.filename) + '">' +
                escapeHtml(doc.filename) + '</span>';
            label.querySelector('input').addEventListener('change', onScopeChanged);
            scopeDocsList.appendChild(label);
        });
    }

    async function onScopeChanged(e) {
        if (!activeConvoId) {
            toast('Start a chat before choosing which documents to search.', 'info');
            e.target.checked = false;
            return;
        }

        var selected = Array.from(scopeDocsList.querySelectorAll('input:checked'))
            .map(function (input) { return input.dataset.id; });

        try {
            // PATCH the existing conversation. Creating a new one here (as an
            // earlier version did) silently duplicated the chat on every click.
            var updated = await api.updateConversation(activeConvoId, {
                document_scope: selected
            });
            activeConvoScope = updated.document_scope;
            var convo = conversations.find(function (c) { return c.id === activeConvoId; });
            if (convo) convo.document_scope = updated.document_scope;
            updateScopeLabel();
        } catch (err) {
            toast(err.message || 'Could not update the document filter.', 'error');
        }
    }

    btnClearScope.addEventListener('click', async function () {
        if (!activeConvoId) return;
        scopeDocsList.querySelectorAll('input:checked').forEach(function (input) {
            input.checked = false;
        });
        try {
            var updated = await api.updateConversation(activeConvoId, { document_scope: [] });
            activeConvoScope = updated.document_scope;
            var convo = conversations.find(function (c) { return c.id === activeConvoId; });
            if (convo) convo.document_scope = null;
            updateScopeLabel();
        } catch (err) {
            toast(err.message || 'Could not clear the filter.', 'error');
        }
    });

    function updateScopeLabel() {
        if (!activeConvoScope || activeConvoScope.length === 0) {
            convoScopeInfo.textContent = 'Searching all documents';
        } else {
            convoScopeInfo.textContent =
                'Searching ' + activeConvoScope.length +
                (activeConvoScope.length === 1 ? ' document' : ' documents');
        }
    }

    // ---- documents ----

    btnOpenDocs.addEventListener('click', function () {
        docsModal.classList.remove('hidden');
        renderDocuments();
    });

    el('btn-close-documents-modal').addEventListener('click', function () {
        docsModal.classList.add('hidden');
    });

    async function loadDocuments() {
        try {
            documents = await api.getDocuments();
            renderScopeList();

            documents.forEach(function (doc) {
                if (doc.status === 'processing') processingDocs.add(doc.id);
            });
            if (processingDocs.size > 0) startPolling();
        } catch (err) {
            console.error('Could not load documents:', err);
        }
    }

    function renderDocuments() {
        if (documents.length === 0) {
            uploadedDocsList.innerHTML =
                '<div class="empty-state">No documents yet. Drop a PDF or DOCX above.</div>';
            return;
        }

        uploadedDocsList.innerHTML = '';
        documents.forEach(function (doc) {
            var row = document.createElement('div');
            row.className = 'doc-row';

            var sizeMb = (doc.file_size_bytes / (1024 * 1024)).toFixed(2);
            var icon = doc.file_type === 'docx'
                ? 'fa-regular fa-file-word'
                : 'fa-regular fa-file-pdf';
            var meta = sizeMb + ' MB';
            if (doc.page_count) meta += ' · ' + doc.page_count + ' pages';
            if (doc.chunk_count) meta += ' · ' + doc.chunk_count + ' chunks';

            row.innerHTML =
                '<div class="doc-row-left">' +
                '<i class="' + icon + ' doc-icon"></i>' +
                '<div><div class="doc-name" title="' + escapeHtml(doc.filename) + '">' +
                escapeHtml(doc.filename) + '</div>' +
                '<div class="doc-meta">' + meta + '</div></div></div>' +
                '<div class="doc-row-actions">' +
                '<span class="doc-status-badge ' + doc.status + '">' + doc.status + '</span>' +
                '<button class="doc-btn btn-summarize" title="Summarize"' +
                (doc.status !== 'ready' ? ' disabled' : '') +
                '><i class="fa-solid fa-wand-magic-sparkles"></i></button>' +
                '<button class="doc-btn delete" title="Delete">' +
                '<i class="fa-regular fa-trash-can"></i></button></div>';

            if (doc.status === 'failed' && doc.error_reason) {
                var reason = document.createElement('div');
                reason.className = 'doc-error';
                reason.textContent = doc.error_reason;
                row.appendChild(reason);
            }

            row.querySelector('.btn-summarize').addEventListener('click', function () {
                docsModal.classList.add('hidden');
                summarizeDocument(doc.id);
            });

            row.querySelector('.delete').addEventListener('click', async function () {
                if (!confirm('Delete "' + doc.filename + '" and everything indexed from it?')) return;
                try {
                    await api.deleteDocument(doc.id);
                    await loadDocuments();
                    renderDocuments();
                    toast('Document deleted.', 'success');
                } catch (err) {
                    toast(err.message || 'Could not delete the document.', 'error');
                }
            });

            uploadedDocsList.appendChild(row);
        });
    }

    async function summarizeDocument(docId) {
        if (!activeConvoId) {
            toast('Open a chat first — the summary is posted into it.', 'info');
            return;
        }

        var placeholder = addMessage('assistant', 'Summarizing…', null);
        var bubble = placeholder.querySelector('.message-bubble');

        try {
            var data = await api.summarizeDocument(docId);
            bubble.innerHTML = renderAnswer(data.summary);

            var stats = data.stats || {};
            var chunks = stats.chunks || 0;
            var meta = document.createElement('div');
            meta.className = 'message-meta';
            meta.innerHTML =
                '<span>' + chunks + (chunks === 1 ? ' chunk' : ' chunks') + '</span>' +
                '<span>' + escapeHtml(stats.provider || 'local') + '</span>' +
                '<span>$' + (stats.estimated_cost_usd || 0).toFixed(6) + '</span>';
            placeholder.querySelector('.message-body').appendChild(meta);
        } catch (err) {
            bubble.innerHTML =
                '<span class="error-text"><i class="fa-solid fa-circle-exclamation"></i> ' +
                escapeHtml(err.message || 'Summary failed.') + '</span>';
        }
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(async function () {
            if (processingDocs.size === 0) {
                clearInterval(pollTimer);
                pollTimer = null;
                return;
            }
            for (var docId of Array.from(processingDocs)) {
                try {
                    var res = await api.getDocumentStatus(docId);
                    if (res.status !== 'processing') {
                        processingDocs.delete(docId);
                        await loadDocuments();
                        if (!docsModal.classList.contains('hidden')) renderDocuments();
                        toast(
                            res.status === 'ready'
                                ? 'Document indexed and ready to query.'
                                : 'Document failed: ' + (res.error_reason || 'unknown error'),
                            res.status === 'ready' ? 'success' : 'error'
                        );
                    }
                } catch (err) {
                    processingDocs.delete(docId);
                }
            }
        }, 2500);
    }

    // ---- uploads ----

    dropzone.addEventListener('click', function () { fileInput.click(); });

    dropzone.addEventListener('dragover', function (e) {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', function () {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', function (e) {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        uploadFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener('change', function () {
        uploadFiles(fileInput.files);
        fileInput.value = '';
    });

    function uploadFiles(files) {
        Array.from(files).forEach(function (file) {
            var ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
            if (ext !== '.pdf' && ext !== '.docx') {
                toast(ext + ' files are not supported — use PDF or DOCX.', 'error');
                return;
            }
            uploadOne(file);
        });
    }

    function uploadOne(file) {
        var item = document.createElement('div');
        item.className = 'progress-item';
        item.innerHTML =
            '<div class="progress-item-header">' +
            '<span class="progress-item-name">' + escapeHtml(file.name) + '</span>' +
            '<span class="progress-percent">0%</span></div>' +
            '<div class="progress-bar-container"><div class="progress-bar"></div></div>';
        progressContainer.appendChild(item);

        var bar = item.querySelector('.progress-bar');
        var percent = item.querySelector('.progress-percent');

        // XHR rather than fetch: it reports upload progress, fetch does not.
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + '/api/documents', true);
        if (api.accessToken) {
            xhr.setRequestHeader('Authorization', 'Bearer ' + api.accessToken);
        }

        xhr.upload.addEventListener('progress', function (e) {
            if (!e.lengthComputable) return;
            var value = Math.round((e.loaded / e.total) * 100);
            bar.style.width = value + '%';
            percent.textContent = value + '%';
        });

        xhr.addEventListener('load', async function () {
            if (xhr.status >= 200 && xhr.status < 300) {
                bar.style.width = '100%';
                bar.classList.add('success');
                percent.textContent = 'Indexing…';
                setTimeout(function () { item.remove(); }, 3000);

                try {
                    processingDocs.add(JSON.parse(xhr.responseText).id);
                } catch (e) { /* the poll below still picks it up */ }

                await loadDocuments();
                renderDocuments();
                startPolling();
            } else {
                var message = 'Upload failed';
                try {
                    var parsed = JSON.parse(xhr.responseText);
                    message = (parsed.error && parsed.error.message) || parsed.detail || message;
                } catch (e) { /* keep the default message */ }
                bar.classList.add('failed');
                percent.textContent = 'Failed';
                item.title = message;
                toast(message, 'error');
            }
        });

        xhr.addEventListener('error', function () {
            bar.classList.add('failed');
            percent.textContent = 'Network error';
            toast('Upload failed — is the backend running?', 'error');
        });

        var form = new FormData();
        form.append('file', file);
        xhr.send(form);
    }

    // ---- contracts ----

    btnOpenContracts.addEventListener('click', async function () {
        contractsModal.classList.remove('hidden');
        await loadContracts();
    });

    el('btn-close-contracts-modal').addEventListener('click', function () {
        contractsModal.classList.add('hidden');
    });

    contractUploadForm.addEventListener('submit', async function (e) {
        e.preventDefault();
        var title = contractTitleInput.value.trim();
        var file = contractFileInput.files[0];
        if (!title || !file) {
            toast('Add a title and pick a file first.', 'info');
            return;
        }

        var button = el('btn-upload-contract');
        var original = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing…';

        try {
            var contract = await api.uploadContract(title, file);
            contractTitleInput.value = '';
            contractFileInput.value = '';
            await loadContracts();
            selectedContractId = contract.id;
            renderContractAnalysis(contract);
            toast('Contract analyzed.', 'success');
        } catch (err) {
            toast(err.message || 'Contract upload failed.', 'error');
        } finally {
            button.disabled = false;
            button.innerHTML = original;
        }
    });

    async function loadContracts() {
        try {
            contracts = await api.getContracts();
            renderContractsList();
        } catch (err) {
            contractsListEl.innerHTML =
                '<div class="empty-state">Could not load contracts.</div>';
        }
    }

    function renderContractsList() {
        if (contracts.length === 0) {
            contractsListEl.innerHTML =
                '<div class="empty-state">No contracts yet. Upload one above.</div>';
            return;
        }

        contractsListEl.innerHTML = '';
        contracts.forEach(function (contract) {
            var card = document.createElement('div');
            card.className = 'contract-item-card' +
                (contract.id === selectedContractId ? ' active' : '');
            card.innerHTML =
                '<div class="contract-item-title">' + escapeHtml(contract.title) + '</div>' +
                '<div class="contract-item-meta">' +
                '<span>' + orDash(contract.vendor) + '</span>' +
                '<span class="badge-risk ' + riskClass(contract.risk_score) + '">' +
                (contract.risk_score === null ? '—' : contract.risk_score + '% risk') +
                '</span></div>';

            card.addEventListener('click', function () {
                selectedContractId = contract.id;
                renderContractsList();
                renderContractAnalysis(contract);
            });

            contractsListEl.appendChild(card);
        });
    }

    function tagList(items, extraClass) {
        if (!items || items.length === 0) {
            return '<span class="muted">None found</span>';
        }
        return items.map(function (item) {
            return '<span class="tag-badge ' + (extraClass || '') + '">' +
                escapeHtml(item) + '</span>';
        }).join('');
    }

    function renderContractAnalysis(c) {
        selectedContractId = c.id;

        var sourceNote = c.analysis_source === 'llm'
            ? '<span class="source-badge llm" title="Extracted by the language model">' +
              'LLM analysis</span>'
            : '<span class="source-badge rules" title="No LLM configured — derived from ' +
              'keyword rules over the contract text">Rule-based analysis</span>';

        var value = c.value === null || c.value === undefined
            ? '—'
            : (c.currency ? c.currency + ' ' : '') + c.value.toLocaleString();

        contractAnalysisViewEl.innerHTML =
            '<div class="analysis-header">' +
            '<div><h3>' + escapeHtml(c.title) + '</h3>' +
            '<span class="analysis-subtitle">' + escapeHtml(c.filename) + ' · ' +
            sourceNote + '</span></div>' +
            '<button class="btn btn-secondary btn-sm" id="btn-reanalyze">' +
            '<i class="fa-solid fa-rotate-right"></i> Re-analyze</button>' +
            '</div>' +

            '<div class="score-row">' +
            '<div class="score-card"><h5>Clause coverage</h5>' +
            '<div class="score-number health">' + orDash(c.health_score) + '</div></div>' +
            '<div class="score-card"><h5>Risk exposure</h5>' +
            '<div class="score-number risk ' + riskClass(c.risk_score) + '">' +
            orDash(c.risk_score) + '</div></div>' +
            '</div>' +

            '<div class="analysis-section"><h5>Details</h5>' +
            '<div class="metadata-grid">' +
            metaField('Contract number', c.contract_number) +
            metaField('Vendor', c.vendor) +
            metaField('Client', c.client) +
            metaField('Value', value, true) +
            metaField('Effective', c.effective_date) +
            metaField('Expires', c.expiry_date) +
            metaField('Priority', c.priority) +
            metaField('Payment terms', c.payment_terms) +
            '</div></div>' +

            '<div class="analysis-section"><h5>Tags</h5>' +
            '<div class="tag-list">' + tagList(c.auto_tags) + '</div></div>' +

            '<div class="analysis-section"><h5>Missing clauses</h5>' +
            (c.missing_clauses.length > 0
                ? c.missing_clauses.map(function (clause) {
                    return '<div class="clause-warning-item">' +
                        '<i class="fa-solid fa-circle-exclamation"></i> ' +
                        escapeHtml(clause) + '</div>';
                }).join('')
                : '<div class="clause-ok"><i class="fa-solid fa-circle-check"></i> ' +
                  'All expected clauses were found.</div>') +
            '</div>' +

            '<div class="analysis-section"><h5>Obligations</h5>' +
            (c.obligations.length > 0
                ? c.obligations.map(function (item) {
                    return '<div class="obligation-item"><i class="fa-solid fa-check"></i> ' +
                        escapeHtml(item) + '</div>';
                }).join('')
                : '<span class="muted">None found</span>') +
            '</div>' +

            '<div class="analysis-section"><h5>Parties</h5>' +
            '<div class="tag-list">' + tagList(c.parties, 'blue') + '</div></div>' +

            '<div class="analysis-section"><h5>Suggested actions</h5>' +
            (c.action_items.length > 0
                ? c.action_items.map(function (item) {
                    return '<div class="action-item"><i class="fa-regular fa-clock"></i> ' +
                        escapeHtml(item) + '</div>';
                }).join('')
                : '<span class="muted">Nothing outstanding</span>') +
            '</div>' +

            '<div class="analysis-section"><h5>Clauses present</h5>' +
            '<div class="tag-list">' + tagList(c.compliance_flags, 'green') + '</div></div>';

        el('btn-reanalyze').addEventListener('click', async function () {
            var button = el('btn-reanalyze');
            button.disabled = true;
            button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing…';
            try {
                var updated = await api.analyzeContract(c.id);
                await loadContracts();
                renderContractAnalysis(updated);
                toast('Analysis refreshed.', 'success');
            } catch (err) {
                toast(err.message || 'Re-analysis failed.', 'error');
                button.disabled = false;
                button.innerHTML = '<i class="fa-solid fa-rotate-right"></i> Re-analyze';
            }
        });
    }

    function metaField(label, value, preEscaped) {
        return '<div class="meta-field"><label>' + label + '</label><span>' +
            (preEscaped ? value : orDash(value)) + '</span></div>';
    }

    // ---- misc ----

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        docsModal.classList.add('hidden');
        contractsModal.classList.add('hidden');
        citationsDrawer.classList.remove('open');
        scopeDropdown.classList.add('hidden');
    });

    [docsModal, contractsModal].forEach(function (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal) modal.classList.add('hidden');
        });
    });

    resetChatPane();
    if (conversations.length > 0) await selectConversation(conversations[0].id);
});
