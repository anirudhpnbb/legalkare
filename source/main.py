
import numpy as np
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import faiss
import json
import os
import logging
from bson import ObjectId

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

MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-mpnet-base-v2")

# Directory in which each user's index & metadata files will be stored
INDEXES_DIR = os.getenv("INDEXES_DIR", "indexes")


# ============================================================================
# File Extraction & Chunking
# ============================================================================
def extract_text_from_pdf(file_stream) -> str:
    """
    Extract text from an uploaded PDF file stream using PyMuPDF.
    """
    try:
        file_stream.seek(0)
        doc = fitz.open(stream=file_stream.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        logger.info("Text extraction from PDF successful.")
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise e


def extract_text(file_stream, file_type: str) -> str:
    """
    Extract text from a file stream, handling PDF or TXT.
    """
    if file_type == "application/pdf":
        return extract_text_from_pdf(file_stream)
    elif file_type == "text/plain":
        try:
            file_stream.seek(0)
            return file_stream.read().decode("utf-8")
        except UnicodeDecodeError as e:
            logger.error(f"Error decoding TXT file: {e}")
            return ""
    else:
        raise ValueError("Unsupported file type for text extraction.")


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list:
    """
    Chunk the provided text into overlapping segments.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def allowed_file(filename: str) -> bool:
    """
    Check if the uploaded file extension is allowed: pdf or txt.
    """
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ["pdf", "txt"]


# ============================================================================
# User-Specific FAISS Index & Metadata
# ============================================================================
def get_user_index_path(user_id: str) -> str:
    """
    Return the filesystem path to the FAISS index for the given user_id.
    Example: indexes/index_UID0001.faiss
    """
    if not os.path.isdir(INDEXES_DIR):
        os.makedirs(INDEXES_DIR, exist_ok=True)
    return os.path.join(INDEXES_DIR, f"index_{user_id}.faiss")


def get_user_metadata_path(user_id: str) -> str:
    """
    Return the filesystem path to the metadata JSON for the given user_id.
    Example: indexes/metadata_UID0001.json
    """
    if not os.path.isdir(INDEXES_DIR):
        os.makedirs(INDEXES_DIR, exist_ok=True)
    return os.path.join(INDEXES_DIR, f"metadata_{user_id}.json")


def load_user_index_and_metadata(user_id: str):
    """
    Load the user's FAISS index and metadata from disk.
    If none exists, return a new empty index and empty metadata list.
    """
    index_path = get_user_index_path(user_id)
    metadata_path = get_user_metadata_path(user_id)

    if not os.path.exists(index_path) or not os.path.exists(metadata_path):
        logger.info(f"No existing index/metadata found for user {user_id}. Creating empty in-memory index.")
        dim = model.get_sentence_embedding_dimension()
        empty_index = faiss.IndexFlatL2(dim)
        return empty_index, []  # fresh metadata

    logger.info(f"Loading FAISS index & metadata for user {user_id}.")
    loaded_index = faiss.read_index(index_path)
    with open(metadata_path, "r", encoding="utf-8") as f:
        loaded_metadata = json.load(f)

    logger.info(
        f"Loaded index with {loaded_index.ntotal} vectors and metadata with {len(loaded_metadata)} entries for user {user_id}."
    )
    return loaded_index, loaded_metadata


def save_user_index_and_metadata(user_id: str, user_index, user_metadata: list):
    """
    Save the user's FAISS index and metadata to disk.
    """
    index_path = get_user_index_path(user_id)
    metadata_path = get_user_metadata_path(user_id)

    faiss.write_index(user_index, index_path)
    logger.info(f"FAISS index saved for user {user_id} at '{index_path}'.")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(user_metadata, f, ensure_ascii=False, indent=2)
    logger.info(f"Metadata saved for user {user_id} at '{metadata_path}'.")


def create_embeddings_for_user(user_id: str, new_chunks: list):
    """
    For each (filename, chunk_text) in new_chunks, embed them and add to the user's FAISS index.

    :param user_id: The user's unique ID (e.g. "UID0013")
    :param new_chunks: A list of tuples [(doc_filename, chunk_text), ...]
    """
    # 1) Load or init the user's index + metadata
    user_index, user_metadata = load_user_index_and_metadata(user_id)

    # 2) Separate chunk_text from new_chunks
    texts = []
    valid_pairs = []  # will store (filename, text) only if text is not empty

    for (filename, chunk_text) in new_chunks:
        cleaned_text = chunk_text.strip()
        if cleaned_text:
            valid_pairs.append((filename, cleaned_text))
            texts.append(cleaned_text)
        else:
            logger.warning(f"Skipping empty chunk from '{filename}'.")

    if not valid_pairs:
        logger.warning(f"No non-empty chunks to embed for user {user_id}. Nothing to do.")
        return

    # 3) Generate embeddings
    logger.info(f"Generating embeddings for {len(texts)} chunks for user {user_id}.")
    embeddings = model.encode(texts, show_progress_bar=False)

    # Check shape: should be (#chunks, embedding_dim)
    if embeddings.ndim != 2:
        raise ValueError(
            f"Expected embeddings of shape (n, dim), got {embeddings.shape} instead."
        )

    embeddings = embeddings.astype("float32")
    logger.info(f"Embeddings shape for user {user_id}: {embeddings.shape}")

    # 4) Add embeddings to the FAISS index
    user_index.add(embeddings)
    logger.info(
        f"User {user_id}: added {embeddings.shape[0]} vectors to their FAISS index. "
        f"Index now contains {user_index.ntotal} total vectors."
    )

    # 5) Update user_metadata
    for (filename, text), emb in zip(valid_pairs, embeddings):
        # You might store extra fields if you want chunk_id, etc.
        user_metadata.append({
            "filename": filename,
            "chunk": text
        })

    # 6) Save everything back
    save_user_index_and_metadata(user_id, user_index, user_metadata)


def retrieve_documents_for_user_doc_specific(user_id: str, query: str, doc_name: str, top_k: int = 5):
    """
    Search the FAISS index *only* among chunks that match `doc_name`.
    This prevents retrieving chunks from other files altogether.
    Returns (top_chunks, top_filenames, top_scores).
    """
    user_index, user_metadata = load_user_index_and_metadata(user_id)

    if user_index.ntotal == 0:
        logger.warning(f"User {user_id}: index empty. No retrieval possible.")
        return [], [], []

    # 1) Gather the row IDs in metadata belonging to doc_name
    row_ids_for_doc = []
    for i, meta in enumerate(user_metadata):
        if meta["filename"] == doc_name:
            row_ids_for_doc.append(i)

    if not row_ids_for_doc:
        logger.warning(f"No chunks for doc '{doc_name}' in user {user_id}'s metadata.")
        return [], [], []

    # 2) Reconstruct all vectors from the user's main index (IndexFlat)
    all_vectors = user_index.reconstruct_n(0, user_index.ntotal)  # shape: (ntotal, dimension)
    dimension = all_vectors.shape[1]

    # 3) Build a local sub-index for just those row IDs
    local_index = faiss.IndexFlatL2(dimension)
    local_to_global_map = []
    doc_vectors = []
    for rid in row_ids_for_doc:
        doc_vectors.append(all_vectors[rid])
        local_to_global_map.append(rid)

    doc_vectors = np.array(doc_vectors, dtype="float32")
    local_index.add(doc_vectors)

    # 4) Embed the query, search the sub-index
    query_emb = model.encode([query]).astype("float32")
    distances, local_indices = local_index.search(query_emb, top_k)

    # 5) Build the results by mapping local index -> global row IDs -> metadata
    results = []
    for i, loc_idx in enumerate(local_indices[0]):
        if loc_idx == -1:
            continue
        global_row = local_to_global_map[loc_idx]
        dist = distances[0][i]
        meta = user_metadata[global_row]
        results.append({
            "filename": meta["filename"],
            "chunk": meta["chunk"],
            "distance": dist
        })

    # Sort by ascending distance
    results.sort(key=lambda x: x["distance"])

    top_chunks = [r["chunk"] for r in results]
    top_filenames = [r["filename"] for r in results]
    top_scores = [r["distance"] for r in results]

    logger.info(f"Doc-specific search for user {user_id}, doc '{doc_name}' => {len(results)} results.")
    return top_chunks, top_filenames, top_scores


def get_document_text_for_user(user_id: str, document_name: str):
    """
    Return the combined text of all chunks belonging to 'document_name' in the user's metadata.
    If none found, returns None.
    """
    _, user_metadata = load_user_index_and_metadata(user_id)
    doc_chunks = [m["chunk"] for m in user_metadata if m["filename"] == document_name]
    if not doc_chunks:
        return None
    return "\n".join(doc_chunks)


def clear_user_data(user_id: str):
    """
    Remove the user's FAISS index & metadata files from disk entirely.
    """
    index_path = get_user_index_path(user_id)
    metadata_path = get_user_metadata_path(user_id)

    if os.path.exists(index_path):
        os.remove(index_path)
        logger.info(f"Removed index file for user {user_id}: {index_path}")

    if os.path.exists(metadata_path):
        os.remove(metadata_path)
        logger.info(f"Removed metadata file for user {user_id}: {metadata_path}")


# ============================================================================
# Misc. Helper
# ============================================================================
def serialize_document(doc):
    """
    Convert MongoDB document to a JSON-serializable dictionary.
    Replaces any ObjectId fields with their string representation.
    """
    if not doc:
        return doc
    serialized_doc = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            serialized_doc[key] = str(value)
        elif isinstance(value, list):
            serialized_doc[key] = [
                str(item) if isinstance(item, ObjectId) else item
                for item in value
            ]
        else:
            serialized_doc[key] = value
    return serialized_doc

# ============================================
# PDF Processing and Chunking
# ============================================

def remove_doc_from_user_embeddings(user_id: str, doc_filename: str):
    """
    Removes the specified document's chunks from the user's local FAISS index,
    and updates the metadata accordingly.
    """
    # 1) Construct paths for the user's index and metadata
    index_path = f"index_{user_id}.faiss"
    metadata_path = f"metadata_{user_id}.json"

    # 2) If the user's index/metadata don't exist, just return
    if not os.path.exists(index_path) or not os.path.exists(metadata_path):
        return

    # 3) Load metadata to find chunk-IDs associated with doc_filename
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata_list = json.load(f)  # e.g. list of dicts, each with { "filename", "chunk_id", ...}

    # 4) Identify chunk IDs that belong to this document
    chunk_ids_to_delete = [
        meta["chunk_id"] for meta in metadata_list
        if meta.get("filename") == doc_filename
    ]
    if not chunk_ids_to_delete:
        return  # No chunks found for this doc

    # 5) Load the FAISS index
    import faiss
    index = faiss.read_index(index_path)

    # 6) Remove embeddings from the index
    #    This step depends on how you handle "chunk_id" vs. "FAISS IDs".
    #    If your chunk_id == FAISS ID, you can do index.remove_ids(...).
    #    If not, you must track mapping from chunk_id -> the row ID in FAISS.
    #    For example:
    to_remove = faiss.IDSelectorBatch()
    for cid in chunk_ids_to_delete:
        to_remove.add(int(cid))  # or parse how you store chunk IDs

    index.remove_ids(to_remove)

    # 7) Save the updated index
    faiss.write_index(index, index_path)

    # 8) Update the metadata JSON by removing those chunk items
    new_metadata = [m for m in metadata_list if m.get("filename") != doc_filename]
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(new_metadata, f, ensure_ascii=False, indent=2)

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

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list:
    """
    Simple chunking with overlap.
    """
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
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






def serialize_document(doc):
    """
    Convert MongoDB document to a JSON-serializable dictionary.
    """
    if not doc:
        return doc
    serialized_doc = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            serialized_doc[key] = str(value)
        elif isinstance(value, list):
            serialized_doc[key] = [str(item) if isinstance(item, ObjectId) else item for item in value]
        else:
            serialized_doc[key] = value
    return serialized_doc


# ============================================
# Initialization
# ============================================

# On module load, attempt to load existing index and metadata
try:
    load_index()  # sets index, metadata, document_store if they exist
    if index is not None and index.ntotal > 0:
        logger.info(f"Loaded existing FAISS index with {index.ntotal} vectors.")
    else:
        logger.info("No existing FAISS index loaded or index is empty. Creating new embeddings...")

        # Define the directory where your documents are stored
        DOCS_FOLDER = os.getenv("DOCS_FOLDER", "docs")

        # Check if the documents folder exists
        if not os.path.isdir(DOCS_FOLDER):
            logger.error(f"Documents folder '{DOCS_FOLDER}' does not exist. Please provide a valid path.")
            raise FileNotFoundError(f"Documents folder '{DOCS_FOLDER}' does not exist.")

        total_documents = 0
        total_chunks = 0

        # Iterate over all files in the documents folder
        for filename in os.listdir(DOCS_FOLDER):
            if allowed_file(filename):
                file_path = os.path.join(DOCS_FOLDER, filename)
                logger.info(f"Processing file: {file_path}")

                try:
                    with open(file_path, 'rb') as f:
                        if filename.lower().endswith('.pdf'):
                            text = extract_text_from_pdf(f)
                        else:
                            text = extract_text(f, 'text/plain')

                    if not text.strip():
                        logger.warning(f"No text extracted from '{filename}'. Skipping this file.")
                        continue

                    # Chunk the extracted text
                    chunks = chunk_text(text, chunk_size=1000, overlap=100)
                    num_chunks = len(chunks)
                    logger.info(f"Generated {num_chunks} chunks from '{filename}'.")

                    if num_chunks == 0:
                        logger.warning(f"No chunks created for '{filename}'. Skipping.")
                        continue

                    # Add chunks to the document_store
                    add_document_chunks(filename, chunks)

                    total_documents += 1
                    total_chunks += num_chunks

                except Exception as e:
                    logger.error(f"Failed to process '{filename}': {e}")
                    continue  # Proceed to the next file

        logger.info(f"Processed {total_documents} documents with a total of {total_chunks} chunks.")

        if not document_store:
            logger.error("No document chunks were added to the document store. Aborting embedding creation.")
            raise ValueError("Document store is empty. Ensure that documents are correctly processed and added.")

        # Create embeddings for all chunks in the document_store
        create_embeddings(initial=True)

        # Save the newly created FAISS index and metadata
        save_index()

        logger.info("Embeddings created and index saved successfully.")

except Exception as e:
    logger.error(f"Failed to load or create FAISS index/metadata: {e}")
