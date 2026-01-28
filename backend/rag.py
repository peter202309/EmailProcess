import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

# Load env to get OPENAI_API_KEY
load_dotenv(dotenv_path="../.env")

class RAGService:
    def __init__(self, index_path="faiss_index"):
        self.index_path = index_path
        self.embeddings = self._get_embeddings()
        self.vector_store = None
        self.store_type = os.getenv("VECTOR_STORE_TYPE", "faiss").lower()
        self.load_index()

    def _get_embeddings(self):
        """Auto-detect and return the best available embedding provider."""
        # Priority: OpenAI > Gemini (DeepSeek doesn't provide embedding API)
        openai_key = os.getenv("OPENAI_API_KEY")
        gemini_key = os.getenv("VITE_GEMINI_API_KEY")
        
        if openai_key and openai_key.startswith("sk-"):
            print("Using OpenAI for embeddings (high quality)")
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(
                model="text-embedding-3-small",
                openai_api_key=openai_key
            )
        elif gemini_key:
            print("Using Gemini for embeddings (default)")
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(
                model="models/text-embedding-004",
                google_api_key=gemini_key
            )
        else:
            raise Exception("No embedding API key found. Please configure OPENAI_API_KEY or VITE_GEMINI_API_KEY in .env")

    def load_index(self):
        if self.store_type == "openai":
            self._load_openai_store()
        else:
            self._load_faiss_store()

    def _load_faiss_store(self):
        """Load local FAISS index."""
        if os.path.exists(self.index_path):
            try:
                self.vector_store = FAISS.load_local(
                    self.index_path, 
                    self.embeddings, 
                    allow_dangerous_deserialization=True
                )
                print(f"FAISS Index loaded successfully from {self.index_path}")
            except Exception as e:
                print(f"Error loading FAISS index: {e}")
        else:
            print("No FAISS index found. RAG will be disabled until KB is built.")

    def _load_openai_store(self):
        """Load OpenAI Vector Store."""
        openai_key = os.getenv("OPENAI_API_KEY")
        vector_store_id = os.getenv("OPENAI_VECTOR_STORE_ID")
        
        if not openai_key or not vector_store_id:
            print("OpenAI Vector Store not configured. Falling back to FAISS.")
            self.store_type = "faiss"
            self._load_faiss_store()
            return
        
        try:
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=openai_key)
            self.vector_store_id = vector_store_id
            print(f"OpenAI Vector Store loaded: {vector_store_id}")
        except Exception as e:
            print(f"Error loading OpenAI Vector Store: {e}. Falling back to FAISS.")
            self.store_type = "faiss"
            self._load_faiss_store()

    def search(self, query: str, k: int = 3) -> str:
        if self.store_type == "openai" and hasattr(self, 'openai_client'):
            return self._search_openai(query, k)
        else:
            return self._search_faiss(query, k)

    def _search_faiss(self, query: str, k: int) -> str:
        """Search using local FAISS."""
        if not self.vector_store:
            return ""
        
        try:
            results = self.vector_store.similarity_search(query, k=k)
            context = "\n\n".join([doc.page_content for doc in results])
            return context
        except Exception as e:
            print(f"FAISS search failed: {e}")
            return ""

    def _search_openai(self, query: str, k: int) -> str:
        """Search using OpenAI Vector Store."""
        try:
            # Create a temporary thread for search
            thread = self.openai_client.beta.threads.create()
            
            # Add message with file search
            self.openai_client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=query
            )
            
            # Run with file search
            run = self.openai_client.beta.threads.runs.create_and_poll(
                thread_id=thread.id,
                assistant_id=self.vector_store_id,
                tools=[{"type": "file_search"}]
            )
            
            # Get results
            messages = self.openai_client.beta.threads.messages.list(thread_id=thread.id)
            if messages.data:
                return messages.data[0].content[0].text.value
            return ""
        except Exception as e:
            print(f"OpenAI Vector Store search failed: {e}")
            return ""
