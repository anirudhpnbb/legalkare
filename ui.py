# ui.py

import streamlit as st
import requests
from PIL import Image
import os
from datetime import datetime, date
from dotenv import load_dotenv
import pandas as pd

# Load environment variables from .env if present
load_dotenv()

# Configuration
API_BASE_URL = "http://127.0.0.1:5002"  # Flask backend URL
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")  # Replace with your actual S3 bucket name

# Initialize Session State
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.user_id = None
    st.session_state.role = None
    st.session_state.session = requests.Session()  # Persistent session for cookies

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

# Inject custom CSS into Streamlit app
st.markdown(tooltip_css, unsafe_allow_html=True)

# ---------------------------- Sidebar Navigation ---------------------------- #

st.sidebar.title("LegalAid")

# Define navigation options based on user role
if st.session_state.logged_in:
    if st.session_state.role == "client":
        navigation_options = ["Home", "Upload Document", "View Documents", "Search Documents",
                              "Chat", "Profile", "Book Appointment"]
    elif st.session_state.role == "lawyer":
        navigation_options = ["Home", "Upload Document", "View Documents", "Search Documents",
                              "Chat", "Profile", "View Appointments"]
    else:
        navigation_options = ["Home", "Profile"]
else:
    navigation_options = ["Home", "Register", "Login", "Upload Document", "View Documents",
                          "Search Documents", "Chat", "Profile"]

selection = st.sidebar.radio("Navigate", navigation_options)

st.sidebar.markdown("---")

if st.session_state.logged_in:
    st.sidebar.write(f"Logged in as: **{st.session_state.username}**")
    st.sidebar.write(f"Role: **{st.session_state.role.capitalize()}**")
    if st.sidebar.button("Logout"):
        try:
            response = st.session_state.session.post(f"{API_BASE_URL}/logout")
            if response.status_code == 200:
                result = response.json()
                st.success(result.get("message"))
                # Reset session state
                st.session_state.logged_in = False
                st.session_state.username = None
                st.session_state.user_id = None
                st.session_state.role = None
                st.session_state.session = requests.Session()  # Reset session
            else:
                result = response.json()
                st.error(result.get("message"))
        except Exception as e:
            st.error(f"An error occurred during logout: {e}")

# ---------------------------- Main Pages ---------------------------- #

# Home Page
if selection == "Home":
    st.title("Welcome to LegalAid")
    st.write("""
    **LegalAid** is a platform designed to assist lawyers and clients in managing and accessing legal services efficiently.

    **Features:**
    - User Registration and Authentication
    - Profile Management
    - Upload and Manage Documents
    - Powerful Search Functionality
    - Chat with Legal LLM for Assistance
    - Book Appointments with Lawyers
    """)
    st.image("https://via.placeholder.com/800x400.png?text=LegalAid+Platform", use_column_width=True)

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
        required_fields = [username, password, email, given_name, family_name, birthdate, gender, addresses, role]
        if not all(required_fields):
            st.error("Please fill in all required fields.")
        elif role == "lawyer" and (not specialization or not court or years_of_experience is None):
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
                response = st.session_state.session.post(f"{API_BASE_URL}/register", json=registration_data)
                # Check if response contains JSON
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
        # Validate required fields
        if not username or not password:
            st.error("Please enter both username and password.")
        else:
            login_data = {
                "username": username,
                "password": password
            }

            try:
                response = st.session_state.session.post(f"{API_BASE_URL}/login", json=login_data)
                # Check if response contains JSON
                try:
                    result = response.json()
                except ValueError:
                    st.error("Received an invalid response from the server.")
                    st.write("**Response Status Code:**", response.status_code)
                    st.write("**Response Content:**", response.text)
                    st.stop()

                if response.status_code == 200:
                    st.success(result.get("message"))
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    # Fetch user profile to get user_id and role
                    profile_response = st.session_state.session.get(f"{API_BASE_URL}/profile/get_profile")
                    if profile_response.status_code == 200:
                        profile_data = profile_response.json().get("profile", {})
                        st.session_state.user_id = profile_data.get("user_id")
                        st.session_state.role = profile_data.get("role")
                        st.success(f"Logged in as {profile_data.get('name')}")
                    else:
                        st.error("Failed to retrieve user profile.")
                else:
                    # Attempt to get a meaningful error message
                    error_message = result.get("error") or result.get("message")
                    st.error(error_message or "Login failed.")
            except requests.exceptions.ConnectionError:
                st.error("Could not connect to the server. Please ensure the backend is running.")
            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")

