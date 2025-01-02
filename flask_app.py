from flask import Flask, request, jsonify, session, Blueprint, send_file
from flask_session import Session
from flask_cors import CORS
import boto3
from botocore.exceptions import ClientError
import hmac
import hashlib
import base64
import os
import io
from pymongo import MongoClient
import datetime
from werkzeug.utils import secure_filename
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from source.main import (
    clear_data, extract_text_from_pdf, retrieve_documents,
    create_embeddings, allowed_file, add_document_chunks,
    chunk_text, save_index, get_document_text
)
from source.llm_process import llm_process
from source.llm_summarizer import llm_summariser

load_dotenv()

# ============================================
# Define the required variables
# ============================================
profile_bp = Blueprint('profile_bp', __name__)

# AWS Configuration
region_name = os.getenv("REGION")
aws_access_key_id = os.getenv("S3_ACCESS_KEY_ID")
aws_secret_access_key=os.getenv("S3_ACCESS_SECRET_TOKEN")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
ses_region_name = os.getenv("AWS_SES_REGION")
ses_access_key_id = os.getenv("AWS_SES_ACCESS_KEY_ID")
ses_secret_access_key = os.getenv("AWS_SES_SECRET_ACCESS_KEY")
AWS_SES_SOURCE_EMAIL = "noreply@anirudhpalaparthi.com"
client = boto3.client('cognito-idp', region_name='ap-south-1')
CLIENT_ID = '1dqp62r33cu2kju8g93dohh4o5'
CLIENT_SECRET = '59paljt3ut71l3e829272de2rmle6ko06hfgm3vcsv6mpvbj5gj'
s3_client = boto3.client('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                         aws_secret_access_key=aws_secret_access_key)
ses_client = boto3.client(
    'ses',
    region_name=ses_region_name,
    aws_access_key_id=ses_access_key_id,
    aws_secret_access_key=ses_secret_access_key
)


# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:8501"}},
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
appointments_collection = db["appointments"]
user_documents_collection = db["user_documents"]
metadata_collection = db["legal_documents"]
summary_collection = db["summary"]

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

def send_email(to_address, subject, body_text, body_html=None):
    """
    Sends an email using AWS SES.

    :param to_address: Recipient's email address
    :param subject: Subject of the email
    :param body_text: Plain text body
    :param body_html: HTML body (optional)
    :return: True if email is sent successfully, else False
    """
    try:
        # Construct the email parameters as per AWS SES requirements
        email_params = {
            'Source': AWS_SES_SOURCE_EMAIL,
            'Destination': {
                'ToAddresses': [
                    to_address,
                ],
            },
            'Message': {
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body_text,
                        'Charset': 'UTF-8'
                    },
                }
            },
        }

        # Add HTML body if provided
        if body_html:
            email_params['Message']['Body']['Html'] = {
                'Data': body_html,
                'Charset': 'UTF-8'
            }

        # Send the email
        response = ses_client.send_email(**email_params)
    except ClientError as e:
        app.logger.error(f"Error sending email to {to_address}: {e.response['Error']['Message']}")
        return False
    else:
        app.logger.info(f"Email sent to {to_address}! Message ID: {response['MessageId']}")
        return True



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
    Endpoint to register a new user with a sequential user ID and additional profile details.
    """
    username = request.json.get('username')
    password = request.json.get('password')
    email = request.json.get('email')
    given_name = request.json.get('given_name')
    family_name = request.json.get('family_name')
    middle_name = request.json.get('middle_name', "")
    formatted_name = f"{given_name} {middle_name} {family_name}"
    birthdate = request.json.get('birthdate')  # YYYY-MM-DD
    gender = request.json.get('gender')
    addresses = request.json.get('addresses')  # Assuming this is a formatted JSON string
    role = request.json.get('role', 'client')  # Default role is 'client'

    # Additional fields for lawyers
    specialization = request.json.get('specialization') if role == 'lawyer' else None
    court = request.json.get('court') if role == 'lawyer' else None
    years_of_experience = request.json.get('years_of_experience') if role == 'lawyer' else None

    # Generate a custom user ID
    user_id = get_next_user_id()

    # Hash the password before storing
    hashed_password = generate_password_hash(password)

    user_data = {
        "user_id": user_id,
        "username": username,
        "password": hashed_password,
        "email": email,
        "name": f"{given_name} {middle_name} {family_name}",
        "given_name": given_name,
        "family_name": family_name,
        "middle_name": middle_name,
        "birthdate": birthdate,
        "gender": gender,
        "addresses": addresses,
        "role": role,
        "specialization": specialization,
        "court": court,
        "years_of_experience": years_of_experience,
        "profile_picture_url": None  # Initialize as None
    }

    try:
        response = client.sign_up(
            ClientId=CLIENT_ID,
            SecretHash=get_secret_hash(username),
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
                {'Name': 'address', 'Value': addresses},
            ]
        )
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
        # Store tokens and user_id in session
        session['access_token'] = response['AuthenticationResult']['AccessToken']
        user_record = users_collection.find_one({"username": username})
        session['user_id'] = user_record["user_id"] if user_record else None
        session['role'] = user_record["role"] if user_record else None
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






@profile_bp.route("/get_profile", methods=["GET"])
@login_required
def get_profile():
    """
    Retrieve the logged-in user's profile details.
    """
    user_id = session.get("user_id")
    user = users_collection.find_one({"user_id": user_id}, {"_id": 0, "password": 0})
    if user:
        return jsonify({"status": "success", "profile": user}), 200
    else:
        return jsonify({"status": "error", "message": "User not found"}), 404

@profile_bp.route("/update_profile", methods=["PUT"])
@login_required
def update_profile():
    """
    Update the logged-in user's profile details.
    """
    user_id = session.get("user_id")
    data = request.json

    # Define allowed fields for update
    allowed_fields = [
        "name", "given_name", "middle_name", "family_name", "birthdate",
        "gender", "addresses", "specialization", "court",
        "years_of_experience"
    ]

    update_fields = {field: data[field] for field in allowed_fields if field in data}

    if not update_fields:
        return jsonify({"status": "error", "message": "No valid fields provided for update."}), 400

    try:
        users_collection.update_one({"user_id": user_id}, {"$set": update_fields})
        return jsonify({"status": "success", "message": "Profile updated successfully."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@profile_bp.route("/update_profile_picture", methods=["POST"])
@login_required
def update_profile_picture():
    """
    Upload a user's profile picture to S3 in the format:
      "profile_pics/<user_id>_<original_filename>"

    Then store the S3 key/URL in the user's record in MongoDB.
    """
    # Check if user is logged in
    if "access_token" not in session:
        return jsonify({"message": "Unauthorized", "status": "error"}), 401

    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"message": "No user ID found in session", "status": "error"}), 401

    user_record = users_collection.find_one({"user_id": user_id})
    if not user_record:
        return jsonify({"message": "User not found in Mongo", "status": "error"}), 404

    if 'profile_picture' not in request.files:
        return jsonify({"message": "No profile picture file provided", "status": "error"}), 400

    file = request.files['profile_picture']
    if file.filename == '':
        return jsonify({"message": "Empty filename", "status": "error"}), 400

    original_name = secure_filename(file.filename)
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

        # Form the public URL
        s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

        # Update MongoDB
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

@profile_bp.route("/list_lawyers", methods=["GET"])
@login_required
def list_lawyers():
    """
    Retrieve a list of all registered lawyers.
    """
    try:
        lawyers = list(users_collection.find({"role": "lawyer"}, {"_id": 0, "password": 0}))
        return jsonify({"status": "success", "lawyers": lawyers}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@profile_bp.route("/book_appointment", methods=["POST"])
@login_required  # Assuming you have a login_required decorator
def book_appointment():
    """
    Book an appointment with a lawyer.
    """
    user_id = session.get("user_id")
    role = session.get("role")

    # Enforce that only clients can book appointments
    if role != "client":
        return jsonify({"status": "error", "message": "Only clients can book appointments."}), 403

    data = request.json

    lawyer_id = data.get("lawyer_id")
    date_str = data.get("date")  # Expected format: "YYYY-MM-DD"
    time_slot = data.get("time_slot")  # Example: "14:00-15:00"

    if not lawyer_id or not date_str or not time_slot:
        return jsonify({"status": "error", "message": "Missing required fields."}), 400

    # Validate lawyer existence
    lawyer = users_collection.find_one({"user_id": lawyer_id, "role": "lawyer"})
    if not lawyer:
        return jsonify({"status": "error", "message": "Lawyer not found."}), 404

    # Check for time slot conflicts
    existing_appointment = appointments_collection.find_one({
        "lawyer_id": lawyer_id,
        "date": date_str,
        "time_slot": time_slot,
        "status": "booked"
    })
    if existing_appointment:
        return jsonify({"status": "error", "message": "The selected time slot is already booked."}), 409

    # Create a unique appointment ID
    appointment_id = f"APT{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{user_id}"

    appointment = {
        "appointment_id": appointment_id,
        "client_id": user_id,
        "lawyer_id": lawyer_id,
        "date": date_str,
        "time_slot": time_slot,
        "created_at": datetime.datetime.utcnow(),
        "status": "booked"
    }

    try:
        # Insert appointment into the database
        appointments_collection.insert_one(appointment)

        # Retrieve emails
        client = users_collection.find_one({"user_id": user_id})
        client_email = client.get("email")
        client_name = client.get("name")
        lawyer_email = lawyer.get("email")
        lawyer_name = lawyer.get("name")

        # Email content for client
        client_subject = "Appointment Confirmation"
        client_body = f"""
        Dear {client_name},

        You have successfully booked an appointment with {lawyer_name} on {date_str} at {time_slot}.

        Thank you for using LegalAid.
        """

        # Email content for lawyer
        lawyer_subject = "New Appointment Booked"
        lawyer_body = f"""
        Dear {lawyer_name},

        {client_name} has booked an appointment with you on {date_str} at {time_slot}.

        Please prepare accordingly.

        Thank you for using LegalAid.
        """

        # Send email to client
        client_email_sent = send_email(
            to_address=client_email,
            subject=client_subject,
            body_text=client_body
        )

        # Send email to lawyer
        lawyer_email_sent = send_email(
            to_address=lawyer_email,
            subject=lawyer_subject,
            body_text=lawyer_body
        )

        if client_email_sent and lawyer_email_sent:
            return jsonify({"status": "success", "message": "Appointment booked successfully."}), 200
        elif client_email_sent:
            return jsonify({"status": "warning", "message": "Appointment booked, but failed to send email to the lawyer."}), 206
        elif lawyer_email_sent:
            return jsonify({"status": "warning", "message": "Appointment booked, but failed to send email to the client."}), 206
        else:
            return jsonify({"status": "error", "message": "Appointment booked, but failed to send emails."}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to book appointment: {str(e)}"}), 500

@profile_bp.route("/view_appointments", methods=["GET"])
@login_required
def view_appointments():
    """
    Retrieve all appointments for the logged-in lawyer.
    """
    user_id = session.get("user_id")
    role = session.get("role")

    if role != "lawyer":
        return jsonify({"status": "error", "message": "Access denied. Only lawyers can view appointments."}), 403

    try:
        # Fetch appointments where lawyer_id matches the logged-in lawyer's user_id
        appointments_cursor = appointments_collection.find({"lawyer_id": user_id})
        appointments = []
        for appt in appointments_cursor:
            client = users_collection.find_one({"user_id": appt.get("client_id")})
            client_name = client.get("name") if client else "Unknown"
            appointments.append({
                "appointment_id": appt.get("appointment_id"),
                "client_name": client_name,
                "date": appt.get("date"),
                "time_slot": appt.get("time_slot"),
                "status": appt.get("status"),
                "created_at": appt.get("created_at").isoformat() if appt.get("created_at") else "N/A"
            })

        return jsonify({"status": "success", "appointments": appointments}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to retrieve appointments: {str(e)}"}), 500


#
# @profile_bp.route("/update_profile_picture", methods=["POST"])
# @login_required
# def update_profile_picture():
#     """
#     Upload a user's profile picture to S3 in the format:
#       "profile_pics/<user_id>_<original_filename>"
#
#     Then store the S3 key/URL in the user's record in MongoDB.
#     """
#     # Check if user is logged in (Cognito or custom auth)
#     if "access_token" not in session:
#         return jsonify({"message": "Unauthorized", "status": "error"}), 401
#
#     # We'll assume user_id is stored in session after they log in
#     user_id = session.get("user_id")
#     if not user_id:
#         return jsonify({"message": "No user ID found in session", "status": "error"}), 401
#
#     # Query your users_collection to ensure user exists
#     user_record = users_collection.find_one({"user_id": user_id})
#     if not user_record:
#         return jsonify({"message": "User not found in Mongo", "status": "error"}), 404
#
#     # Check if file part is in the request
#     if 'profile_picture' not in request.files:
#         return jsonify({"message": "No profile picture file provided", "status": "error"}), 400
#
#     file = request.files['profile_picture']
#     if file.filename == '':
#         return jsonify({"message": "Empty filename", "status": "error"}), 400
#
#     # Secure the filename to avoid special chars, etc.
#     original_name = secure_filename(file.filename)
#
#     # This is the key in S3: "profile_pics/<user_id>_<original_name>"
#     s3_key = f"profile_pics/{user_id}_{original_name}"
#
#     try:
#         # Upload to S3
#         s3_client.upload_fileobj(
#             Fileobj=file,
#             Bucket=S3_BUCKET_NAME,
#             Key=s3_key,
#             ExtraArgs={
#                 "ContentType": file.content_type
#             }
#         )
#
#         # If you used "public-read", you can form the public URL directly:
#         s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
#
#         # Update Mongo: store the profile picture URL/key
#         users_collection.update_one(
#             {"user_id": user_id},
#             {"$set": {
#                 "profile_picture_url": s3_url,
#                 "profile_picture_key": s3_key
#             }}
#         )
#
#         return jsonify({
#             "message": "Profile picture updated",
#             "status": "success",
#             "profile_picture_url": s3_url
#         }), 200
#
#     except ClientError as ce:
#         return jsonify({"message": f"Error uploading to S3: {ce}", "status": "error"}), 500
#     except Exception as e:
#         return jsonify({"message": str(e), "status": "error"}), 500


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





