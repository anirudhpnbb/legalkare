# bulk_upload.py

import os
import requests
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from pymongo import MongoClient
from datetime import datetime
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import logging
import time
from threading import Lock
from collections import deque  # For our custom rate limiter

from main import extract_text_from_pdf  # Ensure this import is correct based on your project structure
from llm_summarizer import llm_summariser

# ---------------------------- Configuration ---------------------------- #

# Load environment variables from .env file
load_dotenv()

# AWS S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("S3_ACCESS_SECRET_TOKEN")
AWS_REGION = os.getenv("REGION", "us-east-1")  # Default to us-east-1 if not set
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_CLIENT")  # e.g., mongodb://username:password@host:port/database

# Summarization API Configuration (if using an API endpoint, otherwise we call llm_summariser directly)
SUMMARIZATION_API_URL = os.getenv("SUMMARIZATION_API_URL", "http://127.0.0.1:5002/summarise")  # Default URL

# Documents Directory
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", "./documents")  # Default to ./documents if not set
if not os.path.isdir(DOCUMENTS_DIR):
    raise ValueError(f"Documents directory '{DOCUMENTS_DIR}' does not exist.")

# Allowed File Extensions
ALLOWED_EXTENSIONS = {'pdf', 'txt'}

# Maximum File Size (e.g., 10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

# Logging Configuration
LOG_FILE = 'process_documents.log'
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# ---------------------------- Custom Rate Limiter ---------------------------- #
# We'll allow up to 200 calls per 60 seconds.

RATE_LIMIT_CALLS = 200
RATE_LIMIT_PERIOD = 60  # in seconds

rate_limiter_lock = Lock()
call_timestamps = deque()  # store timestamps of recent calls


def wait_for_slot():
    """
    Wait until we have capacity to make another call, respecting
    RATE_LIMIT_CALLS within RATE_LIMIT_PERIOD seconds.
    """
    while True:
        with rate_limiter_lock:
            now = time.time()
            # Remove timestamps older than RATE_LIMIT_PERIOD
            while call_timestamps and (now - call_timestamps[0]) > RATE_LIMIT_PERIOD:
                call_timestamps.popleft()

            if len(call_timestamps) < RATE_LIMIT_CALLS:
                # We have capacity
                call_timestamps.append(now)
                return
        # If over limit, wait and retry
        time.sleep(1)


# ---------------------------- Helper Functions ---------------------------- #