# Upload Document Page
elif selection == "Upload Document":
    if not st.session_state.logged_in:
        st.warning("Please log in to upload documents.")
    else:
        st.title("Upload Document")
        uploaded_file = st.file_uploader("Choose a file", type=["pdf", "txt"])
        if uploaded_file is not None:
            filename = uploaded_file.name
            file_bytes = uploaded_file.read()
            files = {
                'file': (filename, file_bytes, uploaded_file.type)
            }
            if st.button("Upload"):
                with st.spinner("Uploading and processing document..."):
                    try:
                        response = st.session_state.session.post(f"{API_BASE_URL}/upload", files=files)
                        # Check if response contains JSON
                        try:
                            result = response.json()
                        except ValueError:
                            st.error("Received an invalid response from the server.")
                            st.write("**Response Status Code:**", response.status_code)
                            st.write("**Response Content:**", response.text)
                            st.stop()

                        if response.status_code == 200:
                            st.success(result.get("message"))
                        else:
                            st.error(result.get("message"))
                    except Exception as e:
                        st.error(f"An error occurred: {e}")

# View Documents Page
elif selection == "View Documents":
    if not st.session_state.logged_in:
        st.warning("Please log in to view your documents.")
    else:
        st.title("My Documents")
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")
            # Check if response contains JSON
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
                    for doc in documents:
                        st.subheader(doc.get("doc_filename"))
                        upload_date = doc.get("upload_date")
                        if upload_date:
                            # Assuming upload_date is a datetime object serialized to string
                            if isinstance(upload_date, str):
                                try:
                                    upload_date = datetime.strptime(upload_date, "%Y-%m-%dT%H:%M:%S.%f")
                                except ValueError:
                                    pass
                            st.write(f"Uploaded on: {upload_date.strftime('%Y-%m-%d %H:%M:%S') if isinstance(upload_date, datetime) else upload_date}")
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
            # Validate required fields
            if not query:
                st.error("Please enter a search query.")
            else:
                search_data = {
                    "query": query,
                    "top_k": int(top_k)
                }
                with st.spinner("Searching documents..."):
                    try:
                        response = st.session_state.session.post(f"{API_BASE_URL}/search_docs", json=search_data)
                        # Check if response contains JSON
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
                                    try:
                                        try:
                                            summary_message = summary_obj.get("answer")
                                            # Determine tooltip content based on summary status
                                            tooltip_content = summary_message
                                        except:
                                            summary_message = summary_obj.get("message")
                                            # Determine tooltip content based on summary status
                                            tooltip_content = summary_message
                                    except:
                                        summary_message = summary_obj
                                        tooltip_content = summary_message

                                    # Construct S3 URL based on your backend's upload structure
                                    s3_key = f"docs/{st.session_state.user_id}/{filename}"
                                    s3_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{s3_key}"

                                    # Create tooltip-enabled filename
                                    tooltip_html = f"""
                                    <div class="tooltip">{filename}
                                        <span class="tooltiptext">{tooltip_content}</span>
                                    </div>
                                    """

                                    st.markdown(tooltip_html, unsafe_allow_html=True)
                                    st.write(f"Similarity: {similarity}%")
                                    st.write(f"Distance: {distance}")
                                    st.markdown(f"[View Document]({s3_url})")
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
        st.title("Chat with LegalAid")
        try:
            # Fetch user's documents for selection
            response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")
            # Check if response contains JSON
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

                    chat_query = st.text_input("Enter your question or query", "")
                    if st.button("Send"):
                        if not chat_query.strip():
                            st.warning("Please enter a valid query.")
                        else:
                            chat_data = {
                                "query": chat_query,
                                "document_name": selected_doc
                            }
                            with st.spinner("Generating response..."):
                                try:
                                    chat_response = st.session_state.session.post(f"{API_BASE_URL}/chat",
                                                                                  json=chat_data)
                                    # Check if response contains JSON
                                    try:
                                        chat_result = chat_response.json()
                                    except ValueError:
                                        st.error("Received an invalid response from the server.")
                                        st.write("**Response Status Code:**", chat_response.status_code)
                                        st.write("**Response Content:**", chat_response.text)
                                        st.stop()

                                    if chat_response.status_code == 200 and chat_result.get("status") == "success":
                                        st.success("LLM Response:")
                                        st.write(chat_result.get("answer"))
                                    else:
                                        st.error(chat_result.get("message"))
                                except requests.exceptions.ConnectionError:
                                    st.error("Could not connect to the server. Please ensure the backend is running.")
                                except Exception as e:
                                    st.error(f"An error occurred: {e}")
                else:
                    st.info("No documents uploaded yet.")
            else:
                st.error(result.get("message"))
        except requests.exceptions.ConnectionError:
            st.error("Could not connect to the server. Please ensure the backend is running.")
        except Exception as e:
            st.error(f"An error occurred: {e}")

