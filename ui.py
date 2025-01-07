# ui.py

import streamlit as st
import requests
from PIL import Image
import os
from datetime import datetime, date
from dotenv import load_dotenv
import pandas as pd
from collections import defaultdict

# Load environment variables from .env if present
load_dotenv()

# ---------------------------- Configuration ---------------------------- #
API_BASE_URL = "http://127.0.0.1:5002"  # Change if needed
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# ---------------------------- Initialize Session State ---------------------------- #
def init_session_state():
    """
    Ensure all required session state variables are defined
    so we don't get AttributeError when clearing/re-initializing.
    """
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'role' not in st.session_state:
        st.session_state.role = None
    if 'session' not in st.session_state:
        st.session_state.session = requests.Session()
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []

init_session_state()

# ---------------------------- Custom CSS for Tooltips ---------------------------- #
tooltip_css = """
<style>
.tooltip {
    position: relative;
    display: inline-block;
    cursor: pointer;
    color: #1e88e5;
    border-bottom: 1px dotted black; /* If you want dots under the hoverable text */
}

.tooltip .tooltiptext {
    visibility: hidden;
    width: 600px;
    background-color: #f9f9f9;
    color: #333;
    text-align: left;
    border: 1px solid #ccc;
    border-radius: 6px;
    padding: 10px;

    /* Position the tooltip */
    position: absolute;
    z-index: 1;
    top: 100%;
    left: 50%;
    margin-left: -100px; /* Half of the tooltip's width */

    /* Fade-in effect */
    opacity: 0;
    transition: opacity 0.3s;
}

.tooltip:hover .tooltiptext {
    visibility: visible;
    opacity: 1;
}
</style>
"""
st.markdown(tooltip_css, unsafe_allow_html=True)

# ---------------------------- Sidebar Navigation ---------------------------- #
st.sidebar.title("AdvoKare")

# Define navigation options based on user role
if st.session_state.logged_in:
    if st.session_state.role == "client":
        navigation_options = ["Home", "Book Appointment"]
    elif st.session_state.role == "lawyer":
        navigation_options = [
            "Home",
            "Upload Document",
            "View Documents",
            "Search Documents",
            "Chat",
            "Profile",
            "View Appointments"
        ]
    else:
        navigation_options = ["Home", "Profile"]
else:
    navigation_options = ["Home", "Register", "Login"]

selection = st.sidebar.radio("Navigate", navigation_options)
st.sidebar.markdown("---")

# Logout button (only visible if logged in)
if st.session_state.logged_in:
    st.sidebar.write(f"Logged in as: **{st.session_state.username}**")
    st.sidebar.write(f"Role: **{st.session_state.role.capitalize()}**")
    if st.sidebar.button("Logout"):
        # 1) Attempt to logout from the backend
        try:
            response = st.session_state.session.post(f"{API_BASE_URL}/logout")
            if response.status_code == 200:
                st.success("You have been logged out.")
            else:
                st.error("Logout failed on backend.")
        except Exception as e:
            st.error(f"An error occurred during logout: {e}")

        # 2) Clear local user/session data
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_id = None
        st.session_state.role = None
        # Clear chat history as well
        st.session_state.chat_history = []

        # 3) Stop execution so we don't reference session keys again
        st.stop()

# ---------------------------- Pages ---------------------------- #

# Home Page
if selection == "Home":
    st.title("Welcome to AdvoKare")
    st.write("""
    **AdvoKare** is a platform designed to assist lawyers and clients in managing and accessing legal services efficiently.

    **Features:**
    - User Registration and Authentication
    - Profile Management
    - Upload and Manage Documents
    - Powerful Search Functionality
    - Chat with Legal LLM for Assistance
    - Book Appointments with Lawyers
    """)
    st.image("https://via.placeholder.com/800x400.png?text=AdvoKare+Platform", use_container_width=True)

