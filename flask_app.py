from flask import Flask, request, jsonify, session, Blueprint, send_file
from flask_session import Session
from flask_cors import CORS
import boto3
from botocore.exceptions import ClientError
import hmac
import hashlib
import base64
from bson.objectid import ObjectId
from bson.json_util import dumps
from bson import json_util
import openai
import os
import io
from pymongo import MongoClient
import datetime
from werkzeug.utils import secure_filename
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()

def validate_required_env_vars():
    """Validate that required environment variables are set"""
    required_vars = [
        "SECRET_KEY_FLASK",
        "MONGO_CLIENT", 
        "COGNITO_CLIENT_ID",
        "COGNITO_CLIENT_SECRET",
        "S3_BUCKET_NAME",
        "TWILIO_ACCOUNT_SID"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file and ensure all required variables are set.")
        print("See .env.template for reference.")
        sys.exit(1)

# Validate environment variables on startup
validate_required_env_vars()
from source.main import *
from source.llm_process import llm_process
from source.llm_summarizer import llm_summariser
from source.chat import llm_process_chat
import bleach
import logging
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VideoGrant
from flask import Flask, request, jsonify
import stripe

# TODO: Convert the following flask app into django microservice architecture.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================
# Define the required variables
# ============================================
profile_bp = Blueprint('profile_bp', __name__)
documents_bp = Blueprint('documents', __name__)
prompts_bp = Blueprint('prompts_bp', __name__)
lawyers_bp = Blueprint('lawyers_bp', __name__)
whatsapp_bp = Blueprint("whatsapp_bp", __name__)





# AWS Configuration
region_name = os.getenv("REGION")
aws_access_key_id = os.getenv("S3_ACCESS_KEY_ID")
aws_secret_access_key=os.getenv("S3_ACCESS_SECRET_TOKEN")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
ses_region_name = os.getenv("AWS_SES_REGION")
ses_access_key_id = os.getenv("AWS_SES_ACCESS_KEY_ID")
ses_secret_access_key = os.getenv("AWS_SES_SECRET_ACCESS_KEY")
AWS_SES_SOURCE_EMAIL = os.getenv("AWS_SES_SOURCE_EMAIL")
client = boto3.client('cognito-idp', region_name=region_name)
CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET")
s3_client = boto3.client('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                         aws_secret_access_key=aws_secret_access_key)
ses_client = boto3.client(
    'ses',
    region_name=ses_region_name,
    aws_access_key_id=ses_access_key_id,
    aws_secret_access_key=ses_secret_access_key
)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY_SID = os.getenv("TWILIO_API_KEY_SID")
TWILIO_API_KEY_SECRET = os.getenv("TWILIO_API_KEY_SECRET")

# Initialize Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY_FLASK")  # Set SECRET_KEY from environment variable

# Existing CORS and session configurations
CORS(app, supports_credentials=True, origins=[
    "http://127.0.0.1:5500",       # Your web app (if needed)
    "http://localhost:19000",      # Common Expo simulator address
    "http://127.0.0.1:19000",
    "http://192.168.0.196:19000"
])

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
teams_collection = db["teams"]
prompts_collection = db["prompts"]
notifications_collection = db["notifications"]
faqs_collection = db["faqs"]
reviews_collection = db["reviews"]
consultations_collection = db["consultations"]

# Load the model
LAWYER_INDEX_PATH = "lawyer_index.faiss"
LAWYER_METADATA_PATH = "lawyer_metadata.json"

Lawyer_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-mpnet-base-v2")
lawyer_model = SentenceTransformer(Lawyer_MODEL_NAME)

# Global references
faiss_index = None
lawyer_metadata = []

# Initialize counter for user IDs
if not db["counters"].find_one({"_id": "user_id"}):
    db["counters"].insert_one({"_id": "user_id", "seq": 0})

if not db["counters"].find_one({"_id": "team_id"}):
    db["counters"].insert_one({"_id": "team_id", "seq": 0})
    logger.info("Initialized counter for team_id with seq=0")

if not db["counters"].find_one({"_id": "prompt_id"}):
    db["counters"].insert_one({"_id": "prompt_id", "seq": 0})
    logger.info("Initialized counter for prompt_id with seq=0")

if not db["counters"].find_one({"_id": "notification_id"}):
    db["counters"].insert_one({"_id": "notification_id", "seq": 0})
    logger.info("Initialized counter for notification_id with seq=0")
# ============================================
# Define the APIs
# ============================================

def create_notification_helper(data):
    """
    Helper function to create a notification.
    """
    team_id = data.get("team_id")
    team_name = data.get("team_name")
    invited_by = data.get("invited_by")  # Team creator
    invited_to = data.get("invited_to")  # Lawyer invited

    if not all([team_id, team_name, invited_by, invited_to]):
        return False, "Missing required fields for notification."

    notification_id = get_next_notification_id()
    invited_at = datetime.datetime.utcnow()

    notification = {
        "notification_id": notification_id,
        "team_id": team_id,
        "team_name": team_name,
        "invited_by": invited_by,
        "invited_to": invited_to,
        "invited_at": invited_at
    }

    try:
        notifications_collection.insert_one(notification)
        logger.info(f"Notification '{notification_id}' created for user '{invited_to}' to join team '{team_id}'.")
        return True, "Notification created successfully."
    except Exception as e:
        logger.error(f"Failed to create notification for user '{invited_to}': {e}")
        return False, f"Failed to create notification: {str(e)}"



def cosine_similarity(vec1, vec2):
    """Compute the cosine similarity between two embedding vectors."""
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)
    dot_product = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return float(dot_product / (norm1 * norm2))


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


def get_next_prompt_id():
    """
    Generate the next prompt ID in the sequence.
    """
    counter = db["counters"].find_one_and_update(
        {"_id": "prompt_id"},
        {"$inc": {"seq": 1}},
        return_document=True,
        upsert=True
    )
    seq_num = counter["seq"]
    return f"PROMPT{seq_num:04d}"  # Format as PROMPT0001, PROMPT0002, ...

def get_next_notification_id():
    """
    Generate the next notification ID in the sequence.
    """
    counter = db["counters"].find_one_and_update(
        {"_id": "notification_id"},
        {"$inc": {"seq": 1}},
        return_document=True,
        upsert=True  # Ensures the counter is created if it doesn't exist
    )
    seq_num = counter["seq"]
    return f"NOTIF{seq_num:04d}"  # Formats as NOTIF0001, NOTIF0002, etc.

def get_next_team_id():
    """
    Generate the next team ID in the sequence.
    """
    counter = db["counters"].find_one_and_update(
        {"_id": "team_id"},
        {"$inc": {"seq": 1}},
        return_document=True
    )
    seq_num = counter["seq"]
    return f"TID{seq_num:04d}"  # Format as TID0001, TID0002, ...



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

def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """
    Generate a pre-signed URL to share an S3 object.

    :param bucket_name: Name of the S3 bucket.
    :param object_key: Key of the S3 object.
    :param expiration: Time in seconds for the pre-signed URL to remain valid.
    :return: Pre-signed URL as string. If error, returns None.
    """
    try:
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_key, 'ResponseContentDisposition': 'inline'},
            ExpiresIn=expiration
        )
    except ClientError as e:
        print(f"Error generating pre-signed URL: {e}")
        return None

    return response


