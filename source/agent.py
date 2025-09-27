import os
import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain.agents import initialize_agent, AgentType
import jwt
from pydantic import BaseModel, root_validator, model_validator, Field
from typing import Dict, Optional
from langchain.tools.base import BaseTool
import inspect
import sys
import json
import re

login_url = "http://127.0.0.1:5002/login"  # Login endpoint
profile_url = "http://127.0.0.1:5002/profile/get_profile"  # Profile endpoint
edit_profile_url = "http://127.0.0.1:5002/profile/update_profile"
# Load environment variables
load_dotenv()

FLASK_API_URL = os.getenv("FLASK_API_URL", "http://127.0.0.1:5002/profile/view_appointments")
openai_api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

# Validate OpenAI API key
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required. Please set it in your .env file.")

class FetchAppointmentsInput(BaseModel):
    user_query: str = ""
    credentials: Dict[str, str]

    @model_validator(mode="before")
    def coerce_credentials(cls, values: any) -> Dict[str, any]:
        # If LangChain passed us a raw string, extract the JSON object
        if isinstance(values, str):
            m = re.search(r"(\{.*\})", values, flags=re.DOTALL)
            if not m:
                raise ValueError(f"Couldn't extract JSON from: {values!r}")
            payload = m.group(1)
            try:
                values = json.loads(payload)
            except json.JSONDecodeError:
                try:
                    values = ast.literal_eval(payload)
                except Exception:
                    raise ValueError(f"Couldn't parse JSON payload: {payload!r}")

        # Now ensure we have a dict and coerce top‐level creds → nested
        if isinstance(values, dict):
            if "username" in values and "password" in values:
                return {
                    "user_query": values.get("user_query", ""),
                    "credentials": {
                        "username": values["username"],
                        "password": values["password"],
                    },
                }
            creds = values.get("credentials")
            if isinstance(creds, dict) and creds.get("username") and creds.get("password"):
                return {"user_query": values.get("user_query", ""), "credentials": creds}

        raise ValueError("Invalid input: expected top-level username/password or a credentials dict")


# Define a Pydantic model for the profile fetching inputs
class FetchProfileInput(BaseModel):
    user_query: str = ""
    credentials: Dict[str, str]

    @root_validator(pre=True)
    def parse_input(cls, values):
        # If the input is already a dict, ensure it has the right nested structure.
        if isinstance(values, dict):
            if "username" in values and "password" in values:
                return {
                    "user_query": values.get("user_query", ""),
                    "credentials": {"username": values["username"], "password": values["password"]}
                }
            else:
                if "user_query" not in values:
                    values["user_query"] = ""
                return values

        # If the input is a string, try to parse it.
        if isinstance(values, str):
            s = values.strip()
            if s.startswith("{"):
                try:
                    import ast
                    obj = ast.literal_eval(s)
                    if "username" in obj and "password" in obj:
                        return {
                            "user_query": obj.get("user_query", ""),
                            "credentials": {"username": obj["username"], "password": obj["password"]}
                        }
                    else:
                        if "user_query" not in obj:
                            obj["user_query"] = ""
                        return obj
                except Exception as e:
                    raise ValueError("Error parsing input string as dict") from e
            else:
                # Use a regex to extract credentials.
                # Accept optional __main__. prefix and either FetchProfileInput or FetchAppointmentsInput.
                import re
                pattern = r"^(?:__main__\.)?(?:FetchProfileInput|FetchAppointmentsInput)\(\s*username\s*=\s*['\"]([^'\"]+)['\"]\s*,\s*password\s*=\s*['\"]([^'\"]+)['\"]\s*\)$"
                match = re.match(pattern, s)
                if match:
                    username = match.group(1)
                    password = match.group(2)
                    return {"user_query": "", "credentials": {"username": username, "password": password}}
                else:
                    raise ValueError("Error parsing input string from model representation")
        raise ValueError("Input must be a dict or string representing a dict")



