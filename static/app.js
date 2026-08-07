document.addEventListener("DOMContentLoaded", () => {
    // --- STATE VARIABLES ---
    let config = {};
    let chatHistory = [];

    // --- DOM ELEMENTS ---
    const envSelector = document.getElementById("envSelector");
    const customUrlGroup = document.getElementById("customUrlGroup");
    const customBaseUrl = document.getElementById("customBaseUrl");
    const bearerToken = document.getElementById("bearerToken");
    const toggleTokenVisibility = document.getElementById("toggleTokenVisibility");
    const btnTestConn = document.getElementById("btnTestConn");
    const connStatus = document.getElementById("connStatus");

    const llmProvider = document.getElementById("llmProvider");
    const groqKeyGroup = document.getElementById("groqKeyGroup");
    const openaiKeyGroup = document.getElementById("openaiKeyGroup");
    const groqApiKey = document.getElementById("groqApiKey");
    const openaiApiKey = document.getElementById("openaiApiKey");

    // --- INITIALIZE CONFIG FROM BACKEND ---
    fetch("/api/config")
        .then(res => res.json())
        .then(data => {
            config = data;
            if (config.default_bearer_token) bearerToken.value = config.default_bearer_token;
            if (config.default_groq_key) groqApiKey.value = config.default_groq_key;
            if (config.default_openai_key) openaiApiKey.value = config.default_openai_key;
            if (config.default_llm_provider) {
                llmProvider.value = config.default_llm_provider;
                toggleLlmProviderUI();
            }
        })
        .catch(err => console.error("Error loading config:", err));

    // --- BASE URL GETTER ---
    function getBaseUrl() {
        if (envSelector.value === "prod") {
            return "https://us2.unifier.oraclecloud.com/consulting/prod/ws/rest/service/v1";
        } else if (envSelector.value === "custom") {
            return customBaseUrl.value.trim() || config.default_base_url;
        } else {
            return "https://us2.unifier.oraclecloud.com/consulting/test/ws/rest/service/v1";
        }
    }

    // --- EVENT LISTENERS ---
    envSelector.addEventListener("change", () => {
        customUrlGroup.style.display = envSelector.value === "custom" ? "block" : "none";
    });

    toggleTokenVisibility.addEventListener("click", () => {
        const type = bearerToken.type === "password" ? "text" : "password";
        bearerToken.type = type;
        toggleTokenVisibility.innerHTML = type === "password" ? '<i class="fa-solid fa-eye"></i>' : '<i class="fa-solid fa-eye-slash"></i>';
    });

    llmProvider.addEventListener("change", toggleLlmProviderUI);
    function toggleLlmProviderUI() {
        if (llmProvider.value === "openai") {
            openaiKeyGroup.style.display = "block";
            groqKeyGroup.style.display = "none";
        } else {
            openaiKeyGroup.style.display = "none";
            groqKeyGroup.style.display = "block";
        }
    }

    // --- TAB SWITCHING ---
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.tab;
            tabBtns.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(target).classList.add("active");
        });
    });

    // --- TEST CONNECTION ---
    btnTestConn.addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        if (!token) {
            showStatus("Please enter a Bearer Token first.", "error");
            return;
        }
        btnTestConn.disabled = true;
        btnTestConn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing...';

        try {
            const res = await fetch("/api/test-connection", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ bearer_token: token, base_url: getBaseUrl() })
            });
            const data = await res.json();
            if (data.success) {
                showStatus(`✓ Connected (${data.message})`, "success");
            } else {
                showStatus(`✕ Disconnected: ${data.message}`, "error");
            }
        } catch (err) {
            showStatus(`✕ Network Error: ${err.message}`, "error");
        } finally {
            btnTestConn.disabled = false;
            btnTestConn.innerHTML = '<i class="fa-solid fa-plug"></i> Test API Connection';
        }
    });

    function showStatus(msg, type) {
        connStatus.innerHTML = `<span style="color: ${type === 'success' ? '#34d399' : '#f87171'}; font-weight:600;">${msg}</span>`;
    }

    // --- TABLE RENDER HELPER ---
    function renderTable(containerId, records, title, rawData) {
        const container = document.getElementById(containerId);
        if (!Array.isArray(records) || records.length === 0) {
            container.innerHTML = `<div class="card margin-top"><h4>${title}</h4><p class="subtitle">No records found or empty response.</p><pre class="code-font margin-top">${JSON.stringify(rawData, null, 2)}</pre></div>`;
            return;
        }

        const keys = Object.keys(records[0]);
        const tableId = `table_${Date.now()}`;
        const searchId = `search_${Date.now()}`;

        let html = `
            <div class="card margin-top">
                <div class="card-header">
                    <div>
                        <h4>${title} (${records.length} Records)</h4>
                    </div>
                    <div class="inline-inputs">
                        <input type="text" id="${searchId}" class="form-control inline-input" placeholder="🔍 Search records...">
                        <button class="btn btn-secondary" onclick="exportCSV('${tableId}', '${title}.csv')"><i class="fa-solid fa-file-csv"></i> Export CSV</button>
                    </div>
                </div>
                <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                    <table class="custom-table" id="${tableId}">
                        <thead>
                            <tr>${keys.map(k => `<th>${k}</th>`).join("")}</tr>
                        </thead>
                        <tbody>
                            ${records.map(r => `<tr>${keys.map(k => `<td>${typeof r[k] === 'object' ? JSON.stringify(r[k]) : (r[k] !== undefined ? r[k] : '')}</td>`).join("")}</tr>`).join("")}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        container.innerHTML = html;

        // Search Filter Event
        document.getElementById(searchId).addEventListener("input", (e) => {
            const val = e.target.value.toLowerCase();
            const rows = document.querySelectorAll(`#${tableId} tbody tr`);
            rows.forEach(row => {
                const text = row.innerText.toLowerCase();
                row.style.display = text.includes(val) ? "" : "none";
            });
        });
    }

    // CSV Exporter Helper
    window.exportCSV = function(tableId, filename) {
        const table = document.getElementById(tableId);
        const rows = Array.from(table.querySelectorAll("tr"));
        const csv = rows.map(r => Array.from(r.querySelectorAll("th, td")).map(td => `"${td.innerText.replace(/"/g, '""')}"`).join(",")).join("\n");
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
    };

    // --- FETCH ACTIVE PROJECTS ---
    document.getElementById("btnFetchProjects").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        if (!token) return alert("Please enter a Bearer Token.");
        const resArea = document.getElementById("projectsResult");
        resArea.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching active projects...';

        const res = await fetch("/api/active-projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bearer_token: token, base_url: getBaseUrl() })
        });
        const data = await res.json();
        if (data.success) {
            let list = data.data;
            if (data.data && data.data.data) list = data.data.data;
            renderTable("projectsResult", list, "Active Projects List", data.data);
        } else {
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed: ${JSON.stringify(data.data)}</div>`;
        }
    });

    // --- FETCH COMPANY BP CATALOG ---
    document.getElementById("btnFetchCompanyBPCatalog").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        if (!token) return alert("Please enter a Bearer Token.");
        const resArea = document.getElementById("companyBPCatalogResult");
        resArea.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Loading catalog...';

        const res = await fetch("/api/company-bp-catalog", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bearer_token: token, base_url: getBaseUrl() })
        });
        const data = await res.json();
        if (data.success) {
            let list = data.data;
            if (data.data && data.data.data) list = data.data.data;
            renderTable("companyBPCatalogResult", list, "Company Business Process Catalog", data.data);
        } else {
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed: ${JSON.stringify(data.data)}</div>`;
        }
    });

    // --- FETCH COMPANY BP RECORDS ---
    document.getElementById("btnFetchCompanyBPRecords").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        const bpName = document.getElementById("companyBpName").value.trim();
        if (!token || !bpName) return alert("Bearer Token and BP Name are required.");
        const resArea = document.getElementById("companyBPRecordsResult");
        resArea.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Fetching records for '${bpName}'...`;

        const payload = {
            bearer_token: token,
            base_url: getBaseUrl(),
            bpname: bpName,
            filter_condition: document.getElementById("companyFilterCond").value.trim(),
            lineitem: document.getElementById("c_lineitem").checked ? "yes" : "no",
            lineitem_file: document.getElementById("c_lineitem_file").checked ? "yes" : "no",
            general_comments: document.getElementById("c_general_comments").checked ? "yes" : "no",
            attach_all_publications: document.getElementById("c_attach_all_publications").checked ? "yes" : "no"
        };

        const res = await fetch("/api/company-bp-records", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            let list = data.data;
            if (data.data && data.data.data) list = data.data.data;
            renderTable("companyBPRecordsResult", list, `Company BP Records: ${bpName}`, data.data);
        } else {
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed: ${JSON.stringify(data.data)}</div>`;
        }
    });

    // --- FETCH PROJECT BP CATALOG ---
    document.getElementById("btnFetchProjectBPCatalog").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        const projNo = document.getElementById("projCatNo").value.trim() || "001";
        if (!token) return alert("Please enter a Bearer Token.");
        const resArea = document.getElementById("projectBPCatalogResult");
        resArea.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Loading Project ${projNo} Catalog...`;

        const res = await fetch("/api/project-bp-catalog", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bearer_token: token, base_url: getBaseUrl(), project_number: projNo })
        });
        const data = await res.json();
        if (data.success) {
            let list = data.data;
            if (data.data && data.data.data) list = data.data.data;
            renderTable("projectBPCatalogResult", list, `Project ${projNo} BP Catalog`, data.data);
        } else {
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed: ${JSON.stringify(data.data)}</div>`;
        }
    });

    // --- FETCH PROJECT BP RECORDS ---
    document.getElementById("btnFetchProjectBPRecords").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        const projNo = document.getElementById("projectNo").value.trim();
        const bpName = document.getElementById("projectBpName").value.trim();
        if (!token || !projNo || !bpName) return alert("Token, Project Number, and BP Name are required.");
        const resArea = document.getElementById("projectBPRecordsResult");
        resArea.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Querying Project ${projNo} BP '${bpName}'...`;

        const payload = {
            bearer_token: token,
            base_url: getBaseUrl(),
            project_number: projNo,
            bpname: bpName,
            filter_condition: document.getElementById("projectFilterCond").value.trim(),
            lineitem: document.getElementById("p_lineitem").checked ? "yes" : "no",
            lineitem_file: document.getElementById("p_lineitem_file").checked ? "yes" : "no",
            general_comments: document.getElementById("p_general_comments").checked ? "yes" : "no",
            attach_all_publications: document.getElementById("p_attach_all_publications").checked ? "yes" : "no"
        };

        const res = await fetch("/api/project-bp-records", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            let list = data.data;
            if (data.data && data.data.data) list = data.data.data;
            renderTable("projectBPRecordsResult", list, `Project ${projNo} BP: ${bpName}`, data.data);
        } else {
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed: ${JSON.stringify(data.data)}</div>`;
        }
    });

    // --- DOWNLOAD FILE ATTACHMENT ---
    document.getElementById("btnDownloadFile").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        let payloadJson;
        try {
            payloadJson = JSON.parse(document.getElementById("filePayload").value.trim());
        } catch (e) {
            return alert("Invalid Payload JSON syntax.");
        }

        const resArea = document.getElementById("downloadResult");
        resArea.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Downloading file...';

        const res = await fetch("/api/download-file", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bearer_token: token, base_url: getBaseUrl(), payload: payloadJson })
        });

        if (res.ok && res.headers.get("content-type") === "application/octet-stream") {
            const blob = await res.blob();
            const fileName = payloadJson.file_name || "download.bin";
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = fileName;
            a.click();
            resArea.innerHTML = `<div class="status-indicator success">✓ Downloaded file: <b>${fileName}</b> (${blob.size} bytes)</div>`;
        } else {
            const errData = await res.json();
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed to download: ${JSON.stringify(errData)}</div>`;
        }
    });

    // --- FETCH USERS ---
    document.getElementById("btnFetchUsers").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        if (!token) return alert("Please enter a Bearer Token.");
        const resArea = document.getElementById("usersResult");
        resArea.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Querying user directory...';

        const res = await fetch("/api/users", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bearer_token: token,
                base_url: getBaseUrl(),
                filter_condition: document.getElementById("userFilterCond").value.trim()
            })
        });
        const data = await res.json();
        if (data.success) {
            let list = data.data;
            if (data.data && data.data.data) list = data.data.data;
            renderTable("usersResult", list, "User Administration Directory", data.data);
        } else {
            resArea.innerHTML = `<div class="status-indicator error">✕ Failed: ${JSON.stringify(data.data)}</div>`;
        }
    });

    // --- API EXPLORER ---
    document.getElementById("btnExecCustom").addEventListener("click", async () => {
        const token = bearerToken.value.trim();
        if (!token) return alert("Please enter a Bearer Token.");
        const resArea = document.getElementById("explorerResult");
        resArea.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Executing REST request...';

        let jsonBody = null;
        let customHeaders = null;

        try {
            const b = document.getElementById("expBody").value.trim();
            if (b) jsonBody = JSON.parse(b);
        } catch (e) { return alert("Invalid JSON body."); }

        try {
            const h = document.getElementById("expHeaders").value.trim();
            if (h) customHeaders = JSON.parse(h);
        } catch (e) { return alert("Invalid custom headers JSON."); }

        const res = await fetch("/api/custom-request", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                bearer_token: token,
                base_url: getBaseUrl(),
                method: document.getElementById("expMethod").value,
                endpoint: document.getElementById("expEndpoint").value.trim(),
                json_body: jsonBody,
                custom_headers: customHeaders
            })
        });
        const data = await res.json();
        resArea.innerHTML = `
            <div class="card margin-top">
                <h4>Status: <span class="badge ${data.success ? 'badge-post' : 'badge-get'}">${data.status_code} (${data.elapsed_ms.toFixed(1)}ms)</span></h4>
                <pre class="code-font margin-top">${JSON.stringify(data.data, null, 2)}</pre>
            </div>
        `;
    });

    // --- FULL PAGE AI CHAT LOGIC (ChatGPT Style) ---
    const chatMessagesFull = document.getElementById("chatMessagesFull");
    const chatInputFull = document.getElementById("chatInputFull");
    const btnSendChatFull = document.getElementById("btnSendChatFull");
    const chatHistoryList = document.getElementById("chatHistoryList");
    const btnNewChatFull = document.getElementById("btnNewChatFull");
    const chatTitleDisplay = document.getElementById("chatTitleDisplay");

    let currentConversationId = null;
    let chatHistory = []; // local cache for current session

    async function loadConversations() {
        try {
            const res = await fetch("/api/conversations");
            const convos = await res.json();
            chatHistoryList.innerHTML = "";
            convos.forEach(c => {
                const div = document.createElement("div");
                div.className = `history-item ${c.id === currentConversationId ? 'active' : ''}`;
                div.innerHTML = `<i class="fa-regular fa-message"></i> ${c.title || "New Chat"}`;
                div.onclick = () => loadConversation(c.id, c.title);
                
                // Add delete button (hover effect handled via css or simple icon)
                const delBtn = document.createElement("i");
                delBtn.className = "fa-solid fa-trash";
                delBtn.style.marginLeft = "auto";
                delBtn.style.opacity = "0.5";
                delBtn.onclick = async (e) => {
                    e.stopPropagation();
                    if(confirm("Delete this chat?")) {
                        await fetch(`/api/conversations/${c.id}`, { method: "DELETE" });
                        if(currentConversationId === c.id) {
                            startNewChat();
                        } else {
                            loadConversations();
                        }
                    }
                };
                div.appendChild(delBtn);
                chatHistoryList.appendChild(div);
            });
        } catch (e) {
            console.error("Failed to load conversations", e);
        }
    }

    async function loadConversation(id, title) {
        currentConversationId = id;
        chatTitleDisplay.innerText = title || "AI Chat";
        chatMessagesFull.innerHTML = '<div class="message assistant"><div class="message-content"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div></div>';
        
        try {
            const res = await fetch(`/api/conversations/${id}`);
            const msgs = await res.json();
            chatMessagesFull.innerHTML = "";
            chatHistory = [];
            msgs.forEach(m => {
                appendMessage(m.role, m.content);
                chatHistory.push(m);
            });
            loadConversations(); // refresh active state
        } catch (e) {
            chatMessagesFull.innerHTML = `<div class="message assistant"><div class="message-content">Failed to load chat.</div></div>`;
        }
    }

    function startNewChat() {
        currentConversationId = null;
        chatHistory = [];
        chatTitleDisplay.innerText = "New Chat";
        chatMessagesFull.innerHTML = `
            <div class="message assistant">
                <div class="message-content">Hello! I am your Primavera Unifier AI Assistant. How can I help you today?</div>
            </div>`;
        loadConversations();
    }

    btnNewChatFull.addEventListener("click", startNewChat);

    async function sendChatMessageFull() {
        const text = chatInputFull.value.trim();
        if (!text) return;

        appendMessage("user", text);
        chatHistory.push({ role: "user", content: text });
        chatInputFull.value = "";

        const thinkingId = appendMessage("assistant", '<i class="fa-solid fa-spinner fa-spin"></i> Thinking...');

        try {
            const res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    bearer_token: bearerToken.value.trim(),
                    base_url: getBaseUrl(),
                    openai_api_key: openaiApiKey.value.trim(),
                    groq_api_key: groqApiKey.value.trim(),
                    provider: llmProvider.value,
                    prompt: text,
                    chat_history: chatHistory,
                    conversation_id: currentConversationId
                })
            });
            const data = await res.json();
            const answer = data.answer || "No response received.";
            
            // If it's a new chat, the server returns the new ID
            if (data.conversation_id && !currentConversationId) {
                currentConversationId = data.conversation_id;
            }
            
            chatHistory.push({ role: "assistant", content: answer });

            const msgEl = document.getElementById(thinkingId);
            if (msgEl) {
                msgEl.innerHTML = marked.parse(answer);
            }
            loadConversations(); // refresh list to show updated titles/sorting
        } catch (err) {
            const msgEl = document.getElementById(thinkingId);
            if (msgEl) msgEl.innerText = `Error: ${err.message}`;
        }
    }

    btnSendChatFull.addEventListener("click", sendChatMessageFull);
    chatInputFull.addEventListener("keypress", (e) => {
        if (e.key === "Enter") sendChatMessageFull();
    });

    function appendMessage(role, content) {
        const id = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
        const div = document.createElement("div");
        div.className = `message ${role}`;
        div.innerHTML = `<div id="${id}" class="message-content">${role === 'user' ? content : marked.parse(content)}</div>`;
        chatMessagesFull.appendChild(div);
        chatMessagesFull.scrollTop = chatMessagesFull.scrollHeight;
        return id;
    }

    // Initial load
    loadConversations();
});
