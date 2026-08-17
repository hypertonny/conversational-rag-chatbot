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
    chatHistory = []; // local cache for current session

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

    // --- STAKEHOLDER PERSONA QUESTIONS MAPPING ---
    const personaQuestions = {
        "1": [
            "What needs my attention today across all projects and shells? Rank items by urgency and impact.",
            "Show my overdue and upcoming workflow tasks including record number, BP, step, due date, and required action.",
            "Explain record [record ID] in plain language: purpose, current status, recent changes, and next steps.",
            "Which business process should I use to submit a request vs report an issue vs request approval?",
            "Guide me step by step through completing business process name, including required fields and attachments.",
            "Review my draft record for missing fields, inconsistent values, missing attachments, and return risks.",
            "Summarize the comments, decisions, attachments, and unanswered questions associated with record ID.",
            "Find all records related to vendor/location/CBS/WBS/asset/keyword and group by BP and status.",
            "What changed in project/shell since date that could affect my responsibilities?",
            "Who currently owns record ID, how long has it been at that workflow step, and who acts next?",
            "Show records assigned to me that are missing supporting documents or evidence.",
            "Draft a concise response to the latest reviewer comment on record ID without sending."
        ],
        "2": [
            "Show all inspections scheduled for today and this week by location, discipline, inspector, and status.",
            "List open punch-list items, defects, or nonconformance records in location sorted by severity.",
            "Which open RFIs, submittals, site instructions, or approvals may block work planned in next 14 days?",
            "Prepare a draft daily site report using today's progress records, inspections, issues, and workforce data.",
            "Compare planned progress with reported physical progress for location/work package.",
            "Identify field records that cannot be closed because photographs, test results, or signatures are missing.",
            "Analyze recurring defects or inspection failures by location, contractor, trade, material, and root cause.",
            "Summarize all outstanding site instructions and identify those that could affect cost, schedule, or safety.",
            "Show unresolved safety and quality observations older than X days including corrective action status.",
            "Prepare a draft escalation for issue/record explaining immediate impact and decision deadline.",
            "Create a handover-readiness summary for area/system/package including punch items and documents.",
            "Which upcoming activities lack completed prerequisite inspections or approvals?"
        ],
        "3": [
            "Show all outstanding actions assigned to my organization grouped by project, BP, due date, priority.",
            "Which of our submitted records were returned or rejected during period and what corrections are required?",
            "Show our outstanding submittals and required submission dates for the next 30 days.",
            "Summarize the status of payment application record ID including approved, disputed, and withheld amounts.",
            "Which change requests, quotations, or claim notices require a response from our organization?",
            "Show our contractual deliverables due within the next X days and identify missing evidence.",
            "Explain why invoice/payment application has not progressed and identify current workflow owner.",
            "Draft a response to reviewer comments on record ID addressing each comment separately.",
            "Prepare a draft transmittal for documents associated with package/record.",
            "Summarize decisions or instructions issued to our organization since date.",
            "Identify upcoming work constrained by missing information, access, materials, or approvals.",
            "Compare our actual response times with agreed turnaround times for RFIs, submittals, and corrective actions."
        ],
        "4": [
            "Find the latest approved revision of document number/title and show approval date and superseded versions.",
            "Identify documents with missing or inconsistent metadata including revision, discipline, owner, status.",
            "Show documents awaiting review for longer than the allowed turnaround time.",
            "Detect duplicate document numbers, duplicate files, or potentially conflicting revisions.",
            "Identify superseded documents that may still be linked to active business-process records.",
            "Prepare a distribution list and draft transmittal for document package based on distribution rules.",
            "Show complete revision and approval history for document including reviewers and dates.",
            "List documents referenced by open RFIs, submittals, changes, inspections, and nonconformance records.",
            "Analyze document-review turnaround times by discipline, reviewer, project, and document type.",
            "Which records contain attachments that are not stored or classified correctly in Document Manager?",
            "Prepare a document closeout checklist for project/system/package and show missing deliverables.",
            "Identify documents at final status that lack required approval evidence or distribution records."
        ],
        "5": [
            "Create today's project action register showing action, owner, source record, due date, and status.",
            "Identify workflow bottlenecks by business process, workflow step, assignee, and average age.",
            "Show records with no activity for more than X days and recommend appropriate follow-up.",
            "Prepare a draft weekly project status report covering progress, cost, schedule, changes, risks, quality.",
            "Extract decisions, commitments, owners, and due dates from meeting record/minutes/thread.",
            "Identify data-quality exceptions across project/shell including missing owners and invalid dates.",
            "Show approvals due during next 7 days and identify those that could affect a milestone or payment.",
            "Map dependencies between open RFIs, submittals, changes, issues, risks, and schedule activities.",
            "Compare this week's open-action position with last week's and explain major movements.",
            "Prepare a month-end controls checklist and show which required updates are incomplete.",
            "Identify records ready for closure and records open only due to missing administrative info.",
            "Create a concise follow-up message for each overdue action owner (draft only)."
        ],
        "6": [
            "Provide a cost-health summary for project/program including budget, commitments, actuals, forecast, EAC.",
            "Show largest cost variances by CBS code, work package, contract, and vendor and explain drivers.",
            "Explain how forecast changed between cutoffs separating scope, quantity, rate, schedule, risk impacts.",
            "Quantify approved, pending, rejected, and potential change exposure and high/expected/low outcomes.",
            "Analyze contingency usage to date and forecast whether remaining contingency is sufficient.",
            "Show available and uncommitted budget by CBS code and identify possible funding shortfalls.",
            "Forecast cash requirements for next 3/6/12 months using commitments, invoices, and schedule progress.",
            "Estimate current period accrual and identify commitments or work completed not yet invoiced.",
            "Identify unusual cost transactions, duplicate invoices, duplicate line items, or negative values.",
            "Reconcile Unifier cost sheet with ERP/finance system and explain material differences.",
            "Show contracts where paid/invoiced amounts appear inconsistent with approved progress.",
            "What are top 5 cost-overrun risks, probability-weighted impact, and recommended management actions?",
            "Model cost impact if milestone slips by X months.",
            "Model effect of approving change record on budget, contingency, cash flow, and EAC.",
            "Prepare cost narrative for monthly report explaining variances without financial jargon.",
            "Recommend corrective actions to protect approved budget ranked by expected value and urgency."
        ],
        "7": [
            "Show milestones due in next 30, 60, 90 days with current forecast, baseline date, variance, owner.",
            "Identify slipped, critical, or near-critical activities and explain primary causes.",
            "Which open RFIs, submittals, changes, procurement items are linked to critical path activities?",
            "Prepare a 2-week or 6-week look-ahead plan with prerequisites, constraints, owners, decision dates.",
            "Identify progress anomalies including activities reported complete without supporting records.",
            "Compare schedule progress with cost progress and earned-value indicators.",
            "Forecast likely project completion date and state confidence level and major assumptions.",
            "Develop 3 recovery scenarios for delayed milestone showing schedule gain, cost impact, and risk.",
            "Show baseline changes made during period including reason, approver, and milestone impact.",
            "Identify activities that have not been updated within required reporting cycle.",
            "Show future activities whose required procurement, design, access, or approval dates were missed.",
            "Prepare schedule narrative describing period progress, delays, mitigations, and forecast."
        ],
        "8": [
            "Show procurement packages at risk of missing required-on-site or award dates.",
            "Summarize active bid packages, invited bidders, received responses, evaluations, and next action.",
            "Identify contracts, insurance certificates, guarantees, warranties, or licenses near expiration.",
            "Summarize base commitment and change commitment positions by contract and vendor.",
            "Show change orders awaiting quotation, negotiation, recommendation, approval, or incorporation.",
            "Identify contractual notice or claim deadlines occurring during next X days.",
            "Compare vendor performance using response time, quality, delivery, compliance, change frequency.",
            "Calculate commercial exposure by vendor including commitments, pending changes, claims, retention.",
            "Show contract deliverables that are late or missing and identify responsible party.",
            "Explain payment status for vendor/contract including certification, deductions, retention, disputes.",
            "Draft a commercial letter regarding late delivery/rejected work/change notice/payment dispute.",
            "Prepare negotiation brief for change/claim including facts, contractual position, amount, settlement range."
        ],
        "9": [
            "Compare workforce demand with available capacity for next 12 weeks by role, discipline, project.",
            "Identify overallocated and underallocated personnel or roles including conflict periods.",
            "Show skill or certification gaps that could affect upcoming work.",
            "Recommend resource reassignments reducing overload while minimizing cost/schedule disruption.",
            "Identify activities or deliverables that lack an assigned responsible person.",
            "Compare planned effort or staffing with actual effort for period and explain differences.",
            "Show staffing-cost forecast by project, role, internal resource, and external contractor.",
            "Assess resource impact of approving new project/change/recovery plan.",
            "Prepare a ramp-up and ramp-down plan for project phase or work package.",
            "Identify cross-project resource conflicts that threaten priority milestones.",
            "Show upcoming absences, mobilization delays, or expiring certifications creating capacity risk.",
            "Recommend whether to hire, contract, transfer, defer, or reprioritize work to close capacity gap."
        ],
        "10": [
            "Show top project risks ranked by current exposure, trend, proximity, and cost/schedule impact.",
            "Identify risks without an owner, mitigation plan, target date, or recent review.",
            "Compare current risk profile with previous period and explain new, increased, and closed risks.",
            "Link highest risks to affected contracts, cost codes, schedule activities, and decisions.",
            "Identify repeated nonconformances or defects by contractor, trade, material, and root cause.",
            "Show overdue quality inspections, corrective actions, and nonconformance closures.",
            "Analyze safety observations, incidents, and near misses for recurring patterns and leading indicators.",
            "Evaluate whether current risk mitigations are reducing probability or impact as expected.",
            "Identify issues that should be escalated into formal risks or changes.",
            "Prepare a risk escalation brief for risk including trigger, exposure, mitigation options, deadline.",
            "Show records closed without sufficient quality, safety, or risk-control evidence.",
            "Assess quality and HSE readiness of area/system/package for handover or operational use."
        ],
        "11": [
            "Give me a weekly project-health summary covering scope, schedule, cost, changes, risks, quality, safety.",
            "Explain project's current RAG status using measurable evidence rather than subjective statements.",
            "What are 5 most important decisions I need to make this week and impact of delay?",
            "Forecast likely final cost and completion date including confidence range and key uncertainties.",
            "Summarize scope changes since date and explain cumulative cost, schedule, contractual impact.",
            "Identify approvals or workflow tasks blocking progress and recommend escalation path.",
            "Compare contractor and consultant performance against contractual/operational responsibilities.",
            "Summarize stakeholder commitments and identify promises that are late, unclear, or unsupported.",
            "Develop 30-day recovery plan for top project issues with owners, dates, dependencies, outcomes.",
            "Identify problems reported differently across cost, schedule, risk, contract, and field records.",
            "Prepare steering-committee update focusing on exceptions, decisions, and required support.",
            "Prepare questions I should ask cost manager, planner, contractor, risk manager at next meeting.",
            "What has materially changed since last reporting period and why does it matter?",
            "Identify early-warning signals that are not yet reflected in formal project status.",
            "Show project top 10 unresolved actions ranked by business impact rather than age.",
            "Recommend which issues I should resolve directly, delegate, escalate, or monitor."
        ],
        "12": [
            "Rank all projects by overall health and explain evidence behind each ranking.",
            "Show portfolio budget, commitments, actuals, forecast, funding gaps, and contingency.",
            "Identify projects most likely to exceed approved cost, miss key milestone, or fail strategic goal.",
            "Show cross-project resource conflicts and recommend portfolio-level prioritization.",
            "Identify common causes of delay or cost growth across the portfolio.",
            "Analyze supplier and contractor concentration risk across projects and programs.",
            "Compare workflow performance across projects and identify systemic approval bottlenecks.",
            "Show projects not complying with governance, reporting, or stage-gate requirements.",
            "Assess whether capital should be reallocated between projects based on strategic value and risk.",
            "Compare benefits planned, benefits forecast, and benefits realized across portfolio.",
            "Model scenario where annual capital budget is reduced by X percentage.",
            "Model scenario where priority project must finish X months earlier.",
            "Identify projects with unusually optimistic forecasts compared with historical performance.",
            "Prepare portfolio-review pack containing exceptions, trends, decisions, recommendations.",
            "Which project managers or delivery teams require additional support and what evidence supports it?",
            "What portfolio-level decisions produce largest reduction in cost and schedule exposure?"
        ],
        "13": [
            "Reconcile approved budget, commitments, actuals, accruals, payments, and forecast for project.",
            "Show period-close exceptions including incomplete postings, missing accruals, in-flight approvals.",
            "Forecast cash requirements by month, project, vendor, and funding source.",
            "Show remaining fund availability and identify projects approaching funding limits.",
            "Identify duplicate invoices, duplicate payment applications, or suspicious amounts.",
            "Identify transactions inconsistent with delegated authority or approval limits.",
            "Analyze segregation-of-duties risks including users creating, reviewing, approving related records.",
            "Show manual overrides, backdated changes, reopened records, and unusual audit-log activity.",
            "Identify commitments or changes approved without sufficient budget or funding.",
            "Prepare audit sample of high-value, high-risk, unusual, and randomly selected transactions.",
            "Trace cost-sheet amount back to originating BP records and supporting documents.",
            "Show transactions whose financial status differs between Unifier and ERP/finance system.",
            "Prepare funding-compliance report for funding source/program.",
            "Identify amounts requiring accounting-policy review before capital or operating classification.",
            "Summarize outstanding retention, withholding, claims, and disputed amounts.",
            "Prepare month-end financial-control certification with unresolved exceptions listed."
        ],
        "14": [
            "Give me a one-page portfolio summary: performance, outlook, top exposures, achievements, decisions.",
            "Where does executive intervention have the highest potential value?",
            "Which projects require a decision in next 30 days and financial/strategic consequence of delay?",
            "Show how current capital spending aligns with organizational strategy and priority outcomes.",
            "Which projects should be accelerated, recovered, paused, rescoped, or stopped and why?",
            "Summarize top 5 portfolio risks in business terms including downside exposure and mitigation.",
            "Show forecast cost and completion ranges rather than single-point estimates.",
            "How reliable are current project forecasts and which projects have low data confidence?",
            "Explain business impact of largest pending changes and claims.",
            "Compare current portfolio performance with approved annual plan.",
            "Show expected benefits, delayed benefits, and benefits at risk.",
            "Model effect of X percentage capital-budget reduction on strategic outcomes.",
            "What are top 3 questions I should ask each project director?",
            "Prepare board-ready narrative distinguishing confirmed facts, forecasts, and management judgment.",
            "Identify bad news that may be hidden by aggregated reporting.",
            "Summarize decisions made at previous steering meeting and whether they produced expected result."
        ],
        "15": [
            "Explain configured purpose, fields, statuses, workflow, permissions, and impacts of BP.",
            "Draw workflow path for BP including conditional routes, approvers, due dates, terminal statuses.",
            "Analyze workflow history and identify steps creating greatest delay, rework, or rejection.",
            "Identify users or groups with excessive, conflicting, unused, or missing permissions.",
            "Show data lineage for data element/report metric/cost column from source record to calculation.",
            "Validate formula or roll-up logic for field/cost column using sample records.",
            "Test proposed auto-creation rule for BP and identify duplicate or missing creation scenarios.",
            "Compare 2 versions of BP configuration and summarize functional, security, reporting impacts.",
            "Identify reports or dashboards using inconsistent definitions for same KPI.",
            "Diagnose failed or delayed integrations between Unifier and ERP/P6/Oracle Primavera Cloud.",
            "Show integration records that failed, partially processed, duplicated, or were unacknowledged.",
            "Review bulk-import file for formatting, required fields, invalid values, duplicate keys.",
            "Find orphaned records, invalid links, broken references, or records without downstream BPs.",
            "Generate configuration test cases for new workflow/process including positive/negative/boundary tests.",
            "Assess impact of proposed configuration change on existing records, reports, integrations.",
            "Analyze user adoption by process, role, project, frequency and identify where training is needed."
        ],
        "16": [
            "Map user request sample request to correct intent, entities, Unifier data sources, permissions.",
            "Generate representative evaluation set for chatbot covering simple, ambiguous, multi-project requests.",
            "Evaluate chatbot answer against source records and classify each statement as supported/inferred/incorrect.",
            "Test whether chatbot exposes information that requesting user is not authorized to see.",
            "Red-team chatbot against prompt injection in comments, attachments, document text, or descriptions.",
            "Identify sensitive fields that should be masked, summarized, or excluded for each user role.",
            "Define confidence thresholds for answering directly, answering with warning, or refusing to infer.",
            "Design citation format linking every major conclusion to record number, BP, project, as-of date.",
            "Create policy for draft, submit, approve, reject, route, update, delete actions with audit requirements.",
            "Analyze chatbot searches returning no result and classify cause (terminology, permissions, indexing).",
            "Identify common user synonyms and map to Unifier terminology (project vs shell, PO vs commitment).",
            "Check whether KPI definitions are consistent across chatbot, dashboards, reports, summaries.",
            "Create hallucination tests involving missing records, nonexistent projects, invalid record numbers.",
            "Evaluate whether chatbot clearly separates source facts, calculated values, assumptions, predictions.",
            "Create audit record design for interaction (user, question, sources, answer, confidence, action).",
            "Summarize user feedback and failed conversations into prioritized improvements for prompts."
        ]
    };

    const personaSelector = document.getElementById("personaSelector");
    const personaQuestionSelector = document.getElementById("personaQuestionSelector");

    function updatePersonaQuestions() {
        if (!personaSelector || !personaQuestionSelector) return;
        const personaId = personaSelector.value || "1";
        const questions = personaQuestions[personaId] || [];
        personaQuestionSelector.innerHTML = '<option value="">-- Select a sample question for this role --</option>';
        questions.forEach((q, idx) => {
            const opt = document.createElement("option");
            opt.value = q;
            opt.textContent = `${idx + 1}. ${q.length > 80 ? q.substr(0, 80) + '...' : q}`;
            personaQuestionSelector.appendChild(opt);
        });
    }

    if (personaSelector && personaQuestionSelector) {
        personaSelector.addEventListener("change", updatePersonaQuestions);
        personaQuestionSelector.addEventListener("change", (e) => {
            const val = e.target.value;
            if (val) {
                chatInputFull.value = val;
                sendChatMessageFull();
                e.target.value = "";
            }
        });
        updatePersonaQuestions(); // initial load
    }

    // Quick Action Pill Click Handlers
    document.querySelectorAll(".btn-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            const promptText = pill.dataset.prompt;
            if (promptText) {
                chatInputFull.value = promptText;
                sendChatMessageFull();
            }
        });
    });

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
