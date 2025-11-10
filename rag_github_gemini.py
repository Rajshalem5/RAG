import os
import sys
import tempfile
import shutil
import stat
import git
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage

# =============== CONFIG ===============
os.environ["GOOGLE_API_KEY"] = "AIzaSyDLyIF07AuZlGlHSS3Va2kA-MYlDgVdmTU"  # replace with your Gemini API key
import hashlib

def get_index_path(repo_url):
    # Create a unique folder name based on repo URL hash
    repo_hash = hashlib.md5(repo_url.encode()).hexdigest()[:8]
    return f"faiss_index_{repo_hash}"

FAISS_INDEX_PATH = get_index_path(sys.argv[1]) if len(sys.argv) > 1 else "faiss_index_github"

# =====================================

def remove_readonly(func, path, _):
    """Fixes Windows PermissionError when removing .git folders"""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def clone_repo(repo_url: str, target_dir: str):
    print(f"Cloning {repo_url} ...")
    git.Repo.clone_from(repo_url, target_dir)
    print("✅ Clone complete.")

def load_source_files(repo_path: str):
    extensions = [".java", ".cpp", ".cc", ".hpp", ".h"]
    docs = []

    for root, _, files in os.walk(repo_path):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                filepath = os.path.join(root, file)
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                docs.append(Document(page_content=text, metadata={"source": filepath}))
    print(f"📄 Found {len(docs)} source files.")
    return docs

def split_docs(documents):
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(documents)
    print(f"🔹 Total chunks: {len(chunks)}")
    return chunks

def build_vectorstore(docs, persist_path=FAISS_INDEX_PATH):
    print("⚙️ Building FAISS vectorstore (using HuggingFace embeddings)...")
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(persist_path)
    print("✅ Vectorstore saved locally.")
    return vectorstore

def load_or_build_index(repo_url, persist_path=FAISS_INDEX_PATH):
    print("🚀 Building or loading Gemini RAG index ...")

    if os.path.exists(persist_path):
        print("🧠 Loading existing FAISS index...")
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        return FAISS.load_local(persist_path, embeddings, allow_dangerous_deserialization=True)

    tmpdir = tempfile.mkdtemp()
    try:
        clone_repo(repo_url, tmpdir)
        docs = load_source_files(tmpdir)
        docs = split_docs(docs)
        vs = build_vectorstore(docs, persist_path=persist_path)
        return vs
    finally:
        shutil.rmtree(tmpdir, onerror=remove_readonly)

def build_qa_chain(vectorstore):
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
    model="models/gemini-2.5-flash",
    temperature=0.3,
    api_version="v1",
)



    template = """You are a coding assistant.
Answer the user's question using the given context from the codebase.
If the answer isn’t clear, say so briefly.

Context:
{context}

Question:
{question}

Answer:"""
    prompt = PromptTemplate(template=template, input_variables=["context", "question"])
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=vectorstore.as_retriever(search_kwargs={"k": 4}),
        chain_type_kwargs={"prompt": prompt},
        return_source_documents=True,
    )
    return qa_chain

def main():
    if len(sys.argv) < 2:
        print("Usage: python rag_github_gemini.py <github_repo_url>")
        sys.exit(1)

    repo_url = sys.argv[1]
    vectorstore = load_or_build_index(repo_url)
    qa_chain = build_qa_chain(vectorstore)

    print("\n🤖 Ask a question about the codebase (type 'exit' to quit):")
    while True:
        question = input("You: ")
        if question.lower() in ["exit", "quit"]:
            break
        result = qa_chain.invoke({"query": question})
        print("\nAI:", result["result"], "\n")

if __name__ == "__main__":
    main()
   