# Register Page
elif selection == "Register":
    st.title("Register")
    with st.form("registration_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        email = st.text_input("Email")
        given_name = st.text_input("Given Name")
        family_name = st.text_input("Family Name")
        middle_name = st.text_input("Middle Name")
        birthdate = st.date_input("Birthdate")
        gender = st.selectbox("Gender", ["Male", "Female", "Other"], index=0)
        addresses = st.text_area("Addresses")
        role = st.selectbox("Role", ["client", "lawyer"], index=0)

        # Conditional fields for lawyers
        if role == "lawyer":
            specialization = st.text_input("Specialization (e.g., Corporate Law, Criminal Law)")
            court = st.text_input("Court(s) You've Worked/In")
            years_of_experience = st.number_input("Years of Experience", min_value=0, max_value=100, value=1)

        submit_button = st.form_submit_button("Register")

    if submit_button:
        # Validate required fields
        required_fields = [
            username, password, email, given_name,
            family_name, birthdate, gender, addresses, role
        ]
        if not all(required_fields):
            st.error("Please fill in all required fields.")
        elif role == "lawyer" and (
            not specialization or not court or years_of_experience is None
        ):
            st.error("Please provide all lawyer-specific details.")
        else:
            registration_data = {
                "username": username,
                "password": password,
                "email": email,
                "given_name": given_name,
                "family_name": family_name,
                "middle_name": middle_name,
                "birthdate": birthdate.strftime("%Y-%m-%d"),
                "gender": gender,
                "addresses": addresses,
                "role": role
            }
            if role == "lawyer":
                registration_data.update({
                    "specialization": specialization,
                    "court": court,
                    "years_of_experience": years_of_experience
                })

            try:
                response = st.session_state.session.post(
                    f"{API_BASE_URL}/register",
                    json=registration_data
                )
                try:
                    result = response.json()
                except ValueError:
                    st.error("Received an invalid response from the server.")
                    st.write("**Response Status Code:**", response.status_code)
                    st.write("**Response Content:**", response.text)
                    st.stop()

                if response.status_code == 200:
                    st.success(result.get("message"))
                    st.info(f"Your User ID: {result.get('user_id')}")
                else:
                    st.error(result.get("message"))
            except Exception as e:
                st.error(f"An error occurred: {e}")

# Login Page
elif selection == "Login":
    st.title("Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")

    if submit_button:
        if not username or not password:
            st.error("Please enter both username and password.")
        else:
            login_data = {"username": username, "password": password}
            try:
                response = st.session_state.session.post(
                    f"{API_BASE_URL}/login",
                    json=login_data
                )
                try:
                    result = response.json()
                except ValueError:
                    st.error("Received an invalid response from the server.")
                    st.write("**Response Status Code:**", response.status_code)
                    st.write("**Response Content:**", response.text)
                    st.stop()

                if response.status_code == 200:
                    st.success(result.get("message"))
                    # Mark user as logged in
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    # Fetch user profile to get user_id and role
                    profile_response = st.session_state.session.get(
                        f"{API_BASE_URL}/profile/get_profile"
                    )
                    if profile_response.status_code == 200:
                        profile_data = profile_response.json().get("profile", {})
                        st.session_state.user_id = profile_data.get("user_id")
                        st.session_state.role = profile_data.get("role")
                        st.success(f"Logged in as {profile_data.get('name')}")
                    else:
                        st.error("Failed to retrieve user profile.")
                else:
                    error_message = result.get("error") or result.get("message")
                    st.error(error_message or "Login failed.")
            except requests.exceptions.ConnectionError:
                st.error("Could not connect to the server. Please ensure the backend is running.")
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")

elif selection == "Upload Document":
    if not st.session_state.logged_in:
        st.warning("Please log in to upload documents.")
    else:
        st.title("Upload Document")

        # 1) Fetch all existing "folders" from the backend
        try:
            folders_response = st.session_state.session.get(f"{API_BASE_URL}/folders")
            if folders_response.headers.get('Content-Type') == 'application/json':
                folders_result = folders_response.json()
                if folders_response.status_code == 200:
                    raw_folders = folders_result.get("folders", [])
                else:
                    raw_folders = []
                    st.error(f"Failed to fetch existing folders: {folders_result.get('message')}")
            else:
                raw_folders = []
                st.error("Failed to fetch existing folders. Invalid response format.")
        except Exception as e:
            raw_folders = []
            st.error(f"An error occurred while fetching folders: {e}")

        # 2) Convert raw_folders to TOP-LEVEL folders only (split on the first slash)
        top_level_folders = set()
        for f in raw_folders:
            parts = f.split("/", 1)  # only split on the first slash
            top_level_folders.add(parts[0])  # keep the main folder

        # Convert to a sorted list (optional)
        top_level_folders_list = sorted(list(top_level_folders))

        # 3) Folder dropdown: show either "Create New Folder" or the top-level ones
        folder_option = st.selectbox(
            "Select Main Folder",
            ["Create New Folder"] + top_level_folders_list
        )

        if folder_option == "Create New Folder":
            new_folder_name = st.text_input("Enter New Folder Name", placeholder="e.g. Case-00003")
            if new_folder_name.strip():
                selected_folder = new_folder_name.strip()
            else:
                selected_folder = "General"
        else:
            selected_folder = folder_option

        # 4) Subfolder input
        subfolder_name = st.text_input("Subfolder (Optional)", placeholder="e.g. personal details")
        if subfolder_name.strip():
            combined_folder_path = f"{selected_folder}/{subfolder_name.strip()}"
        else:
            combined_folder_path = selected_folder

        # 5) File uploader
        uploaded_file = st.file_uploader("Choose a file", type=["pdf", "txt"])
        if uploaded_file is not None:
            filename = uploaded_file.name
            file_bytes = uploaded_file.read()

            # Determine content type
            if filename.lower().endswith('.txt'):
                content_type = 'text/plain'
            elif filename.lower().endswith('.pdf'):
                content_type = 'application/pdf'
            else:
                content_type = uploaded_file.type or 'application/octet-stream'

            files = {
                'file': (filename, file_bytes, content_type)
            }
            data = {
                'folder': combined_folder_path  # Combine main folder + subfolder
            }

            if st.button("Upload"):
                with st.spinner("Uploading and processing document..."):
                    try:
                        response = st.session_state.session.post(
                            f"{API_BASE_URL}/upload",
                            files=files,
                            data=data
                        )
                        if 'application/json' in response.headers.get('Content-Type', ''):
                            result = response.json()
                        else:
                            st.error("Invalid response format from the server.")
                            st.write("**Response Status Code:**", response.status_code)
                            st.write("**Response Content:**", response.text)
                            st.stop()

                        if response.status_code == 200:
                            st.success(result.get("message"))
                        else:
                            st.error(result.get("message"))
                    except Exception as e:
                        st.error(f"An error occurred: {e}")


elif selection == "View Documents":
    if not st.session_state.logged_in:
        st.warning("Please log in to view your documents.")
    else:
        st.title("My Documents")
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")
            if 'application/json' in response.headers.get('Content-Type', ''):
                result = response.json()
            else:
                st.error("Received an invalid response from the server.")
                st.write("**Response Status Code:**", response.status_code)
                st.write("**Response Content:**", response.text)
                st.stop()

            if response.status_code == 200:
                documents = result.get("documents", [])
                if documents:
                    # Build a 2-level dictionary: main_folder -> sub_folder -> list_of_docs
                    from collections import defaultdict
                    folder_tree = defaultdict(lambda: defaultdict(list))

                    for doc in documents:
                        folder_path = doc.get('folder', 'General')
                        parts = folder_path.split('/', 1)  # split on the first slash only
                        if len(parts) == 2:
                            main_folder, sub_folder = parts
                        else:
                            main_folder = parts[0]
                            sub_folder = "No Subfolder"
                        folder_tree[main_folder][sub_folder].append(doc)

                    # Display in a single expander for the main folder; subfolders shown as headings.
                    for main_folder, subfolders in folder_tree.items():
                        with st.expander(f"📁 {main_folder}"):
                            for subfolder, docs_in_subfolder in subfolders.items():
                                # Subfolder heading (NOT an expander)
                                st.markdown(f"### {subfolder} ({len(docs_in_subfolder)})")

                                for doc in docs_in_subfolder:
                                    st.subheader(doc.get("doc_filename"))
                                    upload_date = doc.get("upload_date")
                                    if upload_date:
                                        try:
                                            from datetime import datetime
                                            upload_datetime = datetime.fromisoformat(upload_date)
                                            st.write(f"Uploaded on: {upload_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
                                        except ValueError:
                                            st.write(f"Uploaded on: {upload_date}")
                                    else:
                                        st.write("Upload date not available.")

                                    s3_key = doc.get("s3_key")
                                    s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"
                                    st.markdown(f"[View Document]({s3_url})")
                                    st.markdown("---")

                else:
                    st.info("No documents uploaded yet.")
            else:
                st.error(result.get("message"))
        except requests.exceptions.ConnectionError:
            st.error("Could not connect to the server. Please ensure the backend is running.")
        except Exception as e:
            st.error(f"An error occurred: {e}")


# Search Documents Page
elif selection == "Search Documents":
    if not st.session_state.logged_in:
        st.warning("Please log in to search documents.")
    else:
        st.title("Search Documents")
        with st.form("search_form"):
            query = st.text_input("Enter your search query")
            top_k = st.number_input("Number of top results", min_value=1, max_value=1000, value=100)
            submit_button = st.form_submit_button("Search")

        if submit_button:
            if not query:
                st.error("Please enter a search query.")
            else:
                search_data = {"query": query, "top_k": int(top_k)}
                with st.spinner("Searching documents..."):
                    try:
                        response = st.session_state.session.post(
                            f"{API_BASE_URL}/search_docs", json=search_data
                        )
                        try:
                            result = response.json()
                        except ValueError:
                            st.error("Received an invalid response from the server.")
                            st.write("**Response Status Code:**", response.status_code)
                            st.write("**Response Content:**", response.text)
                            st.stop()

                        if response.status_code == 200 and result.get("status") == "success":
                            results = result.get("results", [])
                            results_count = len(results)
                            st.success(f"Found {results_count} result{'s' if results_count != 1 else ''}.")

                            if results:
                                for doc in results:
                                    filename = doc.get("filename")
                                    similarity = doc.get("similarity")
                                    distance = doc.get("distance")
                                    summary_obj = doc.get("summary", {})
                                    # Grab the summary text
                                    if isinstance(summary_obj, str):
                                        tooltip_content = summary_obj
                                    else:
                                        tooltip_content = summary_obj.get("answer") or summary_obj.get("message", "No summary available.")

                                    # Generate pre-signed URL if needed
                                    s3_key = f"documents/{filename}"
                                    url_resp = st.session_state.session.post(
                                        f"{API_BASE_URL}/generate_presigned_url",
                                        json={"object_key": s3_key}
                                    )
                                    if url_resp.status_code == 200:
                                        presigned_url = url_resp.json().get("url")
                                    else:
                                        presigned_url = None

                                    # Tooltip
                                    tooltip_html = f"""
                                    <div class="tooltip">{filename}
                                        <span class="tooltiptext">{tooltip_content}</span>
                                    </div>
                                    """
                                    st.markdown(tooltip_html, unsafe_allow_html=True)
                                    st.write(f"Similarity: {similarity}%")
                                    st.write(f"Distance: {distance}")
                                    if presigned_url:
                                        st.markdown(
                                            f'<a href="{presigned_url}" target="_blank">View Document</a>',
                                            unsafe_allow_html=True
                                        )
                                    else:
                                        st.error("Failed to generate a pre-signed URL for the document.")
                                    st.markdown("---")
                            else:
                                st.info("No documents meet the similarity threshold.")
                        else:
                            st.error(result.get("message"))
                    except requests.exceptions.ConnectionError:
                        st.error("Could not connect to the server. Please ensure the backend is running.")
                    except Exception as e:
                        st.error(f"An unexpected error occurred: {e}")

# Chat Page
elif selection == "Chat":
    if not st.session_state.logged_in:
        st.warning("Please log in to access chat functionality.")
    else:
        st.title("Chat with AdvoKare")

        # 1) Fetch user's documents for selection
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")
            try:
                result = response.json()
            except ValueError:
                st.error("Received an invalid response from the server.")
                st.write("**Response Status Code:**", response.status_code)
                st.write("**Response Content:**", response.text)
                st.stop()

            if response.status_code == 200:
                documents = result.get("documents", [])
                if documents:
                    document_names = [doc.get("doc_filename") for doc in documents]
                    selected_doc = st.selectbox("Select a document to chat about", document_names)
                else:
                    st.info("No documents uploaded yet.")
                    selected_doc = None
            else:
                st.error(result.get("message"))
                selected_doc = None
        except requests.exceptions.ConnectionError:
            st.error("Could not connect to the server. Please ensure the backend is running.")
            selected_doc = None
        except Exception as e:
            st.error(f"An error occurred: {e}")
            selected_doc = None

        # 2) User input for chat
        chat_query = st.text_input("Enter your question or query")
        if st.button("Send"):
            if not chat_query.strip():
                st.warning("Please enter a valid query.")
            elif not selected_doc:
                st.warning("No document selected or no documents available.")
            else:
                # Append user's question to chat_history
                st.session_state.chat_history.append({
                    "role": "user",
                    "content": chat_query
                })

                # Send chat request to backend
                with st.spinner("Generating response..."):
                    try:
                        chat_data = {
                            "query": chat_query,
                            "document_name": selected_doc
                        }
                        chat_response = st.session_state.session.post(
                            f"{API_BASE_URL}/chat", json=chat_data
                        )
                        try:
                            chat_result = chat_response.json()
                        except ValueError:
                            st.error("Received an invalid response from the server.")
                            st.write("**Response Status Code:**", chat_response.status_code)
                            st.write("**Response Content:**", chat_response.text)
                            st.stop()

                        if chat_response.status_code == 200 and chat_result.get("status") == "success":
                            assistant_reply = chat_result.get("answer", "")
                            st.session_state.chat_history.append({
                                "role": "assistant",
                                "content": assistant_reply
                            })
                        else:
                            st.error(chat_result.get("message"))
                    except Exception as e:
                        st.error(f"An error occurred: {e}")

        # 3) Display conversation history
        st.subheader("Conversation History")
        if st.session_state.chat_history:
            for msg in st.session_state.chat_history:
                if msg["role"] == "user":
                    st.markdown(f"**You:** {msg['content']}")
                else:
                    st.markdown(f"**Assistant:** {msg['content']}")
        else:
            st.info("No conversation yet. Type something above.")

        # 4) Download conversation button
        if st.session_state.chat_history:
            # Convert chat to a single string
            chat_text = []
            for entry in st.session_state.chat_history:
                role = "You" if entry["role"] == "user" else "Assistant"
                chat_text.append(f"{role}: {entry['content']}")
            conversation_str = "\n\n".join(chat_text)

            st.download_button(
                label="Download Conversation",
                data=conversation_str,
                file_name="conversation.txt",
                mime="text/plain"
            )

# Profile Page
elif selection == "Profile":
    if not st.session_state.logged_in:
        st.warning("Please log in to access profile settings.")
    else:
        st.title("Your Profile")

        # 1) Ensure a session-state variable for edit mode
        if "edit_profile_mode" not in st.session_state:
            st.session_state.edit_profile_mode = False

        # 2) Fetch current profile
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/profile/get_profile")
            result = response.json()
            if response.status_code == 200 and result.get("status") == "success":
                profile = result.get("profile")
            else:
                st.error(result.get("message", "Failed to retrieve profile."))
                st.stop()
        except Exception as e:
            st.error(f"An error occurred while fetching profile: {e}")
            st.stop()

        # 3) Two columns: Picture / Info
        col1, col2 = st.columns([1, 2])

        with col1:
            # Show current profile picture
            if profile.get("profile_picture_url"):
                st.image(profile["profile_picture_url"], caption='Profile Picture', width=200)
            else:
                st.image("https://via.placeholder.com/150", caption='No Profile Picture', width=200)

        with col2:
            # Basic info display
            st.markdown(f"**Name:** {profile.get('name')}")
            st.markdown(f"**Email:** {profile.get('email')}")
            st.markdown(f"**Role:** {profile.get('role', '').capitalize()}")
            st.markdown(f"**Given Name:** {profile.get('given_name')}")
            st.markdown(f"**Middle Name:** {profile.get('middle_name')}")
            st.markdown(f"**Family Name:** {profile.get('family_name')}")
            st.markdown(f"**Birthdate:** {profile.get('birthdate')}")
            st.markdown(f"**Gender:** {profile.get('gender')}")
            st.markdown(f"**Addresses:** {profile.get('addresses')}")

        # 4) If user is a lawyer, show "Edit Profile" logic (remove if all roles can edit)
        if st.session_state.role == "lawyer":
            st.divider()

            # If not in edit mode, show a single "Edit Profile" button
            if not st.session_state.edit_profile_mode:
                if st.button("Edit Profile"):
                    # Toggle on edit mode
                    st.session_state.edit_profile_mode = True
                    # Streamlit will rerun automatically; no second click needed
            else:
                # If in edit mode, show the edit form (text + picture)
                st.subheader("Edit Your Profile")

                import datetime
                from datetime import date

                # Convert birthdate to a date object
                try:
                    birthdate_str = profile.get("birthdate", "")
                    birthdate_obj = datetime.datetime.strptime(birthdate_str, "%Y-%m-%d").date() if birthdate_str else date.today()
                except ValueError:
                    birthdate_obj = date.today()

                with st.form("edit_profile_form"):
                    updated_name = st.text_input("Full Name", value=profile.get("name", ""))
                    updated_given_name = st.text_input("Given Name", value=profile.get("given_name", ""))
                    updated_middle_name = st.text_input("Middle Name", value=profile.get("middle_name", ""))
                    updated_family_name = st.text_input("Family Name", value=profile.get("family_name", ""))
                    updated_birthdate = st.date_input("Birthdate", value=birthdate_obj)

                    gender_options = ["Male", "Female", "Other"]
                    current_gender = profile.get("gender", "Male")
                    if current_gender not in gender_options:
                        gender_options.append(current_gender)  # fallback
                    updated_gender = st.selectbox("Gender", gender_options, index=gender_options.index(current_gender))

                    updated_addresses = st.text_area("Addresses", value=profile.get("addresses", ""))

                    # Additional fields for lawyers (customize as needed)
                    updated_specialization = st.text_input("Specialization", value=profile.get("specialization", ""))
                    updated_court = st.text_input("Court(s) You've Worked/In", value=profile.get("court", ""))
                    updated_exp = st.number_input("Years of Experience", min_value=0, max_value=100, value=profile.get("years_of_experience", 1))

                    # Picture upload (optional)
                    new_pic = st.file_uploader("Upload New Profile Picture (optional)", type=["jpg", "jpeg", "png"])

                    # Form buttons
                    submit_btn = st.form_submit_button("Save Changes")
                    cancel_btn = st.form_submit_button("Cancel")

                    if cancel_btn:
                        # revert to read-only view
                        st.session_state.edit_profile_mode = False
                        # next run will show normal mode
                    elif submit_btn:
                        # 4A) Update textual fields
                        updated_data = {
                            "name": updated_name,
                            "given_name": updated_given_name,
                            "middle_name": updated_middle_name,
                            "family_name": updated_family_name,
                            "birthdate": updated_birthdate.strftime("%Y-%m-%d"),
                            "gender": updated_gender,
                            "addresses": updated_addresses,
                            "specialization": updated_specialization,
                            "court": updated_court,
                            "years_of_experience": updated_exp
                        }

                        try:
                            with st.spinner("Updating profile details..."):
                                update_resp = st.session_state.session.put(
                                    f"{API_BASE_URL}/profile/update_profile",
                                    json=updated_data
                                )
                            update_result = update_resp.json()
                            if update_resp.status_code == 200 and update_result.get("status") == "success":
                                st.success("Profile details updated successfully!")
                            else:
                                st.error(update_result.get("message", "Failed to update profile details."))
                        except Exception as e:
                            st.error(f"Error updating profile details: {e}")

                        # 4B) If a new picture was uploaded, update it
                        if new_pic is not None:
                            try:
                                with st.spinner("Uploading new profile picture..."):
                                    pic_files = {
                                        "profile_picture": (new_pic.name, new_pic.read(), new_pic.type)
                                    }
                                    pic_resp = st.session_state.session.post(
                                        f"{API_BASE_URL}/profile/update_profile_picture",
                                        files=pic_files
                                    )
                                pic_result = pic_resp.json()
                                if pic_resp.status_code == 200 and pic_result.get("status") == "success":
                                    st.success("Profile picture updated successfully.")
                                else:
                                    st.error(pic_result.get("message", "Failed to update profile picture."))
                            except Exception as e:
                                st.error(f"Error uploading profile picture: {e}")

                        # revert to read-only mode so next run won't show form
                        st.session_state.edit_profile_mode = False
        else:
            # If user is not a lawyer, just read-only
            st.info("You can view your profile details here.")




elif selection == "Book Appointment":
    if not st.session_state.logged_in:
        st.warning("Please log in to book appointments.")
    elif st.session_state.role != "client":
        st.error("Only clients can book appointments.")
    else:
        st.title("Book an Appointment")

        # 1) We use a session-state variable to track whether we are
        #    in "grid mode" or viewing a single lawyer's details.
        if "selected_lawyer_id" not in st.session_state:
            st.session_state.selected_lawyer_id = None

        # 2) If no lawyer is selected yet, show the GRID of lawyers
        if st.session_state.selected_lawyer_id is None:
            st.subheader("Available Lawyers")

            # Fetch all lawyers
            try:
                response = st.session_state.session.get(f"{API_BASE_URL}/profile/list_lawyers")
                result = response.json()
                if response.status_code == 200 and result.get("status") == "success":
                    lawyers = result.get("lawyers", [])
                    if not lawyers:
                        st.info("No lawyers available at the moment.")
                        st.stop()
                else:
                    st.error(result.get("message"))
                    st.stop()
            except Exception as e:
                st.error(f"An error occurred while fetching lawyers: {e}")
                st.stop()

            # Display lawyers in a grid
            import math

            num_cols = 3  # how many columns per row
            total_lawyers = len(lawyers)
            rows_needed = math.ceil(total_lawyers / num_cols)

            for row_idx in range(rows_needed):
                # create a row of columns
                cols = st.columns(num_cols, gap="large")
                for col_idx in range(num_cols):
                    index = row_idx * num_cols + col_idx
                    if index < total_lawyers:
                        lawyer = lawyers[index]
                        with cols[col_idx]:
                            # Show lawyer's profile picture if available
                            if lawyer.get("profile_picture_url"):
                                st.image(
                                    lawyer["profile_picture_url"],
                                    use_container_width=True  # Replaces deprecated use_column_width
                                )
                            else:
                                st.image(
                                    "https://via.placeholder.com/150",
                                    use_container_width=True
                                )

                            st.write(f"**Name:** {lawyer.get('name')}")
                            st.write(f"**Specialization:** {lawyer.get('specialization', 'N/A')}")
                            st.write(f"**Experience:** {lawyer.get('years_of_experience', 0)} years")

                            # A button to view details
                            # We embed the user_id in the button key or label
                            if st.button(
                                f"View Details {lawyer['user_id']}",
                                key=f"view_{lawyer['user_id']}"
                            ):
                                st.session_state.selected_lawyer_id = lawyer["user_id"]
                                st.session_state.lawyers_cache = lawyers  # store entire list for detail mode

        else:
            # 3) If a lawyer is selected, show detail view + appointment booking
            selected_lawyer_id = st.session_state.selected_lawyer_id
            lawyers = st.session_state.get("lawyers_cache", [])

            # Find the selected lawyer in the cached list
            selected_lawyer = next((lw for lw in lawyers if lw["user_id"] == selected_lawyer_id), None)
            if not selected_lawyer:
                st.error("Selected lawyer not found in the list.")
                # Offer a button to go back to grid
                if st.button("Back to List"):
                    st.session_state.selected_lawyer_id = None
                st.stop()

            # Show detailed info
            st.subheader(f"Lawyer Details: {selected_lawyer.get('name')}")
            detail_col1, detail_col2 = st.columns([1, 2])

            with detail_col1:
                if selected_lawyer.get("profile_picture_url"):
                    st.image(selected_lawyer["profile_picture_url"], use_container_width=True)
                else:
                    st.image("https://via.placeholder.com/150", use_container_width=True)

            with detail_col2:
                st.write(f"**Name:** {selected_lawyer.get('name')}")
                st.write(f"**Specialization:** {selected_lawyer.get('specialization', 'N/A')}")
                st.write(f"**Court(s):** {selected_lawyer.get('court', 'N/A')}")
                st.write(f"**Experience:** {selected_lawyer.get('years_of_experience', 0)} years")
                st.write(f"**Email:** {selected_lawyer.get('email')}")
                # Add more fields as needed

            st.markdown("---")

            # Offer a button to go back to the grid
            if st.button("Back to List"):
                st.session_state.selected_lawyer_id = None
                st.stop()

            st.subheader("Book an Appointment")

            from datetime import date
            selected_date = st.date_input("Choose a Date", min_value=date.today())
            time_slot_options = [f"{hour}:00-{hour + 1}:00" for hour in range(9, 18)]  # 9 AM to 5 PM
            selected_time_slot = st.selectbox("Choose a Time Slot", time_slot_options)

            if st.button("Book Appointment"):
                booking_data = {
                    "lawyer_id": selected_lawyer_id,
                    "date": selected_date.strftime("%Y-%m-%d"),
                    "time_slot": selected_time_slot
                }
                with st.spinner("Booking your appointment..."):
                    try:
                        response = st.session_state.session.post(
                            f"{API_BASE_URL}/profile/book_appointment",
                            json=booking_data
                        )
                        result = response.json()
                        if response.status_code == 200 and result.get("status") == "success":
                            st.success(result.get("message"))
                        elif response.status_code == 206:
                            st.warning(result.get("message"))
                        else:
                            st.error(result.get("message"))
                    except Exception as e:
                        st.error(f"An error occurred while booking the appointment: {e}")


# View Appointments Page (For Lawyers)
elif selection == "View Appointments":
    if not st.session_state.logged_in:
        st.warning("Please log in to view appointments.")
    elif st.session_state.role != "lawyer":
        st.error("Only lawyers can view appointments.")
    else:
        st.title("View Appointments")
        with st.spinner("Fetching your appointments..."):
            try:
                response = st.session_state.session.get(f"{API_BASE_URL}/profile/view_appointments")
                try:
                    result = response.json()
                except ValueError:
                    st.error("Received an invalid response from the server.")
                    st.write("**Response Status Code:**", response.status_code)
                    st.write("**Response Content:**", response.text)
                    st.stop()

                if response.status_code == 200 and result.get("status") == "success":
                    appointments = result.get("appointments", [])
                    if appointments:
                        df = pd.DataFrame(appointments)
                        # Format datetime fields
                        if 'date' in df.columns and 'time_slot' in df.columns:
                            df['Appointment Time'] = df['date'] + ' ' + df['time_slot']
                        if 'created_at' in df.columns:
                            df['Created At'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
                        display_columns = ['appointment_id', 'client_name', 'Appointment Time', 'status', 'Created At']
                        if 'client_name' not in df.columns:
                            df['client_name'] = df.get('client_name', 'N/A')
                        if 'status' not in df.columns:
                            df['status'] = df.get('status', 'N/A')
                        st.dataframe(df[display_columns].sort_values(by='Appointment Time', ascending=False))
                    else:
                        st.info("No appointments booked yet.")
                else:
                    st.error(result.get("message"))
            except requests.exceptions.ConnectionError:
                st.error("Could not connect to the server. Please ensure the backend is running.")
            except Exception as e:
                st.error(f"An error occurred: {e}")