# Profile Page
elif selection == "Profile":
    if not st.session_state.logged_in:
        st.warning("Please log in to access profile settings.")
    else:
        st.title("Your Profile")

        # Fetch current profile details
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/profile/get_profile")
            result = response.json()
            if response.status_code == 200 and result.get("status") == "success":
                profile = result.get("profile")
            else:
                st.error(result.get("message"))
                st.stop()
        except Exception as e:
            st.error(f"An error occurred while fetching profile: {e}")
            st.stop()

        # Display current profile picture
        if profile.get("profile_picture_url"):
            st.image(profile.get("profile_picture_url"), caption='Profile Picture', use_column_width=True)
        else:
            st.image("https://via.placeholder.com/150", caption='No Profile Picture', use_column_width=True)

        st.subheader("Update Profile Picture")
        uploaded_image = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])
        if uploaded_image is not None:
            image = Image.open(uploaded_image)
            st.image(image, caption='Uploaded Image.', use_column_width=True)
            st.write("")
            if st.button("Upload Profile Picture"):
                # Validate required fields
                if not uploaded_image:
                    st.error("Please select an image to upload.")
                else:
                    image_bytes = uploaded_image.read()
                    files = {
                        'profile_picture': (uploaded_image.name, image_bytes, uploaded_image.type)
                    }
                    with st.spinner("Uploading profile picture..."):
                        try:
                            response = st.session_state.session.post(
                                f"{API_BASE_URL}/profile/update_profile_picture",
                                files=files
                            )
                            # Check if response contains JSON
                            try:
                                result = response.json()
                            except ValueError:
                                st.error("Received an invalid response from the server.")
                                st.write("**Response Status Code:**", response.status_code)
                                st.write("**Response Content:**", response.text)
                                st.stop()

                            if response.status_code == 200:
                                st.success(result.get("message"))
                                profile_pic_url = result.get("profile_picture_url")
                                if profile_pic_url:
                                    st.image(profile_pic_url, caption='Current Profile Picture.', use_column_width=True)
                            else:
                                st.error(result.get("message"))
                        except Exception as e:
                            st.error(f"An error occurred: {e}")

        st.subheader("Update Profile Details")
        with st.form("update_profile_form"):
            name = st.text_input("Full Name", value=profile.get("name", ""))
            given_name = st.text_input("Given Name", value=profile.get("given_name", ""))
            middle_name = st.text_input("Middle Name", value=profile.get("middle_name", ""))
            family_name = st.text_input("Family Name", value=profile.get("family_name", ""))
            birthdate = st.date_input("Birthdate", value=datetime.strptime(profile.get("birthdate"), "%Y-%m-%d") if profile.get("birthdate") else date.today())
            gender = st.selectbox("Gender", ["Male", "Female", "Other"], index=["Male", "Female", "Other"].index(profile.get("gender", "Male")))
            addresses = st.text_area("Addresses", value=profile.get("addresses", ""))

            # Conditional fields for lawyers
            if profile.get("role") == "lawyer":
                specialization = st.text_input("Specialization", value=profile.get("specialization", ""))
                court = st.text_input("Court(s) You've Worked/In", value=profile.get("court", ""))
                years_of_experience = st.number_input("Years of Experience", min_value=0, max_value=100, value=profile.get("years_of_experience", 1))

            submit_button = st.form_submit_button("Update Profile")

        if submit_button:
            update_data = {
                "name": name,
                "given_name": given_name,
                "middle_name": middle_name,
                "family_name": family_name,
                "birthdate": birthdate.strftime("%Y-%m-%d"),
                "gender": gender,
                "addresses": addresses
            }

            if profile.get("role") == "lawyer":
                update_data.update({
                    "specialization": specialization,
                    "court": court,
                    "years_of_experience": years_of_experience
                })

            with st.spinner("Updating profile..."):
                try:
                    response = st.session_state.session.put(
                        f"{API_BASE_URL}/profile/update_profile",
                        json=update_data
                    )
                    result = response.json()
                    if response.status_code == 200:
                        st.success(result.get("message"))
                    else:
                        st.error(result.get("message"))
                except Exception as e:
                    st.error(f"An error occurred: {e}")