@tool
def fetch_profile(inputs: FetchProfileInput):  # <-- Use FetchProfileInput here!
    """
    Fetches the profile from the Flask API for the logged-in lawyer.
    It first logs in using the provided credentials, then uses the returned session token
    to access the profile endpoint.
    """
    # Ensure that inputs is a FetchProfileInput instance
    if not isinstance(inputs, FetchProfileInput):
        try:
            inputs = FetchProfileInput.parse_obj(inputs)
        except Exception as e:
            return "Error converting input: " + str(e)

    credentials = inputs.credentials

    try:
        login_data = {
            "username": credentials["username"],
            "password": credentials["password"]
        }

        # Login to get the session token
        login_response = requests.post(login_url, json=login_data)
        data = login_response.json()

        if login_response.status_code == 200:
            session_token = data["data"]["AccessToken"]
            refresh_token = data["data"]["RefreshToken"]

            if not session_token:
                return "Error: No session token received during login."

            # Extract user information (assuming these fields are returned)
            user_id = data["user_id"]
            role = data["role"]
            print(user_id, role)

            if not user_id or not role:
                return "Error: Missing user_id or role in the session token."

            # Prepare headers and cookies for subsequent requests
            headers = {
                "Authorization": f"Bearer {session_token}",
            }
            cookies = login_response.cookies

            # Fetch the profile using the same token and cookies
            response = requests.get(profile_url, headers=headers, cookies=cookies)
            print(response.json())

            # Check if the access token expired and refresh if needed
            if response.status_code == 401:
                print("Token expired, refreshing the token...")
                refresh_data = {"refresh_token": refresh_token}
                refresh_response = requests.post(login_url, json=refresh_data)
                if refresh_response.status_code == 200:
                    new_data = refresh_response.json()
                    new_access_token = new_data["data"]["AccessToken"]
                    headers["Authorization"] = f"Bearer {new_access_token}"

                    # Retry the profile request with the new token
                    response = requests.get(profile_url, headers=headers, cookies=cookies)
                    print("New request status code:", response.status_code)
                else:
                    return "Failed to refresh token."

            if response.status_code == 200:
                data = response.json()
                return data.get("profile", "Profile not found.") if data.get("status") == "success" else f"Error: {data.get('message')}"
            return f"Request failed with status code {response.status_code}"
        else:
            return f"Login failed with status code {login_response.status_code}"

    except jwt.ExpiredSignatureError:
        return "Error: Token has expired."
    except jwt.InvalidTokenError:
        return "Error: Invalid token."
    except Exception as e:
        return f"Error: {str(e)}"


class UpdateProfileInput(BaseModel):
    user_id: Optional[str] = None
    name: Optional[str] = None
    username: str = ""
    given_name: str = ""
    family_name: str = ""
    middle_name: str = ""
    birthdate: str = ""
    gender: str = ""
    court: str = ""
    specialization: str = ""
    profile_picture_key: str = ""
    profile_picture_url: str = ""
    role: str = ""
    years_of_experience: int = 0
    email: Optional[str] = None
    addresses: Optional[str] = None
    credentials: Dict[str, str]  # Required field, no default

    @model_validator(mode="before")
    @classmethod
    def check_credentials(cls, values):
        if "credentials" not in values or not isinstance(values["credentials"], dict):
            raise ValueError("Missing or invalid credentials")
        return values


@tool
def edit_profile(inputs: UpdateProfileInput):
    """
    Updates the profile of a logged-in lawyer using Flask API.
    It logs in with provided credentials and sends a PUT request with the allowed fields.
    """
    if isinstance(inputs, str):
        try:
            inputs = json.loads(inputs)  # Convert string to dict
            inputs = UpdateProfileInput.model_validate(inputs)  # Validate using Pydantic V2
        except json.JSONDecodeError:
            return "Error: Invalid JSON format."
        except Exception as e:
            return f"Error parsing input: {str(e)}"

    credentials = inputs.credentials
    if not credentials.get("username") or not credentials.get("password"):
        return "Error: Missing username or password in credentials."

    # Build the payload exactly matching the working curl:
    profile_data = {
        "name": inputs.given_name + " " + inputs.middle_name + " " + inputs.family_name,  # Use full name if 'name' not explicitly provided
        "given_name": inputs.given_name,
        "middle_name": inputs.middle_name,
        "family_name": inputs.family_name,
        "birthdate": inputs.birthdate,
        "gender": inputs.gender,
        "addresses": inputs.addresses,
        "specialization": inputs.specialization,
        "court": inputs.court,
        "years_of_experience": inputs.years_of_experience,
    }

    try:
        login_data = {
            "username": credentials["username"],
            "password": credentials["password"]
        }
        # Login to get the session token
        login_response = requests.post(login_url, json=login_data)
        data = login_response.json()

        if login_response.status_code == 200:
            session_token = data["data"].get("AccessToken")
            refresh_token = data["data"].get("RefreshToken")

            if not session_token:
                return "Error: No session token received during login."

            headers = {"Authorization": f"Bearer {session_token}"}
            cookies = login_response.cookies

            # Send PUT request with JSON payload
            response = requests.put(edit_profile_url, json=profile_data, headers=headers, cookies=cookies)

            if response.status_code == 401:
                print("Token expired, refreshing...")
                refresh_response = requests.post(login_url, json={"refresh_token": refresh_token})
                if refresh_response.status_code == 200:
                    new_token = refresh_response.json()["data"].get("AccessToken")
                    headers["Authorization"] = f"Bearer {new_token}"
                    response = requests.put(edit_profile_url, json=profile_data, headers=headers, cookies=cookies)
                else:
                    return "Error: Failed to refresh token."

            return response.json() if response.status_code == 200 else f"Error: {response.text}"

        return f"Login failed: {login_response.status_code}"

    except requests.RequestException as e:
        return f"API request error: {str(e)}"