def allowed_file(filename):
    """
    Check if the file has an allowed extension.
    """
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_s3_client():
    """
    Initialize and return a boto3 S3 client.
    """
    try:
        s3_client = boto3.client(
            's3',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        # Verify credentials by listing buckets
        s3_client.list_buckets()
        logging.info("Initialized S3 client successfully.")
        return s3_client
    except NoCredentialsError:
        logging.critical("AWS credentials not found. Please set them in the environment variables.")
        raise
    except ClientError as e:
        logging.critical(f"Failed to initialize S3 client: {e}")
        raise


def init_mongo_client():
    """
    Initialize and return a MongoDB client.
    """
    try:
        mongo_client = MongoClient(MONGO_URI)
        # Optionally, ping the server to ensure connection
        mongo_client.admin.command('ping')
        logging.info("Connected to MongoDB successfully.")
        return mongo_client
    except Exception as e:
        logging.critical(f"Failed to connect to MongoDB: {e}")
        raise


def upload_to_s3(s3_client, file_path, s3_key):
    """
    Upload a file to S3 and return its URL.
    """
    try:
        # Check if the file already exists in S3
        s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        logging.info(f"File '{s3_key}' already exists in S3. Skipping upload.")
        return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            # File does not exist, proceed to upload
            try:
                with open(file_path, 'rb') as data:
                    s3_client.upload_fileobj(data, S3_BUCKET_NAME, s3_key)
                s3_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
                logging.info(f"Uploaded '{s3_key}' to S3 at {s3_url}.")
                return s3_url
            except ClientError as upload_error:
                logging.error(f"Failed to upload '{s3_key}' to S3: {upload_error}")
                return None
        else:
            # Some other error occurred
            logging.error(f"Error checking if '{s3_key}' exists in S3: {e}")
            return None


def store_metadata(mongo_collection, metadata):
    """
    Store document metadata in MongoDB.
    """
    try:
        # Check if metadata already exists based on filename
        existing_doc = mongo_collection.find_one({"filename": metadata['filename']})
        if existing_doc:
            logging.info(f"Metadata for '{metadata['filename']}' already exists in MongoDB. Skipping.")
            return existing_doc['_id']

        result = mongo_collection.insert_one(metadata)
        logging.info(f"Stored metadata for '{metadata['filename']}' in MongoDB with ID {result.inserted_id}.")
        return result.inserted_id
    except Exception as e:
        logging.error(f"Failed to insert metadata into MongoDB for '{metadata['filename']}': {e}")
        return None


def store_summary(mongo_collection, document_id, summary):
    """
    Store the summary of a document in MongoDB.
    """
    try:
        # Check if summary already exists
        existing_summary = mongo_collection.find_one({"document_id": document_id})
        if existing_summary:
            if existing_summary.get("status") == "success":
                logging.info(f"Valid summary for document ID '{document_id}' already exists. Skipping.")
                return True
            else:
                # If previous summarization failed, allow re-summarization
                logging.info(f"Previous summarization for document ID '{document_id}' failed. Reattempting.")
                mongo_collection.delete_one({"_id": existing_summary["_id"]})

        mongo_collection.insert_one({
            "document_id": document_id,
            "summary": summary,
            "status": "success" if summary else "error",
            "generated_at": datetime.utcnow()
        })
        logging.info(f"Stored summary for document ID '{document_id}' in MongoDB.")
        return True
    except Exception as e:
        logging.error(f"Failed to store summary in MongoDB for document ID '{document_id}': {e}")
        return False


def extract_text_from_txt(file_path):
    """
    Extract text from a TXT file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        logging.info(f"Extracted text from TXT file '{file_path}'.")
        return text
    except UnicodeDecodeError:
        logging.error(f"Failed to decode TXT file '{file_path}'. Ensure it's encoded in UTF-8.")
        return None
    except Exception as e:
        logging.error(f"Error extracting text from TXT file '{file_path}': {e}")
        return None


def summarise_indefinitely(text):
    """
    Indefinitely retry summarizing the given text until a 'success' status is returned.
    Respects the rate limiter for each attempt.
    """
    prompt_for_summary = "Please summarise the document in 10 to 15 lines"

    while True:
        # Rate-limit each attempt
        wait_for_slot()

        try:
            # If using a local function llm_summariser (no external call):
            # answer = llm_summariser(text, "gpt-4o-mini", prompt_for_summary, remaining_tokens=2000)
            # summary_obj = {"status": "success", "answer": answer.strip()}

            # OR if you're hitting an external API:
            # files/data approach if needed:
            # response = requests.post(...)

            # For example, calling local llm_summariser:
            result = llm_summariser(text, "gpt-4o-mini", prompt_for_summary, remaining_tokens=2000)
            summary_obj = {
                "status": "success",
                "query": prompt_for_summary,
                "answer": result.strip()
            }

            if summary_obj.get("status") == "success":
                return summary_obj
            else:
                logging.error("Summarization returned 'error' status, retrying in 30s...")
                time.sleep(30)

        except Exception as e:
            logging.error(f"Summarization failed: {e}, retrying in 30s...")
            time.sleep(30)


def process_document(s3_client, mongo_collections, document_path):
    """
    Process a single document: upload to S3, store metadata, generate summary (retry until success),
    and store summary.
    """
    metadata_collection, summary_collection = mongo_collections
    filename = os.path.basename(document_path)
    file_ext = filename.rsplit('.', 1)[1].lower()

    if not allowed_file(filename):
        logging.warning(f"Skipping unsupported file type: '{filename}'.")
        return

    # Validate file size
    try:
        file_size = os.path.getsize(document_path)
    except OSError as e:
        logging.error(f"Could not get size for '{filename}': {e}")
        return

    if file_size > MAX_FILE_SIZE:
        logging.warning(
            f"Skipping '{filename}': File size {file_size} bytes exceeds the maximum limit of {MAX_FILE_SIZE} bytes.")
        return

    # Define S3 key
    s3_key = f"documents/{secure_filename(filename)}"

    # Upload to S3
    s3_url = upload_to_s3(s3_client, document_path, s3_key)
    if not s3_url:
        logging.error(f"Failed to upload '{filename}' to S3.")
        return

    # Extract metadata
    metadata = {
        "filename": filename,
        "s3_url": s3_url,
        "upload_date": datetime.utcnow(),
        "file_size": file_size,
        "file_type": file_ext,
        "original_path": document_path
    }

    # Store metadata in MongoDB
    document_id = store_metadata(metadata_collection, metadata)
    if not document_id:
        logging.error(f"Failed to store metadata for '{filename}' in MongoDB.")
        return

    # Check if summary already exists
    existing_summary = summary_collection.find_one({"document_id": document_id})
    if existing_summary:
        if existing_summary.get("status") == "success":
            logging.info(f"Valid summary for '{filename}' already exists in MongoDB. Skipping summarization.")
            return
        else:
            # If previous summarization failed, attempt to re-summarize
            logging.info(f"Previous summarization for '{filename}' failed. Attempting to re-summarize.")
            summary_collection.delete_one({"_id": existing_summary["_id"]})

    # Extract text
    if file_ext == 'pdf':
        try:
            text = extract_text_from_pdf(document_path)
            if not text or not text.strip():
                logging.warning(f"No text extracted from PDF file '{filename}'. Skipping summarization.")
                return
        except Exception as e:
            logging.error(f"Error extracting text from PDF file '{filename}': {e}")
            return
    elif file_ext == 'txt':
        text = extract_text_from_txt(document_path)
        if not text:
            logging.warning(f"No text extracted from TXT file '{filename}'. Skipping summarization.")
            return
    else:
        logging.warning(f"Unsupported file extension for '{filename}'. Skipping summarization.")
        return

    # Summarize the text (indefinitely retry until success)
    summary_obj = summarise_indefinitely(text)

    # Store summary in MongoDB
    summary_success = store_summary(summary_collection, document_id, summary_obj)
    if not summary_success:
        logging.error(f"Failed to store summary for '{filename}' in MongoDB.")
        return

    logging.info(f"Successfully processed '{filename}'.")


def main():
    """
    Main function to process all documents in the specified directory.
    """
    # Initialize clients
    try:
        s3_client = init_s3_client()
    except Exception as e:
        logging.critical("Aborting script due to S3 client initialization failure.")
        print("Aborting script due to S3 client initialization failure. Check logs for details.")
        return

    try:
        mongo_client = init_mongo_client()
    except Exception as e:
        logging.critical("Aborting script due to MongoDB client initialization failure.")
        print("Aborting script due to MongoDB client initialization failure. Check logs for details.")
        return

    # Define MongoDB collections
    try:
        db = mongo_client["legalaid"]
        metadata_collection = db['legal_documents']
        summary_collection = db['summary']
        mongo_collections = (metadata_collection, summary_collection)
        logging.info("Connected to MongoDB collections successfully.")
    except Exception as e:
        logging.critical(f"Failed to connect to MongoDB collections: {e}")
        print("Failed to connect to MongoDB collections. Check logs for details.")
        return

    # Get list of documents
    all_documents = []
    for root, dirs, files in os.walk(DOCUMENTS_DIR):
        for file in files:
            if allowed_file(file):
                full_path = os.path.join(root, file)
                all_documents.append(full_path)

    logging.info(f"Total documents found: {len(all_documents)}")
    print(f"Total documents found: {len(all_documents)}")

    if not all_documents:
        logging.warning("No documents found to process.")
        print("No documents found to process.")
        return

    # Define maximum number of worker threads
    MAX_WORKERS = 5  # concurrency

    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(process_document, s3_client, mongo_collections, doc_path)
            for doc_path in all_documents
        ]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing Documents"):
            try:
                future.result()
            except Exception as e:
                logging.error(f"Error processing a document: {e}")

    logging.info("All documents have been processed.")
    print("All documents have been processed.")


if __name__ == "__main__":
    main()
