import os
import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from pymongo import MongoClient
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ------------------------------
#  A) Mongo & Model Setup
# ------------------------------
MONGO_URI = os.getenv("MONGO_CLIENT")
client = MongoClient(MONGO_URI)
db = client["legalaid"]
users_collection = db["users"]

# You can choose a model name from https://www.sbert.net/docs/pretrained_models.html
MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-mpnet-base-v2")
logger.info(f"Loading SentenceTransformer model: {MODEL_NAME}")
model = SentenceTransformer(MODEL_NAME)

# Where to store the FAISS index + metadata
LAWYER_INDEX_PATH = "lawyer_index.faiss"
LAWYER_METADATA_PATH = "lawyer_metadata.json"


# ------------------------------
#  B) Creating Lawyer Embeddings
# ------------------------------
def create_lawyer_embeddings():
    """
    1) Retrieve all lawyers from MongoDB.
    2) For each lawyer, build a 'profile text' that we want to embed.
    3) Use SentenceTransformer to embed them.
    4) Build a FAISS index that can be searched.
    5) Save index and metadata to disk (lawyer_index.faiss, lawyer_metadata.json).
    """
    # 1) Get all lawyers
    lawyers = list(users_collection.find({"role": "lawyer"}))
    if not lawyers:
        logger.warning("No lawyers found in MongoDB. Aborting embedding creation.")
        return

    # 2) Build profile texts & store metadata
    texts = []
    metadata = []
    for i, lw in enumerate(lawyers):
        # Example: combine relevant fields
        # You might have: specialization, court, years_of_experience, city, etc.
        lawyer_id = lw.get("user_id", "")
        name = lw.get("name", "")
        specialization = lw.get("specialization", "")
        court = lw.get("court", "")
        exp = lw.get("years_of_experience", "")
        # Combine into a single text:
        profile_text = f"Name: {name}. Specialization: {specialization}. Court: {court}. Experience: {exp} years."

        texts.append(profile_text)
        # store minimal metadata so we can identify the lawyer in the FAISS results
        metadata.append({
            "lawyer_id": lawyer_id,
            "name": name,
            "specialization": specialization,
            "court": court,
            "years_of_experience": exp,
        })

    # 3) Embed the lawyers’ profile texts
    logger.info(f"Embedding {len(texts)} lawyers using {MODEL_NAME}...")
    embeddings = model.encode(texts, show_progress_bar=True)
    embeddings = embeddings.astype("float32")  # FAISS prefers float32
    dimension = embeddings.shape[1]
    logger.info(f"Embeddings shape: {embeddings.shape} (num_lawyers x dim)")

    # 4) Build a FAISS index
    index = faiss.IndexFlatL2(dimension)  # L2 distance
    index.add(embeddings)
    logger.info(f"FAISS index created with {index.ntotal} entries.")

    # 5) Save the index and metadata to disk
    faiss.write_index(index, LAWYER_INDEX_PATH)
    with open(LAWYER_METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    logger.info(f"Lawyer embeddings saved to '{LAWYER_INDEX_PATH}' and metadata to '{LAWYER_METADATA_PATH}'.")


if __name__ == "__main__":
    # Run the function if this script is executed directly:
    create_lawyer_embeddings()
