import json
import pandas as pd
import streamlit as st
from unifier_client import UnifierClient
from chatbot_engine import ChatbotEngine

# Set Page Config
st.set_page_config(
    page_title="Oracle Primavera Unifier REST API Dashboard",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for Modern Aesthetic Design
st.markdown("""
<style>
    /* Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Main Container Styles */
    .stApp {
        background-color: #0e1117;
        color: #e0e6ed;
    }

    /* Top Hero Header */
    .hero-container {
        background: linear-gradient(135deg, #1e2640 0%, #0f172a 100%);
        border: 1px solid #2e3a59;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 24px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }
    
    .hero-title {
        font-size: 26px;
        font-weight: 700;
        color: #38bdf8;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .hero-subtitle {
        color: #94a3b8;
        font-size: 14px;
        margin-bottom: 0;
    }

    /* Badge & Card Components */
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-success { background-color: #064e3b; color: #34d399; border: 1px solid #059669; }
    .badge-error { background-color: #7f1d1d; color: #f87171; border: 1px solid #dc2626; }
    .badge-warning { background-color: #78350f; color: #fbbf24; border: 1px solid #d97706; }
    .badge-info { background-color: #1e3a8a; color: #60a5fa; border: 1px solid #2563eb; }

    .card-box {
        background: #161e2e;
        border: 1px solid #243049;
        border-radius: 10px;
        padding: 18px;
        margin-bottom: 16px;
    }

    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #111827;
        padding: 6px;
        border-radius: 10px;
        border: 1px solid #1f2937;
    }

    .stTabs [data-baseweb="tab"] {
        height: 44px;
        border-radius: 8px;
        color: #9ca3af;
        font-weight: 500;
        padding: 0 16px;
    }

    .stTabs [aria-selected="true"] {
        background-color: #2563eb !important;
        color: #ffffff !important;
        font-weight: 600;
    }

    /* Code block container tweak */
    div.stCodeBlock {
        border-radius: 8px;
        border: 1px solid #374151;
    }

    /* Workflow Visualizer Stepper Styles */
    .workflow-stepper {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #111827;
        padding: 16px 20px;
        border-radius: 12px;
        border: 1px solid #1f2937;
        margin: 16px 0;
    }
    
    .wf-step {
        text-align: center;
        flex: 1;
        position: relative;
    }
    
    .wf-badge {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 14px;
        margin-bottom: 6px;
    }
    
    .wf-done { background: #059669; color: #ffffff; box-shadow: 0 0 10px rgba(5, 150, 105, 0.5); }
    .wf-active { background: #0284c7; color: #ffffff; box-shadow: 0 0 12px rgba(2, 132, 199, 0.7); border: 2px solid #38bdf8; }
    .wf-pending { background: #374151; color: #9ca3af; }
    
    .wf-label { font-size: 12px; font-weight: 600; color: #e2e8f0; }
    .wf-sub { font-size: 10px; color: #64748b; }
</style>
""", unsafe_allow_html=True)


import os

# Initialize Session State with environment variable fallbacks for Dokploy deployment
if "bearer_token" not in st.session_state:
    st.session_state.bearer_token = os.getenv("UNIFIER_BEARER_TOKEN", "")

if "base_url" not in st.session_state:
    st.session_state.base_url = os.getenv("UNIFIER_BASE_URL", UnifierClient.DEFAULT_BASE_URL)

if "active_projects_df" not in st.session_state:
    st.session_state.active_projects_df = None

if "selected_project_no" not in st.session_state:
    st.session_state.selected_project_no = ""

if "conn_status" not in st.session_state:
    st.session_state.conn_status = None

if "openai_api_key" not in st.session_state:
    st.session_state.openai_api_key = os.getenv("OPENAI_API_KEY", "")

if "groq_api_key" not in st.session_state:
    st.session_state.groq_api_key = os.getenv("GROQ_API_KEY", "")

if "llm_provider" not in st.session_state:
    st.session_state.llm_provider = os.getenv("LLM_PROVIDER", "groq").lower()

if "chatbot_messages" not in st.session_state:
    st.session_state.chatbot_messages = [{"role": "assistant", "content": "Hello! I am your Primavera Unifier AI Assistant. How can I help?"}]

if "chatbot_engine" not in st.session_state:
    st.session_state.chatbot_engine = ChatbotEngine()


# --- SIDEBAR ---
with st.sidebar:
    st.image("https://img.icons8.com/?size=100&id=102558&format=png", width=50)
    st.title("Primavera Unifier")
    st.caption("REST API v1 Management Console")
    st.markdown("---")

    st.subheader("🔑 Authentication & Config")

    # Environment selector
    env_choice = st.selectbox(
        "Environment Endpoint",
        ["Consulting Test Environment", "Production Environment", "Custom Base URL"],
        index=0
    )

    if env_choice == "Consulting Test Environment":
        current_base_url = "https://us2.unifier.oraclecloud.com/consulting/test/ws/rest/service/v1"
    elif env_choice == "Production Environment":
        current_base_url = "https://us2.unifier.oraclecloud.com/ws/rest/service/v1"
    else:
        current_base_url = st.text_input(
            "Custom Base URL",
            value=st.session_state.base_url,
            help="Enter base URL ending in /ws/rest/service/v1"
        )

    st.session_state.base_url = current_base_url

    # Bearer token input
    token_input = st.text_input(
        "Bearer Token",
        value=st.session_state.bearer_token,
        type="password",
        help="Paste your Unifier Bearer Token here."
    )
    st.session_state.bearer_token = token_input

    # OpenAI/Groq API Key Input for Chatbot
    st.markdown("---")
    st.subheader("🤖 AI Chatbot Config")
    provider_choice = st.selectbox("LLM Provider", ["OpenAI", "Groq"])
    st.session_state.llm_provider = provider_choice.lower()
    
    if provider_choice == "OpenAI":
        oai_key = st.text_input(
            "OpenAI API Key (Optional)",
            value=st.session_state.openai_api_key,
            type="password",
            help="Provide OpenAI key to enable the conversational AI chatbot."
        )
        if oai_key != st.session_state.openai_api_key:
            st.session_state.openai_api_key = oai_key
            st.session_state.chatbot_engine = ChatbotEngine(openai_api_key=oai_key, groq_api_key=st.session_state.groq_api_key)
    else:
        groq_key = st.text_input(
            "Groq API Key (Optional)",
            value=st.session_state.groq_api_key,
            type="password",
            help="Provide Groq API key for blazing fast LPU inference."
        )
        if groq_key != st.session_state.groq_api_key:
            st.session_state.groq_api_key = groq_key
            st.session_state.chatbot_engine = ChatbotEngine(openai_api_key=st.session_state.openai_api_key, groq_api_key=groq_key)

    st.markdown("---")

    # Test connection button
    if st.button("🔌 Test API Connection", use_container_width=True, type="primary"):
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token first.")
        else:
            with st.spinner("Testing API connection..."):
                client = UnifierClient(
                    bearer_token=st.session_state.bearer_token,
                    base_url=st.session_state.base_url
                )
                success, msg, code = client.test_connection()
                st.session_state.conn_status = {"success": success, "msg": msg, "code": code}

    # Connection Status indicator
    if st.session_state.conn_status:
        st.markdown("<br>", unsafe_allow_html=True)
        stat = st.session_state.conn_status
        if stat["success"]:
            st.markdown(f'<div class="status-badge badge-success">✓ Connected ({stat["msg"]})</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status-badge badge-error">✕ Disconnected: {stat["msg"]}</div>', unsafe_allow_html=True)

    st.markdown("---")

    # Documentation Quick Reference
    st.subheader("📚 Client Documentation Reference")
    with st.expander("📖 Available Guides List"):
        st.markdown("""
        - 📌 **Integration Interface Guide** - REST v1 APIs
        - 📊 **Data Reference Guide** - Data Elements & Views
        - 💼 **Business Processes User Guide** - BP operations
        - 🛠️ **uDesigner User Guide** - Custom BPs & schemas
        - 🚀 **General User Guide** - Basic unifier setup
        - 📈 **Managers User Guide** - Shell & project management
        """)


# Instantiate Client (Persist session for connection pooling to reduce latency)
if "api_client" not in st.session_state:
    st.session_state.api_client = UnifierClient(
        bearer_token=st.session_state.bearer_token,
        base_url=st.session_state.base_url
    )
else:
    # Update token and base url in case user changed them in sidebar
    st.session_state.api_client.bearer_token = st.session_state.bearer_token
    st.session_state.api_client.base_url = st.session_state.base_url

client = st.session_state.api_client


# --- MAIN HEADER ---
st.markdown("""
<div class="hero-container">
    <div class="hero-title">
        <span>🏛️ Oracle Primavera Unifier REST API Portal</span>
    </div>
    <p class="hero-subtitle">
        Interactive dashboard for querying Active Projects, Company-Level Business Processes, Project-Level Business Processes, File Attachments, and REST endpoints.
    </p>
</div>
""", unsafe_allow_html=True)


# --- TABS NAVIGATION ---
tab_overview, tab_projects, tab_company_bp, tab_project_bp, tab_files, tab_users, tab_workflows, tab_explorer = st.tabs([
    "📊 Overview",
    "📁 Active Projects",
    "🏢 Company BPs",
    "🏗️ Project BPs",
    "📎 Attachments",
    "👥 User Admin",
    "🔄 Workflows & Lifecycles",
    "⚡ API Explorer"
])


# ==========================================
# TAB 1: OVERVIEW
# ==========================================
with tab_overview:
    st.subheader("📌 System Overview & Quick Start")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="card-box">
            <h4>1. Authenticate</h4>
            <p style="color:#94a3b8; font-size:13px;">
                Enter your Unifier Bearer Token in the left sidebar. Click <b>Test API Connection</b> to verify permissions.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div class="card-box">
            <h4>2. Query Business Processes</h4>
            <p style="color:#94a3b8; font-size:13px;">
                Navigate to Company or Project BP tabs. Select BP Names (e.g. Vendor, Contract, RFI) and filter conditions.
            </p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div class="card-box">
            <h4>3. Export & Download</h4>
            <p style="color:#94a3b8; font-size:13px;">
                Download BP records, line items, and attached files directly in CSV, Excel, or binary formats.
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### 🔌 Connected Target Environment")
    env_col1, env_col2 = st.columns([2, 1])
    with env_col1:
        st.info(f"**Current Base URL**: `{st.session_state.base_url}`")
    with env_col2:
        if st.session_state.bearer_token:
            st.success("Bearer Token: Loaded (Masked)")
        else:
            st.warning("Bearer Token: Not Provided")

    st.markdown("### 📋 Supported Core Endpoints Summary")
    st.markdown("""
    | Action / Resource | HTTP Method | Endpoint Path | Sample Body / Filter |
    | :--- | :--- | :--- | :--- |
    | **Active Projects List** | `GET` | `/admin/projectshell?Status=Active` | N/A (URL Query Param) |
    | **Company BP Records** | `POST` | `/bp/records/` | `{"bpname": "Vendor", "lineitem": "yes"}` |
    | **Company Record Search** | `POST` | `/bp/records/` | `{"bpname": "Vendor", "filter_condition": "record_no=VEN-0000006"}` |
    | **Project BP Records** | `POST` | `/bp/records/{project_number}` | `{"bpname": "Contract", "lineitem": "yes"}` |
    | **User Administration** | `POST` | `/admin/user/get` | `{"filterCondition": "uuu_user_status=1"}` |
    | **Download Record File** | `POST` | `/bp/record/file` | `{"bpname": "Contract", "record_no": "..."}` |
    """)

    st.markdown("### ⚡ End-to-End System & RAG Data Flow")
    st.graphviz_chart("""
    digraph {
        graph [bgcolor="transparent", rankdir="LR", fontname="Inter"];
        node [shape="rect", style="filled,rounded", fontname="Inter", fontsize=11, fontcolor="#ffffff"];
        edge [fontname="Inter", fontsize=9, color="#475569", fontcolor="#94a3b8"];

        unifier [label="🏛️ Oracle Primavera Unifier\n(REST API v1)", fillcolor="#1e293b", color="#3b82f6"];
        client [label="⚡ Unifier API Client\n(Session Pool)", fillcolor="#1e293b", color="#38bdf8"];
        dashboard [label="📊 Streamlit Dashboard\n(Interactive Portal)", fillcolor="#0f172a", color="#0ea5e9"];
        chroma [label="🗄️ ChromaDB Vector Store\n(Local Embeddings)", fillcolor="#162e2d", color="#10b981"];
        llm [label="🤖 Groq LPU / OpenAI LLM\n(Conversational Engine)", fillcolor="#2e1065", color="#a855f7"];
        user [label="💬 User Floating Chatbot UI", fillcolor="#3b0764", color="#d8b4fe"];

        unifier -> client [label="JSON Response"];
        client -> dashboard [label="Data Tables & Charts"];
        dashboard -> chroma [label="Auto Text Ingestion"];
        user -> chroma [label="Vector Similarity Search"];
        chroma -> llm [label="Context Window"];
        llm -> user [label="RAG Answer Stream"];
    }
    """)


# ==========================================
# TAB 2: ACTIVE PROJECTS (PROJECT SHELL)
# ==========================================
with tab_projects:
    st.subheader("📁 Active Projects (ProjectShell)")
    st.caption("Endpoint: GET `/admin/projectshell?Status=Active`")

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        fetch_projects = st.button("🚀 Fetch Active Projects", type="primary", key="btn_fetch_projects")

    if fetch_projects:
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token in the sidebar first.")
        else:
            with st.spinner("Fetching active projects from Primavera Unifier..."):
                success, data, status_code, elapsed_ms = client.get_active_projects()
                if success:
                    st.success(f"Fetched active projects successfully! (HTTP {status_code} in {elapsed_ms:.1f}ms)")
                    st.session_state.raw_projects_data = data
                    
                    # Try to parse list of projects into DataFrame
                    projects_list = []
                    if isinstance(data, dict):
                        projects_list = data.get("data", data.get("projectshell", data.get("project_list", [data])))
                    elif isinstance(data, list):
                        projects_list = data

                    if isinstance(projects_list, list) and len(projects_list) > 0:
                        df = pd.DataFrame(projects_list)
                        st.session_state.active_projects_df = df
                    else:
                        st.warning("API returned success, but no project records array was found in JSON structure.")
                        
                    # Feed to chatbot
                    st.session_state.chatbot_engine.ingest_json_data(data, source_name="Active Projects List")
                else:
                    st.error(f"Failed to fetch projects (HTTP {status_code}): {data}")

    if st.session_state.active_projects_df is not None:
        df = st.session_state.active_projects_df
        st.markdown(f"**Total Active Projects Found**: `{len(df)}`")

        # Filters & Search
        search_query = st.text_input("🔍 Search Projects (Filter by any column)", "")
        if search_query:
            mask = df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)
            filtered_df = df[mask]
        else:
            filtered_df = df

        st.dataframe(filtered_df, use_container_width=True, height=350)

        # Quick Select for Project BP queries
        st.markdown("#### 🎯 Select Project for BP Queries")
        col_sel1, col_sel2 = st.columns([2, 1])
        
        # Look for common project number column names
        proj_no_cols = [c for c in df.columns if 'project' in c.lower() or 'number' in c.lower() or 'code' in c.lower() or 'shell' in c.lower()]
        sel_col = proj_no_cols[0] if proj_no_cols else df.columns[0]
        
        with col_sel1:
            selected_val = st.selectbox("Select Project Code/Number", df[sel_col].dropna().unique())
        with col_sel2:
            if st.button("Set Active Project Number"):
                st.session_state.selected_project_no = str(selected_val)
                st.success(f"Selected project: `{selected_val}`! Switch to 'Project BPs' tab to fetch records.")

        # Export Options
        st.markdown("#### 💾 Export Data")
        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
            csv_data = filtered_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Download CSV",
                data=csv_data,
                file_name="active_projects.csv",
                mime="text/csv"
            )
        with exp_col2:
            if 'raw_projects_data' in st.session_state:
                json_str = json.dumps(st.session_state.raw_projects_data, indent=2)
                st.download_button(
                    "📥 Download Raw JSON",
                    data=json_str,
                    file_name="active_projects.json",
                    mime="application/json"
                )
    elif 'raw_projects_data' in st.session_state:
        st.subheader("Raw Projects API Response")
        st.json(st.session_state.raw_projects_data)


