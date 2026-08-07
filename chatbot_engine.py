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
        """Ingest arbitrary JSON data from the Unifier API into the vector store."""
        if not self.vector_store:
            return False, "Vector store not initialized."

        # Convert JSON to string representation for embedding
        if isinstance(data, (dict, list)):
            text_data = json.dumps(data, indent=2)
        else:
            text_data = str(data)

        # Split text
        chunks = self.text_splitter.split_text(text_data)
        documents = [Document(page_content=chunk, metadata={"source": source_name}) for chunk in chunks]

        # Add to Chroma
        self.vector_store.add_documents(documents)
        return True, f"Ingested {len(documents)} chunks from {source_name}."

    def get_chat_response(self, user_query: str, chat_history: List[Dict[str, str]] = [], provider: str = "openai") -> str:
        """Query the vector database and generate a response using LLM."""
        if not self.is_ready():
            return "Chatbot is not ready. Please provide an API Key in the sidebar."

        query_lower = user_query.lower().strip()

        # --- STEP 1: PYTHON-LEVEL DOMAIN RELEVANCE PRE-FILTER ---
        unifier_keywords = [
            "project", "projects", "unifier", "vendor", "vendors", "contract", "contracts",
            "record", "records", "bp", "bps", "business process", "user", "users", "admin",
            "file", "files", "attachment", "attachments", "shell", "shells", "rfi", "submittal",
            "change order", "status", "active", "cost", "budget", "count", "how many", "list",
            "show", "fetch", "query", "catalog", "schema", "uuu", "oracle"
        ]
        
        is_unifier_query = any(kw in query_lower for kw in unifier_keywords)

        # Non-Unifier general trivia check (e.g., PM of India, weather, general jokes)
        general_trivia_indicators = [
            "pm of", "prime minister", "president", "capital of", "weather", "who is", "tell me a joke",
            "actor", "movie", "song", "sports", "cricket", "football", "recipe", "country"
        ]
        is_general_trivia = any(ind in query_lower for ind in general_trivia_indicators) and not is_unifier_query

        if is_general_trivia:
            return "I am a dedicated Oracle Primavera Unifier Database Assistant. I can only answer questions related to your fetched Unifier database records, projects, and business processes."

        # --- STEP 2: SIMILARITY SEARCH CHECK ---
        docs = []
        try:
            docs = self.vector_store.similarity_search(user_query, k=5)
        except Exception:
            docs = []

        if not docs or len(docs) == 0:
            if is_unifier_query:
                return "No matching Unifier database records were found in loaded memory. Please use the dashboard tabs (e.g., Active Projects, Company BPs, User Admin) to fetch your data first."
            else:
                return "I am a dedicated Oracle Primavera Unifier Database Assistant. I can only answer questions related to your fetched Unifier database records, projects, and business processes."

        # --- STEP 3: STRICT CONTEXT-ONLY LLM EXECUTION ---
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

        # System prompt strictly forbidding external knowledge
        system_prompt = (
            "You are a strict Oracle Primavera Unifier Database RAG assistant.\n"
            "STRICT RULES:\n"
            "1. Answer the user's question STRICTLY AND ONLY using the retrieved Unifier context provided below.\n"
            "2. DO NOT use any outside knowledge, pre-trained world facts, or external trivia.\n"
            "3. If the retrieved context does not contain the explicit answer to the user's question, reply EXACTLY with:\n"
            "   'The loaded Unifier database context does not contain enough information to answer this question.'\n"
            "4. Format your response cleanly using Markdown.\n\n"
            "Retrieved Unifier Database Context:\n{context}"
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
