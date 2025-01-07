import numpy as np
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import faiss
import json
import os
import logging

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from a .env file if present
load_dotenv()

# ============================================
# Global Variables and Configurations
# ============================================

document_store = []  # Stores tuples: (filename, chunk_text)
model = SentenceTransformer(os.getenv("EMBEDDING_MODEL_NAME"))  # Embedding model
index = None  # FAISS index
metadata = []  # Metadata corresponding to embeddings

# Paths for saving/loading FAISS index and metadata
INDEX_PATH = os.getenv("INDEX_FOLDER")
print(INDEX_PATH)
METADATA_PATH = os.getenv("METADATA_FOLDER")
print(METADATA_PATH)

# ============================================
# PDF Processing and Chunking
# ============================================

def extract_text_from_pdf(file_stream):
    """
    Extract text from an uploaded PDF file stream.
    """
    try:
        file_stream.seek(0)  # Ensure the file stream is at the start
        doc = fitz.open(stream=file_stream.read(), filetype="pdf")
        text = ''
        for page in doc:
            text += page.get_text()
        doc.close()
        logger.info("Text extraction successful.")
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise e

def extract_text(file_stream, file_type):
    if file_type == 'application/pdf':
        return extract_text_from_pdf(file_stream)
    elif file_type == 'text/plain':
        try:
            return file_stream.read().decode('utf-8')
        except UnicodeDecodeError as e:
            logger.error(f"Error decoding TXT file: {e}")
            return ""
    else:
        raise ValueError("Unsupported file type for text extraction.")

def chunk_text(text, chunk_size=1000, overlap=100):
    # Implement your text chunking logic here
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def add_document_chunks(filename, chunks):
    """
    Add chunks of a document along with filename to the global store.
    """
    global document_store
    for ch in chunks:
        document_store.append((filename, ch))
    logger.info(f"Added {len(chunks)} chunks from '{filename}' to document_store.")

# ============================================
# Embeddings and FAISS Index Management
# ============================================

def create_embeddings(initial=False, new_chunks=None):
    """
    Create embeddings for all documents in document_store and build a FAISS index.
    If initial=True, it initializes the FAISS index.
    If new_chunks are provided, it adds embeddings for these chunks to the existing index.
    """
    global index, metadata

    try:
        if initial:
            if not document_store:
                logger.warning("No documents found. Add documents before creating embeddings.")
                raise ValueError("No documents found. Add documents before creating embeddings.")

            texts = [doc[1] for doc in document_store]
            embeddings = model.encode(texts, show_progress_bar=True)
            embeddings = embeddings.astype('float32')  # FAISS requires float32

            logger.info(f"Generated embeddings for {len(embeddings)} chunks.")

            # Initialize FAISS index
            dimension = embeddings.shape[1]
            index = faiss.IndexFlatL2(dimension)
            logger.info(f"Initialized FAISS IndexFlatL2 with dimension {dimension}.")

            # Build metadata
            metadata = [{"filename": doc[0], "chunk": doc[1]} for doc in document_store]

            # Add embeddings to the FAISS index
            index.add(embeddings)
            logger.info(f"FAISS index built with {index.ntotal} vectors.")

        elif new_chunks:
            if index is None:
                logger.warning("FAISS index not initialized. Initializing now.")
                create_embeddings(initial=True)

            # Embed only the new chunks
            texts = [chunk for filename, chunk in new_chunks]
            embeddings = model.encode(texts, show_progress_bar=True)
            embeddings = embeddings.astype('float32')

            logger.info(f"Generated embeddings for {len(embeddings)} new chunks.")

            # Add embeddings to the FAISS index
            index.add(embeddings)
            logger.info(f"FAISS index now has {index.ntotal} vectors.")

            # Update metadata
            for (filename, chunk) in new_chunks:
                metadata.append({"filename": filename, "chunk": chunk})

    except Exception as e:
        logger.error(f"Error in create_embeddings: {e}")
        raise e

def create_query_embedding(query):
    """
    Create an embedding for a single query string.
    Returns a 1D NumPy array representing the embedding vector.
    """
    try:
        embedding = model.encode([query])
        embedding = embedding[0].astype('float32')
        logger.info("Query embedding created successfully.")
        return embedding
    except Exception as e:
        logger.error(f"Error creating query embedding: {e}")
        raise e


