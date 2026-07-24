/* 
 * DocuIntel - Main App Workspace Logic
 * Controls document uploads, chat SSE streams, citation drawer, and scoping filters.
 * Simple, functional JS with student comments.
 */

document.addEventListener('DOMContentLoaded', async () => {
    // Redirect to login page if no auth tokens are present
    if (!api.accessToken) {
        window.location.href = 'index.html';
        return;
    }

    // --- State variables ---
    let currentUser = null;
    let conversations = [];
    let activeConvoId = null;
    let activeConvoScope = null; // List of UUIDs or null
    let documents = [];
    let processingDocs = new Set();
    let pollInterval = null;

    // --- DOM Elements ---
    const listConvos = document.getElementById('conversations-list');
    const btnNewConvo = document.getElementById('btn-new-convo');
    const userInitials = document.getElementById('user-avatar-initials');
    const userName = document.getElementById('user-display-name');
    const userRole = document.getElementById('user-display-role');
    const btnAdminPanel = document.getElementById('btn-admin-panel');
    const btnLogout = document.getElementById('btn-logout');
    
    const convoTitle = document.getElementById('active-convo-title');
    const convoScopeInfo = document.getElementById('active-convo-scope-info');
    const chatContainer = document.getElementById('chat-messages-container');
    const chatTextarea = document.getElementById('chat-textarea');
    const btnSend = document.getElementById('btn-send');

    const btnToggleScope = document.getElementById('btn-toggle-scope');
    const scopeDropdown = document.getElementById('scope-dropdown-menu');
    const scopeDocsList = document.getElementById('scope-documents-list');
    const btnClearScope = document.getElementById('btn-clear-scope');

    const btnOpenDocs = document.getElementById('btn-open-documents');
    const docsModal = document.getElementById('documents-modal');
    const btnCloseDocsModal = document.getElementById('btn-close-documents-modal');
    const dropzone = document.getElementById('upload-dropzone');
    const fileInput = document.getElementById('file-input');
    const progressContainer = document.getElementById('upload-progress-container');
    const uploadedDocsList = document.getElementById('uploaded-documents-list');

    const citationsDrawer = document.getElementById('citations-drawer');
    const citationsDrawerBody = document.getElementById('citations-drawer-body');
    const btnCloseDrawer = document.getElementById('btn-close-drawer');

    // --- 1. Boot up: Load profile and conversations ---
    try {
        currentUser = await api.getMe();
        userName.textContent = currentUser.full_name;
        userRole.textContent = currentUser.role === 'admin' ? 'Administrator' : 'User';
        userInitials.textContent = currentUser.full_name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

        // Show admin button if role is admin
        if (currentUser.role === 'admin') {
            btnAdminPanel.classList.remove('hidden');
            btnAdminPanel.addEventListener('click', () => {
                window.location.href = 'admin.html';
            });
        }

        await loadConversations();
        await loadDocuments();
    } catch (err) {
        console.error('Failed to load profile context:', err);
        api.clearTokens();
        window.location.href = 'index.html';
    }

    // --- 2. Authentication handlers ---
    btnLogout.addEventListener('click', async () => {
        if (confirm('Are you sure you want to sign out?')) {
            await api.logout();
            window.location.href = 'index.html';
        }
    });

    // --- 3. Conversations CRUD ---
    async function loadConversations() {
        try {
            conversations = await api.getConversations();
            renderConversationsList();
        } catch (err) {
            console.error('Error fetching conversations:', err);
        }
    }

    function renderConversationsList() {
        if (conversations.length === 0) {
            listConvos.innerHTML = '<div class="convo-empty-state">No conversations yet.</div>';
            return;
        }

        listConvos.innerHTML = '';
        const list = document.createElement('div');
        list.className = 'convo-list';

        conversations.forEach(convo => {
            const item = document.createElement('div');
            item.className = `convo-item ${convo.id === activeConvoId ? 'active' : ''}`;
            item.dataset.id = convo.id;

            item.innerHTML = `
                <div class="convo-item-left">
                    <i class="fa-regular fa-comment"></i>
                    <span class="convo-item-title">${escapeHtml(convo.title)}</span>
                </div>
                <button class="btn-delete-convo" title="Delete conversation">
                    <i class="fa-regular fa-trash-can"></i>
                </button>
            `;

            // Click convo item to switch chats
            item.addEventListener('click', (e) => {
                if (e.target.closest('.btn-delete-convo')) return; // handled below
                selectConversation(convo.id);
            });

            // Delete conversation handler
            item.querySelector('.btn-delete-convo').addEventListener('click', async (e) => {
                e.stopPropagation();
                if (confirm(`Delete conversation "${convo.title}"?`)) {
                    try {
                        await api.deleteConversation(convo.id);
                        if (activeConvoId === convo.id) {
                            activeConvoId = null;
                            activeConvoScope = null;
                            convoTitle.textContent = 'Select or Start a Chat';
                            convoScopeInfo.textContent = 'Searching all documents';
                            chatContainer.innerHTML = `
                                <div class="chat-empty" id="chat-empty-state">
                                    <i class="fa-solid fa-comments"></i>
                                    <h3>Welcome to DocuIntel</h3>
                                    <p>Upload your PDFs or DOCX reports and start chatting. Your questions will be answered with page-level citations based on your uploaded context.</p>
                                </div>
                            `;
                            chatTextarea.disabled = true;
                            btnSend.disabled = true;
                        }
                        await loadConversations();
                    } catch (err) {
                        alert(err.message || 'Could not delete conversation.');
                    }
                }
            });

            list.appendChild(item);
        });

        listConvos.appendChild(list);
    }

    // New conversation trigger
    btnNewConvo.addEventListener('click', async () => {
        try {
            const scope = activeConvoScope ? activeConvoScope : null;
            const newConvo = await api.createConversation('New conversation', scope);
            activeConvoId = newConvo.id;
            await loadConversations();
            selectConversation(newConvo.id);
        } catch (err) {
            alert(err.message || 'Could not create conversation');
        }
    });

    async function selectConversation(convoId) {
        activeConvoId = convoId;
        const convo = conversations.find(c => c.id === convoId);
        if (!convo) return;

        // Set header state
        convoTitle.textContent = convo.title;
        activeConvoScope = convo.document_scope;
        updateScopeHeaderLabel();

        // Enable prompt inputs
        chatTextarea.disabled = false;
        btnSend.disabled = false;
        chatTextarea.focus();

        // Highlighting active item
        document.querySelectorAll('.convo-item').forEach(el => {
            el.classList.toggle('active', el.dataset.id === convoId);
        });

        // Load messages history
        chatContainer.innerHTML = '<div class="chat-empty"><i class="fa-solid fa-spinner fa-spin"></i><p>Loading messages...</p></div>';
        try {
            const messages = await api.getMessages(convoId);
            renderMessages(messages);
        } catch (err) {
            chatContainer.innerHTML = '<div class="chat-empty"><i class="fa-solid fa-triangle-exclamation"></i><p>Error loading messages history.</p></div>';
        }
    }

    // --- 4. Chat Messages Rendering & SSE Streaming ---
    function renderMessages(messages) {
        if (messages.length === 0) {
            chatContainer.innerHTML = `
                <div class="chat-empty" id="chat-empty-state">
                    <i class="fa-solid fa-comments"></i>
                    <h3>Start the Conversation</h3>
                    <p>Ask a question about your uploaded documents.</p>
                </div>
            `;
            return;
        }

        chatContainer.innerHTML = '';
        messages.forEach(msg => {
            appendMessageToUi(msg.role, msg.content, {
                id: msg.id,
                citations: msg.citations,
                latency_ms: msg.latency_ms,
                llm_provider: msg.llm_provider,
                token_cost: msg.token_cost
            });
        });
        scrollChatToBottom();
    }

    function appendMessageToUi(role, content, meta = {}) {
        // Remove empty state if present
        const emptyState = document.getElementById('chat-empty-state');
        if (emptyState) emptyState.remove();

        const messageEl = document.createElement('div');
        messageEl.className = `message ${role}`;
        
        const avatarIcon = role === 'user' ? 'fa-regular fa-user' : 'fa-solid fa-robot';
        
        // Build inline citation chips helper function
        let citationsHtml = '';
        if (role === 'assistant' && meta.citations && meta.citations.length > 0) {
            citationsHtml = `<div class="citations-container">`;
            meta.citations.forEach(cit => {
                const pageText = cit.page ? `Page ${cit.page}` : 'N/A';
                citationsHtml += `
                    <button class="citation-chip" data-marker="${cit.marker}" data-doc-id="${cit.document_id}" data-filename="${cit.filename}" data-page="${cit.page || ''}" data-snippet="${escapeHtml(cit.snippet)}">
                        <i class="fa-solid fa-quote-left"></i>
                        <span>[${cit.marker}] ${escapeHtml(cit.filename)} (${pageText})</span>
                    </button>
                `;
            });
            citationsHtml += `</div>`;
        }

        messageEl.innerHTML = `
            <div class="message-avatar">
                <i class="${avatarIcon}"></i>
            </div>
            <div class="message-body">
                <div class="message-bubble glass">${escapeMarkdown(content)}</div>
                ${citationsHtml}
            </div>
        `;

        chatContainer.appendChild(messageEl);
        scrollChatToBottom();
        return messageEl;
    }

    function scrollChatToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // Streaming chat trigger
    async function handleSendMessage() {
        const question = chatTextarea.value.trim();
        if (!question || !activeConvoId) return;

        // Render user message in UI
        appendMessageToUi('user', question);
        chatTextarea.value = '';
        chatTextarea.style.height = '56px';

        // Set inputs to disabled during streaming
        chatTextarea.disabled = true;
        btnSend.disabled = true;

        // Render temporary assistant placeholder bubble
        const aiMessageEl = document.createElement('div');
        aiMessageEl.className = 'message assistant';
        aiMessageEl.innerHTML = `
            <div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-body">
                <div class="message-bubble glass">
                    <div class="streaming-indicator">
                        <div class="dot"></div>
                        <div class="dot"></div>
                        <div class="dot"></div>
                    </div>
                </div>
            </div>
        `;
        chatContainer.appendChild(aiMessageEl);
        scrollChatToBottom();

        const bubbleEl = aiMessageEl.querySelector('.message-bubble');
        let rawAnswer = '';
        let citations = [];

        // Call the custom SSE reader
        await api.askStream(
            activeConvoId, 
            question, 
            true,
            // Meta callback: returns doc citations and retrieval timings
            (meta) => {
                citations = meta.citations || [];
            },
            // Token callback: appends incoming characters to bubble
            (token) => {
                if (bubbleEl.querySelector('.streaming-indicator')) {
                    bubbleEl.innerHTML = '';
                }
                rawAnswer += token;
                bubbleEl.innerHTML = escapeMarkdown(rawAnswer);
                scrollChatToBottom();
            },
            // Done callback: final payload saves message id and telemetry stats
            async (done) => {
                // Re-render message bubble with clean chips and buttons
                aiMessageEl.remove();
                appendMessageToUi('assistant', rawAnswer, {
                    id: done.message_id,
                    citations: done.citations || citations,
                    latency_ms: done.latency_ms,
                    llm_provider: done.provider,
                    token_cost: done.token_cost
                });
                
                // Re-enable text inputs
                chatTextarea.disabled = false;
                btnSend.disabled = false;
                chatTextarea.focus();
                
                // Reload conversations list in case title auto-updated
                await loadConversations();
            },
            // Error callback
            (err) => {
                bubbleEl.innerHTML = `<span style="color: var(--danger);"><i class="fa-solid fa-circle-exclamation"></i> Error: ${err.message || 'Chat generation failed'}</span>`;
                chatTextarea.disabled = false;
                btnSend.disabled = false;
                chatTextarea.focus();
            }
        );
    }

    // Input listeners
    btnSend.addEventListener('click', handleSendMessage);
    chatTextarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    });

    // Auto-growing textarea
    chatTextarea.addEventListener('input', () => {
        chatTextarea.style.height = 'auto';
        chatTextarea.style.height = (chatTextarea.scrollHeight) + 'px';
    });

    // --- 5. Citation Details Slide-Out Drawer ---
    // Listen for citation chip clicks in the messages area
    chatContainer.addEventListener('click', (e) => {
        const chip = e.target.closest('.citation-chip');
        if (!chip) return;

        const marker = chip.dataset.marker;
        const docId = chip.dataset.docId;
        const filename = chip.dataset.filename;
        const page = chip.dataset.page;
        const snippet = chip.dataset.snippet;

        citationsDrawerBody.innerHTML = `
            <div class="citation-card">
                <div class="citation-card-header">
                    <i class="fa-solid fa-file-pdf"></i>
                    <span>[${marker}] ${escapeHtml(filename)}</span>
                </div>
                <div style="font-size: 0.8rem; color: var(--text-dark); margin-bottom: 12px;">
                    <span style="margin-right: 15px;"><i class="fa-regular fa-hashtag"></i> Document ID: ${docId.substring(0,8)}...</span>
                    <span><i class="fa-regular fa-bookmark"></i> Page Number: ${page || 'N/A'}</span>
                </div>
                <div class="citation-snippet">
                    "${escapeHtml(snippet)}"
                </div>
            </div>
            
            <div style="margin-top: 24px;">
                <button class="btn btn-secondary btn-block btn-sm" id="btn-drawer-summarize" data-id="${docId}">
                    <i class="fa-solid fa-wand-magic-sparkles"></i> Summarize This Document
                </button>
            </div>
        `;

        // Drawer summarize action
        document.getElementById('btn-drawer-summarize').addEventListener('click', async () => {
            citationsDrawer.classList.remove('open');
            await triggerSummarization(docId);
        });

        citationsDrawer.classList.add('open');
    });

    btnCloseDrawer.addEventListener('click', () => {
        citationsDrawer.classList.remove('open');
    });

    // --- 6. Documents Manager and File Upload Modal ---
    btnOpenDocs.addEventListener('click', () => {
        docsModal.classList.remove('hidden');
        renderDocumentsList();
    });

    btnCloseDocsModal.addEventListener('click', () => {
        docsModal.classList.add('hidden');
    });

    // Toggle dropdown scoping menu
    btnToggleScope.addEventListener('click', (e) => {
        e.stopPropagation();
        scopeDropdown.classList.toggle('hidden');
    });

    document.addEventListener('click', (e) => {
        if (!scopeDropdown.classList.contains('hidden') && !e.target.closest('.scope-selector-wrapper')) {
            scopeDropdown.classList.add('hidden');
        }
    });

    async function loadDocuments() {
        try {
            documents = await api.getDocuments();
            renderScopeDropdownList();
            
            // Check if any document is currently in "processing" state
            // If so, setup an interval to poll status mirroring from Redis
            const isProcessing = documents.some(d => d.status === 'processing');
            if (isProcessing) {
                documents.forEach(d => {
                    if (d.status === 'processing') processingDocs.add(d.id);
                });
                startStatusPolling();
            }
        } catch (e) {
            console.error('Error fetching documents list:', e);
        }
    }

    // Render checkable items in filter document scope menu
    function renderScopeDropdownList() {
        const readyDocs = documents.filter(d => d.status === 'ready');
        
        if (readyDocs.length === 0) {
            scopeDocsList.innerHTML = '<div class="empty-state">No ready documents found.</div>';
            return;
        }

        scopeDocsList.innerHTML = '';
        readyDocs.forEach(doc => {
            const label = document.createElement('label');
            label.className = 'scope-item';
            
            const isChecked = activeConvoScope && activeConvoScope.includes(doc.id);

            label.innerHTML = `
                <input type="checkbox" data-id="${doc.id}" ${isChecked ? 'checked' : ''}>
                <span title="${escapeHtml(doc.filename)}">${escapeHtml(doc.filename)}</span>
            `;

            label.querySelector('input').addEventListener('change', async (e) => {
                if (!activeConvoId) {
                    alert('Please select or start a chat first before choosing scope');
                    e.target.checked = false;
                    return;
                }
                
                // Build array of currently checked document scope UUIDs
                const checkedInputs = scopeDocsList.querySelectorAll('input:checked');
                const selectedIds = Array.from(checkedInputs).map(el => el.dataset.id);
                
                try {
                    // Update scoping on active conversation
                    const convo = conversations.find(c => c.id === activeConvoId);
                    if (convo) {
                        convo.document_scope = selectedIds.length > 0 ? selectedIds : null;
                        activeConvoScope = convo.document_scope;
                        
                        // Call server to persist scope changes
                        await api.createConversation(convo.title, activeConvoScope);
                        updateScopeHeaderLabel();
                    }
                } catch (err) {
                    alert('Failed to update scope: ' + err.message);
                }
            });

            scopeDocsList.appendChild(label);
        });
    }

    function updateScopeHeaderLabel() {
        if (!activeConvoScope || activeConvoScope.length === 0) {
            convoScopeInfo.textContent = 'Searching all documents';
        } else {
            convoScopeInfo.textContent = `Searching ${activeConvoScope.length} filtered document(s)`;
        }
    }

    btnClearScope.addEventListener('click', async () => {
        if (!activeConvoId) return;
        scopeDocsList.querySelectorAll('input:checked').forEach(input => {
            input.checked = false;
        });
        
        try {
            const convo = conversations.find(c => c.id === activeConvoId);
            if (convo) {
                convo.document_scope = null;
                activeConvoScope = null;
                await api.createConversation(convo.title, null);
                updateScopeHeaderLabel();
            }
        } catch (err) {
            console.error('Clear scope failed:', err);
        }
    });

    // Render list of files in Document Manager Table
    function renderDocumentsList() {
        if (documents.length === 0) {
            uploadedDocsList.innerHTML = '<div class="empty-state">No uploaded documents yet. Drag a file to ingest!</div>';
            return;
        }

        uploadedDocsList.innerHTML = '';
        documents.forEach(doc => {
            const row = document.createElement('div');
            row.className = 'doc-row';
            row.dataset.id = doc.id;

            const sizeMb = (doc.file_size_bytes / (1024 * 1024)).toFixed(2);
            const badgeClass = doc.status; // processing, ready, failed
            
            row.innerHTML = `
                <div class="doc-row-left">
                    <i class="fa-regular fa-file-pdf doc-icon"></i>
                    <div>
                        <div class="doc-name" title="${escapeHtml(doc.filename)}">${escapeHtml(doc.filename)}</div>
                        <div class="doc-meta">
                            <span>${sizeMb} MB</span> • 
                            <span>${doc.page_count ? doc.page_count + ' pages' : 'N/A'}</span>
                        </div>
                    </div>
                </div>
                <div class="doc-row-actions">
                    <span class="doc-status-badge ${badgeClass}">${doc.status}</span>
                    <button class="doc-btn btn-summarize" title="Summarize document" ${doc.status !== 'ready' ? 'disabled' : ''}><i class="fa-solid fa-wand-magic-sparkles"></i></button>
                    <button class="doc-btn delete" title="Delete document"><i class="fa-regular fa-trash-can"></i></button>
                </div>
            `;

            // Document Manager Event Listeners
            row.querySelector('.btn-summarize').addEventListener('click', async () => {
                docsModal.classList.add('hidden');
                await triggerSummarization(doc.id);
            });

            row.querySelector('.delete').addEventListener('click', async () => {
                if (confirm(`Delete document "${doc.filename}"? This will cascade to delete chunks and vectors.`)) {
                    try {
                        await api.deleteDocument(doc.id);
                        await loadDocuments();
                        renderDocumentsList();
                    } catch (err) {
                        alert('Deletion failed: ' + err.message);
                    }
                }
            });

            uploadedDocsList.appendChild(row);
        });
    }

    // Trigger map-reduce summarization logic
    async function triggerSummarization(docId) {
        if (!activeConvoId) {
            alert('Please select or start a chat first to output summaries.');
            return;
        }

        // Render loading state in chat area
        appendMessageToUi('user', 'Triggering AI summary of document...');
        const aiMessageEl = appendMessageToUi('assistant', 'Generating summary... (this uses map-reduce over the document chunks)');
        const bubble = aiMessageEl.querySelector('.message-bubble');

        try {
            const data = await api.summarizeDocument(docId);
            bubble.innerHTML = `<h3>Document Summary</h3><p>${escapeMarkdown(data.summary)}</p>`;
            
            // Add timing stats
            const stats = data.stats || {};
            const costText = stats.estimated_cost_usd ? `$${stats.estimated_cost_usd.toFixed(6)}` : '$0.00';
            
            const metaEl = document.createElement('div');
            metaEl.className = 'message-meta';
            metaEl.innerHTML = `
                <span><i class="fa-solid fa-boxes-stacked"></i> Chunks: ${stats.chunks || 0}</span>
                <span><i class="fa-solid fa-microchip"></i> Provider: ${stats.provider || 'Local'}</span>
                <span><i class="fa-solid fa-coins"></i> Cost: ${costText}</span>
            `;
            aiMessageEl.querySelector('.message-body').appendChild(metaEl);
        } catch (err) {
            bubble.innerHTML = `<span style="color: var(--danger);"><i class="fa-solid fa-circle-exclamation"></i> Summary failed: ${err.message}</span>`;
        }
    }

    // Ingestion Polling: Polls status checks on processing documents
    function startStatusPolling() {
        if (pollInterval) return;

        console.log('Ingestion background tasks active. Starting status polling...');
        pollInterval = setInterval(async () => {
            if (processingDocs.size === 0) {
                clearInterval(pollInterval);
                pollInterval = null;
                return;
            }

            for (const docId of processingDocs) {
                try {
                    const res = await api.getDocumentStatus(docId);
                    if (res.status === 'ready' || res.status === 'failed') {
                        processingDocs.delete(docId);
                        console.log(`Document ${docId} finished with status: ${res.status}`);
                        
                        // Reload lists to show active badges
                        await loadDocuments();
                        if (!docsModal.classList.contains('hidden')) {
                            renderDocumentsList();
                        }
                    }
                } catch (e) {
                    processingDocs.delete(docId);
                }
            }
        }, 3000); // Check status every 3s
    }

    // --- 7. Ingestion Upload Drag-and-Drop Area ---
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileUploads(files);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFileUploads(fileInput.files);
        }
    });

    function handleFileUploads(files) {
        Array.from(files).forEach(file => {
            const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
            if (ext !== '.pdf' && ext !== '.docx') {
                alert(`File format "${ext}" is not supported. Please upload a PDF or DOCX.`);
                return;
            }
            uploadFileStream(file);
        });
    }

    // Stream upload with progress bar
    async function uploadFileStream(file) {
        const id = Math.random().toString(36).substring(2, 9);
        
        // Add item to progress UI container list
        const progressItem = document.createElement('div');
        progressItem.className = 'progress-item';
        progressItem.id = `upload-${id}`;
        progressItem.innerHTML = `
            <div class="progress-item-header">
                <span class="progress-item-name">${escapeHtml(file.name)}</span>
                <span class="progress-percent">0%</span>
            </div>
            <div class="progress-bar-container">
                <div class="progress-bar" style="width: 0%"></div>
            </div>
        `;
        progressContainer.appendChild(progressItem);

        const pBar = progressItem.querySelector('.progress-bar');
        const pPercent = progressItem.querySelector('.progress-percent');

        // Create standard XMLHttpRequest to track progress percentage upload hooks
        const xhr = new XMLHttpRequest();
        const url = `${API_BASE}/api/documents/upload`;
        
        xhr.open('POST', url, true);
        xhr.setRequestHeader('X-Request-ID', Math.random().toString(36).substring(2, 10));
        if (api.accessToken) {
            xhr.setRequestHeader('Authorization', `Bearer ${api.accessToken}`);
        }

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                pBar.style.width = `${percent}%`;
                pPercent.textContent = `${percent}%`;
            }
        });

        xhr.addEventListener('load', async () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                pBar.classList.add('success');
                pPercent.innerHTML = '<span style="color: var(--secondary)"><i class="fa-solid fa-circle-check"></i> Processing...</span>';
                
                // Clear bar item after a few seconds
                setTimeout(() => progressItem.remove(), 4000);
                
                // Refresh list and poll status
                await loadDocuments();
                renderDocumentsList();
            } else {
                let errText = 'Upload failed';
                try {
                    const parsed = JSON.parse(xhr.responseText);
                    errText = parsed.error?.message || errText;
                } catch(e) {}
                
                pBar.classList.add('failed');
                pPercent.innerHTML = `<span style="color: var(--danger)" title="${errText}"><i class="fa-solid fa-circle-xmark"></i> Failed</span>`;
            }
        });

        xhr.addEventListener('error', () => {
            pBar.classList.add('failed');
            pPercent.innerHTML = '<span style="color: var(--danger)"><i class="fa-solid fa-triangle-exclamation"></i> Network Error</span>';
        });

        const formData = new FormData();
        formData.append('file', file);
        xhr.send(formData);
    }

    // --- 8. General Helpers ---
    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Simple markdown parsing helper for bullets and citations
    function escapeMarkdown(text) {
        if (!text) return '';
        let clean = escapeHtml(text);
        
        // Bold parsing (**text**)
        clean = clean.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Bullet parsing
        clean = clean.replace(/^\s*-\s+(.*)$/gm, '<li>$1</li>');
        clean = clean.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
        
        // Citation chips highlighting inline [S1] or [S2][S3] markers
        clean = clean.replace(/\[S(\d+)\]/g, '<span class="citation-highlight" style="color: var(--primary); font-weight: 600; background: rgba(99, 102, 241, 0.1); padding: 1px 4px; border-radius: 4px; font-size: 0.82rem; cursor: pointer;">[S$1]</span>');
        
    // --- 9. Contract Lifecycle & AI Risk Analytics UI Handlers ---
    const btnOpenContracts = document.getElementById('btn-open-contracts');
    const contractsModal = document.getElementById('contracts-modal');
    const btnCloseContractsModal = document.getElementById('btn-close-contracts-modal');
    const contractUploadForm = document.getElementById('contract-upload-form');
    const contractTitleInput = document.getElementById('contract-title-input');
    const contractFileInput = document.getElementById('contract-file-input');
    const contractsListEl = document.getElementById('contracts-list');
    const contractAnalysisViewEl = document.getElementById('contract-analysis-view');

    let contracts = [];
    let selectedContract = null;

    if (btnOpenContracts) {
        btnOpenContracts.addEventListener('click', async () => {
            contractsModal.classList.remove('hidden');
            await loadContractsList();
        });
    }

    if (btnCloseContractsModal) {
        btnCloseContractsModal.addEventListener('click', () => {
            contractsModal.classList.add('hidden');
        });
    }

    if (contractUploadForm) {
        contractUploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const title = contractTitleInput.value.trim();
            const file = contractFileInput.files[0];

            if (!title || !file) {
                alert('Please enter a contract title and choose a file');
                return;
            }

            const uploadBtn = document.getElementById('btn-upload-contract');
            uploadBtn.disabled = true;
            uploadBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing AI Risk...';

            try {
                const newContract = await api.uploadContract(title, file);
                contractTitleInput.value = '';
                contractFileInput.value = '';
                await loadContractsList();
                renderContractAnalysis(newContract);
            } catch (err) {
                alert('Contract upload failed: ' + err.message);
            } finally {
                uploadBtn.disabled = false;
                uploadBtn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Upload & Run AI Analysis';
            }
        });
    }

    async function loadContractsList() {
        try {
            contracts = await api.getContracts();
            renderContractsList();
        } catch (err) {
            console.error('Failed to load contracts:', err);
        }
    }

    function renderContractsList() {
        if (!contractsListEl) return;
        if (contracts.length === 0) {
            contractsListEl.innerHTML = '<div class="empty-state">No contracts analyzed yet. Upload a contract above!</div>';
            return;
        }

        contractsListEl.innerHTML = '';
        contracts.forEach(contract => {
            const card = document.createElement('div');
            card.className = `contract-item-card ${selectedContract && selectedContract.id === contract.id ? 'active' : ''}`;
            
            const riskClass = (contract.risk_score || 15) > 50 ? 'high' : (contract.risk_score || 15) > 25 ? 'medium' : 'low';

            card.innerHTML = `
                <div class="contract-item-title">${escapeHtml(contract.title)}</div>
                <div class="contract-item-meta">
                    <span>#${contract.contract_number || 'CNT-2026-101'}</span>
                    <span class="badge-risk ${riskClass}">${contract.risk_score || 15}% Risk</span>
                </div>
            `;

            card.addEventListener('click', () => {
                document.querySelectorAll('.contract-item-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                selectedContract = contract;
                renderContractAnalysis(contract);
            });

            contractsListEl.appendChild(card);
        });
    }

    function renderContractAnalysis(c) {
        if (!contractAnalysisViewEl) return;
        selectedContract = c;

        let missingClauses = [];
        let obligations = [];
        let parties = [];
        let autoTags = [];
        let actionItems = [];
        let complianceFlags = [];

        try { missingClauses = JSON.parse(c.missing_clauses || '[]'); } catch (e) {}
        try { obligations = JSON.parse(c.obligations || '[]'); } catch (e) {}
        try { parties = JSON.parse(c.parties || '[]'); } catch (e) {}
        try { autoTags = JSON.parse(c.auto_tags || '[]'); } catch (e) {}
        try { actionItems = JSON.parse(c.action_items || '[]'); } catch (e) {}
        try { complianceFlags = JSON.parse(c.compliance_flags || '[]'); } catch (e) {}

        const riskClass = (c.risk_score || 15) > 50 ? 'high' : (c.risk_score || 15) > 25 ? 'medium' : 'low';

        contractAnalysisViewEl.innerHTML = `
            <div class="analysis-header">
                <div>
                    <h3>${escapeHtml(c.title)}</h3>
                    <span style="font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(c.filename)}</span>
                </div>
                <button class="btn btn-secondary btn-sm" id="btn-reanalyze" data-id="${c.id}">
                    <i class="fa-solid fa-rotate-right"></i> Re-Run AI Risk Check
                </button>
            </div>

            <!-- Health & Risk Scores -->
            <div class="score-gauge-container">
                <div class="score-card">
                    <h5>Contract Health Score</h5>
                    <div class="score-number health">${c.health_score || 85}/100</div>
                </div>
                <div class="score-card">
                    <h5>Risk Exposure</h5>
                    <div class="score-number risk">${c.risk_score || 15}%</div>
                </div>
            </div>

            <!-- Extended Metadata Grid -->
            <h5>Contract Metadata</h5>
            <div class="metadata-grid">
                <div class="meta-field"><label>Contract Number</label><span>${c.contract_number || 'CNT-2026-101'}</span></div>
                <div class="meta-field"><label>Owner</label><span>${escapeHtml(c.owner || 'Legal Dept')}</span></div>
                <div class="meta-field"><label>Department</label><span>${escapeHtml(c.department || 'Procurement')}</span></div>
                <div class="meta-field"><label>Vendor</label><span>${escapeHtml(c.vendor || 'Vendor Inc')}</span></div>
                <div class="meta-field"><label>Client</label><span>${escapeHtml(c.client || 'Enterprise Org')}</span></div>
                <div class="meta-field"><label>Contract Value</label><span>$${c.value ? c.value.toLocaleString() : '50,000'} ${c.currency || 'USD'}</span></div>
                <div class="meta-field"><label>Effective Date</label><span>${c.effective_date || '2026-01-01'}</span></div>
                <div class="meta-field"><label>Expiry Date</label><span>${c.expiry_date || '2027-01-01'}</span></div>
                <div class="meta-field"><label>Renewal Date</label><span>${c.renewal_date || '2026-12-01'}</span></div>
                <div class="meta-field"><label>Priority</label><span style="color: var(--primary); font-weight:700;">${c.priority || 'High'}</span></div>
            </div>

            <!-- Auto Tags -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-tags"></i> Categorization & Auto Tags</h5>
                <div class="tag-list">
                    ${autoTags.map(t => `<span class="tag-badge">${escapeHtml(t)}</span>`).join('') || '<span class="text-muted">No tags</span>'}
                </div>
            </div>

            <!-- Missing Clauses -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-triangle-exclamation"></i> Missing Clauses Detection</h5>
                ${missingClauses.length > 0 
                    ? missingClauses.map(mc => `<div class="clause-warning-item"><i class="fa-solid fa-circle-exclamation"></i> Missing: <strong>${escapeHtml(mc)}</strong></div>`).join('')
                    : '<div style="color: #4ade80; font-size: 0.85rem;"><i class="fa-solid fa-circle-check"></i> All standard required clauses are present.</div>'}
            </div>

            <!-- Obligations Extraction -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-list-check"></i> Key Contractual Obligations</h5>
                ${obligations.map(ob => `<div class="obligation-item"><i class="fa-solid fa-check"></i> ${escapeHtml(ob)}</div>`).join('')}
            </div>

            <!-- Payment Terms & Parties -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-credit-card"></i> Payment Terms Extraction</h5>
                <p style="font-size: 0.85rem; color: var(--text-main); background: var(--bg-tertiary); padding: 10px; border-radius: 6px;">
                    ${escapeHtml(c.payment_terms || 'Net 30 days upon invoice receipt; 1.5% late penalty per month.')}
                </p>
            </div>

            <!-- Parties Extraction -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-users"></i> Signatory Parties</h5>
                <div class="tag-list">
                    ${parties.map(p => `<span class="tag-badge" style="background: rgba(59,130,246,0.15); color: #93c5fd;">${escapeHtml(p)}</span>`).join('')}
                </div>
            </div>

            <!-- Action Items -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-calendar-check"></i> Action Items & Reminders</h5>
                ${actionItems.map(act => `<div style="font-size:0.84rem; color: var(--text-main); margin-bottom: 4px;"><i class="fa-regular fa-clock" style="color: var(--primary);"></i> ${escapeHtml(act)}</div>`).join('')}
            </div>

            <!-- Compliance Flags -->
            <div class="analysis-section">
                <h5><i class="fa-solid fa-shield-check"></i> Compliance Flags</h5>
                <div class="tag-list">
                    ${complianceFlags.map(cf => `<span class="tag-badge" style="background: rgba(34,197,94,0.15); color: #4ade80; border-color: rgba(34,197,94,0.3);"><i class="fa-solid fa-check"></i> ${escapeHtml(cf)}</span>`).join('')}
                </div>
            </div>
        `;

        document.getElementById('btn-reanalyze').addEventListener('click', async () => {
            const btn = document.getElementById('btn-reanalyze');
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Re-Analyzing...';
            try {
                const updated = await api.analyzeContract(c.id);
                await loadContractsList();
                renderContractAnalysis(updated);
            } catch (err) {
                alert('Analysis failed: ' + err.message);
            } finally {
                btn.disabled = false;
            }
        });
    }
});