def get_secret_hash(username):
    message = username + CLIENT_ID
    dig = hmac.new(key=CLIENT_SECRET.encode('UTF-8'),
                   msg=message.encode('UTF-8'),
                   digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


# Helper decorator to check for login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'access_token' not in session:
            logger.warning("Unauthorized access attempt - no access token.")
            return jsonify({"message": "Unauthorized access. Please log in.", "status": "error"}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route("/", methods=["GET"])
def root_home():
    return "Hello, this is the root of my Flask app!"


@app.route('/register', methods=['POST'])
def register_user():
    """
    Endpoint to register a new user.
    """
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    given_name = data.get('given_name')
    family_name = data.get('family_name')
    middle_name = data.get('middle_name', "")
    birthdate = data.get('birthdate')
    gender = data.get('gender')
    addresses = data.get('addresses')
    role = data.get('role', 'client')

    # Additional fields for lawyers
    specialization = data.get('specialization') if role == 'lawyer' else None
    court = data.get('court') if role == 'lawyer' else None
    years_of_experience = data.get('years_of_experience') if role == 'lawyer' else None

    user_id = get_next_user_id()
    hashed_password = generate_password_hash(password)
    formatted_name = f"{given_name} {middle_name} {family_name}"

    user_data = {
        "user_id": user_id,
        "username": username,
        "password": hashed_password,
        "email": email,
        "name": formatted_name,
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
        "profile_picture_url": None
    }

    try:
        # Register with Cognito
        client.sign_up(
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
        # Insert into our local Mongo
        users_collection.insert_one(user_data)
        return jsonify({"message": "User registered successfully", "user_id": user_id}), 200
    except Exception as e:
        logger.error(f"Error registering user: {str(e)}")
        return jsonify({"message": str(e), "status": "error"}), 500


@app.route('/login', methods=['POST'])
def login_user():
    """
    Endpoint to log in a user.
    """
    data = request.json
    username = data.get('username')
    password = data.get('password')
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
        user_record = users_collection.find_one({"username": username})
        session['user_id'] = user_record["user_id"] if user_record else None
        session['role'] = user_record["role"] if user_record else None

        return jsonify({
            "message": "Login successful",
            "data": response['AuthenticationResult'],
            "role": user_record["role"],
            "user_id": user_record["user_id"]
        }), 200

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
    user_id = session.get("user_id")
    user = users_collection.find_one({"user_id": user_id}, {"_id": 0, "password": 0})
    if user:
        # If the user has a profile_picture_key, create a pre-signed URL
        if user.get("profile_picture_key"):
            presigned_url = generate_presigned_url(S3_BUCKET_NAME, user["profile_picture_key"])
            user["profile_picture_url"] = presigned_url
        return jsonify({"status": "success", "profile": user}), 200
    else:
        return jsonify({"status": "error", "message": "User not found"}), 404



@profile_bp.route("/update_profile", methods=["PUT"])
@login_required
def update_profile():
    user_id = session.get("user_id")
    data = request.json
    allowed_fields = [
        "name", "given_name", "middle_name", "family_name", "birthdate",
        "gender", "addresses", "specialization", "court", "years_of_experience"
    ]
    update_fields = {f: data[f] for f in allowed_fields if f in data}

    if not update_fields:
        return jsonify({"status": "error", "message": "No valid fields provided."}), 400

    try:
        users_collection.update_one({"user_id": user_id}, {"$set": update_fields})
        return jsonify({"status": "success", "message": "Profile updated."}), 200
    except Exception as e:
        logger.error(f"Error updating profile for user {user_id}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@profile_bp.route("/update_profile_picture", methods=["POST"])
@login_required
def update_profile_picture():
    user_id = session.get("user_id")
    if 'profile_picture' not in request.files:
        return jsonify({"message": "No profile_picture provided", "status": "error"}), 400

    file = request.files['profile_picture']
    if file.filename == '':
        return jsonify({"message": "Empty filename", "status": "error"}), 400

    original_name = secure_filename(file.filename)
    s3_key = f"profile_pics/{user_id}_{original_name}"

    try:
        s3_client.upload_fileobj(
            Fileobj=file,
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={"ContentType": file.content_type}
        )
        s3_url = f"https://{S3_BUCKET_NAME}.s3.{region_name}.amazonaws.com/{s3_key}"

        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {
                "profile_picture_url": s3_url,
                "profile_picture_key": s3_key
            }}
        )
        return jsonify({
            "message": "Profile picture updated successfully.",
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
    # ... [unchanged from your original code] ...
    try:
        lawyers_cursor = users_collection.find({"role": "lawyer"})
        lawyers_list = []
        for lw in lawyers_cursor:
            lw["_id"] = str(lw["_id"])
            lw.pop("password", None)
            profile_key = lw.get("profile_picture_key")
            if profile_key:
                presigned_url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": S3_BUCKET_NAME,
                        "Key": profile_key,
                        "ResponseContentDisposition": "inline"
                    },
                    ExpiresIn=3600
                )
                lw["profile_picture_url"] = presigned_url
            else:
                lw["profile_picture_url"] = None
            lawyers_list.append(lw)
        return jsonify({"status": "success", "lawyers": lawyers_list}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/clear_user_embeddings', methods=['POST'])
@login_required
def clear_user_embeddings():
    """
    Example endpoint to remove the current user's private FAISS index & metadata from disk.
    This does NOT remove the documents from MongoDB or S3—only the embeddings stored on disk.
    """
    user_id = session.get("user_id")
    try:
        clear_user_data(user_id)  # Removes the index_{user_id}.faiss and metadata_{user_id}.json
        return jsonify({
            "message": f"Embeddings for user {user_id} have been cleared.",
            "status": "success"
        }), 200
    except Exception as e:
        logger.error(f"Error clearing embeddings for user {user_id}: {str(e)}")
        return jsonify({"message": str(e), "status": "error"}), 500


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

        Thank you for using LegalKare.
        """

        # Email content for lawyer
        lawyer_subject = "New Appointment Booked"
        lawyer_body = f"""
        Dear {lawyer_name},

        {client_name} has booked an appointment with you on {date_str} at {time_slot}.

        Please prepare accordingly.

        Thank you for using LegalKare.
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





@profile_bp.route("/update_appointment", methods=["POST"])
@login_required
def update_appointment():
    """
    Endpoint to accept, reject, or update an appointment.
    Expects JSON body with:
        - appointment_id: str
        - action: str ('accept', 'reject', 'update')
        - date: str (YYYY-MM-DD) [Required if action is 'update']
        - time_slot: str (e.g., "14:00-15:00") [Required if action is 'update']
    """
    user_id = session.get("user_id")
    role = session.get("role")

    if role != "lawyer":
        return jsonify({"status": "error", "message": "Only lawyers can update appointments."}), 403

    data = request.json
    appointment_id = data.get("appointment_id")
    action = data.get("action")

    if not appointment_id or not action:
        return jsonify({"status": "error", "message": "Missing 'appointment_id' or 'action'."}), 400

    # Fetch the appointment
    appointment = appointments_collection.find_one({"appointment_id": appointment_id, "lawyer_id": user_id})

    if not appointment:
        return jsonify({"status": "error", "message": "Appointment not found."}), 404

    current_status = appointment.get("status", "").lower()

    # Define allowed transitions
    allowed_transitions = {
        "booked": ["accepted", "rejected"],
        "pending": ["accepted", "rejected"],
        "accepted": ["rejected"],
        "rejected": ["accepted"]
    }

    action = action.lower()

    if action == "accept":
        new_status = "accepted"
    elif action == "reject":
        new_status = "rejected"
    elif action == "update":
        new_date = data.get("date")
        new_time_slot = data.get("time_slot")
        if not new_date or not new_time_slot:
            return jsonify({"status": "error", "message": "Both 'date' and 'time_slot' are required for updating."}), 400

        # Validate date format
        try:
            datetime.datetime.strptime(new_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}), 400

        # Check for time slot conflicts
        existing_appointment = appointments_collection.find_one({
            "lawyer_id": user_id,
            "date": new_date,
            "time_slot": new_time_slot,
            "status": {"$in": ["booked", "accepted", "pending"]}
        })
        if existing_appointment and existing_appointment.get("appointment_id") != appointment_id:
            return jsonify({"status": "error", "message": "The selected time slot is already booked."}), 409

        # Update the appointment's date and time_slot
        try:
            appointments_collection.update_one(
                {"appointment_id": appointment_id},
                {"$set": {
                    "date": new_date,
                    "time_slot": new_time_slot,
                    "status": "booked"  # Reset status to 'booked' after update
                }}
            )
            # Notify the client about the update
            client_id = appointment.get("client_id")
            client = users_collection.find_one({"user_id": client_id})
            if client:
                client_email = client.get("email")
                client_name = client.get("name")
                lawyer = users_collection.find_one({"user_id": user_id})
                lawyer_name = lawyer.get("name") if lawyer else "Your Lawyer"

                subject = "Your Appointment has been Updated"
                body = f"""
                Dear {client_name},

                Your appointment with {lawyer_name} has been updated to {new_date} at {new_time_slot}.

                Please confirm your availability.

                Thank you for using LegalKare.
                """

                send_email(
                    to_address=client_email,
                    subject=subject,
                    body_text=body
                )

            return jsonify({"status": "success", "message": "Appointment updated successfully."}), 200

        except Exception as e:
            logger.error(f"Error updating appointment: {e}")
            return jsonify({"status": "error", "message": f"Failed to update appointment: {str(e)}"}), 500

    else:
        return jsonify({"status": "error", "message": "Invalid action. Must be 'accept', 'reject', or 'update'."}), 400

    # Check if the transition is allowed
    if new_status not in allowed_transitions.get(current_status, []):
        return jsonify({"status": "error", "message": f"Cannot change status from '{current_status}' to '{new_status}'."}), 400

    # Prepare update data
    update_data = {"status": new_status}

    try:
        # Update the appointment in the database
        appointments_collection.update_one(
            {"appointment_id": appointment_id},
            {"$set": update_data}
        )

        # Notify the client about the status change
        client_id = appointment.get("client_id")
        client = users_collection.find_one({"user_id": client_id})
        if client:
            client_email = client.get("email")
            client_name = client.get("name")
            lawyer = users_collection.find_one({"user_id": user_id})
            lawyer_name = lawyer.get("name") if lawyer else "Your Lawyer"

            if action == "accept":
                subject = "Your Appointment has been Accepted"
                body = f"""
                Dear {client_name},

                Your appointment with {lawyer_name} on {appointment.get('date')} at {appointment.get('time_slot')} has been accepted.

                Thank you for using LegalKare.
                """
            elif action == "reject":
                subject = "Your Appointment has been Rejected"
                body = f"""
                Dear {client_name},

                We regret to inform you that your appointment with {lawyer_name} on {appointment.get('date')} at {appointment.get('time_slot')} has been rejected.

                Please book another appointment at your convenience.

                Thank you for using LegalKare.
                """

            # Send email to client
            send_email(
                to_address=client_email,
                subject=subject,
                body_text=body
            )

        return jsonify({"status": "success", "message": f"Appointment {action}ed successfully."}), 200

    except Exception as e:
        logger.error(f"Error updating appointment: {e}")
        return jsonify({"status": "error", "message": f"Failed to update appointment: {str(e)}"}), 500


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



@app.route('/add_annotation', methods=['POST'])
def add_annotation():
    """
    Endpoint to add annotations to a document with optional highlights.
    Expects user_id from the frontend.
    """
    data = request.json
    user_id = data.get('user_id')
    document_name = data.get('document_name')
    annotation = data.get('annotation')
    highlighted_text = data.get('highlighted_text')
    start_index = data.get('start_index')
    end_index = data.get('end_index')
    page_number = data.get('page_number', 1)

    # Basic validation
    if not user_id or not document_name or not annotation:
        return jsonify({"message": "User ID, document name, or annotation is missing.", "status": "error"}), 400

    if highlighted_text and (start_index is None or end_index is None):
        return jsonify({"message": "Start and end indices are required for highlighted text.", "status": "error"}), 400

    try:
        # Validate user exists
        user = users_collection.find_one({"user_id": user_id})
        if not user:
            return jsonify({"message": "Invalid user ID.", "status": "error"}), 400

        # Optional: Sanitize annotation to prevent XSS
        # import bleach
        # annotation = bleach.clean(annotation)

        # Prepare annotation data
        annotation_data = {
            "user_id": user_id,
            "document_name": document_name,
            "annotation": annotation,
            "highlighted_text": highlighted_text,
            "start_index": start_index,
            "end_index": end_index,
            "page_number": page_number,
            "timestamp": datetime.datetime.utcnow()
        }

        # Insert into MongoDB
        annotations_collection.insert_one(annotation_data)

        return jsonify({
            "message": "Annotation added successfully.",
            "status": "success",
            "user_id": user_id,
            "timestamp": annotation_data["timestamp"].isoformat()
        }), 200
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500

@app.route('/get_annotations', methods=['GET'])
def get_annotations():
    """
    Endpoint to retrieve annotations for a specific document.
    """
    document_name = request.args.get('document_name')
    if not document_name:
        return jsonify({"message": "Document name is missing.", "status": "error"}), 400

    try:
        # Retrieve annotations from MongoDB
        annotations = list(annotations_collection.find({"document_name": document_name}, {"_id": 0}))
        # Convert datetime objects to ISO format strings
        for ann in annotations:
            if isinstance(ann.get("timestamp"), datetime.datetime):
                ann["timestamp"] = ann["timestamp"].isoformat()
        return jsonify({"status": "success", "annotations": annotations}), 200
    except Exception as e:
        return jsonify({"message": str(e), "status": "error"}), 500


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """
    Upload a document privately for the current user. Creates user-specific embeddings
    with a doc_filename that matches your MongoDB "doc_filename".
    """
    user_id = session.get("user_id")
    if not user_id:
        logger.warning("No user_id in session.")
        return jsonify({"message": "No user_id in session", "status": "error"}), 401

    # 1) Get or create the folder structure
    folder = request.form.get('folder', 'General').strip()
    if not folder:
        folder = 'General'

    # 2) Check for file in request
    if 'file' not in request.files:
        logger.warning("No file in the request.")
        return jsonify({"message": "No file in request", "status": "error"}), 400
    file = request.files['file']
    if file.filename == '':
        logger.warning("Empty filename received.")
        return jsonify({"message": "Empty filename", "status": "error"}), 400

    # 3) Validate extension
    if not allowed_file(file.filename):
        logger.warning(f"Disallowed file extension for: {file.filename}")
        return jsonify({"message": "Invalid or missing file extension", "status": "error"}), 400

    # 4) We keep the original filename as doc_filename for consistent matching
    original_filename = secure_filename(file.filename)
    file_bytes = file.read()

    # 5) Upload to S3
    s3_key = f"docs/{user_id}/{folder}/{original_filename}"
    try:
        file_obj = io.BytesIO(file_bytes)
        s3_client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            ExtraArgs={"ContentType": file.content_type}
        )
        logger.info(f"File uploaded to S3 at key: {s3_key}")

        # 6) Store doc info in DB with the EXACT same doc_filename:
        doc_info = {
            "user_id": user_id,
            "doc_filename": original_filename,  # match the chunk filename
            "s3_key": s3_key,
            "folder": folder,
            "upload_date": datetime.datetime.utcnow()
        }
        user_documents_collection.insert_one(doc_info)
        logger.info(f"Document info inserted into Mongo: {doc_info}")

        # 7) Extract text from the PDF/TXT
        file_for_text = io.BytesIO(file_bytes)
        text = extract_text(file_for_text, file.content_type)
        if not text.strip():
            logger.warning(f"No text extracted from '{original_filename}'. Returning success but no embeddings.")
            return jsonify({
                "message": f"File '{original_filename}' uploaded but no text extracted for embeddings.",
                "status": "success"
            }), 200

        # 8) Chunk the extracted text
        chunks = chunk_text(text, chunk_size=1000, overlap=100)
        if not chunks:
            logger.warning(f"No chunks created from '{original_filename}'.")
            return jsonify({
                "message": f"File '{original_filename}' uploaded but could not create text chunks.",
                "status": "success"
            }), 200
        logger.info(f"Generated {len(chunks)} chunks for document '{original_filename}'.")

        # 9) Create user-specific embeddings
        # Build list of (filename, chunk_text) pairs
        new_chunks = [(original_filename, ch) for ch in chunks]
        create_embeddings_for_user(user_id, new_chunks)

        success_msg = f"File '{original_filename}' uploaded and embeddings created for user {user_id}."
        logger.info(success_msg)
        return jsonify({"message": success_msg, "status": "success"}), 200

    except ClientError as e:
        err_msg = f"Error uploading to S3: {e}"
        logger.error(err_msg)
        return jsonify({"message": err_msg, "status": "error"}), 500
    except Exception as ex:
        err_msg = f"Unexpected error: {ex}"
        logger.error(err_msg)
        return jsonify({"message": err_msg, "status": "error"}), 500

@app.route('/folders', methods=['GET'])
@login_required
def get_folders():
    user_id = session.get("user_id")
    if not user_id:
        logger.warning("No user_id in session for fetching folders.")
        return jsonify({"message": "No user_id in session", "status": "error"}), 401

    try:
        # Fetch distinct folders for the user from the database
        folders = user_documents_collection.distinct("folder", {"user_id": user_id})
        logger.info(f"Fetched folders for user {user_id}: {folders}")
        return jsonify({"folders": folders, "status": "success"}), 200
    except Exception as ex:
        error_message = f"Error fetching folders: {ex}"
        logger.error(error_message)
        return jsonify({"message": error_message, "status": "error"}), 500

@app.route('/my_documents', methods=['GET'])
@login_required
def get_my_documents():
    user_id = session.get("user_id")
    if not user_id:
        logger.warning("No user_id in session for fetching documents.")
        return jsonify({"message": "No user_id in session", "status": "error"}), 401

    try:
        documents = list(user_documents_collection.find({"user_id": user_id}))
        # Serialize documents: convert ObjectId and datetime to string
        for doc in documents:
            doc["_id"] = str(doc["_id"])
            if isinstance(doc.get("upload_date"), datetime.datetime):
                doc["upload_date"] = doc["upload_date"].isoformat()
        logger.info(f"Fetched {len(documents)} documents for user {user_id}.")
        return jsonify({"documents": documents, "status": "success"}), 200
    except Exception as ex:
        error_message = f"Error fetching documents: {ex}"
        logger.error(error_message)
        return jsonify({"message": error_message, "status": "error"}), 500




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
    user_id = session.get("user_id")
    data = request.json
    query = data.get('query')
    document_name = data.get('document_name')

    if not query or not document_name:
        return jsonify({"message": "No query or document name provided", "status": "error"}), 400

    # Ensure the doc_name is valid in Mongo
    doc_record = user_documents_collection.find_one({"user_id": user_id, "doc_filename": document_name})
    if not doc_record:
        return jsonify({
            "message": f"Document '{document_name}' not found or unauthorized.",
            "status": "error"
        }), 403

    # 1) Retrieve the top chunks *for that doc only*
    try:
        top_chunks, top_filenames, top_scores = retrieve_documents_for_user_doc_specific(
            user_id=user_id,
            query=query,
            doc_name=document_name,  # pass the doc name
            top_k=5
        )
    except Exception as e:
        logger.error(f"Error in doc-specific retrieval: {str(e)}")
        return jsonify({"message": str(e), "status": "error"}), 500

    # 2) If no chunks, respond gracefully
    if not top_chunks:
        return jsonify({
            "status": "success",
            "document_name": document_name,
            "query": query,
            "answer": "No relevant content found in your document."
        }), 200

    # 3) Combine relevant chunks
    combined_text = "\n".join(top_chunks)

    # 4) Send to LLM
    try:
        # E.g. if you have llm_process_chat
        answer = llm_process_chat([combined_text], "gpt-4o-mini", query)
        return jsonify({
            "status": "success",
            "document_name": document_name,
            "query": query,
            "answer": answer.strip()
        }), 200
    except Exception as e:
        logger.error(f"Error calling LLM: {str(e)}")
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
    SIMILARITY_THRESHOLD = 0.1
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
@login_required
def summarise():
    """
    Summarize an uploaded PDF/TXT file (not necessarily stored in S3).
    """
    ALLOWED_EXTENSIONS = {'pdf', 'txt'}

    if 'file' not in request.files:
        return jsonify({"message": "No file provided", "status": "error"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"message": "No file selected", "status": "error"}), 400

    filename = secure_filename(file.filename)
    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if file_ext not in ALLOWED_EXTENSIONS:
        return jsonify({"message": f"Unsupported file type: {file_ext}", "status": "error"}), 400

    try:
        if file_ext == 'pdf':
            text = extract_text_from_pdf(file)
            if not text.strip():
                raise ValueError("No text extracted from PDF.")
        else:  # txt
            text_bytes = file.read()
            text = text_bytes.decode('utf-8')
    except Exception as e:
        return jsonify({"message": f"Error extracting text: {str(e)}", "status": "error"}), 500

    # Summarization prompt
    prompt_for_summary = request.form.get("query")
    if not prompt_for_summary and request.is_json:
        data = request.get_json()
        prompt_for_summary = data.get('query', '')

    if not prompt_for_summary:
        return jsonify({"message": "Query for summarization not provided", "status": "error"}), 400

    # Summarize
    try:
        answer = llm_summariser(text, "gpt-4o-mini", prompt_for_summary, remaining_tokens=2000)
        return jsonify({
            "status": "success",
            "query": prompt_for_summary,
            "answer": answer.strip()
        }), 200
    except Exception as e:
        logger.error(f"Summarization failed: {str(e)}")
        return jsonify({"message": f"Summarization failed: {str(e)}", "status": "error"}), 500


@app.route('/generate_presigned_url', methods=['POST'])
@login_required
def generate_presigned_url_route():
    data = request.json
    object_key = data.get("object_key")
    if not object_key:
        return jsonify({"message": "Object key is missing", "status": "error"}), 400

    url = generate_presigned_url(S3_BUCKET_NAME, object_key)
    if url:
        return jsonify({"url": url, "status": "success"}), 200
    else:
        return jsonify({"message": "Failed to generate pre-signed URL", "status": "error"}), 500



@app.route('/serve_document', methods=['GET'])
@login_required
def serve_document():
    document_key = request.args.get('document_key')
    if not document_key:
        return jsonify({"status": "error", "message": "Missing 'document_key' parameter."}), 400

    try:
        # Generate pre-signed URL
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': document_key},
            ExpiresIn=3600
        )
    except ClientError as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    # Or serve directly (as your code does):
    try:
        s3_response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=document_key)
        content = s3_response['Body'].read().decode('utf-8')
        return content, 200
    except ClientError as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@documents_bp.route('/delete_document/<document_id>', methods=['DELETE'])