# Book Appointment Page
elif selection == "Book Appointment":
    if not st.session_state.logged_in:
        st.warning("Please log in to book appointments.")
    elif st.session_state.role != "client":
        st.error("Only clients can book appointments.")
    else:
        st.title("Book an Appointment")

        # Step 1: Select a Lawyer
        st.subheader("Select a Lawyer")
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/profile/list_lawyers")
            result = response.json()
            if response.status_code == 200 and result.get("status") == "success":
                lawyers = result.get("lawyers", [])
                if not lawyers:
                    st.info("No lawyers available at the moment.")
                    st.stop()
                lawyer_options = {f"{lawyer['name']} (Specialization: {lawyer.get('specialization', 'N/A')})": lawyer['user_id'] for lawyer in lawyers}
                selected_lawyer_name = st.selectbox("Choose a Lawyer", list(lawyer_options.keys()))
                selected_lawyer_id = lawyer_options[selected_lawyer_name]
            else:
                st.error(result.get("message"))
                st.stop()
        except Exception as e:
            st.error(f"An error occurred while fetching lawyers: {e}")
            st.stop()

        # Step 2: Select Date and Time Slot
        st.subheader("Select Date and Time Slot")
        selected_date = st.date_input("Choose a Date", min_value=date.today())
        time_slot_options = [f"{hour}:00-{hour + 1}:00" for hour in range(9, 18)]  # 9 AM to 5 PM
        selected_time_slot = st.selectbox("Choose a Time Slot", time_slot_options)

        # Step 3: Confirm Booking
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
                # Check if response contains JSON
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
                        # Convert appointments to a DataFrame for better display
                        df = pd.DataFrame(appointments)
                        # Optional: Format datetime fields
                        if 'date' in df.columns and 'time_slot' in df.columns:
                            df['Appointment Time'] = df['date'] + ' ' + df['time_slot']
                        if 'created_at' in df.columns:
                            df['Created At'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
                        # Select relevant columns
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
