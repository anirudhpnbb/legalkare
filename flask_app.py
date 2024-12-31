from flask import Flask, request, jsonify, session, Blueprint
from flask_session import Session
from flask_cors import CORS
import boto3
from botocore.exceptions import ClientError
import hmac
import hashlib
import base64
import json
import os
from pymongo import MongoClient
import datetime
from source.main import (
    clear_data, extract_text_from_pdf, retrieve_documents,
    create_embeddings, allowed_file, add_document_chunks,
    chunk_text, save_index, get_document_text
)
from source.llm_process import llm_process
from source.llm_summarizer import llm_summariser
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv

# ============================================
# Define the required variables
# ============================================
profile_bp = Blueprint('profile_bp', __name__)

# AWS Configuration
region_name = os.getenv("REGION")
aws_access_key_id = os.getenv("S3_ACCESS_KEY_ID")
aws_secret_access_key=os.getenv("S3_ACCESS_SECRET_TOKEN")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
print(region_name, aws_access_key_id, aws_secret_access_key, "_________________________________")
s3_client = boto3.client('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                         aws_secret_access_key=aws_secret_access_key)
client = boto3.client('cognito-idp', region_name='ap-south-1')
CLIENT_ID = '1dqp62r33cu2kju8g93dohh4o5'
CLIENT_SECRET = '59paljt3ut71l3e829272de2rmle6ko06hfgm3vcsv6mpvbj5gj'

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}},
     supports_credentials=True,
     allow_headers=["Content-Type", "Authorization", "Access-Control-Allow-Credentials", "Access-Control-Allow-Origin"],
     methods=["GET", "POST", "OPTIONS"])

# Flask session configuration
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# MongoDB Client
mongo_client = MongoClient(os.getenv("MONGO_CLIENT"))
db = mongo_client["legalaid"]
users_collection = db["users"]
annotations_collection = db["annotations"]
user_documents_collection = db["user_documents"]

# Initialize counter for user IDs
if not db["counters"].find_one({"_id": "user_id"}):
    db["counters"].insert_one({"_id": "user_id", "seq": 0})


# ============================================
# Define the APIs
# ============================================


def get_next_user_id():
    """
    Generate the next user ID in the sequence.
    """
    counter = db["counters"].find_one_and_update(
        {"_id": "user_id"},
        {"$inc": {"seq": 1}},
        return_document=True
    )
    seq_num = counter["seq"]
    return f"UID{seq_num:04d}"  # Format as UID0001, UID0002, ...


def get_secret_hash(username):
    message = username + CLIENT_ID
    dig = hmac.new(key=CLIENT_SECRET.encode('UTF-8'),
                   msg=message.encode('UTF-8'),
                   digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


# Decorator to check if the user is logged in
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'access_token' not in session:
            return jsonify({"message": "Unauthorized access. Please log in.", "status": "error"}), 401
        return f(*args, **kwargs)
    return decorated_function


@app.route('/register', methods=['POST'])
def register_user():
    """
    Endpoint to register a new user with a sequential user ID.
    """
    username = request.json.get('username')
    password = request.json.get('password')
    email = request.json.get('email')
    given_name = request.json.get('given_name')
    family_name = request.json.get('family_name')
    middle_name = request.json.get('middle_name')
    formatted_name = f"{given_name} {middle_name} {family_name}"
    birthdate = request.json.get('birthdate')  # YYYY-MM-DD
    gender = request.json.get('gender')
    addresses = request.json.get('addresses')  # Assuming this is a formatted JSON string
    secret_hash = get_secret_hash(username)

    # Generate a custom user ID
    user_id = get_next_user_id()

    try:
        response = client.sign_up(
            ClientId=CLIENT_ID,
            SecretHash=secret_hash,
            Username=username,
            Password=password,
            UserAttributes=[
                {'Name': 'email', 'Value': email},
                {'Name': 'name', 'Value': formatted_name},
                {'Name': 'given_name', 'Value': given_name},
                {'Name': 'family_name', 'Value': family_name},
                {'Name': 'middle_name', 'Value': middle_name},
                {'Name': 'birthdate', 'Value': birthdate},
                {'Name': 'gender', 'Value': gender},
                {'Name': 'address', 'Value': addresses}
            ]
        )
        user_data = {
            "user_id": user_id,
            "username": username,
            "password": password,  # Ensure password is hashed in production
            "email": email,
            "name": f"{given_name} {middle_name} {family_name}",
            "birthdate": birthdate,
            "gender": gender,
            "addresses": addresses
        }
        users_collection.insert_one(user_data)
        return jsonify({"message": "User registered successfully", "user_id": user_id}), 200
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500


@app.route('/login', methods=['POST'])
def login_user():
    """
    Endpoint to log in a user.
    """
    username = request.json.get('username')
    password = request.json.get('password')
    secret_hash = get_secret_hash(username)

    try:
        response = client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password,
                'SECRET_HASH': secret_hash
            }
        )
        session['access_token'] = response['AuthenticationResult']['AccessToken']
        session['user_id'] = users_collection.find_one({"username": username})["user_id"]
        return jsonify({"message": "Login successful", "data": response['AuthenticationResult']}), 200
    except ClientError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/logout', methods=['POST'])
