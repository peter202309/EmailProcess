import os
import glob
import json
import hashlib
from langchain_community.document_loaders import TextLoader, PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")

KB_DIR = "knowledge_base"
INDEX_PATH = "faiss_index"
METADATA_PATH = "faiss_index_metadata.json"

def get_embeddings():
    """Get embeddings using the same auto-detection logic as RAG."""
    # Priority: OpenAI > Gemini (Extremely stable)
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("VITE_GEMINI_API_KEY")
    
    if openai_key and openai_key.startswith("sk-"):
        print("Using OpenAI for embeddings (User Updated Key)")
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
            google_api_key=gemini_key,
            task_type="retrieval_document"
        )
    else:
        raise Exception("No embedding API key found")

def calculate_file_hash(filepath):
    """Calculate MD5 hash of file."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def load_metadata():
    """Load file metadata from previous build."""
    if os.path.exists(METADATA_PATH):
        with open(METADATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_metadata(metadata):
    """Save file metadata."""
    with open(METADATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

def get_all_kb_files():
    """Get all knowledge base files."""
    text_files = glob.glob(os.path.join(KB_DIR, "*.txt"))
    pdf_files = glob.glob(os.path.join(KB_DIR, "*.pdf"))
    docx_files = glob.glob(os.path.join(KB_DIR, "*.docx"))
    return text_files + pdf_files + docx_files

def load_document(file_path):
    """Load a single document."""
    try:
        if file_path.endswith('.txt'):
            loader = TextLoader(file_path, encoding='utf-8')
        elif file_path.endswith('.pdf'):
            loader = PyPDFLoader(file_path)
        elif file_path.endswith('.docx'):
            loader = Docx2txtLoader(file_path)
        else:
            return []
        
        docs = loader.load()
        print(f"Loaded: {os.path.basename(file_path)}")
        return docs
    except Exception as e:
        print(f"Failed to load {file_path}: {e}")
        return []

def build_index(incremental=True):
    """
    Build or update FAISS index.
    
    Args:
        incremental: If True, only process changed files. If False, rebuild from scratch.
    """
    os.makedirs(KB_DIR, exist_ok=True)
    
    # Get all files
    all_files = get_all_kb_files()
    
    if not all_files:
        print(f"No documents found in {KB_DIR}. Creating sample...")
        sample_path = os.path.join(KB_DIR, "sample_policy.txt")
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("Refund Policy: All requests must be made within 30 days.")
        all_files = [sample_path]
    
    # Load previous metadata
    old_metadata = load_metadata() if incremental else {}
    new_metadata = {}
    
    # Detect changes
    files_to_process = []
    unchanged_files = []
    
    for file_path in all_files:
        file_hash = calculate_file_hash(file_path)
        filename = os.path.basename(file_path)
        new_metadata[filename] = file_hash
        
        if incremental and filename in old_metadata and old_metadata[filename] == file_hash:
            unchanged_files.append(filename)
        else:
            files_to_process.append(file_path)
            if filename in old_metadata:
                print(f"📝 Modified: {filename}")
            else:
                print(f"✨ New: {filename}")
    
    # Check for deleted files
    deleted_files = set(old_metadata.keys()) - set(new_metadata.keys())
    if deleted_files:
        print(f"🗑️  Deleted: {', '.join(deleted_files)}")
    
    # If incremental and no changes, return early
    if incremental and not files_to_process and not deleted_files:
        print("✅ No changes detected. Index is up to date.")
        if os.path.exists(INDEX_PATH):
            return {
                "status": "success", 
                "message": "No changes detected",
                "doc_count": len(all_files), 
                "chunks": 0,
                "mode": "incremental",
                "unchanged": len(unchanged_files)
            }
        else:
            print("⚠️  Index doesn't exist. Building from scratch...")
            incremental = False
    
    # Load documents
    documents = []
    
    if incremental and os.path.exists(INDEX_PATH) and unchanged_files:
        print(f"📦 Keeping {len(unchanged_files)} unchanged files in index")
        # We'll merge with existing index later
    
    # Load new/modified documents
    for file_path in files_to_process:
        documents.extend(load_document(file_path))
    
    # Split text
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
    new_docs = text_splitter.split_documents(documents)
    
    print(f"📊 Processing {len(files_to_process)} files → {len(new_docs)} chunks")
    
    # Create embeddings
    try:
        embeddings = get_embeddings()
        
        if incremental and os.path.exists(INDEX_PATH) and (unchanged_files or not deleted_files):
            # Load existing index
            print("🔄 Loading existing index for incremental update...")
            existing_vector_store = FAISS.load_local(INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
            
            if new_docs:
                # Add new documents to existing index
                print(f"➕ Adding {len(new_docs)} new chunks to index...")
                existing_vector_store.add_documents(new_docs)
            
            vector_store = existing_vector_store
            mode = "incremental"
        else:
            # Build from scratch
            if not new_docs and not documents:
                print("❌ No documents to index.")
                return {"status": "error", "message": "No documents found"}
            
            print("🏗️  Building index from scratch...")
            all_docs = new_docs if new_docs else text_splitter.split_documents([load_document(f) for f in all_files])
            vector_store = FAISS.from_documents(all_docs, embeddings)
            mode = "full_rebuild"
        
        # Save index and metadata
        vector_store.save_local(INDEX_PATH)
        save_metadata(new_metadata)
        
        total_chunks = len(new_docs) if mode == "incremental" else len(vector_store.docstore._dict)
        
        print(f"✅ Success! FAISS index saved to '{INDEX_PATH}'.")
        return {
            "status": "success", 
            "doc_count": len(all_files), 
            "chunks": total_chunks,
            "mode": mode,
            "processed": len(files_to_process),
            "unchanged": len(unchanged_files)
        }
    except Exception as e:
        print(f"❌ Error building index: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import sys
    incremental = "--full" not in sys.argv
    result = build_index(incremental=incremental)
    print(result)
