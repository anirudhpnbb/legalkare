import os
from main import (
    chunk_text,
    add_document_chunks,
    create_embeddings,
    save_index,
    load_index,
    document_store,   # global from main.py
    metadata          # global from main.py
)

def file_already_in_metadata(filename: str) -> bool:
    """
    Check if a given filename already appears in the global 'metadata' list.
    Returns True if found, False otherwise.
    """
    for m in metadata:
        if m.get("filename") == filename:
            return True
    return False

def process_text_files(directory_path):
    """
    Reads all .txt files from the given directory, checks if they exist in
    metadata, and if not, chunks them, adds them to the global document_store.
    Finally, creates/saves embeddings for everything in memory.
    """
    # Load any existing index/metadata from disk (optional if main.py already did it)
    load_index()

    processed_count = 0
    skipped_count = 0

    for filename in os.listdir(directory_path):
        if filename.lower().endswith('.txt'):
            file_path = os.path.join(directory_path, filename)

            # Check if we've already processed this file
            if file_already_in_metadata(filename):
                print(f"[!] Skipping '{filename}' (already in metadata).")
                skipped_count += 1
                continue

            print(f"[+] Processing new file '{filename}'...")
            # 1) Read plain-text from file
            with open(file_path, 'r', encoding='utf-8') as f:
                text_content = f.read()

            # 2) Chunk the text
            chunks = chunk_text(text_content, chunk_size=1000, overlap=100)

            # 3) Add these chunks to the document_store (filename + chunk_text)
            add_document_chunks(filename, chunks)
            processed_count += 1

    # Only if there are new documents added do we rebuild embeddings
    if processed_count > 0:
        # 4) Create embeddings for ALL documents in memory (old + new)
        create_embeddings()

        # 5) Save the FAISS index + metadata
        save_index()
        print(f"[+] {processed_count} new files processed, embeddings/index saved.")
    else:
        print(f"[!] No new files processed (skipped={skipped_count}). Embeddings not rebuilt.")

if __name__ == "__main__":
    folder_with_txt_files = "ik_downloads"
    process_text_files(folder_with_txt_files)
