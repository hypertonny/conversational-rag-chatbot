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

        # Set up LLM based on provider
        if provider == "groq":
            if not self.groq_api_key:
                return "Groq API key is missing. Please provide it in the sidebar."
            # Use llama-3.3-70b-versatile or fallback to llama3-8b-8192 / llama-3.1-8b-instant
            try:
                llm = ChatGroq(
                    model_name="llama-3.3-70b-versatile",
                    temperature=0.4,
                    groq_api_key=self.groq_api_key
                )
            except Exception:
                llm = ChatGroq(
                    model_name="llama-3.1-8b-instant",
                    temperature=0.4,
                    groq_api_key=self.groq_api_key
                )
        else:
            if not self.openai_api_key:
                return "OpenAI API key is missing. Please provide it in the sidebar."
            llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                temperature=0.4,
                openai_api_key=self.openai_api_key
            )

        # Build system prompt for open conversational QA with context prioritization
        system_prompt = (
            "You are a friendly, highly intelligent conversational AI assistant for Oracle Primavera Unifier and general construction project management.\n"
            "You can answer ANY question the user asks—whether about Primavera Unifier APIs, fetched data, project management, or general queries.\n"
            "If retrieved context from the Unifier database is provided below, use it to give accurate, data-backed answers.\n"
            "If the retrieved context does NOT contain the answer or is empty, rely on your extensive general knowledge to answer helpful and accurately.\n"
            "Always format your response cleanly using Markdown.\n\n"
            "Retrieved Unifier Data Context:\n{context}"
        )

        # Construct message list with conversation history
        messages = [("system", system_prompt)]

        # Include prior conversation history (excluding the current user prompt which is passed as {input})
        if chat_history:
            # Look at past messages (excluding the last one if it's identical to user_query)
            past_msgs = chat_history[:-1] if chat_history and chat_history[-1].get("content") == user_query else chat_history
            # Keep last 6 exchanges for context window efficiency
            for msg in past_msgs[-8:]:
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
            return response.get("answer", "I couldn't generate a response.")
        except Exception as e:
            # Fallback to direct LLM response if vector retriever fails or is empty
            try:
                direct_messages = [
                    ("system", "You are a helpful AI assistant for Oracle Primavera Unifier and general queries. Format answers in Markdown."),
                    ("human", user_query)
                ]
                direct_prompt = ChatPromptTemplate.from_messages(direct_messages)
                direct_chain = direct_prompt | llm
                res = direct_chain.invoke({})
                return res.content
            except Exception as inner_e:
                return f"Error communicating with LLM: {str(e)} | {str(inner_e)}"
