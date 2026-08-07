import os
import json
from typing import List, Dict, Any, Optional

from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_groq import ChatGroq

class ChatbotEngine:
    def __init__(self, openai_api_key: Optional[str] = None, groq_api_key: Optional[str] = None, use_local_embeddings: bool = True):
        self.openai_api_key = openai_api_key
        self.groq_api_key = groq_api_key
        self.use_local_embeddings = use_local_embeddings
        
        # Set up Embeddings
        if self.use_local_embeddings:
            self.embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        elif self.openai_api_key:
            self.embeddings = OpenAIEmbeddings(openai_api_key=self.openai_api_key)
        else:
            self.embeddings = None # Will throw error if we try to embed without API key or local

        # Set up Vector Store
        self.persist_directory = "./chroma_db"
        if self.embeddings:
            self.vector_store = Chroma(
                embedding_function=self.embeddings,
                persist_directory=self.persist_directory
            )
        else:
            self.vector_store = None

        # Text Splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )

    def is_ready(self):
        """Check if engine has necessary credentials/models to run."""
        return (self.openai_api_key or self.groq_api_key) and self.vector_store is not None

    def ingest_json_data(self, data: Any, source_name: str = "unifier_api"):
        """Ingest JSON data from Unifier API into vector store with structured summaries and record sentences."""
        if not self.vector_store:
            return False, "Vector store not initialized."

        records = []
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                records = data["data"]
            elif "data" in data and isinstance(data["data"], dict):
                records = [data["data"]]
            else:
                records = [data]
        elif isinstance(data, list):
            records = data
        else:
            records = [{"content": str(data)}]

        documents = []
        total_count = len(records)

        # 1. GENERATE MASTER SUMMARY DOCUMENT FOR AGGREGATE QA (Counts, Totals, Summaries)
        sample_names = []
        for r in records[:20]:
            if isinstance(r, dict):
                name = r.get("projectname") or r.get("bp_name") or r.get("user_name") or r.get("first_name") or r.get("record_no") or str(r)
                pnum = r.get("projectnumber") or r.get("project_number") or ""
                if pnum:
                    sample_names.append(f"{name} (No: {pnum})")
                else:
                    sample_names.append(str(name))

        summary_text = (
            f"Unifier Database Dataset Summary for {source_name}:\n"
            f"Total records count in database for {source_name}: {total_count}.\n"
            f"Sample records present in {source_name}: {', '.join(sample_names)}.\n"
            f"Dataset Source: {source_name}."
        )
        documents.append(Document(page_content=summary_text, metadata={"source": source_name, "type": "summary"}))

        # 2. GENERATE STRUCTURED INDIVIDUAL RECORD SENTENCES
        record_sentences = []
        for idx, r in enumerate(records[:1000]): # Ingest up to 1000 records per dataset cleanly
            if isinstance(r, dict):
                sentence_parts = [f"{source_name} Record #{idx+1}:"]
                for k, v in r.items():
                    if isinstance(v, (dict, list)):
                        continue
                    sentence_parts.append(f"{k}: {v}")
                record_sentences.append(" | ".join(sentence_parts))
            else:
                record_sentences.append(f"{source_name} Record #{idx+1}: {str(r)}")

        full_records_text = "\n".join(record_sentences)
        chunks = self.text_splitter.split_text(full_records_text)
        for chunk in chunks:
            documents.append(Document(page_content=chunk, metadata={"source": source_name, "type": "record"}))

        try:
            self.vector_store.add_documents(documents)
            return True, f"Ingested master summary + {len(documents)} document chunks for {source_name} ({total_count} records)."
        except Exception as e:
            return False, f"Failed to ingest to vector store: {str(e)}"

    def get_chat_response(self, user_query: str, chat_history: List[Dict[str, str]] = [], provider: str = "openai") -> str:
        """Query the vector database and generate a response using LLM."""
        if not self.is_ready():
            return "Chatbot is not ready. Please provide an API Key in the sidebar."

        # --- STEP 1: RETRIEVE FROM VECTOR DATABASE ---
        docs = []
        try:
            docs = self.vector_store.similarity_search(user_query, k=6)
            
            # If query is aggregate/summary, also include dataset summary documents
            query_lower = user_query.lower()
            if any(term in query_lower for term in ["how many", "total", "count", "active project", "company bp", "project", "info", "summary", "list", "have"]):
                summary_docs = self.vector_store.similarity_search("Unifier Database Dataset Summary", k=4)
                for s_doc in summary_docs:
                    if s_doc.page_content not in [d.page_content for d in docs]:
                        docs.append(s_doc)
        except Exception:
            docs = []

        # If vector database is empty or no relevant documents returned
        if not docs or len(docs) == 0:
            return "I did not find any information related to this in the database."

        # --- STEP 2: LLM EXECUTION WITH MAXIMUM STRICTNESS (temperature=0.0) ---
        if provider == "groq":
            if not self.groq_api_key:
                return "Groq API key is missing. Please provide it in the sidebar."
            try:
                llm = ChatGroq(
                    model_name="llama-3.3-70b-versatile",
                    temperature=0.0,
                    groq_api_key=self.groq_api_key
                )
            except Exception:
                llm = ChatGroq(
                    model_name="llama-3.1-8b-instant",
                    temperature=0.0,
                    groq_api_key=self.groq_api_key
                )
        else:
            if not self.openai_api_key:
                return "OpenAI API key is missing. Please provide it in the sidebar."
            llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                temperature=0.0,
                openai_api_key=self.openai_api_key
            )

        # System prompt with absolute strictness requirement
        system_prompt = (
            "You are a strict database QA assistant.\n"
            "STRICT RULES YOU MUST FOLLOW WITHOUT EXCEPTION:\n"
            "1. If the user says a casual greeting (like 'hi', 'hello', 'how are you'), respond politely and ask how you can help with the Unifier data. Do NOT reply with the strict rejection message for casual greetings.\n"
            "2. For any question asking for data, summaries, or information, answer ONLY using the retrieved database context provided below.\n"
            "3. If the user asks a question about data/information, and the answer cannot be found explicitly in the retrieved database context below, reply EXACTLY with: 'I did not find any information related to this in the database.'\n"
            "4. Do NOT use any external knowledge, assumptions, pre-trained facts, or general trivia.\n\n"
            "Retrieved Database Context:\n{context}"
        )

        messages = [("system", system_prompt)]
        if chat_history:
            past_msgs = chat_history[:-1] if chat_history and chat_history[-1].get("content") == user_query else chat_history
            for msg in past_msgs[-6:]:
                role = "human" if msg.get("role") == "user" else "assistant"
                messages.append((role, msg.get("content", "")))

        messages.append(("human", "{input}"))
        prompt = ChatPromptTemplate.from_messages(messages)

        try:
            question_answer_chain = create_stuff_documents_chain(llm, prompt)
            response = question_answer_chain.invoke({"input": user_query, "context": docs})
            return response if isinstance(response, str) else response.get("answer", str(response))
        except Exception as e:
            return f"Error querying database AI engine: {str(e)}"
