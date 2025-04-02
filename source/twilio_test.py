from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VideoGrant
from flask import Flask, request, jsonify

TWILIO_ACCOUNT_SID = "ACeef16be78c5f2620cb378c55c57d3cce"
TWILIO_API_KEY = "SKcaac9310aa926d9ff27f067f90349508"
TWILIO_API_SECRET = "S6ntzZrWr8n5wUtDg0KJGj9z0vahWtYT"

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