# ✅ Define Appointments Agent using @tool decorator with the custom input model
# ✅ Define Appointments Agent using @tool decorator with the custom input model
@tool
def fetch_appointments(inputs: FetchAppointmentsInput):
    """
    Fetches appointments from the Flask API for the logged-in lawyer.
    Requires a valid username and password for login and captures the session token.
    """
    # Ensure that inputs is a FetchAppointmentsInput instance
    if not isinstance(inputs, FetchAppointmentsInput):
        try:
            inputs = FetchAppointmentsInput.parse_obj(inputs)
        except Exception as e:
            return "Error converting input: " + str(e)

    user_query = inputs.user_query
    credentials = inputs.credentials
    try:
        login_data = {
            "username": credentials["username"],
            "password": credentials["password"]
        }

        # Send login request to get session token
        login_response = requests.post(login_url, json=login_data)
        data = login_response.json()
        print(data)

        if login_response.status_code == 200:
            session_token = data["data"]["AccessToken"]
            refresh_token = data["data"]["RefreshToken"]  # Store the refresh token

            if not session_token:
                return "Error: No session token received during login."

            # Decode the JWT to extract user_id and role
            user_id = data["user_id"]  # Assuming user_id is in the "sub" field
            role = data["role"]  # Assuming role is in the "role" field
            print(user_id, role)

            if not user_id or not role:
                return "Error: Missing user_id or role in the session token."

            # Prepare headers with Authorization token
            headers = {
                "Authorization": f"Bearer {session_token}",
                "user_id": user_id,
                "role": role
            }

            # Send the request to view appointments with cookies
            cookies = login_response.cookies  # Store the session cookies
            response = requests.get(FLASK_API_URL, headers=headers, cookies=cookies)

            # Check if token expired and refresh
            if response.status_code == 401:  # Unauthorized (Token expired)
                print("Token expired, refreshing the token...")

                refresh_data = {
                    "refresh_token": refresh_token
                }

                # Refresh the access token using the refresh token
                refresh_response = requests.post(login_url, json=refresh_data)
                if refresh_response.status_code == 200:
                    new_data = refresh_response.json()
                    new_access_token = new_data["data"]["AccessToken"]
                    new_refresh_token = new_data["data"]["RefreshToken"]
                    print(f"New Access Token: {new_access_token}")

                    # Update headers with new access token
                    headers["Authorization"] = f"Bearer {new_access_token}"
                    headers["user_id"] = user_id
                    headers["role"] = role

                    # Retry the appointment request with the new token and the same cookies
                    response = requests.get(FLASK_API_URL, headers=headers, cookies=cookies)
                    print("New request status code:", response.status_code)
                else:
                    return "Failed to refresh token."

            # If the response is successful, return the appointments
            if response.status_code == 200:
                data = response.json()
                return data.get("appointments", "No appointments found.") if data.get(
                    "status") == "success" else f"Error: {data.get('message')}"
            return f"Request failed with status code {response.status_code}"
        else:
            return f"Login failed with status code {login_response.status_code}"

    except jwt.ExpiredSignatureError:
        return "Error: Token has expired."
    except jwt.InvalidTokenError:
        return "Error: Invalid token."
    except Exception as e:
        return f"Error: {str(e)}"
# Modify the route_query function to ensure input is correctly formatted:
def route_query(user_query: str, credentials: dict):
    """
    Routes the user query to the appropriate agent using all registered tools.
    """
    # Prepare the correct input format (dictionary, not a string)
    inputs = {
        "user_query": user_query,
        "credentials": credentials
    }
    print(inputs)



    # Find all tool functions in the current module
    tools = []
    for name, obj in inspect.getmembers(sys.modules[__name__]):
        # Check if the object is a BaseTool instance (which happens when using @tool)
        if isinstance(obj, BaseTool):
            tools.append(obj)

    print(f"Automatically found {len(tools)} tools: {[t.name for t in tools]}")
    router_agent = initialize_agent(
        tools=tools,
        llm=ChatOpenAI(model=model_name, openai_api_key=openai_api_key),
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True
    )

    # Ensure input is passed in the correct dictionary format
    response = router_agent.invoke({"input":inputs})
    return response

# ✅ Example Usage
if __name__ == "__main__":
    user_query = "What are my last 5 appointments?"
    # Note: Replace these with actual credentials or load from environment
    # Never hardcode credentials in production code
    credentials = {
        "username": os.getenv("TEST_USERNAME", "your_username_here"),  
        "password": os.getenv("TEST_PASSWORD", "your_password_here")  
    }
    
    if credentials["username"] == "your_username_here":
        print("Warning: Using placeholder credentials. Set TEST_USERNAME and TEST_PASSWORD environment variables for testing.")
    
    response = route_query(user_query=user_query, credentials=credentials)
    print(response)
