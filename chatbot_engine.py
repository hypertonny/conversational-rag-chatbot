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

        # Set up LLM based on provider with low temperature for factual precision
        if provider == "groq":
            if not self.groq_api_key:
                return "Groq API key is missing. Please provide it in the sidebar."
            try:
                llm = ChatGroq(
                    model_name="llama-3.3-70b-versatile",
                    temperature=0.1,
                    groq_api_key=self.groq_api_key
                )
            except Exception:
                llm = ChatGroq(
                    model_name="llama-3.1-8b-instant",
                    temperature=0.1,
                    groq_api_key=self.groq_api_key
                )
        else:
            if not self.openai_api_key:
                return "OpenAI API key is missing. Please provide it in the sidebar."
            llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                temperature=0.1,
                openai_api_key=self.openai_api_key
            )

        # Build strict system prompt for database-scoped RAG QA
        system_prompt = (
            "You are a strict RAG-based AI Assistant for the Oracle Primavera Unifier Database.\n"
            "STRICT RULES YOU MUST FOLLOW WITHOUT EXCEPTION:\n"
            "1. ONLY answer questions that are directly related to Oracle Primavera Unifier database records, active projects, business processes, project management, or system users based on the retrieved context below.\n"
            "2. If the user asks general trivia, world news, personal questions, or anything unrelated to Primavera Unifier / database records (e.g. 'who is pm of india', weather, general jokes), REJECT the question politely with:\n"
            "   'I am a dedicated Oracle Primavera Unifier Database Assistant. I can only answer questions related to your fetched Unifier database records, projects, and business processes.'\n"
            "3. If the retrieved context is empty or does not contain enough information to answer a Unifier database question, inform the user clearly:\n"
            "   'No matching Unifier database records were found in loaded memory. Please use the dashboard tabs (e.g., Active Projects, Company BPs, User Admin) to fetch your data first.'\n"
            "4. Never hallucinate or invent fake database records.\n"
            "5. Always format your responses cleanly using Markdown.\n\n"
            "Retrieved Unifier Database Context:\n{context}"
        )

        # Construct message list with conversation history
        messages = [("system", system_prompt)]

        if chat_history:
            past_msgs = chat_history[:-1] if chat_history and chat_history[-1].get("content") == user_query else chat_history
            for msg in past_msgs[-6:]:
                role = "human" if msg.get("role") == "user" else "assistant"
                messages.append((role, msg.get("content", "")))

        messages.append(("human", "{input}"))
        prompt = ChatPromptTemplate.from_messages(messages)

        # Create retrieval chain
        try:
            retriever = self.vector_store.as_retriever(search_kwargs={"k": 5})
            question_answer_chain = create_stuff_documents_chain(llm, prompt)
            chain = create_retrieval_chain(retriever, question_answer_chain)

            response = chain.invoke({"input": user_query})
            return response.get("answer", "I couldn't generate a response based on the retrieved database context.")
        except Exception as e:
            return f"Error querying database AI engine: {str(e)}"