@login_required
def delete_document(document_id):
    """
    Delete a document uploaded by the user.
    """
    user_id = session.get("user_id")

    # Validate the document ID
    try:
        doc_obj_id = ObjectId(document_id)
    except:
        return jsonify({"message": "Invalid document ID.", "status": "error"}), 400

    # Find the document
    document = user_documents_collection.find_one({"_id": doc_obj_id, "user_id": user_id})
    if not document:
        return jsonify({"message": "Document not found or unauthorized.", "status": "error"}), 404

    s3_key = document.get("s3_key")
    if not s3_key:
        return jsonify({"message": "S3 key not found for the document.", "status": "error"}), 500

    try:
        # >>> 1) Remove doc from local embeddings
        remove_doc_from_user_embeddings(user_id, document["doc_filename"])  # <--- call your helper

        # 2) Delete the document from S3
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)

        # 3) Remove the document from the database
        user_documents_collection.delete_one({"_id": doc_obj_id})

        return jsonify({"message": "Document deleted successfully.", "status": "success"}), 200

    except ClientError as e:
        return jsonify({"message": f"Error deleting document from S3: {str(e)}", "status": "error"}), 500
    except Exception as e:
        return jsonify({"message": f"Error deleting document: {str(e)}", "status": "error"}), 500



@documents_bp.route('/create_team', methods=['POST'])
@login_required
def create_team():
    data = request.get_json()
    team_name = data.get("team_name")
    member_user_ids = data.get("member_user_ids", [])

    # Input Validation
    if not team_name or not member_user_ids:
        return jsonify({"status": "error", "message": "Team name and members are required."}), 400

    try:
        # Generate a unique team_id using the counter
        team_id = get_next_team_id()

        # Create the team document
        team = {
            "team_id": team_id,
            "team_name": team_name,
            "created_by": session.get("user_id"),
            "created_at": datetime.datetime.utcnow(),
            "members": member_user_ids
        }

        # Insert the new team into the database
        teams_collection.insert_one(team)

        logger.info(f"Team '{team_name}' created with ID '{team_id}' by user '{session.get('user_id')}'.")

        # Create notifications for each member added to the team
        for member_id in member_user_ids:
            if member_id != session.get("user_id"):  # Optional: Exclude the team creator
                notification_data = {
                    "team_id": team_id,
                    "team_name": team_name,
                    "invited_by": session.get("user_id"),
                    "invited_to": member_id
                }
                success, message = create_notification_helper(notification_data)
                if not success:
                    # Log the failure but continue creating other notifications
                    logger.error(f"Failed to create notification for user '{member_id}': {message}")

        return jsonify({
            "status": "success",
            "message": "Team created successfully.",
            "team_id": team_id
        }), 201

    except Exception as e:
        logger.error(f"Error creating team: {e}")
        return jsonify({"status": "error", "message": f"Failed to create team. {str(e)}"}), 500