def retrieve_documents(query, top_k=3, top_k_all=False):
    """
    Retrieve the most relevant documents from FAISS index for the given query.
    If top_k_all=True, we'll attempt to retrieve *all* entries from the index,
    then manually sort by ascending distance. Otherwise, top_k results are returned.

    Returns: (top_chunks, top_filenames, top_scores)
    where each is a list in ascending distance order.
    """
    if index is None or index.ntotal == 0:
        logger.warning("FAISS index not created or empty. Call create_embeddings() first.")
        raise ValueError("FAISS index not created or empty. Call create_embeddings() first.")

    try:
        # Create query embedding
        query_embedding = create_query_embedding(query).reshape(1, -1)
        logger.debug(f"Query embedding created for query: '{query}'.")

        # If we want "all" possible items, we can do: top_k = index.ntotal
        # Or pick a large number if index.ntotal is huge
        if top_k_all:
            num_vectors = index.ntotal
            top_k = num_vectors  # retrieve as many as exist

        # Perform FAISS search
        distances, indices = index.search(query_embedding, top_k)
        logger.info(
            f"FAISS search completed for query: '{query}'. Retrieved indices: {indices}, distances: {distances}"
        )

        # Initialize result lists
        results = []

        # Each row in 'indices' and 'distances' corresponds to top_k results
        for i, idx in enumerate(indices[0]):
            # If no more results available, -1 can appear
            if idx == -1:
                logger.debug(f"No more results available. Index {i} returned -1.")
                continue

            doc_meta = metadata[idx]
            logger.debug(f"Document retrieved: {doc_meta}")

            # Store in a single list so we can sort
            results.append({
                "filename": doc_meta["filename"],
                "chunk": doc_meta["chunk"],
                "distance": distances[0][i]  # smaller = more similar
            })

        # If results are not empty, sort by ascending distance
        results.sort(key=lambda x: x["distance"])

        # Then split them back out
        top_chunks = [r["chunk"] for r in results]
        top_filenames = [r["filename"] for r in results]
        top_scores = [r["distance"] for r in results]

        if not results:
            logger.warning("No relevant documents retrieved for the query.")
        else:
            logger.info(f"Retrieved and sorted {len(results)} documents for the query.")

        return top_chunks, top_filenames, top_scores

    except Exception as e:
        logger.error(f"Error retrieving documents: {e}")
        raise e


def get_document_text(document_name):
    """
    Fetch the text of a specific document by its name.
    """
    for doc_meta in metadata:  # Assuming metadata is a list of dictionaries with document details
        if doc_meta['filename'] == document_name:
            return doc_meta['chunk']  # or however the text is stored
    return None





def allowed_file(filename):
    """
    Check if the uploaded file is a PDF.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf' or '.' in filename and filename.rsplit('.', 1)[1].lower() == 'txt'

# ============================================
# Persistence Functions
# ============================================

def save_index(index_path=INDEX_PATH, metadata_path=METADATA_PATH):
    """
    Save FAISS index and metadata to disk.
    """
    try:
        if index is None:
            logger.warning("No FAISS index to save.")
            raise ValueError("No FAISS index to save.")
        faiss.write_index(index, index_path)
        logger.info(f"FAISS index saved to '{index_path}'.")
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        logger.info(f"Metadata saved to '{metadata_path}'.")
    except Exception as e:
        logger.error(f"Error saving FAISS index and metadata: {e}")
        raise e

def load_index(index_path=INDEX_PATH, metadata_path=METADATA_PATH):
    """
    Load FAISS index and metadata from disk.
    """
    global index, metadata, document_store
    try:
        if not os.path.exists(index_path) or not os.path.exists(metadata_path):
            logger.info("No existing FAISS index or metadata found. Starting fresh.")
            return

        index = faiss.read_index(index_path)
        logger.info(f"FAISS index loaded from '{index_path}' with {index.ntotal} vectors.")

        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        logger.info(f"Metadata loaded from '{metadata_path}' with {len(metadata)} entries.")

        # Rebuild document_store from metadata
        document_store = [(doc["filename"], doc["chunk"]) for doc in metadata]
        logger.info(f"Document store rebuilt with {len(document_store)} chunks.")

    except Exception as e:
        logger.error(f"Error loading FAISS index and metadata: {e}")
        raise e

def clear_data():
    """
    Clear the document store and FAISS index.
    """
    global document_store, index, metadata
    try:
        document_store.clear()
        index = None
        metadata = []
        logger.info("Cleared document_store, FAISS index, and metadata.")
    except Exception as e:
        logger.error(f"Error clearing data: {e}")
        raise e

# ============================================
# Initialization
# ============================================

# On module load, attempt to load existing index and metadata
try:
    load_index()
    if index is not None:
        logger.info("Loaded existing FAISS index and metadata.")
    else:
        logger.info("No existing FAISS index loaded. Ready to create new embeddings.")
except Exception as e:
    logger.error(f"Failed to load FAISS index and metadata: {e}")