@app.route("/my_documents", methods=["GET"])
@login_required
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
    Accepts a 'query' string and returns documents in order of similarity,
    including their summaries if available.
    """
    content = request.json
    SIMILARITY_THRESHOLD = 0.6
    query = content.get('query')
    if not query:
        return jsonify({"message": "No query provided", "status": "error"}), 400

    # Let the user specify top_k (how many results to retrieve)
    top_k = content.get('top_k', 1000)  # default = 1000

    try:
        # 'retrieve_documents' returns (top_chunks, top_filenames, top_scores)
        top_chunks, top_filenames, top_scores = retrieve_documents(query, top_k=top_k)
        # 'top_scores' are distances (L2), so smaller = more similar

        # Calculate similarity scores and filter based on threshold
        results = []
        for filename, distance in zip(top_filenames, top_scores):
            # Convert distance to similarity score
            similarity_score = 1 / (1 + distance)  # Example transformation

            if similarity_score >= SIMILARITY_THRESHOLD:
                results.append({
                    "filename": filename,
                    "distance": float(distance),
                    "similarity": round(similarity_score * 100, 2),
                })

        # Sort results by ascending distance (descending similarity)
        results.sort(key=lambda x: x["distance"])

        if not results:
            return jsonify({
                "status": "success",
                "query": query,
                "results": []
            }), 200

        # Bulk fetch document metadata based on filenames
        filenames = [doc['filename'] for doc in results]
        metadata_cursor = metadata_collection.find({"filename": {"$in": filenames}})
        metadata_map = {meta['filename']: meta['_id'] for meta in metadata_cursor}

        # Bulk fetch summaries based on document_ids
        document_ids = list(metadata_map.values())
        summaries_cursor = summary_collection.find({"document_id": {"$in": document_ids}})
        summaries_map = {summ['document_id']: summ for summ in summaries_cursor}

        # Attach summaries to the results
        for doc in results:
            filename = doc['filename']
            document_id = metadata_map.get(filename)
            if not document_id:
                # Metadata not found; skip attaching summary
                doc['summary'] = "Metadata not found."
                continue

            summary = summaries_map.get(document_id)
            try:
                    # Safely extract the summary message
                    summary_message = summary.get('summary')
                    doc['summary'] = summary_message
            except:
                # Summary not found
                doc['summary'] = {"status": "failed", "answer": "Summary not available."}

        return jsonify({
            "status": "success",
            "query": query,
            "results": results  # List of documents with summaries
        }), 200

    except Exception as e:
        # Log the exception (ensure you have proper logging configured)
        app.logger.error(f"Error in search_docs: {str(e)}")
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

# ... [Other configurations and route definitions] ...

@app.route("/summarise", methods=["POST"])
@login_required  # Ensure this decorator is applied if required
def summarise():
    """
    Endpoint to summarize documents. Handles file upload and additional data.
    Accepts PDF and TXT files.
    """
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'pdf', 'txt'}

    # Check if a file is part of the request
    if 'file' not in request.files:
        return jsonify({"message": "No file provided", "status": "error"}), 400

    file = request.files['file']

    # Check if the file has a valid filename
    if file.filename == '':
        return jsonify({"message": "No file selected", "status": "error"}), 400

    # Secure the filename to prevent directory traversal attacks
    filename = secure_filename(file.filename)
    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    # Validate file extension
    if file_ext not in ALLOWED_EXTENSIONS:
        return jsonify(
            {"message": f"Unsupported file type: .{file_ext}. Allowed types are PDF and TXT.", "status": "error"}), 400

    # Optional: Validate file size (e.g., max 10MB)
    # MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    # file.seek(0, os.SEEK_END)
    # file_length = file.tell()
    # file.seek(0)  # Reset file pointer
    # if file_length > MAX_FILE_SIZE:
    #     return jsonify({"message": "File size exceeds the maximum limit of 10MB.", "status": "error"}), 400

    # Extract text based on file type
    try:
        if file_ext == 'pdf':
            text = extract_text_from_pdf(file)
            if not text.strip():
                raise ValueError("No text extracted from PDF.")
        elif file_ext == 'txt':
            # Read the file content as UTF-8 text
            text_bytes = file.read()
            try:
                text = text_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return jsonify(
                    {"message": "Failed to decode TXT file. Ensure it's encoded in UTF-8.", "status": "error"}), 400
    except Exception as e:
        return jsonify({"message": f"Error extracting text from file: {str(e)}", "status": "error"}), 500

    # Retrieve the summarization query from form data or JSON
    prompt_for_summary = request.form.get("query")
    if not prompt_for_summary:
        # Attempt to parse JSON payload if 'query' not found in form data
        if request.is_json:
            data = request.get_json()
            prompt_for_summary = data.get('query', '')

    if not prompt_for_summary:
        return jsonify({"message": "Query for summarization not provided", "status": "error"}), 400

    # Optional: Validate the prompt length
    MAX_PROMPT_LENGTH = 1000  # Adjust as per model capabilities
    if len(prompt_for_summary) > MAX_PROMPT_LENGTH:
        return jsonify(
            {"message": f"Query exceeds maximum length of {MAX_PROMPT_LENGTH} characters.", "status": "error"}), 400

    # Summarize the extracted text
    try:
        # Adjust remaining_tokens as per your model's requirements
        answer = llm_summariser(text, "gpt-4o-mini", prompt_for_summary, remaining_tokens=2000)
    except Exception as e:
        return jsonify({"message": f"Summarization failed: {str(e)}", "status": "error"}), 500

    # Return the summarization result
    return jsonify({
        "status": "success",
        "query": prompt_for_summary,
        "answer": answer.strip()
    }), 200


@app.route('/serve_document', methods=['GET'])
@login_required  # Ensure only authenticated users can access
def serve_document():
    document_key = request.args.get('document_key')

    if not document_key:
        return jsonify({"message": "No document_key provided.", "status": "error"}), 400

    # Additional authorization checks can be added here
    # For example, verify if the user has access to the requested document

    try:
        s3_response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=document_key)
        file_stream = s3_response['Body'].read()
        return send_file(
            io.BytesIO(file_stream),
            attachment_filename=document_key.split('/')[-1],
            mimetype=s3_response['ContentType']
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return jsonify({"message": "Document not found.", "status": "error"}), 404
        else:
            return jsonify({"message": "Error fetching document.", "status": "error"}), 500


app.register_blueprint(profile_bp, url_prefix="/profile")

if __name__ == '__main__':
    app.run(debug=True, port=5002)