@app.route('/notifications/create', methods=['POST'])
def create_notification():
    """
    Endpoint to create a new notification when a lawyer is invited to a team.
    """
    data = request.get_json()
    success, message = create_notification_helper(data)

    if success:
        return jsonify({"status": "success", "message": message}), 201
    else:
        return jsonify({"status": "error", "message": message}), 500

@app.route('/notifications/respond', methods=['POST'])
def respond_notification():
    """
    Handle lawyer's response to a notification (join or exit).
    """
    data = request.get_json()
    notification_id = data.get("notification_id")
    response = data.get("response")  # "join" or "exit"

    if not all([notification_id, response]):
        return jsonify({"status": "error", "message": "Missing required fields."}), 400

    notification = notifications_collection.find_one({"notification_id": notification_id})

    if not notification:
        return jsonify({"status": "error", "message": "Notification not found."}), 404

    team_id = notification.get("team_id")
    invited_to = notification.get("invited_to")  # Lawyer's user ID

    if response.lower() == "join":
        # Add the lawyer to the team's members
        try:
            teams_collection.update_one(
                {"team_id": team_id},
                {"$addToSet": {"members": invited_to}}
            )
            # Optionally, remove the notification after responding
            notifications_collection.delete_one({"notification_id": notification_id})
            return jsonify({"status": "success", "message": "Successfully joined the team."}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to join the team. {str(e)}"}), 500

    elif response.lower() == "exit":
        # Remove the lawyer from the team's members
        try:
            teams_collection.update_one(
                {"team_id": team_id},
                {"$pull": {"members": invited_to}}
            )
            # Optionally, remove the notification after responding
            notifications_collection.delete_one({"notification_id": notification_id})
            return jsonify({"status": "success", "message": "Successfully exited the team."}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to exit the team. {str(e)}"}), 500

    else:
        return jsonify({"status": "error", "message": "Invalid response. Choose 'join' or 'exit'."}), 400

@app.route('/notifications', methods=['GET'])
@login_required  # Ensure only authenticated users can access this endpoint
def get_notifications():
    """
    Fetch all notifications for the logged-in user.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"status": "error", "message": "User not found in session."}), 401

    try:
        # Retrieve all notifications where 'invited_to' matches the current user's ID
        notifications_cursor = notifications_collection.find({"invited_to": user_id})
        notifications = []
        for notif in notifications_cursor:
            # Serialize ObjectId and datetime fields
            notif_serialized = {
                "notification_id": notif.get("notification_id"),
                "team_id": notif.get("team_id"),
                "team_name": notif.get("team_name"),
                "invited_by": notif.get("invited_by"),
                "invited_to": notif.get("invited_to"),
                "invited_at": notif.get("invited_at").isoformat() if notif.get("invited_at") else "N/A"
            }
            notifications.append(notif_serialized)

        return jsonify({"status": "success", "notifications": notifications}), 200

    except Exception as e:
        logger.error(f"Error fetching notifications for user {user_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch notifications."}), 500

@documents_bp.route('/share_document_with_team', methods=['POST'])
@login_required
def share_document_with_team():
    """
    Share a document with a specific team.
    """
    user_id = session.get("user_id")
    data = request.json
    document_id = data.get("document_id")
    team_id = data.get("team_id")

    if not document_id or not team_id:
        return jsonify({"message": "Document ID and team ID are required.", "status": "error"}), 400

    # Validate document ownership
    try:
        doc_obj_id = ObjectId(document_id)
    except:
        return jsonify({"message": "Invalid document ID.", "status": "error"}), 400

    document = user_documents_collection.find_one({"_id": doc_obj_id, "user_id": user_id})
    if not document:
        return jsonify({"message": "Document not found or unauthorized.", "status": "error"}), 404

    # Check if team exists
    team = teams_collection.find_one({"team_id": team_id})
    if not team:
        return jsonify({"message": "Team does not exist.", "status": "error"}), 404

    # Update the 'shared_with_teams' list
    try:
        user_documents_collection.update_one(
            {"_id": doc_obj_id},
            {"$addToSet": {"shared_with_teams": team_id}}
        )
        return jsonify({"message": f"Document shared with team {team_id} successfully.", "status": "success"}), 200
    except Exception as e:
        return jsonify({"message": f"Error sharing document with team: {str(e)}", "status": "error"}), 500


@documents_bp.route('/set_document_privacy/<document_id>', methods=['PUT'])
@login_required
def set_document_privacy(document_id):
    """
    Set the privacy status of a document (private or public).
    """
    user_id = session.get("user_id")
    data = request.json
    is_private = data.get("is_private")

    if is_private is None:
        return jsonify({"message": "is_private field is required.", "status": "error"}), 400

    # Validate document ownership
    try:
        doc_obj_id = ObjectId(document_id)
    except:
        return jsonify({"message": "Invalid document ID.", "status": "error"}), 400

    document = user_documents_collection.find_one({"_id": doc_obj_id, "user_id": user_id})
    if not document:
        return jsonify({"message": "Document not found or unauthorized.", "status": "error"}), 404

    try:
        user_documents_collection.update_one(
            {"_id": doc_obj_id},
            {"$set": {"is_private": bool(is_private)}}
        )
        status = "private" if is_private else "public"
        return jsonify({"message": f"Document privacy set to {status}.", "status": "success"}), 200
    except Exception as e:
        return jsonify({"message": f"Error setting document privacy: {str(e)}", "status": "error"}), 500






# -------------- Team details APIs ---------------- #

@documents_bp.route('/add_team_member', methods=['POST'])
@login_required
def add_team_member():
    """
    Add a new member to an existing team and create a notification for the added member.
    """
    data = request.get_json()
    team_id = data.get("team_id")
    member_user_id = data.get("member_user_id")

    if not team_id or not member_user_id:
        return jsonify({"status": "error", "message": "team_id and member_user_id are required."}), 400

    try:
        # Check if the team exists
        team = teams_collection.find_one({"team_id": team_id})
        if not team:
            return jsonify({"status": "error", "message": "Team not found."}), 404

        # Optionally, check if the member_user_id exists in users_collection
        member = users_collection.find_one({"user_id": member_user_id})
        if not member:
            return jsonify({"status": "error", "message": "User to add not found."}), 404

        # Add the member to the team if not already a member
        if member_user_id in team.get("members", []):
            return jsonify({"status": "error", "message": "User is already a member of the team."}), 400

        teams_collection.update_one(
            {"team_id": team_id},
            {"$push": {"members": member_user_id}}
        )

        # Create a notification for the added member
        notification_data = {
            "team_id": team_id,
            "team_name": team.get("team_name"),
            "invited_by": session.get("user_id"),
            "invited_to": member_user_id
        }
        success, message = create_notification_helper(notification_data)
        if not success:
            logger.error(f"Failed to create notification for user '{member_user_id}': {message}")

        return jsonify({"status": "success", "message": "Member added to the team successfully."}), 200
    except Exception as e:
        logger.error(f"Error adding team member: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500





@documents_bp.route('/get_teams', methods=['GET'])
@login_required
def get_teams():
    """
    Retrieve all teams the user is part of.
    """
    user_id = session.get("user_id")
    try:
        teams = teams_collection.find({"members": user_id})
        teams_list = [serialize_document(team) for team in teams]
        return jsonify({"status": "success", "teams": teams_list}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500





@documents_bp.route('/get_team_members', methods=['GET'])
@login_required
def get_team_members():
    """
    Retrieve all members of a specific team.
    """
    team_id = request.args.get("team_id")
    if not team_id:
        return jsonify({"status": "error", "message": "team_id is required."}), 400
    try:
        team = teams_collection.find_one({"team_id": team_id})
        if not team:
            return jsonify({"status": "error", "message": "Team not found."}), 404
        members_ids = team.get("members", [])
        members = users_collection.find({"user_id": {"$in": members_ids}}, {"password": 0})
        members_list = [serialize_document(member) for member in members]
        return jsonify({"status": "success", "members": members_list}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/get_team_member_profile_picture', methods=['GET'])
@login_required
def get_team_member_profile_picture():
    """
    Retrieve team member profile picture
    """
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"status":"error", "message":"user_id is required"}), 400
    try:
        user = users_collection.find_one({"user_id":user_id})
        if not user:
            return jsonify({"status":"error", "message":"User not found"}), 400
        if user.get("profile_picture_key"):
            presigned_url = generate_presigned_url(S3_BUCKET_NAME, user["profile_picture_key"])
            user["profile_picture_url"] = presigned_url
            return jsonify({"status":"success", "url":user["profile_picture_url"]})
    except:
        return jsonify({"status":"error", "message":"Invalid"})






# -------------- Prompt APIs ------------------- #

@app.route('/get_prompts', methods=['GET'])
@login_required
def get_prompts():
    """
    Retrive all default prompts
    """
    prompt_type = request.args.get("type")
    try:
        type_of_prompt=prompt_type
        prompts_cursor = prompts_collection.find({"type":type_of_prompt})
        prompts = list(prompts_cursor)
        prompts_json = dumps(prompts)
        return app.response_class(prompts_json, mimetype='application/json'), 200
    except Exception as e:
        app.logger.error(f"Error fetching prompts: {e}")

        return jsonify({
            "message": "An error occurred while fetching prompts.",
            "error": str(e),
            "status": "error"
        }), 500


@prompts_bp.route('/add_prompt', methods=['POST'])
@login_required
def add_prompt():
    """
    Add a new prompt to the prompts collection.
    Expects JSON body with 'type_of_prompt', 'title', 'description', 'content'.
    """
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized access. Please log in."}), 401

    # Get data from request body
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Invalid JSON body."}), 400

    type_of_prompt = data.get("type_of_prompt")
    title = data.get("title")
    content = data.get("content")

    # Validate required fields
    missing_fields = []
    for field in ["type_of_prompt", "title", "content"]:
        if not data.get(field):
            missing_fields.append(field)

    if missing_fields:
        return jsonify({
            "status": "error",
            "message": f"Missing required fields: {', '.join(missing_fields)}."
        }), 400

    # Generate a unique prompt_id
    prompt_id = get_next_prompt_id()

    # Prepare the prompt document
    prompt_doc = {
        "prompt_id": prompt_id,
        "type": type_of_prompt,
        "title": title,
        "content": content,
        "created_by": user_id,
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow(),
    }

    try:
        # Insert the new prompt into the prompts collection
        prompt_doc["status"] = "success"
        prompts_collection.insert_one(prompt_doc)
        logger.info(f"Prompt '{prompt_id}' added by user '{user_id}'.")
        return jsonify({"status":"success"})
    except Exception as e:
        logger.error(f"Error adding prompt: {e}")
        return jsonify({
            "status": "error",
            "message": f"An error occurred while adding the prompt: {str(e)}."
        }), 500

@prompts_bp.route('/update_prompt/<prompt_id>', methods=['PUT'])
@login_required
def update_prompt(prompt_id):
    """
    Update an existing prompt's details.
    Expects JSON body with any of the fields: 'type_of_prompt', 'title', 'description', 'content'.
    Only users with the 'admin' role can perform this action.
    """
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized access. Please log in."}), 401

    # Restrict prompt updates to admin users
    if role != "admin":
        return jsonify({"status": "error", "message": "Permission denied. Only admins can update prompts."}), 403

    # Get data from request body
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Invalid JSON body."}), 400

    # Allowed fields for update
    allowed_fields = ["type_of_prompt", "title", "description", "content"]

    # Prepare update data with sanitization
    update_data = {}
    for field in allowed_fields:
        if field in data:
            sanitized_value = bleach.clean(data[field])
            if field == "type_of_prompt" and sanitized_value not in ["default", "custom"]:
                return jsonify({
                    "status": "error",
                    "message": "Invalid value for 'type_of_prompt'. Allowed values are 'default' or 'custom'."
                }), 400
            update_data[field] = sanitized_value

    if not update_data:
        return jsonify({"status": "error", "message": "No valid fields provided for update."}), 400

    try:
        # Find and update the prompt
        result = prompts_collection.update_one(
            {"prompt_id": prompt_id},
            {
                "$set": {
                    **update_data,
                    "updated_at": datetime.datetime.utcnow()
                }
            }
        )

        if result.matched_count == 0:
            return jsonify({"status": "error", "message": "Prompt not found."}), 404

        return jsonify({"status": "success", "message": "Prompt updated successfully."}), 200

    except Exception as e:
        logger.error(f"Error updating prompt '{prompt_id}': {e}")
        return jsonify({"status": "error", "message": f"An error occurred while updating the prompt: {str(e)}."}), 500

@prompts_bp.route('/delete_prompt/<prompt_id>', methods=['DELETE'])
@login_required
def delete_prompt(prompt_id):
    """
    Delete an existing prompt.
    Only users with the 'admin' role can perform this action.
    """
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized access. Please log in."}), 401

    # Restrict prompt deletion to admin users
    if role != "admin":
        return jsonify({"status": "error", "message": "Permission denied. Only admins can delete prompts."}), 403

    try:
        # Attempt to delete the prompt
        result = prompts_collection.delete_one({"prompt_id": prompt_id})

        if result.deleted_count == 0:
            return jsonify({"status": "error", "message": "Prompt not found."}), 404

        return jsonify({"status": "success", "message": "Prompt deleted successfully."}), 200

    except Exception as e:
        logger.error(f"Error deleting prompt '{prompt_id}': {e}")
        return jsonify({"status": "error", "message": f"An error occurred while deleting the prompt: {str(e)}."}), 500

@prompts_bp.route('/promote_prompt/<prompt_id>', methods=['PUT'])
@login_required
def promote_prompt(prompt_id):
    """
    Convert a prompt to public by setting its 'type_of_prompt' to 'default'.
    Only users with the 'admin' role can perform this action.
    """
    user_id = session.get("user_id")
    role = session.get("role")

    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized access. Please log in."}), 401

    # Restrict prompt promotion to admin users
    if role != "admin":
        return jsonify({"status": "error", "message": "Permission denied. Only admins can promote prompts."}), 403

    try:
        # Update the prompt's type to 'default' to make it public
        result = prompts_collection.update_one(
            {"prompt_id": prompt_id},
            {
                "$set": {
                    "type": "default",
                    "updated_at": datetime.datetime.utcnow()
                }
            }
        )

        if result.matched_count == 0:
            return jsonify({"status": "error", "message": "Prompt not found."}), 404

        return jsonify({"status": "success", "message": "Prompt promoted to public successfully."}), 200

    except Exception as e:
        logger.error(f"Error promoting prompt '{prompt_id}' to public: {e}")
        return jsonify({"status": "error", "message": f"An error occurred while promoting the prompt: {str(e)}."}), 500

# ============================================
# FAQs APIs
# ============================================

@app.route('/get_faqs')
def get_faqs():
    faqs = list(db.faqs.find({}))
    # Convert MongoDB BSON to JSON, handling ObjectId and other types
    return json_util.dumps(faqs), 200, {'ContentType': 'application/json'}

@app.route('/add_faqs', methods=['POST'])
def add_faq():
    data = request.get_json()
    faq_id = faqs_collection.insert_one(data).inserted_id
    return jsonify({'message': 'FAQ added successfully', 'id': str(faq_id)}), 201

@app.route('/faqs/<string:faq_id>', methods=['PUT'])
def update_faq(faq_id):
    data = request.get_json()
    result = faqs_collection.update_one({'_id': ObjectId(faq_id)}, {'$set': data})
    if result.modified_count:
        return jsonify({'message': 'FAQ updated successfully'}), 200
    else:
        return jsonify({'message': 'No FAQ found or data unchanged'}), 404

@app.route('/faqs/<string:faq_id>', methods=['DELETE'])
def delete_faq(faq_id):
    result = faqs_collection.delete_one({'_id': ObjectId(faq_id)})
    if result.deleted_count:
        return jsonify({'message': 'FAQ deleted successfully'}), 200
    else:
        return jsonify({'message': 'FAQ not found'}), 404

# ============================================
# Reviews APIs
# ============================================


# Endpoint to add a review
@app.route('/add_review', methods=['POST'])
def add_review():
    data = request.json
    result = reviews_collection.insert_one({
        "lawyer_id": data['lawyer_id'],
        "client_id": data['client_id'],
        "review": data['review'],
        "rating": data['rating'],
        "date": datetime.datetime.now()
    })
    return jsonify({"success": True, "message": "Review added"}), 201

# Endpoint to fetch reviews
@app.route('/get_reviews/<user_id>', methods=['GET'])
def get_reviews(user_id):
    try:
        reviews_cursor = reviews_collection.find({"lawyer_id": user_id})
        reviews_list = []
        for r in reviews_cursor:
            # Manually convert ObjectId and datetime:
            r['_id'] = str(r['_id'])
            r['date'] = r['date'].isoformat() if 'date' in r else None
            reviews_list.append(r)

        return jsonify(reviews_list), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def load_lawyer_index():
    global faiss_index, lawyer_metadata

    if not os.path.exists(LAWYER_INDEX_PATH) or not os.path.exists(LAWYER_METADATA_PATH):
        print("No lawyer index or metadata found...")
        return

    # Load FAISS index from disk
    faiss_index = faiss.read_index(LAWYER_INDEX_PATH)
    print(faiss_index, "_______________________")
    print(f"Loaded FAISS index with {faiss_index.ntotal} lawyer embeddings.")

    # Load metadata from disk
    with open(LAWYER_METADATA_PATH, "r", encoding="utf-8") as f:
        lawyer_metadata = json.load(f)
    return faiss_index

@app.route('/recommend_lawyer', methods=['POST'])
@login_required
def recommend_lawyer():
    """
    Given a user's case details (query), embed it with Sentence Transformers,
    search the lawyer FAISS index, and return the top matches.
    """
    try:
        # 1. Load FAISS index
        faiss_index = load_lawyer_index()
        if faiss_index is None:
            return jsonify({
                "status": "error",
                "message": "Lawyer index not found or empty. Please run the embedding script."
            }), 500

        logger.info(f"FAISS index loaded with {faiss_index.ntotal} entries, dimension = {faiss_index.d}")

        # 2. Parse input data
        data = request.json or {}
        case_details = data.get('case_details', "").strip()
        if not case_details:
            return jsonify({"status": "error", "message": "No case details provided."}), 400

        # 3. Generate the query embedding
        query_embedding = lawyer_model.encode([case_details])[0].astype("float32")

        # Normalize the query vector to unit length for cosine similarity
        norm = np.linalg.norm(query_embedding)
        if norm == 0:
            return jsonify({"status": "error", "message": "Query embedding is a zero vector."}), 500
        query_embedding = query_embedding / norm

        # Ensure the embedding dimension matches the FAISS index dimension
        if query_embedding.shape[0] != faiss_index.d:
            error_msg = f"Query vector dimension {query_embedding.shape[0]} does not match index dimension {faiss_index.d}."
            logger.error(error_msg)
            return jsonify({"status": "error", "message": error_msg}), 500

        # Reshape to (1, d) as FAISS expects a 2D array
        user_query_vector = np.array([query_embedding], dtype="float32")

        # 4. Determine top_k: if provided use that; otherwise return all available lawyers
        top_k = int(data.get("top_k", faiss_index.ntotal))
        if top_k > faiss_index.ntotal:
            top_k = faiss_index.ntotal

        # 5. Search the FAISS index
        distances, indices = faiss_index.search(user_query_vector, top_k)
        logger.info(f"Search indices: {indices}, distances: {distances}")

        # 6. Collect results from lawyer_metadata
        results = []
        for i in range(top_k):
            idx = indices[0][i]
            dist = distances[0][i]
            # Skip invalid indices (e.g. -1 or out of range)
            if idx == -1 or idx >= len(lawyer_metadata):
                logger.debug(f"Skipping invalid index {idx} at rank {i}")
                continue
            meta = lawyer_metadata[idx]
            results.append({
                "lawyer_id": meta.get("lawyer_id"),
                "name": meta.get("name"),
                "specialization": meta.get("specialization"),
                "court": meta.get("court"),
                "years_of_experience": meta.get("years_of_experience"),
                "distance": float(dist)
            })

        # 7. Sort the results by ascending distance (closer = more similar)
        results.sort(key=lambda x: x["distance"])

        return jsonify({
            "status": "success",
            "case_details": case_details,
            "recommendations": results
        }), 200

    except Exception as e:
        logger.error(f"Error in recommend_lawyer: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# Example Twilio token generator
def generate_twilio_token(identity, room_name):
    """
    Returns a Twilio Access Token as a **string**.
    Make sure you're not calling .decode('utf-8') if to_jwt() already returns str.
    """
    token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY_SID,
        TWILIO_API_KEY_SECRET,
        identity=identity,  # This is how Twilio will label this participant
        ttl=3600  # token valid for 1 hour (adjust as needed)
    )

    video_grant = VideoGrant(room=room_name)
    token.add_grant(video_grant)

    # If using a newer Twilio library, to_jwt() is already a string
    return token.to_jwt()


# -----------------------------------------------------------------------------
# Endpoint to initiate a video call with a specific lawyer
# -----------------------------------------------------------------------------
@app.route("/initiate_video_call", methods=["POST"])
@login_required
def initiate_video_call():
    """
    1) Validate the client's request for a call with lawyer 'UID0013'.
    2) Insert a new "consultation" document with 'status': 'pending'.
    3) Return Twilio token + room_name to the client so they can connect.
    """
    data = request.get_json()
    lawyer_id = data.get("lawyer_id")

    if not lawyer_id or lawyer_id != "UID0013":
        return jsonify({"status": "error", "message": "Lawyer must be 'UID0013'."}), 400

    # Suppose your session stores the client user_id
    client_id = session.get("user_id")
    if not client_id:
        return jsonify({"status": "error", "message": "No valid client ID found in session."}), 401

    # Generate a unique room_name
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    room_name = f"call_{client_id}_{lawyer_id}_{timestamp}"

    # Generate Twilio token
    token_str = generate_twilio_token(identity=client_id, room_name=room_name)

    # =========== Store a "pending" consultation in DB ===========
    consultation_doc = {
        "client_id": client_id,
        "lawyer_id": lawyer_id,
        "room_name": room_name,
        "status": "pending",
        "created_at": datetime.datetime.utcnow()
    }
    # Insert into your 'consultations' collection
    db.consultations.insert_one(consultation_doc)

    return jsonify({
        "status": "success",
        "message": "Video call initiated successfully.",
        "room_name": room_name,
        "token": token_str
    }), 200


@app.route("/lawyer/consultations", methods=["GET"])
@login_required
def get_lawyer_consultations():
    user_id = session.get("user_id")
    role = session.get("role", "").lower()

    if user_id != "UID0013" or role != "lawyer":
        return jsonify({"status": "error", "message": "Access denied."}), 403

    # Fetch from 'consultations' where lawyer_id == "UID0013"
    # AND status in ["pending", "accepted"]
    consultations_cursor = db.consultations.find({
        "lawyer_id": "UID0013",
        "status": { "$in": ["pending", "accepted"] }
    })
    results = []
    for doc in consultations_cursor:
        results.append({
            "consultation_id": str(doc.get("_id")),
            "client_id": doc.get("client_id"),
            "status": doc.get("status"),
            "room_name": doc.get("room_name"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None
        })

    return jsonify({"status": "success", "consultations": results}), 200

# -----------------------------------------------------------------------------
# (B) Respond to a consultation (Accept or Reject)
# -----------------------------------------------------------------------------
@app.route("/lawyer/consultations/respond", methods=["POST"])
@login_required
def respond_consultation():
    """
    Lawyer (UID0013) accepts or rejects a consultation.
    Request body: { "consultation_id": "...", "action": "accept" or "reject" }
    """
    user_id = session.get("user_id")
    role = session.get("role", "").lower()
    if user_id != "UID0013" or role != "lawyer":
        return jsonify({"status": "error", "message": "Access denied. Only UID0013 (lawyer) can respond."}), 403

    data = request.json or {}
    consultation_id = data.get("consultation_id")
    action = data.get("action", "").lower()

    if not consultation_id or action not in ["accept", "reject"]:
        return jsonify({"status": "error", "message": "Invalid request body."}), 400

    # Find the consultation
    try:
        consult_obj_id = ObjectId(consultation_id)
    except:
        return jsonify({"status": "error", "message": "Invalid consultation_id ObjectId."}), 400

    consultation = consultations_collection.find_one({"_id": consult_obj_id, "lawyer_id": "UID0013"})
    if not consultation:
        return jsonify({"status": "error", "message": "Consultation not found or doesn't belong to UID0013."}), 404

    if consultation.get("status") not in ["pending", "accepted"]:
        return jsonify({"status": "error", "message": "Cannot respond to a consultation that's already rejected or completed."}), 400

    if action == "reject":
        # Update status to "rejected"
        consultations_collection.update_one(
            {"_id": consult_obj_id},
            {"$set": {"status": "rejected", "updated_at": datetime.datetime.utcnow()}}
        )
        return jsonify({"status": "success", "message": "Consultation rejected."}), 200

    if action == "accept":
        # If not already accepted, we set "status" = "accepted"
        # Generate a Twilio token so the lawyer can join
        room_name = consultation.get("room_name")
        if not room_name:
            # Possibly the client created it at time of request, but if not, create one
            timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
            room_name = f"call_{consultation.get('client_id')}_{consultation.get('lawyer_id')}_{timestamp}"
            # Also update the doc
            consultations_collection.update_one(
                {"_id": consult_obj_id},
                {"$set": {"room_name": room_name}}
            )

        token_bytes = generate_twilio_token(identity=user_id, room_name=room_name)
        token_str = token_bytes

        # Update the doc to "accepted"
        consultations_collection.update_one(
            {"_id": consult_obj_id},
            {
                "$set": {
                    "status": "accepted",
                    "updated_at": datetime.datetime.utcnow(),
                    "room_name": room_name
                }
            }
        )
        return jsonify({
            "status": "success",
            "message": "Consultation accepted. Here is your token.",
            "token": token_str,
            "room_name": room_name
        }), 200
    
# # -----------------------------------------------------------------------------
# # Whatsapp agent for one time requests
# # -----------------------------------------------------------------------------
# stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "YOUR_STRIPE_SECRET_KEY")

# # A dictionary mapping each "feature" to its price (in cents)
# FEATURE_PRICING = {
#     "BOOK_APPOINTMENT": 500,  # e.g., $5.00
#     "FEATURE_X": 1200,        # e.g., $12.00
#     # ...
# }

# # Store user’s pending “feature usage” in a simple dict for demo
# # In production, store in DB with a status ("pending_payment", "paid", etc.)
# PENDING_PURCHASES = {}
# # Format: PENDING_PURCHASES[phone_number] = {
# #     "feature": "BOOK_APPOINTMENT",
# #     "price_cents": 500,
# #     "timestamp": <some datetime>,
# #     ...
# # }
# @whatsapp_bp.route("/webhook", methods=["POST"])
# def whatsapp_webhook():
#     """
#     Webhook to handle incoming WhatsApp messages from Twilio.
#     Configure your Twilio WhatsApp Sandbox or phone number to POST here.
#     """
#     from_number = request.form.get("From", "")
#     incoming_msg = (request.form.get("Body") or "").strip().lower()

