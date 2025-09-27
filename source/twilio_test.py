from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VideoGrant
from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY_SID")
TWILIO_API_SECRET = os.getenv("TWILIO_API_KEY_SECRET")

# Validate required Twilio environment variables
if not all([TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET]):
    raise ValueError("Missing Twilio environment variables. Please set TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, and TWILIO_API_KEY_SECRET in your .env file.")

app = Flask(__name__)

def generate_video_token(identity, room_name):
    # identity = unique user identifier (e.g., 'lawyer123' or 'client456')
    # room_name = the Twilio room name (unique per session)
    token = AccessToken(TWILIO_ACCOUNT_SID, TWILIO_API_KEY, TWILIO_API_SECRET, identity=identity)
    video_grant = VideoGrant(room=room_name)
    token.add_grant(video_grant)
    return token.to_jwt()


@app.route("/get_video_token", methods=["POST"])
def get_video_token():
    data = request.json
    room_name = data.get('room_name')
    identity = data.get('identity')  # Typically the user’s username or ID

    # (Optional) Ensure the user is logged in and authorized to join this room

    # Generate Twilio Video token
    token_jwt = generate_video_token(identity, room_name)

    return jsonify({
        "token": token_jwt.decode('utf-8') if hasattr(token_jwt, 'decode') else token_jwt,
        "room_name": room_name
    })


if __name__ == "__main__":
    app.run(port=5003, debug=True)