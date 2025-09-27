import re
from pymongo import MongoClient
import os
from dotenv import load_dotenv
import datetime

load_dotenv()

mongo_client = MongoClient(os.getenv("MONGO_CLIENT"))
db = mongo_client["legalaid"]
metadata_collection=db["metadata"]



LOCAL_DIRECTORY="ik_downloads/"

# Regex patterns for metadata extraction
COURT_TYPE_PATTERN = re.compile(r"(Supreme Court|High Court)", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
MONTH_PATTERN = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b", re.IGNORECASE)
DATE_PATTERN = re.compile(r"\b\d{1,2}[-/\s](January|February|March|April|May|June|July|August|September|October|November|December)[-/\s]\d{4}\b", re.IGNORECASE)
STATE_PATTERN = re.compile(r"(Maharashtra|Delhi|Karnataka|Tamil Nadu|Punjab|...)", re.IGNORECASE)  # Add all state names
ACCUSED_NAME_PATTERN = re.compile(r"Accused:\s*(.+)", re.IGNORECASE)

def extract_metadata_from_text(text):
    """
    Extract metadata from the given text using regex patterns.
    """
    court_type = COURT_TYPE_PATTERN.search(text)
    year = YEAR_PATTERN.search(text)
    month = MONTH_PATTERN.search(text)
    date = DATE_PATTERN.search(text)
    state = STATE_PATTERN.search(text)
    accused_name = ACCUSED_NAME_PATTERN.search(text)

    metadata = {
        "court_type": court_type.group(0) if court_type else None,
        "year": int(year.group(0)) if year else None,
        "month": month.group(0) if month else None,
        "date": date.group(0) if date else None,
        "state": state.group(0) if state else None,
        "accused_name": accused_name.group(1).strip() if accused_name else None,
    }

    return metadata

def process_document(file_path):
    """
    Process a single document, extract text, and extract metadata.
    """
    try:
        # Read the text content of the file
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        # Extract metadata
        metadata = extract_metadata_from_text(text)

        # Add file info
        metadata.update({
            "filename": os.path.basename(file_path),
            "file_path": file_path,
            "processed_at": datetime.datetime.utcnow(),
        })

        return metadata
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return None

def process_all_documents():
    """
    Process all .txt documents in the local directory and store metadata in MongoDB.
    """
    try:
        # List all .txt files in the directory
        for root, dirs, files in os.walk(LOCAL_DIRECTORY):
            for file in files:
                if file.endswith(".txt"):
                    file_path = os.path.join(root, file)
                    print(f"Processing file: {file_path}")

                    # Process the document and extract metadata
                    metadata = process_document(file_path)
                    if metadata:
                        # Insert or update metadata in MongoDB
                        metadata_collection.update_one(
                            {"file_path": file_path},
                            {"$set": metadata},
                            upsert=True
                        )
                        print(f"Metadata saved for {file_path}")
                    else:
                        print(f"Failed to process {file_path}")

    except Exception as e:
        print(f"Error processing documents: {e}")

if __name__ == "__main__":
    process_all_documents()