#     resp = MessagingResponse()
#     outgoing_msg = resp.message()

#     # Basic logic to parse the user's request
#     if "hello" in incoming_msg or "hi" in incoming_msg:
#         # Greet user
#         outgoing_msg.body(
#             "Hello! I’m your LegalKare WhatsApp assistant.\n\n"
#             "Here are some commands you can try:\n"
#             "1) Type 'Book Appointment' to schedule a meeting with a lawyer.\n"
#             "2) Type 'Feature X' to access some special feature.\n"
#             "3) Type 'Help' to see this menu again."
#         )
#         return str(resp)

#     elif "help" in incoming_msg:
#         outgoing_msg.body(
#             "Commands:\n"
#             "• 'Book Appointment' => We'll guide you to pay & then schedule an appointment.\n"
#             "• 'Feature X' => We'll guide you to pay & then unlock it.\n"
#         )
#         return str(resp)

#     elif "book appointment" in incoming_msg:
#         # Save a pending purchase for this user
#         feature = "BOOK_APPOINTMENT"
#         price_cents = FEATURE_PRICING.get(feature, 500)
#         PENDING_PURCHASES[from_number] = {
#             "feature": feature,
#             "price_cents": price_cents,
#             "timestamp": datetime.datetime.utcnow()
#         }
#         # Send payment link
#         outgoing_msg.body(
#             "To proceed with booking an appointment, please pay the required fee.\n"
#             f"Price: ${price_cents/100:.2f}\n\n"
#             "Reply 'Pay' and we’ll generate a payment link for you."
#         )
#         return str(resp)