def logout():
    """
    Endpoint to log out a user.
    """
    session.clear()
    return jsonify({"message": "Logout successful"}), 200


@profile_bp.route("/update_profile_picture", methods=["POST"])
@login_required
def update_profile_picture():
    """
    Upload a user's profile picture to S3 in the format:
      "profile_pics/<user_id>_<original_filename>"

    Then store the S3 key/URL in the user's record in MongoDB.
    """
    # Check if user is logged in (Cognito or custom auth)
    if "access_token" not in session:
        return jsonify({"message": "Unauthorized", "status": "error"}), 401

    # We'll assume user_id is stored in session after they log in
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"message": "No user ID found in session", "status": "error"}), 401

    # Query your users_collection to ensure user exists
    user_record = users_collection.find_one({"user_id": user_id})
    if not user_record:
        return jsonify({"message": "User not found in Mongo", "status": "error"}), 404

    # Check if file part is in the request
    if 'profile_picture' not in request.files:
        return jsonify({"message": "No profile picture file provided", "status": "error"}), 400

    file = request.files['profile_picture']
    if file.filename == '':
        return jsonify({"message": "Empty filename", "status": "error"}), 400

    # Secure the filename to avoid special chars, etc.
    original_name = secure_filename(file.filename)

    # This is the key in S3: "profile_pics/<user_id>_<original_name>"
    s3_key = f"profile_pics/{user_id}_{original_name}"

    try:
        # Upload to S3
        s3_client.upload_fileobj(
            Fileobj=file,
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={
                "ContentType": file.content_type
            }
        )

        # If you used "public-read", you can form the public URL directly:
        s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

        # Update Mongo: store the profile picture URL/key
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "profile_picture_url": s3_url,
                "profile_picture_key": s3_key
            }}
        )

        return jsonify({
            "message": "Profile picture updated",
            "status": "success",
            "profile_picture_url": s3_url
        }), 200

    except ClientError as ce:
        return jsonify({"message": f"Error uploading to S3: {ce}", "status": "error"}), 500
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500


@app.route('/add_annotation', methods=['POST'])
@login_required
def add_annotation():
    """
    Endpoint to add annotations to a document with optional highlights.
    """
    user_id = session.get('user_id')
    document_name = request.json.get('document_name')
    annotation = request.json.get('annotation')  # The annotation text
    highlighted_text = request.json.get('highlighted_text')  # The text highlighted by the user
    start_index = request.json.get('start_index')  # Start position of the highlighted text
    end_index = request.json.get('end_index')  # End position of the highlighted text
    page_number = request.json.get('page_number', None)  # Optional page number

    if not document_name or not annotation:
        return jsonify({"message": "Document name or annotation is missing", "status": "error"}), 400

    if highlighted_text and (start_index is None or end_index is None):
        return jsonify({"message": "Start and end indices are required for highlighted text.", "status": "error"}), 400

    try:
        annotation_data = {
            "user_id": user_id,
            "document_name": document_name,
            "annotation": annotation,
            "highlighted_text": highlighted_text,
            "start_index": start_index,
            "end_index": end_index,
            "page_number": page_number
        }
        annotations_collection.insert_one(annotation_data)
        return jsonify({"message": "Annotation added successfully.", "status": "success"}), 200
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500


