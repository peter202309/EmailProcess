import os
import glob
from langchain_community.document_loaders import TextLoader, PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")

KB_DIR = "knowledge_base"
INDEX_PATH = "faiss_index"

def get_embeddings():
    """Get embeddings using the same auto-detection logic as RAG."""
    # Priority: OpenAI > Gemini (DeepSeek doesn't provide embedding API)
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("VITE_GEMINI_API_KEY")
    
    if openai_key and openai_key.startswith("sk-"):
        print("Using OpenAI for embeddings")
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=openai_key
        )
    elif gemini_key:
        print("Using Gemini for embeddings")
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=gemini_key
        )
    else:
        raise Exception("No embedding API key found")

def build_index():
    # 1. Load Documents
    documents = []
    
    # Support multiple formats
    text_files = glob.glob(os.path.join(KB_DIR, "*.txt"))
    pdf_files = glob.glob(os.path.join(KB_DIR, "*.pdf"))
    docx_files = glob.glob(os.path.join(KB_DIR, "*.docx"))
    
    all_files = text_files + pdf_files + docx_files
    
    if not all_files:
        print(f"No documents found in {KB_DIR}. Creating sample...")
        os.makedirs(KB_DIR, exist_ok=True)
        sample_path = os.path.join(KB_DIR, "sample_policy.txt")
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("Refund Policy: All requests must be made within 30 days.")
        all_files = [sample_path]

    for file_path in all_files:
        try:
            if file_path.endswith('.txt'):
                loader = TextLoader(file_path, encoding='utf-8')
            elif file_path.endswith('.pdf'):
                loader = PyPDFLoader(file_path)
            elif file_path.endswith('.docx'):
                loader = Docx2txtLoader(file_path)
            else:
                continue
            
            documents.extend(loader.load())
            print(f"Loaded: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"Failed to load {file_path}: {e}")

    # 2. Split Text
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    docs = text_splitter.split_documents(documents)

    if not docs:
        print("No documents to index.")
        return {"status": "error", "message": "No documents found"}

    # 3. Embed and Store
    print("Creating embeddings...")
    try:
        embeddings = get_embeddings()
        vector_store = FAISS.from_documents(docs, embeddings)
        
        # 4. Save Index
        vector_store.save_local(INDEX_PATH)
        print(f"Success! FAISS index saved to '{INDEX_PATH}'.")
        return {"status": "success", "doc_count": len(all_files), "chunks": len(docs)}
    except Exception as e:
        print(f"Error building index: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    result = build_index()
    print(result)