# ==========================================
# TAB 3: COMPANY-LEVEL BUSINESS PROCESSES
# ==========================================
with tab_company_bp:
    st.subheader("🏢 Company-Level Business Processes")
    st.caption("Endpoint: POST `/bp/records/`")

    with st.form("company_bp_form"):
        col_bp1, col_bp2 = st.columns(2)
        with col_bp1:
            bp_name = st.text_input("Business Process Name (bpname)", value="Vendor", help="e.g. Vendor, Company BP, etc.")
            filter_cond = st.text_input("Filter Condition (optional)", value="", help="e.g. record_no=VEN-0000006 or status='Active'")
        with col_bp2:
            st.markdown("**Include Details in Payload:**")
            inc_lineitem = st.checkbox("Line Items (lineitem)", value=False)
            inc_lineitem_file = st.checkbox("Line Item Files (lineitem_file)", value=False)
            inc_comments = st.checkbox("General Comments (general_comments)", value=False)
            inc_publications = st.checkbox("Attach All Publications (attach_all_publications)", value=False)

        submit_company_bp = st.form_submit_button("🚀 Fetch Company BP Records", type="primary")

    if submit_company_bp:
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token in the sidebar.")
        elif not bp_name:
            st.error("Business Process Name is required.")
        else:
            with st.spinner(f"Querying Company BP '{bp_name}'..."):
                success, data, status_code, elapsed_ms = client.get_company_bp_records(
                    bpname=bp_name,
                    filter_condition=filter_cond,
                    lineitem="yes" if inc_lineitem else "no",
                    lineitem_file="yes" if inc_lineitem_file else "no",
                    general_comments="yes" if inc_comments else "no",
                    attach_all_publications="yes" if inc_publications else "no"
                )

                st.session_state.company_bp_res = {
                    "success": success,
                    "data": data,
                    "status_code": status_code,
                    "elapsed_ms": elapsed_ms,
                    "bpname": bp_name
                }
                if success:
                    st.session_state.chatbot_engine.ingest_json_data(data, source_name=f"Company BP: {bp_name}")

    if "company_bp_res" in st.session_state:
        res = st.session_state.company_bp_res
        if res["success"]:
            st.success(f"Successfully fetched BP '{res['bpname']}' records! (HTTP {res['status_code']} in {res['elapsed_ms']:.1f}ms)")

            sub_tab_table, sub_tab_json = st.tabs(["📊 Table View", "🔍 Raw JSON"])
            
            with sub_tab_table:
                data = res["data"]
                records = []
                if isinstance(data, dict):
                    records = data.get("data", data.get("records", data.get("row", [data])))
                elif isinstance(data, list):
                    records = data

                if isinstance(records, list) and len(records) > 0:
                    df_bp = pd.DataFrame(records)
                    st.dataframe(df_bp, use_container_width=True)

                    # Export options
                    st.download_button(
                        "📥 Download CSV",
                        data=df_bp.to_csv(index=False).encode('utf-8'),
                        file_name=f"company_bp_{res['bpname']}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("Response received cleanly, but no top-level record array was detected in standard structure.")
                    st.json(data)

            with sub_tab_json:
                st.json(res["data"])
        else:
            st.error(f"Error fetching Company BP records (HTTP {res['status_code']}): {res['data']}")


# ==========================================
# TAB 4: PROJECT-LEVEL BUSINESS PROCESSES
# ==========================================
with tab_project_bp:
    st.subheader("🏗️ Project / Shell-Level Business Processes")
    st.caption("Endpoint: POST `/bp/records/{project_number}`")

    # Display active project selection indicator
    if st.session_state.selected_project_no:
        st.info(f"Selected Project Number: `{st.session_state.selected_project_no}` (from Active Projects tab)")

    with st.form("project_bp_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            proj_no_input = st.text_input(
                "Project Number / Code",
                value=st.session_state.selected_project_no or "001",
                help="e.g. 001, PRJ-1001, etc."
            )
            p_bp_name = st.text_input("Business Process Name (bpname)", value="Contract", help="e.g. Contract, Submittal, RFI, Change Order")
            p_filter_cond = st.text_input("Filter Condition (optional)", value="", help="e.g. record_no=CON-0000001")
        
        with col_p2:
            st.markdown("**Include Details in Payload:**")
            p_inc_lineitem = st.checkbox("Line Items (lineitem)", value=False, key="p_li")
            p_inc_lineitem_file = st.checkbox("Line Item Files (lineitem_file)", value=False, key="p_lif")
            p_inc_comments = st.checkbox("General Comments (general_comments)", value=False, key="p_gc")
            p_inc_publications = st.checkbox("Attach All Publications (attach_all_publications)", value=False, key="p_aap")

        submit_proj_bp = st.form_submit_button("🚀 Fetch Project BP Records", type="primary")

    if submit_proj_bp:
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token in the sidebar.")
        elif not proj_no_input:
            st.error("Project Number is required.")
        elif not p_bp_name:
            st.error("Business Process Name is required.")
        else:
            with st.spinner(f"Fetching BP '{p_bp_name}' for Project '{proj_no_input}'..."):
                success, data, status_code, elapsed_ms = client.get_project_bp_records(
                    project_number=proj_no_input,
                    bpname=p_bp_name,
                    filter_condition=p_filter_cond,
                    lineitem="yes" if p_inc_lineitem else "no",
                    lineitem_file="yes" if p_inc_lineitem_file else "no",
                    general_comments="yes" if p_inc_comments else "no",
                    attach_all_publications="yes" if p_inc_publications else "no"
                )

                st.session_state.proj_bp_res = {
                    "success": success,
                    "data": data,
                    "status_code": status_code,
                    "elapsed_ms": elapsed_ms,
                    "bpname": p_bp_name,
                    "project_no": proj_no_input
                }
                if success:
                    st.session_state.chatbot_engine.ingest_json_data(data, source_name=f"Project {proj_no_input} BP: {p_bp_name}")

    if "proj_bp_res" in st.session_state:
        res = st.session_state.proj_bp_res
        if res["success"]:
            st.success(f"Fetched BP '{res['bpname']}' for Project '{res['project_no']}'! (HTTP {res['status_code']} in {res['elapsed_ms']:.1f}ms)")

            sub_p_table, sub_p_json = st.tabs(["📊 Table View", "🔍 Raw JSON"])

            with sub_p_table:
                data = res["data"]
                records = []
                if isinstance(data, dict):
                    records = data.get("data", data.get("records", data.get("row", [data])))
                elif isinstance(data, list):
                    records = data

                if isinstance(records, list) and len(records) > 0:
                    df_p_bp = pd.DataFrame(records)
                    st.dataframe(df_p_bp, use_container_width=True)

                    st.download_button(
                        "📥 Download CSV",
                        data=df_p_bp.to_csv(index=False).encode('utf-8'),
                        file_name=f"project_{res['project_no']}_bp_{res['bpname']}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("Response received, display raw format:")
                    st.json(data)

            with sub_p_json:
                st.json(res["data"])
        else:
            st.error(f"Error fetching Project BP records (HTTP {res['status_code']}): {res['data']}")


# ==========================================
# TAB 5: FILE ATTACHMENT DOWNLOADER
# ==========================================
with tab_files:
    st.subheader("📎 File Attachment Downloader")
    st.caption("Endpoint: POST `/bp/record/file`")

    st.markdown("Download attachments associated with Business Process records by supplying JSON details.")

    default_file_payload = json.dumps({
        "bpname": "Contract",
        "record_no": "CON-0000001",
        "file_name": "sample_document.pdf"
    }, indent=2)

    file_payload_str = st.text_area(
        "Request JSON Payload for File Download",
        value=default_file_payload,
        height=180,
        help="JSON payload containing bpname, record_no, file_name, or custom attachment keys required by your Unifier environment."
    )

    if st.button("📥 Request & Download File", type="primary"):
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token in sidebar.")
        else:
            try:
                payload_dict = json.loads(file_payload_str)
                with st.spinner("Downloading file from Primavera Unifier..."):
                    success, content_or_err, status_code, elapsed_ms, resp_headers = client.download_bp_file(payload_dict)

                    if success and isinstance(content_or_err, bytes):
                        st.success(f"File downloaded successfully! (HTTP {status_code} in {elapsed_ms:.1f}ms)")
                        
                        # Guess filename from payload or headers
                        download_name = payload_dict.get("file_name", "unifier_attachment.bin")
                        if "content-disposition" in resp_headers:
                            cd = resp_headers["content-disposition"]
                            if "filename=" in cd:
                                download_name = cd.split("filename=")[-1].strip('"\'')

                        st.download_button(
                            label=f"💾 Save Download ({download_name})",
                            data=content_or_err,
                            file_name=download_name,
                            mime="application/octet-stream"
                        )
                    else:
                        st.error(f"Failed to download file (HTTP {status_code}): {content_or_err}")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON syntax in request payload: {str(e)}")


# ==========================================
# TAB 6: USER ADMIN
# ==========================================
with tab_users:
    st.subheader("👥 User Administration")
    st.caption("Endpoint: POST `/admin/user/get`")

    with st.form("user_admin_form"):
        u_filter = st.text_input("Filter Condition (optional)", value="", help="e.g. uuu_user_status=1")
        submit_users = st.form_submit_button("🚀 Fetch Users", type="primary")

    if submit_users:
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token in the sidebar.")
        else:
            with st.spinner("Fetching user list from Primavera Unifier..."):
                success, data, status_code, elapsed_ms = client.get_users(filter_condition=u_filter)
                if success:
                    st.success(f"Fetched users successfully! (HTTP {status_code} in {elapsed_ms:.1f}ms)")
                    records = data.get("data", data.get("users", data))
                    if isinstance(records, list) and len(records) > 0:
                        df_u = pd.DataFrame(records)
                        st.dataframe(df_u, use_container_width=True)
                    else:
                        st.json(data)
                        
                    st.session_state.chatbot_engine.ingest_json_data(data, source_name="User Admin List")
                else:
                    st.error(f"Error fetching users (HTTP {status_code}): {data}")


# ==========================================
# TAB 7: WORKFLOWS & LIFECYCLES VISUALIZER
# ==========================================
with tab_workflows:
    st.subheader("🔄 Primavera Unifier Business Process & Workflow Visualizer")
    st.caption("Interactive lifecycle state diagrams, approval pipelines, and dynamic status distribution charts.")

    wf_type = st.selectbox(
        "Select Business Process Workflow Diagram",
        [
            "📜 Contract Lifecycle Workflow",
            "🏢 Vendor Onboarding & Audit Workflow",
            "📑 Request for Information (RFI) Approval Pipeline",
            "👥 User Role & Access Authorization Workflow"
        ]
    )

    if wf_type == "📜 Contract Lifecycle Workflow":
        st.markdown("#### Contract Record State Diagram")
        st.graphviz_chart("""
        digraph {
            graph [bgcolor="transparent", rankdir="LR", fontname="Inter"];
            node [shape="rect", style="filled,rounded", fontname="Inter", fontsize=11, fontcolor="#ffffff"];
            edge [fontname="Inter", fontsize=10, color="#64748b", fontcolor="#cbd5e1"];

            draft [label="1. Draft\n(Initiator)", fillcolor="#334155", color="#64748b"];
            review [label="2. Legal Review\n(Pending Review)", fillcolor="#1e3a8a", color="#3b82f6"];
            approval [label="3. Management Approval\n(Pending Approval)", fillcolor="#78350f", color="#f59e0b"];
            executed [label="4. Executed & Signed\n(Active Contract)", fillcolor="#064e3b", color="#10b981"];
            amendment [label="5. Change Order / Amendment\n(In Revision)", fillcolor="#581c87", color="#a855f7"];
            closed [label="6. Contract Closed\n(Completed)", fillcolor="#18181b", color="#71717a"];

            draft -> review [label="Submit for Review"];
            review -> approval [label="Legal Cleared"];
            review -> draft [label="Reject / Revise"];
            approval -> executed [label="Sign & Approve"];
            approval -> draft [label="Send Back"];
            executed -> amendment [label="Issue Change Order"];
            amendment -> executed [label="Approve Change Order"];
            executed -> closed [label="Final Acceptance"];
        }
        """)

        st.markdown("""
        <div class="workflow-stepper">
            <div class="wf-step">
                <div class="wf-badge wf-done">✓</div>
                <div class="wf-label">Draft</div>
                <div class="wf-sub">Record Initiated</div>
            </div>
            <div style="color:#475569; font-weight:bold;">➔</div>
            <div class="wf-step">
                <div class="wf-badge wf-done">✓</div>
                <div class="wf-label">Legal Review</div>
                <div class="wf-sub">Contracts Team</div>
            </div>
            <div style="color:#475569; font-weight:bold;">➔</div>
            <div class="wf-step">
                <div class="wf-badge wf-active">3</div>
                <div class="wf-label">Approval</div>
                <div class="wf-sub">PMO Manager</div>
            </div>
            <div style="color:#475569; font-weight:bold;">➔</div>
            <div class="wf-step">
                <div class="wf-badge wf-pending">4</div>
                <div class="wf-label">Executed</div>
                <div class="wf-sub">Active Contract</div>
            </div>
            <div style="color:#475569; font-weight:bold;">➔</div>
            <div class="wf-step">
                <div class="wf-badge wf-pending">5</div>
                <div class="wf-label">Closed</div>
                <div class="wf-sub">Finalized</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    elif wf_type == "🏢 Vendor Onboarding & Audit Workflow":
        st.markdown("#### Vendor Onboarding Lifecycle")
        st.graphviz_chart("""
        digraph {
            graph [bgcolor="transparent", rankdir="LR", fontname="Inter"];
            node [shape="rect", style="filled,rounded", fontname="Inter", fontsize=11, fontcolor="#ffffff"];
            edge [fontname="Inter", fontsize=10, color="#64748b", fontcolor="#cbd5e1"];

            app [label="1. Vendor Application\n(Submitted)", fillcolor="#1e3a8a", color="#2563eb"];
            audit [label="2. Compliance & Safety Audit\n(Under Review)", fillcolor="#78350f", color="#d97706"];
            approved [label="3. Approved Vendor List (AVL)\n(Active Vendor)", fillcolor="#064e3b", color="#059669"];
            suspended [label="4. Temporarily Suspended\n(Audit Hold)", fillcolor="#7f1d1d", color="#dc2626"];

            app -> audit [label="Verify Documents"];
            audit -> approved [label="Audit Passed"];
            audit -> app [label="Request Info"];
            approved -> suspended [label="Safety Violation"];
            suspended -> approved [label="Re-certified"];
        }
        """)

    elif wf_type == "📑 Request for Information (RFI) Approval Pipeline":
        st.markdown("#### RFI Workflow Pipeline")
        st.graphviz_chart("""
        digraph {
            graph [bgcolor="transparent", rankdir="LR", fontname="Inter"];
            node [shape="rect", style="filled,rounded", fontname="Inter", fontsize=11, fontcolor="#ffffff"];
            edge [fontname="Inter", fontsize=10, color="#64748b", fontcolor="#cbd5e1"];

            contractor [label="Contractor / Subcontractor\n(Submit RFI)", fillcolor="#1e293b", color="#3b82f6"];
            pm [label="Project Manager\n(Triage & Assign)", fillcolor="#1e3a8a", color="#60a5fa"];
            eng [label="Architect / Engineer\n(Technical Solution)", fillcolor="#581c87", color="#c084fc"];
            closed [label="RFI Response Issued\n(Closed Record)", fillcolor="#064e3b", color="#34d399"];

            contractor -> pm [label="Submit RFI"];
            pm -> eng [label="Forward to Engineer"];
            eng -> pm [label="Provide Technical Answer"];
            pm -> contractor [label="Official Response Sent"];
            pm -> closed [label="Mark Resolved"];
        }
        """)

    elif wf_type == "👥 User Role & Access Authorization Workflow":
        st.markdown("#### User Administration Authorization Pipeline")
        st.graphviz_chart("""
        digraph {
            graph [bgcolor="transparent", rankdir="LR", fontname="Inter"];
            node [shape="rect", style="filled,rounded", fontname="Inter", fontsize=11, fontcolor="#ffffff"];
            edge [fontname="Inter", fontsize=10, color="#64748b", fontcolor="#cbd5e1"];

            req [label="User Account Request\n(New User)", fillcolor="#1e293b", color="#94a3b8"];
            auth [label="Identity Verification\n(SSO / IAM)", fillcolor="#1e3a8a", color="#3b82f6"];
            permission [label="Group & Permission Mapping\n(Shell & BP Permission)", fillcolor="#581c87", color="#a855f7"];
            active [label="Active Integration User\n(Status = 1)", fillcolor="#064e3b", color="#10b981"];

            req -> auth [label="Submit Info"];
            auth -> permission [label="IAM Validated"];
            permission -> active [label="Grant Access"];
        }
        """)

    # Dynamic Record Status Distribution Chart (Plotly)
    st.markdown("---")
    st.markdown("#### 📊 Dynamic Record Status Analytics")
    
    import plotly.express as px
    # Sample status distribution chart based on session state or standard metrics
    status_counts = {"Active / Approved": 14, "Pending Approval": 5, "In Review": 3, "Draft": 2, "Closed": 8}
    
    fig = px.pie(
        names=list(status_counts.keys()),
        values=list(status_counts.values()),
        title="Business Process Status Distribution",
        color_discrete_sequence=px.colors.qualitative.Pastel,
        hole=0.4
    )
    fig.update_layout(
        paper_bgcolor="#161e2e",
        plot_bgcolor="#161e2e",
        font_color="#e0e6ed",
        margin=dict(l=20, r=20, t=40, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)


# ==========================================
# TAB 8: API EXPLORER & REST TESTER
# ==========================================
with tab_explorer:
    st.subheader("⚡ API Explorer & REST Tester")
    st.caption("Test any endpoint in the Unifier REST API suite with custom HTTP methods, headers, and request bodies.")

    col_exp1, col_exp2 = st.columns([1, 3])
    with col_exp1:
        http_method = st.selectbox("HTTP Method", ["GET", "POST", "PUT", "DELETE"], index=1)
    with col_exp2:
        endpoint_url = st.text_input(
            "Endpoint Path or Full URL",
            value="/bp/records/",
            help="Relative path (e.g. /admin/projectshell) or absolute URL."
        )

    col_exp_body, col_exp_hdr = st.columns(2)
    with col_exp_body:
        st.markdown("**Request JSON Body**")
        default_body = json.dumps({
            "bpname": "Vendor",
            "lineitem": "yes",
            "lineitem_file": "yes",
            "general_comments": "yes",
            "attach_all_publications": "yes"
        }, indent=2)
        req_body_str = st.text_area("JSON Body", value=default_body, height=200)

    with col_exp_hdr:
        st.markdown("**Additional Custom Headers (JSON)**")
        default_hdr = json.dumps({"X-Custom-Header": "UnifierPortal"}, indent=2)
        req_hdr_str = st.text_area("Headers JSON", value=default_hdr, height=200)

    if st.button("🔥 Execute Request", type="primary", key="btn_exec_custom"):
        if not st.session_state.bearer_token:
            st.error("Please enter a Bearer Token in sidebar.")
        else:
            try:
                json_data = json.loads(req_body_str) if req_body_str.strip() else None
            except json.JSONDecodeError:
                st.error("Invalid JSON syntax in Request Body.")
                json_data = None

            try:
                hdr_data = json.loads(req_hdr_str) if req_hdr_str.strip() else None
            except json.JSONDecodeError:
                st.error("Invalid JSON syntax in Custom Headers.")
                hdr_data = None

            with st.spinner(f"Executing {http_method} request..."):
                success, resp_data, status_code, elapsed_ms, resp_headers = client.custom_request(
                    method=http_method,
                    endpoint_or_full_url=endpoint_url,
                    json_data=json_data,
                    custom_headers=hdr_data
                )

                st.markdown("### 📥 Response Details")
                
                res_col1, res_col2 = st.columns(2)
                with res_col1:
                    if success:
                        st.markdown(f'<div class="status-badge badge-success">HTTP {status_code} OK</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="status-badge badge-error">HTTP {status_code} Error</div>', unsafe_allow_html=True)
                with res_col2:
                    st.info(f"⏱️ Latency: `{elapsed_ms:.1f} ms`")

                with st.expander("📄 Response Headers"):
                    st.json(resp_headers)

                st.markdown("**Response Body:**")
                if isinstance(resp_data, (dict, list)):
                    st.json(resp_data)
                else:
                    st.code(str(resp_data))


# --- FOOTER ---
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #6b7280; font-size: 12px;'>"
    "Oracle Primavera Unifier REST API Dashboard | Built with Streamlit & Python"
    "</div>",
    unsafe_allow_html=True
)

# --- FLOATING CHATBOT BUBBLE ---
st.markdown("""
    <style>
        /* Target the exact block containing the chatbot anchor and fix it to the bottom right */
        div[data-testid="stVerticalBlock"] > div:has(div.chatbot-anchor) {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 380px;
            z-index: 99999;
            background: #1e293b;
            border: 1px solid #38bdf8;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
            padding: 0;
            overflow: hidden;
        }
        
        /* Make the expander header look like a chat header */
        div.chatbot-anchor + div[data-testid="stExpander"] {
            border: none;
            background: transparent;
        }
    </style>
""", unsafe_allow_html=True)

chat_container = st.container()
with chat_container:
    st.markdown("<div class='chatbot-anchor'></div>", unsafe_allow_html=True)
    with st.expander("💬 AI Chatbot (Click to Open)", expanded=False):
        
        # Determine if engine is ready
        engine_ready = st.session_state.chatbot_engine.is_ready()
        if not engine_ready:
            st.warning("Please enter your OpenAI or Groq API Key in the sidebar to enable the chatbot.")
        else:
            # Display chat messages
            chat_box = st.container(height=350)
            with chat_box:
                for msg in st.session_state.chatbot_messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
            
            # Chat input
            if prompt := st.chat_input("Ask a question about your Unifier data..."):
                # Append user message
                st.session_state.chatbot_messages.append({"role": "user", "content": prompt})
                with chat_box:
                    with st.chat_message("user"):
                        st.markdown(prompt)
                
                # Get bot response
                with chat_box:
                    with st.chat_message("assistant"):
                        with st.spinner("Thinking..."):
                            response = st.session_state.chatbot_engine.get_chat_response(
                                prompt, 
                                chat_history=st.session_state.chatbot_messages,
                                provider=st.session_state.llm_provider
                            )
                        st.markdown(response)
                
                # Append bot response
                st.session_state.chatbot_messages.append({"role": "assistant", "content": response})