#     elif "feature x" in incoming_msg:
#         # Another example feature
#         feature = "FEATURE_X"
#         price_cents = FEATURE_PRICING.get(feature, 1200)
#         PENDING_PURCHASES[from_number] = {
#             "feature": feature,
#             "price_cents": price_cents,
#             "timestamp": datetime.datetime.utcnow()
#         }
#         outgoing_msg.body(
#             "Feature X costs $12.00. Reply 'Pay' to get the payment link."
#         )
#         return str(resp)

#     elif incoming_msg == "pay":
#         # Generate payment link if there's a pending purchase
#         pending = PENDING_PURCHASES.get(from_number)
#         if not pending:
#             outgoing_msg.body(
#                 "No pending feature found. Type 'Help' to see available commands."
#             )
#             return str(resp)

#         # Create a Stripe Checkout Session
#         session = stripe.checkout.Session.create(
#             payment_method_types=['card'],
#             mode='payment',
#             line_items=[{
#                 'price_data': {
#                     'currency': 'usd',
#                     'product_data': {
#                         'name': pending["feature"],
#                     },
#                     'unit_amount': pending["price_cents"],
#                 },
#                 'quantity': 1,
#             }],
#             success_url=os.getenv("PAYMENT_SUCCESS_URL", "https://example.com/payment_success") 
#                         + f"?phone={from_number}",
#             cancel_url=os.getenv("PAYMENT_CANCEL_URL", "https://example.com/payment_cancel")
#         )
#         checkout_url = session.url
#         outgoing_msg.body(
#             "Click here to pay:\n"
#             f"{checkout_url}\n\n"
#             "After payment, you’ll receive instructions automatically."
#         )
#         return str(resp)