@app.route('/get_annotations', methods=['GET'])
@login_required
def get_annotations():
    """
    Endpoint to get annotations and highlights for a document by a user.
    """
    user_id = session.get('user_id')
    document_name = request.args.get('document_name')

    if not document_name:
        return jsonify({"message": "Document name is missing", "status": "error"}), 400

    try:
        annotations = list(annotations_collection.find({
            "user_id": user_id,
            "document_name": document_name
        }, {"_id": 0}))  # Exclude MongoDB's default _id field
        return jsonify({"annotations": annotations, "status": "success"}), 200
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"message": "No user_id in session", "status": "error"}), 401

    if 'file' not in request.files:
        return jsonify({"message": "No file in request", "status": "error"}), 400

    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"message": "Invalid or missing file", "status": "error"}), 400

    from werkzeug.utils import secure_filename
    import datetime
    original_filename = secure_filename(file.filename)

    # 1) Read ALL bytes from the file into memory first
    file_bytes = file.read()

    # 2) Upload to S3 from memory
    s3_key = f"docs/{user_id}/{original_filename}"
    try:
        import io
        file_obj = io.BytesIO(file_bytes)       # create a new BytesIO from bytes
        s3_client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={
                "ContentType": file.content_type
                # omit "ACL" if bucket disallows ACL
            }
        )
        doc_info = {
            "user_id": user_id,
            "doc_filename": original_filename,
            "s3_key": s3_key,
            "upload_date": datetime.datetime.utcnow()
        }
        user_documents_collection.insert_one(doc_info)

        # 3) Extract text by passing bytes again
        # e.g. pass file_bytes directly to your extract_text_from_pdf
        # if extract_text_from_pdf expects a file-like, wrap file_bytes in BytesIO again
        file_for_pdf = io.BytesIO(file_bytes)
        text = extract_text_from_pdf(file_for_pdf)

        # 4) Then chunk, create embeddings, etc.
        chunks = chunk_text(text, chunk_size=1000, overlap=100)
        add_document_chunks(original_filename, chunks)
        create_embeddings()
        save_index()

        return jsonify({
            "message": f"File '{original_filename}' uploaded, text extracted",
            "status": "success"
        }), 200

    except ClientError as e:
        return jsonify({"message": f"Error uploading to S3: {e}", "status": "error"}), 500
    except Exception as ex:
        return jsonify({"message": str(ex), "status": "error"}), 500





@profile_bp.route("/my_documents", methods=["GET"])
def my_documents():
    """
    Return a list of the user's documents from Mongo, with the S3 keys.
    """
    if "access_token" not in session:
        return jsonify({"message": "Unauthorized", "status": "error"}), 401

    user_id = session["user_id"]
    docs = user_documents_collection.find({"user_id": user_id})

    doc_list = []
    for d in docs:
        doc_list.append({
            "document_id": str(d["_id"]),
            "doc_filename": d["doc_filename"],
            "s3_key": d["s3_key"],
            "upload_date": d.get("upload_date"),
        })

    return jsonify({"message": "Documents retrieved", "status": "success", "documents": doc_list}), 200