#     else:
#         # Unrecognized message
#         outgoing_msg.body(
#             "Sorry, I didn’t understand that.\n"
#             "Type 'Help' to see available commands."
#         )
#         return str(resp)


# # ---------------- Stripe Payment Success Webhook or Route -------------
# @whatsapp_bp.route("/payment_success", methods=["GET"])
# def payment_success():
#     """
#     This route is called after Stripe's checkout success. 
#     You’d configure your success_url to point here with the user’s phone. 
#     Example: success_url?phone=whatsapp:+123456789
#     """
#     from_number = request.args.get("phone", "")

#     # Mark the pending purchase as "paid" and proceed with the feature
#     pending = PENDING_PURCHASES.get(from_number)
#     if not pending:
#         return "No pending purchase was found. Possibly already processed."

#     feature = pending["feature"]

#     # ---- Here, you can finalize the logic:
#     # e.g., if feature == 'BOOK_APPOINTMENT': 
#     #       create an appointment entry in DB for the user
#     # Or you can store them in some "paid" table, etc.

#     # For demonstration, if it’s "BOOK_APPOINTMENT", call your existing logic
#     if feature == "BOOK_APPOINTMENT":
#         # Example: create an appointment “placeholder” in DB
#         # (Use your actual DB calls from your existing code.)
#         # appointments_collection.insert_one(...)
#         # Or simply record somewhere that the user can next send 
#         # "I want to meet on date/time" via WhatsApp, etc.
#         pass

#     # Remove from pending
#     del PENDING_PURCHASES[from_number]

#     return (
#         "Payment received! Thank you.\n\n"
#         f"We have unlocked feature: {feature}.\n"
#         "You can close this tab and continue on WhatsApp now."
#     ), 200

app.register_blueprint(profile_bp, url_prefix="/profile")
app.register_blueprint(documents_bp, url_prefix="/documents")
app.register_blueprint(prompts_bp, url_prefix='/prompts')
app.register_blueprint(lawyers_bp, url_prefix = "/lawyers")

if __name__ == '__main__':
    app.run(debug=True, port=5002)