@app.route('/chat', methods=['POST'])
@login_required
def chat():
    """
    Endpoint to generate chat-based responses using a specified document.
    """
    content = request.json
    query = content.get('query')
    document_name = content.get('document_name')  # Get document name from request

    if not query or not document_name:
        return jsonify({"message": "No query or document name provided", "status": "error"}), 400

    try:
        # Retrieve the specific document text
        document_text = get_document_text(document_name)
        if not document_text:
            return jsonify({"message": "Document not found", "status": "error"}), 404

        # Generate a response using the LLM with the document text
        answer = llm_process([document_text], "gpt-4o-mini", query)  # Assuming llm_process can handle text directly

        return jsonify({
            "status": "success",
            "document_name": document_name,
            "query": query,
            "answer": answer.strip()
        })
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500



@app.route('/search_docs', methods=['POST'])
@login_required
def search_docs():
    """
    Endpoint to search and list documents most relevant to a specific query.
    Accepts a 'query' string, which can be short or long.
    Returns documents in order of similarity (descending).
    """
    content = request.json
    query = content.get('query')
    if not query:
        return jsonify({"message": "No query provided", "status": "error"}), 400

    # Optional: Let the user specify top_k (how many results to retrieve)
    top_k = content.get('top_k', 1000)  # default = 10

    try:
        # 'retrieve_documents' returns (top_chunks, top_filenames, top_scores)
        top_chunks, top_filenames, top_scores = retrieve_documents(query, top_k=top_k)
        # 'top_scores' are distances (L2), so smaller = more similar

        results = []
        for filename, distance in zip(top_filenames, top_scores):
            # Convert the distance to a similarity score if you prefer
            # For example, similarity = 1 / (1 + distance) or something else
            # Or just keep distance as is, but remember lower is "better"
            similarity_score = 1 / (1 + distance)  # Example transformation

            results.append({
                "filename": filename,
                "distance": float(distance),
                "similarity": similarity_score,
            })

        # We want them sorted by descending similarity => ascending distance
        # If they're already in ascending order from retrieve_docs, we can just reverse.
        # But let's explicitly sort in ascending distance, in case we want to handle ties, etc.
        results.sort(key=lambda x: x["distance"])  # ascending distance => descending similarity

        return jsonify({
            "status": "success",
            "query": query,
            "results": results  # Full list of documents in sorted order
        })
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500



# Optional: Endpoint to clear all data (documents and embeddings)
@app.route('/clear_data', methods=['POST'])
@login_required
def clear_data_endpoint():
    """
    Endpoint to clear all uploaded documents and FAISS index.
    """

    try:
        clear_data()
        # Remove saved index and metadata files
        if os.path.exists("index.faiss"):
            os.remove("index.faiss")
        if os.path.exists("metadata.json"):
            os.remove("metadata.json")
        return jsonify({"message": "All data cleared successfully.", "status": "success"})
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500

@app.route("/summarise", methods=["POST"])
@login_required
def summarise():
    """
    Endpoint to summarize documents. Handles file upload and additional data.
    """
    # Check if there is a file in the request
    if 'file' not in request.files:
        return jsonify({"message": "No file provided", "status": "error"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"message": "No file selected", "status": "error"}), 400

    # Extract text from the file
    try:
        text = extract_text_from_pdf(file)
    except Exception as e:
        return jsonify({"message": "Failed to process file", "status": "error"}), 500

    # Handling non-file form data or JSON data
    prompt_for_summary = request.form.get("query")
    if prompt_for_summary is None:
        # Try to load it as JSON if not found in form
        try:
            data = json.loads(request.data.decode('utf-8'))
            prompt_for_summary = data.get('query')
        except json.JSONDecodeError:
            return jsonify({"message": "Missing or malformed query", "status": "error"}), 400

    if not prompt_for_summary:
        return jsonify({"message": "Query for summarization not provided", "status": "error"}), 400

    try:
        answer = llm_summariser(text, "gpt-4o-mini", prompt_for_summary, remaining_tokens=200000)
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500

    return jsonify({
        "status": "success",
        "query": prompt_for_summary,
        "answer": answer.strip()
    })

app.register_blueprint(profile_bp, url_prefix="/profile")

if __name__ == '__main__':
    app.run(debug=True, port=5002)