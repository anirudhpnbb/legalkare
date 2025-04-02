# ui.py

import streamlit as st
import requests
import os
from datetime import datetime, date
from dotenv import load_dotenv
import pandas as pd
from collections import defaultdict
import json
import io
import re
from streamlit_lottie import st_lottie
import plotly.express as px
from matplotlib import pyplot as plt

load_dotenv()

model = os.getenv("OPENAI_MODEL_NAME")

# ---------------------------- Configuration ---------------------------- #
API_BASE_URL = "http://127.0.0.1:5002"  # Change if needed
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
BOT_NAME = "Gavel"
COURT_TEMPLATES_FOLDER = "court_templates"

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
    # Additional variables for page navigation
    if 'current_view' not in st.session_state:
        st.session_state.current_view = "Main"  # Default view
    if 'selected_document' not in st.session_state:
        st.session_state.selected_document = None
    if 'selected_widgets' not in st.session_state:
        st.session_state.selected_widgets = None

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

# ---------------------------- Custom CSS for Tooltips and General Styling ---------------------------- #
custom_css = """
<style>
    /* General Styling */
    body {
        background-color: #f0f2f6;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }

    /* Hero Section */
    .hero {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 50px 0;
    }

    .hero-text {
        max-width: 600px;
    }

    .hero-text h1 {
        font-size: 3rem;
        color: #333333;
    }

    .hero-text p {
        font-size: 1.2rem;
        color: #555555;
        margin-top: 20px;
        line-height: 1.6;
    }

    /* Features Section */
    .features {
        padding: 50px 0;
    }

    .feature {
        text-align: center;
        padding: 20px;
    }

    .feature img {
        width: 100px;
        height: 100px;
    }

    .feature h3 {
        margin-top: 20px;
        font-size: 1.5rem;
        color: #333333;
    }

    .feature p {
        color: #555555;
        margin-top: 10px;
        line-height: 1.4;
    }

    /* Button Styling */
    .btn {
        display: inline-block;
        padding: 12px 24px;
        font-size: 1rem;
        color: #ffffff;
        background-color: #1e88e5;
        border: none;
        border-radius: 25px;
        cursor: pointer;
        transition: background-color 0.3s ease;
        text-decoration: none;
    }

    .btn:hover {
        background-color: #1565c0;
    }
</style>
"""

st.markdown(custom_css, unsafe_allow_html=True)

def load_lottieurl(url: str):
    """
    Load a Lottie animation from a URL.
    """
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

def fetch_data(endpoint, user_id):
    """ Helper function to fetch data from the Flask API """
    response = requests.get(f'{API_BASE_URL}/{endpoint}/{user_id}')
    if response.status_code == 200:
        return response.json()
    else:
        st.error('Failed to fetch data')
        return []

def process_reviews(reviews):
    """
    Convert MongoDB extended JSON to a normal Python dict
    and return a pandas DataFrame.
    """
    for review in reviews:
        # Convert the ObjectId
        if "_id" in review and "$oid" in review["_id"]:
            review["_id"] = review["_id"]["$oid"]

        # Convert the date
        if "date" in review and "$date" in review["date"]:
            # e.g. "2023-08-10T12:34:56Z"
            iso_str = review["date"]["$date"]
            review["date"] = datetime.fromisoformat(iso_str.replace("Z", ""))

    return pd.DataFrame(reviews)

def plot_reviews(df):
    """ Plots the distribution of review ratings """
    if not df.empty and 'rating' in df.columns:
        fig, ax = plt.subplots()
        df['rating'].value_counts().plot(kind='bar', ax=ax, color='skyblue')
        ax.set_title('Review Ratings Distribution')
        ax.set_xlabel('Ratings')
        ax.set_ylabel('Frequency')
        st.pyplot(fig)

# ---------------------------- Sidebar Navigation ---------------------------- #
st.sidebar.title("LegalKare")

if st.session_state.logged_in:
    if st.session_state.role == "client":
        navigation_options = ["Home", "Book Appointment", "Submit Review", "FAQs"]
    elif st.session_state.role == "lawyer":
        navigation_options = [
            "Home",
            "Upload Document",
            "Documents Control Panel",
            "View Documents",
            "Search Documents",
            "Create Court Document",
            "Chat",
            "Profile",
            "Teams",
            "Notifications",
            "Dashboard",
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


# ---------------------------- Home Page Function ---------------------------- #
def home_page():
    st.markdown("---")
    st.image("logo.png", use_container_width=True, width=400)

    # Load Lottie animation for the hero section
    lottie_animation = load_lottieurl(
        "https://assets9.lottiefiles.com/packages/lf20_jcikwtux.json")  # Replace with your chosen animation URL

    # Hero Section
    st.markdown('<div class="hero">', unsafe_allow_html=True)

    # Hero Text
    st.markdown('<div class="hero-text">', unsafe_allow_html=True)
    st.markdown("### Welcome to **LegalKare**", unsafe_allow_html=True)
    st.markdown("""
        **LegalKare** is a comprehensive platform designed to assist lawyers and clients in managing and accessing legal services efficiently.

        **Our Mission:** To bridge the gap between legal professionals and clients by providing a seamless, secure, and intuitive platform for all your legal needs.
    """, unsafe_allow_html=True)

    # Action Buttons
    st.markdown("""
        <a href="#features" class="btn">Learn More</a>
        <a href="#register" class="btn">Get Started</a>
    """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Hero Animation
    st.markdown('<div>', unsafe_allow_html=True)
    st_lottie(lottie_animation, height=300, key="hero_animation")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Features Section
    st.markdown('<div class="features" id="features">', unsafe_allow_html=True)
    st.markdown("### Features", unsafe_allow_html=True)
    st.markdown('<hr>', unsafe_allow_html=True)

    # Create columns for features
    feature_cols = st.columns(3)

    features = [
        {
            "icon": "https://img.icons8.com/ios-filled/100/1e88e5/user-male-circle.png",
            "title": "User Registration & Authentication",
            "description": "Secure and seamless registration process ensuring your data privacy."
        },
        {
            "icon": "https://img.icons8.com/ios-filled/100/1e88e5/user-male-circle.png",
            "title": "Profile Management",
            "description": "Manage your personal and professional information with ease."
        },
        {
            "icon": "https://img.icons8.com/ios-filled/100/1e88e5/upload.png",
            "title": "Upload & Manage Documents",
            "description": "Efficiently upload, organize, and access your legal documents."
        },
        {
            "icon": "https://img.icons8.com/ios-filled/100/1e88e5/search.png",
            "title": "Powerful Search Functionality",
            "description": "Find the information you need quickly with our advanced search tools."
        },
        {
            "icon": "https://img.icons8.com/ios-filled/100/1e88e5/chat.png",
            "title": "Chat with Legal LLM",
            "description": "Get instant assistance and legal advice through our intelligent chat system."
        },
        {
            "icon": "https://img.icons8.com/ios-filled/100/1e88e5/calendar.png",
            "title": "Book Appointments",
            "description": "Schedule meetings with lawyers at your convenience."
        }
    ]

    for idx, feature in enumerate(features):
        with feature_cols[idx % 3]:
            st.markdown('<div class="feature">', unsafe_allow_html=True)
            st.image(feature["icon"], width=100)
            st.markdown(f"### {feature['title']}", unsafe_allow_html=True)
            st.markdown(f"{feature['description']}", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Optional: Add another animation or decorative elements below
    st.markdown('<div>', unsafe_allow_html=True)
    lottie_decor = load_lottieurl(
        "https://assets10.lottiefiles.com/packages/lf20_jcikwtux.json")  # Replace with another animation if desired
    st_lottie(lottie_decor, height=200, key="decor_animation")
    st.markdown('</div>', unsafe_allow_html=True)

    # Register Section (Anchor)
    st.markdown('<div id="register">', unsafe_allow_html=True)
    st.markdown("### Ready to Get Started?", unsafe_allow_html=True)
    st.markdown("""
        Join **LegalKare** today and take the first step towards efficient and effective legal management.
    """, unsafe_allow_html=True)
    st.markdown("""
        <a href="Register" class="btn">Register Now</a>
        <a href="Login" class="btn">Login</a>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ---------------------------- Pages ---------------------------- #
def view_document_page(document):
    """
    Displays the document content with interactive annotation capabilities.

    Args:
        document (dict): A dictionary containing document details.
    """
    st.title(f"Document Viewer: {document.get('doc_filename')}")

    # 1. Display the Document Content
    st.subheader("Document Content")

    # Fetch and display the TXT content
    s3_key = document.get("s3_key")
    filename = document.get("doc_filename", "")
    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    if file_ext != 'txt':
        st.warning("Interactive annotations are currently supported only for TXT documents.")
        return

    try:
        # Fetch the TXT content from the backend
        txt_resp = st.session_state.session.get(
            f"{API_BASE_URL}/serve_document",
            params={"document_key": s3_key}
        )
        if txt_resp.status_code == 200:
            txt_content = txt_resp.text
            if not txt_content.strip():
                st.info("The document is empty.")
                return
        else:
            st.error("Failed to fetch TXT document content.")
            st.write(f"**Status Code:** {txt_resp.status_code}")
            st.write(f"**Response Body:** {txt_resp.text}")
            return
    except Exception as e:
        st.error(f"Error fetching TXT content: {e}")
        return

    # 2. Fetch Existing Annotations
    try:
        annotations_resp = st.session_state.session.get(
            f"{API_BASE_URL}/get_annotations",
            params={"document_name": filename}
        )
        annotations_result = annotations_resp.json()
        if annotations_resp.status_code == 200 and annotations_result.get("status") == "success":
            annotations = annotations_result.get("annotations", [])
        else:
            st.error(annotations_result.get("message", "Failed to fetch annotations."))
            annotations = []
    except Exception as e:
        st.error(f"Error fetching annotations: {e}")
        annotations = []

    # 3. Prepare Annotations Data for Frontend
    annotations_json = json.dumps(annotations)

    # Get user_id from session_state
    user_id = st.session_state.get('user_id', 'anonymous')  # Replace 'anonymous' as needed

    # 4. Embed HTML and JavaScript for Interactive Annotation
    # Ensure backticks in txt_content are escaped to prevent breaking the JavaScript template literals
    escaped_txt_content = txt_content.replace("`", "\\`").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    annotation_html = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                white-space: pre-wrap;
                position: relative;
            }}
            .highlight {{
                background-color: yellow;
                cursor: pointer;
            }}
            .tooltip {{
                position: relative;
                display: inline-block;
            }}

            .tooltip .tooltiptext {{
                visibility: hidden;
                width: 200px;
                background-color: black;
                color: #fff;
                text-align: center;
                border-radius: 6px;
                padding: 5px 0;
                position: absolute;
                z-index: 1;
                bottom: 125%; /* Position above the text */
                left: 50%;
                margin-left: -100px;
                opacity: 0;
                transition: opacity 0.3s;
            }}

            .tooltip:hover .tooltiptext {{
                visibility: visible;
                opacity: 1;
            }}

            /* Modal styles */
            .modal {{
                display: none; /* Hidden by default */
                position: fixed; /* Stay in place */
                z-index: 100; /* Sit on top */
                left: 0;
                top: 0;
                width: 100%; /* Full width */
                height: 100%; /* Full height */
                overflow: auto; /* Enable scroll if needed */
                background-color: rgba(0,0,0,0.4); /* Black w/ opacity */
            }}

            /* Modal content */
            .modal-content {{
                background-color: #fefefe;
                margin: 10% auto; /* 10% from the top and centered */
                padding: 20px;
                border: 1px solid #888;
                width: 300px; /* Could be more or less, depending on screen size */
                border-radius: 5px;
            }}

            /* Close button */
            .close {{
                color: #aaa;
                float: right;
                font-size: 28px;
                font-weight: bold;
            }}

            .close:hover,
            .close:focus {{
                color: black;
                text-decoration: none;
                cursor: pointer;
            }}

            /* Annotation input styles */
            .annotation-input {{
                width: 100%;
                padding: 8px;
                margin: 8px 0;
                box-sizing: border-box;
            }}

            .annotation-buttons {{
                display: flex;
                justify-content: flex-end;
            }}

            .annotation-buttons button {{
                margin-left: 10px;
                padding: 8px 12px;
            }}

            /* Add Highlight Button */
            #addHighlightBtn {{
                display: none; /* Hidden by default */
                position: absolute;
                background-color: #4CAF50;
                color: white;
                padding: 5px 10px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                z-index: 101;
            }}

            #addHighlightBtn:hover {{
                background-color: #45a049;
            }}
        </style>
    </head>
    <body>
        <div id="document-content">{escaped_txt_content}</div>

        <!-- The Modal -->
        <div id="annotationModal" class="modal">
            <!-- Modal content -->
            <div class="modal-content">
                <span class="close">&times;</span>
                <h3>Add Highlight (Optional Annotation)</h3>
                <textarea id="annotationText" class="annotation-input" rows="4" placeholder="Enter your annotation here (optional)..."></textarea>
                <div class="annotation-buttons">
                    <button id="cancelBtn">Cancel</button>
                    <button id="submitBtn">Submit</button>
                </div>
            </div>
        </div>

        <!-- Add Highlight Button -->
        <button id="addHighlightBtn">Add Highlight</button>

        <script>
            // Parse existing annotations
            const annotations = {annotations_json};
            console.log("Existing Annotations:", annotations);

            // User ID passed from Python
            const user_id = "{user_id}";
            console.log("User ID:", user_id);

            // Store the original text
            const originalText = `{escaped_txt_content}`;

            /**
             * Function to apply all annotations
             */
            function applyAnnotations() {{
                console.log("Applying annotations...");
                if (annotations.length === 0) {{
                    document.getElementById('document-content').innerHTML = originalText;
                    return;
                }}

                // Sort annotations by start_index ascending
                annotations.sort((a, b) => a.start_index - b.start_index);

                let highlightedHTML = "";
                let lastIndex = 0;

                annotations.forEach(function(ann) {{
                    const start = ann.start_index;
                    const end = ann.end_index;
                    const highlighted_text = ann.highlighted_text;
                    const comment = ann.annotation || "No annotation provided.";

                    // Append text before the highlight
                    highlightedHTML += originalText.slice(lastIndex, start);

                    // Escape any HTML in the highlighted_text and comment to prevent XSS
                    const escapedHighlightedText = highlighted_text.replace(/&/g, "&amp;")
                                                                   .replace(/</g, "&lt;")
                                                                   .replace(/>/g, "&gt;")
                                                                   .replace(/"/g, "&quot;")
                                                                   .replace(/'/g, "&#039;");
                    const escapedComment = comment.replace(/&/g, "&amp;")
                                                  .replace(/</g, "&lt;")
                                                  .replace(/>/g, "&gt;")
                                                  .replace(/"/g, "&quot;")
                                                  .replace(/'/g, "&#039;");

                    // Append the highlighted span with escaped variables
                    highlightedHTML += `<span class="tooltip highlight">${{escapedHighlightedText}}<span class="tooltiptext">${{escapedComment}}</span></span>`;

                    // Update lastIndex
                    lastIndex = end;
                }});

                // Append any remaining text after the last highlight
                highlightedHTML += originalText.slice(lastIndex);

                // Set the innerHTML
                document.getElementById('document-content').innerHTML = highlightedHTML;
            }}

            // Apply existing annotations on page load
            applyAnnotations();

            // Get modal elements
            const modal = document.getElementById("annotationModal");
            const span = document.getElementsByClassName("close")[0];
            const cancelBtn = document.getElementById("cancelBtn");
            const submitBtn = document.getElementById("submitBtn");
            const annotationText = document.getElementById("annotationText");
            const addHighlightBtn = document.getElementById("addHighlightBtn");

            let currentSelection = null;

            /**
             * Function to get the selected text and its indices
             */
            function getSelectedTextIndices(element, range) {{
                let charCount = 0;
                let foundStart = false;
                let startIndex = 0;
                let endIndex = 0;

                function traverseNodes(node) {{
                    if (node === range.startContainer) {{
                        startIndex = charCount + range.startOffset;
                        foundStart = true;
                    }}
                    if (node.nodeType === Node.TEXT_NODE) {{
                        charCount += node.textContent.length;
                    }}
                    if (foundStart && node === range.endContainer) {{
                        endIndex = charCount + range.endOffset;
                        return true; // Stop traversal
                    }}
                    if (node.hasChildNodes()) {{
                        for (let i = 0; i < node.childNodes.length; i++) {{
                            if (traverseNodes(node.childNodes[i])) {{
                                return true; // Stop traversal
                            }}
                        }}
                    }}
                    return false;
                }}

                traverseNodes(element);
                return {{
                    selectedText: range.toString(),
                    startIndex: startIndex,
                    endIndex: endIndex
                }};
            }}

            /**
             * Function to position the Add Highlight button near the selection
             */
            function positionAddHighlightBtn(x, y) {{
                addHighlightBtn.style.left = x + "px";
                addHighlightBtn.style.top = y + "px";
                addHighlightBtn.style.display = "block";
            }}

            /**
             * Function to hide the Add Highlight button
             */
            function hideAddHighlightBtn() {{
                addHighlightBtn.style.display = "none";
            }}

            /**
             * Listen for mouseup events to detect text selection within #document-content
             */
            const documentContentDiv = document.getElementById("document-content");
            documentContentDiv.addEventListener('mouseup', function(event) {{
                const selection = window.getSelection();
                if (selection && selection.toString().trim() !== '') {{
                    const range = selection.getRangeAt(0);
                    currentSelection = getSelectedTextIndices(documentContentDiv, range);
                    if (currentSelection) {{
                        // Get the position of the selection
                        const rect = range.getBoundingClientRect();
                        const x = rect.right + window.scrollX;
                        const y = rect.top + window.scrollY - 40; // Adjust as needed
                        positionAddHighlightBtn(x, y);
                    }}
                }} else {{
                    currentSelection = null;
                    hideAddHighlightBtn();
                }}
            }});

            /**
             * When the user clicks on Add Highlight button
             */
            addHighlightBtn.onclick = function() {{
                if (!currentSelection) {{
                    alert('No text selected. Please select some text to highlight.');
                    return;
                }}
                console.log("Add Highlight button clicked.");
                // Open the modal
                modal.style.display = "block";
                annotationText.value = "";
                annotationText.focus();
                hideAddHighlightBtn();
            }}

            /**
             * When the user clicks on <span> (x), close the modal
             */
            span.onclick = function() {{
                console.log("Modal closed via close button.");
                modal.style.display = "none";
                currentSelection = null;
            }}

            /**
             * When the user clicks on cancel button, close the modal
             */
            cancelBtn.onclick = function() {{
                console.log("Modal closed via cancel button.");
                modal.style.display = "none";
                currentSelection = null;
            }}

            /**
             * When the user clicks anywhere outside of the modal, close it
             */
            window.onclick = function(event) {{
                if (event.target == modal) {{
                    console.log("Modal closed by clicking outside.");
                    modal.style.display = "none";
                    currentSelection = null;
                }}
            }}

            /**
             * When the user clicks on submit button, add the annotation (optional)
             */
            submitBtn.onclick = function() {{
                const annotation = annotationText.value.trim(); // Optional
                if (!currentSelection) {{
                    alert('No text selected to highlight. Please try again.');
                    return;
                }}

                console.log("Submitting highlight/annotation:", {{
                    "user_id": user_id,
                    "document_name": "{filename}",
                    "annotation": annotation, // Can be empty
                    "highlighted_text": currentSelection.selectedText,
                    "start_index": currentSelection.startIndex,
                    "end_index": currentSelection.endIndex,
                    "page_number": 1  // For TXT files, page number can be set to 1 or calculated if needed
                }});

                // Disable the submit button to prevent multiple submissions
                submitBtn.disabled = true;

                // Send the data to the backend
                fetch("{API_BASE_URL}/add_annotation", {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        "user_id": user_id,
                        "document_name": "{filename}",
                        "annotation": annotation, // Can be empty
                        "highlighted_text": currentSelection.selectedText,
                        "start_index": currentSelection.startIndex,
                        "end_index": currentSelection.endIndex,
                        "page_number": 1
                    }})
                }})
                .then(response => response.json())
                .then(data => {{
                    console.log("Received response:", data);
                    if (data.status === "success") {{
                        // Add the new highlight/annotation to the annotations array
                        annotations.push({{
                            "user_id": data.user_id,
                            "document_name": "{filename}",
                            "annotation": annotation,
                            "highlighted_text": currentSelection.selectedText,
                            "start_index": currentSelection.startIndex,
                            "end_index": currentSelection.endIndex,
                            "page_number": 1,
                            "timestamp": data.timestamp // From backend
                        }});

                        console.log("New highlight/annotation added:", data);

                        // Reapply annotations to display the new one
                        applyAnnotations();

                        // Close the modal
                        modal.style.display = "none";
                        currentSelection = null;
                    }} else {{
                        alert('Failed to add annotation: ' + data.message);
                    }}
                    submitBtn.disabled = false;
                }})
                .catch((error) => {{
                    console.error('Error adding annotation:', error);
                    alert('Error adding annotation: ' + error);
                    submitBtn.disabled = false;
                }});
            }};
        </script>
    </body>
    </html>
    """

    # Render the HTML with Streamlit
    st.components.v1.html(annotation_html, height=800, scrolling=True)

    # 5. Display Existing Annotations List
    st.markdown("---")

    # 6. Back Button to Return to "View Documents" Page
    if st.button("Back to Documents"):
        st.session_state.current_view = "Main"
        st.session_state.selected_document = None

# Home Page
if st.session_state.current_view == "Document Viewer":
    if st.session_state.selected_document:
        view_document_page(st.session_state.selected_document)
    else:
        st.error("No document selected to view.")
else:
    # Home Page
    if selection == "Home":
        home_page()


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

    # ---------------------------- View Documents Page ---------------------------- #
    elif selection == "Documents Control Panel":
        if not st.session_state.logged_in:
            st.warning("Please log in to manage your documents.")
        else:
            st.title("Documents Management")

            # ---------------------------- List Documents ---------------------------- #
            st.subheader("My Documents")
            try:
                response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")
                if response.headers.get('Content-Type') == 'application/json':
                    result = response.json()
                    if response.status_code == 200 and result.get("status") == "success":
                        documents = result.get("documents", [])
                        if documents:
                            # Display documents in a table
                            doc_df = pd.DataFrame(documents)
                            doc_df = doc_df.rename(columns={
                                "_id": "Document ID",
                                "doc_filename": "Filename",
                                "upload_date": "Upload Date",
                            })
                            doc_df = doc_df[["Document ID", "Filename", "Upload Date"]]
                            st.dataframe(doc_df)

                            # ---------------------------- Actions ---------------------------- #
                            st.markdown("---")
                            st.subheader("Actions")

                            # Select a document for actions
                            selected_doc_id = st.selectbox("Select Document ID for Actions", doc_df["Document ID"])

                            # Fetch the selected document's details
                            selected_document = next((doc for doc in documents if str(doc["_id"]) == selected_doc_id),
                                                     None)
                            if selected_document:
                                action = st.selectbox("Choose Action",
                                                      ["Delete Document", "Share with User", "Share with Team",
                                                       "Set Privacy"])

                                if action == "Delete Document":
                                    if st.button("Delete"):
                                        confirm = st.warning("Are you sure you want to delete this document?",
                                                             icon="⚠️")
                                        if st.button("Yes, Delete"):
                                            try:
                                                delete_resp = st.session_state.session.delete(
                                                    f"{API_BASE_URL}/documents/delete_document/{selected_doc_id}"
                                                )
                                                delete_result = delete_resp.json()
                                                if delete_resp.status_code == 200 and delete_result.get(
                                                        "status") == "success":
                                                    st.success(delete_result.get("message"))
                                                else:
                                                    st.error(delete_result.get("message", "Failed to delete document."))
                                            except Exception as e:
                                                st.error(f"An error occurred: {e}")

                                elif action == "Share with User":
                                    with st.form("share_user_form"):
                                        target_user_id = st.text_input("Enter User ID to Share With")
                                        submit_share_user = st.form_submit_button("Share with User")
                                    if submit_share_user:
                                        if not target_user_id:
                                            st.error("Please enter a valid User ID.")
                                        else:
                                            share_user_data = {
                                                "document_id": selected_doc_id,
                                                "target_user_id": target_user_id
                                            }
                                            try:
                                                share_user_resp = st.session_state.session.post(
                                                    f"{API_BASE_URL}/documents/share_document_with_user",
                                                    json=share_user_data
                                                )
                                                share_user_result = share_user_resp.json()
                                                if share_user_resp.status_code == 200 and share_user_result.get(
                                                        "status") == "success":
                                                    st.success(share_user_result.get("message"))
                                                else:
                                                    st.error(share_user_result.get("message",
                                                                                   "Failed to share document with user."))
                                            except Exception as e:
                                                st.error(f"An error occurred: {e}")

                                elif action == "Share with Team":
                                    with st.form("share_team_form"):
                                        target_team_id = st.text_input("Enter Team ID to Share With")
                                        submit_share_team = st.form_submit_button("Share with Team")
                                    if submit_share_team:
                                        if not target_team_id:
                                            st.error("Please enter a valid Team ID.")
                                        else:
                                            share_team_data = {
                                                "document_id": selected_doc_id,
                                                "team_id": target_team_id
                                            }
                                            try:
                                                share_team_resp = st.session_state.session.post(
                                                    f"{API_BASE_URL}/documents/share_document_with_team",
                                                    json=share_team_data
                                                )
                                                share_team_result = share_team_resp.json()
                                                if share_team_resp.status_code == 200 and share_team_result.get(
                                                        "status") == "success":
                                                    st.success(share_team_result.get("message"))
                                                else:
                                                    st.error(share_team_result.get("message",
                                                                                   "Failed to share document with team."))
                                            except Exception as e:
                                                st.error(f"An error occurred: {e}")

                                elif action == "Set Privacy":
                                    with st.form("set_privacy_form"):
                                        current_privacy = selected_document.get("is_private", False)
                                        new_privacy = st.selectbox("Select Privacy Status", ["Private", "Public"],
                                                                   index=0 if not current_privacy else 1)
                                        submit_set_privacy = st.form_submit_button("Set Privacy")
                                    if submit_set_privacy:
                                        is_private = True if new_privacy == "Private" else False
                                        try:
                                            set_privacy_resp = st.session_state.session.put(
                                                f"{API_BASE_URL}/documents/set_document_privacy/{selected_doc_id}",
                                                json={"is_private": is_private}
                                            )
                                            set_privacy_result = set_privacy_resp.json()
                                            if set_privacy_resp.status_code == 200 and set_privacy_result.get(
                                                    "status") == "success":
                                                st.success(set_privacy_result.get("message"))
                                            else:
                                                st.error(set_privacy_result.get("message",
                                                                                "Failed to set document privacy."))
                                        except Exception as e:
                                            st.error(f"An error occurred: {e}")
                            else:
                                st.error("Selected document not found.")
                    else:
                        st.error("Received an invalid response from the server.")
                        st.write("**Response Status Code:**", response.status_code)
                        st.write("**Response Content:**", response.text)
                        st.stop()
            except requests.exceptions.ConnectionError:
                st.error("Could not connect to the server. Please ensure the backend is running.")
            except Exception as e:
                st.error(f"An error occurred: {e}")




    # ---------------------------- View Documents Page ---------------------------- #
    elif selection == "View Documents":
        st.title("View Documents")

        # ---------------------------- List Folders ---------------------------- #
        st.subheader("Folders and Subfolders")

        # Get documents from the backend
        try:
            response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    documents = result.get("documents", [])

                    # Create folder structure
                    folders = {}
                    for doc in documents:
                        folder_path = doc.get("folder", "")
                        if folder_path:
                            parts = folder_path.split('/')
                            top_level_folder = parts[0]
                            subfolder = parts[1] if len(parts) > 1 else None

                            if top_level_folder not in folders:
                                folders[top_level_folder] = {"subfolders": {}, "files": []}

                            if subfolder:
                                if subfolder not in folders[top_level_folder]["subfolders"]:
                                    folders[top_level_folder]["subfolders"][subfolder] = []
                                folders[top_level_folder]["subfolders"][subfolder].append(doc)
                            else:
                                folders[top_level_folder]["files"].append(doc)


                    # Function to render files with highlighting
                    def render_files(files, key_prefix):
                        for file in files:
                            file_name = file.get("doc_filename")
                            unique_key = file.get("_id")  # Use the _id as the unique key
                            is_selected = st.session_state.selected_document and st.session_state.selected_document.get(
                                "_id") == unique_key

                            # Render the button
                            if st.button(f"📄 {file_name}", key=f"{key_prefix}_{unique_key}"):
                                # When file is clicked, set it as selected
                                st.session_state.selected_document = file
                                st.session_state.current_view = "Document Viewer"

                            # Apply highlighting if selected
                            if is_selected:
                                st.markdown(
                                    f"<div style='background-color: #d3d3d3; padding: 5px; border-radius: 5px; margin-top: -35px; margin-bottom: 15px;'>📄 {file_name}</div>",
                                    unsafe_allow_html=True
                                )


                    # Display top-level folders
                    for folder_name, folder_data in folders.items():
                        with st.expander(f"📂 {folder_name}"):
                            # Show files in this folder
                            if folder_data["files"]:
                                st.markdown("### Files:")
                                render_files(folder_data["files"], f"file_{folder_name}")
                            else:
                                st.info(f"No files found in {folder_name}")

                            # Show subfolders in this folder
                            if folder_data["subfolders"]:
                                subfolder_selection = st.selectbox(
                                    f"Select Subfolder in {folder_name}",
                                    ["-- Select Subfolder --"] + list(folder_data["subfolders"].keys()),
                                    key=f"select_{folder_name}"
                                )
                                if subfolder_selection != "-- Select Subfolder --":
                                    subfolder_files = folder_data["subfolders"][subfolder_selection]
                                    st.markdown(f"### Files in {subfolder_selection} Subfolder:")
                                    render_files(subfolder_files, f"subfolder_file_{subfolder_selection}")

                else:
                    st.error("Failed to fetch documents from the server.")
            else:
                st.error(f"Failed to fetch documents. Status code: {response.status_code}")

        except requests.exceptions.ConnectionError:
            st.error("Could not connect to the server. Please ensure the backend is running.")
        except Exception as e:
            st.error(f"An error occurred: {e}")

    # ---------------------------- Document Viewer ---------------------------- #
    if st.session_state.current_view == "Document Viewer":
        selected_doc = st.session_state.selected_document
        if selected_doc:
            st.title(f"Viewing Document: {selected_doc.get('doc_filename')}")
            # Add your document viewing logic here
            st.write(selected_doc)
        else:
            st.warning("No document selected.")





    elif selection == "Search Documents":
        if not st.session_state.logged_in:
            st.warning("Please log in to search documents.")
        else:
            st.title("Search Documents")

            # 1) Let the lawyer select their role for classification matching
            #    If you want to be more general, rename "Lawyer Role" -> "Which side are you representing?"
            role_options = ["Defense", "State", "Plaintiff", "Petitioner"]
            user_role = st.selectbox("Select Your Role", role_options, index=0)

            with st.form("search_form"):
                query = st.text_input("Enter your search query")
                top_k = st.number_input("Number of top results", min_value=1, max_value=1000, value=100)
                submit_button = st.form_submit_button("Search")

            if submit_button:
                if not query:
                    st.error("Please enter a search query.")
                else:
                    search_data = {"query": query, "top_k": int(top_k)}

                    # 2) Attempt the search
                    with st.spinner("Searching documents..."):
                        try:
                            response = st.session_state.session.post(
                                f"{API_BASE_URL}/search_docs",
                                json=search_data
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
                                    # 3) Load the classification data from Excel
                                    excel_path = "classified_results.xlsx"
                                    if not os.path.exists(excel_path):
                                        st.error(
                                            f"Classification Excel '{excel_path}' not found. "
                                            "Please ensure it exists."
                                        )
                                        st.stop()

                                    df_class = pd.read_excel(excel_path)
                                    classification_data = {}
                                    for idx, row in df_class.iterrows():
                                        fname = str(row["Filename"]).strip()
                                        raw_class = str(row["Classification"]).lower()
                                        # e.g. "case_type: criminal, winner: defense"
                                        # We'll parse the substring after "winner: "
                                        # or default to "unknown"
                                        winner = "unknown"
                                        if "winner:" in raw_class:
                                            try:
                                                # e.g. "case_type: civil, winner: plaintiff"
                                                winner_part = raw_class.split("winner:")[1]
                                                # " plaintiff"
                                                winner = winner_part.strip().split(",")[0].split()[0]
                                                # e.g. "plaintiff"
                                            except:
                                                pass

                                        classification_data[fname] = winner
                                    grouped_results = defaultdict(list)
                                    for doc in results:
                                        try:
                                            filename = doc.get("filename")
                                        except:
                                            filename = ""
                                        try:
                                            similarity = doc.get("similarity")
                                        except:
                                            similarity = 0
                                        try:
                                            summary = doc.get("summary", {}).get("answer")
                                        except:
                                            summary = "No summary available."


                                        grouped_results[filename].append({
                                            "similarity": similarity,
                                            "summary": summary
                                        })

                                    # 4) Separate the search results into two groups
                                    in_favor_results = []
                                    not_in_favor_results = []

                                    user_role_lower = user_role.lower()

                                    unique_results = []
                                    for filename, docs in grouped_results.items():
                                        # Sort the chunks by similarity in descending order
                                        sorted_docs = sorted(docs, key=lambda x: x["similarity"], reverse=True)
                                        top_doc = sorted_docs[0]  # Select the chunk with highest similarity
                                        unique_results.append({
                                            "filename": filename,
                                            "similarity": top_doc["similarity"],
                                            "summary": top_doc["summary"]
                                        })

                                    # 5) Classify the unique results into 'In Favor' and 'Not in Favor'
                                    in_favor_results = []
                                    not_in_favor_results = []

                                    for doc in unique_results:
                                        filename = doc.get("filename", "")
                                        # If the classification is unknown or not present, treat it as 'not in favor'
                                        doc_winner = classification_data.get(filename, "unknown")

                                        if doc_winner == user_role_lower:
                                            in_favor_results.append(doc)
                                        else:
                                            not_in_favor_results.append(doc)

                                    # 6) Inject local CSS to adjust tooltip styles
                                    st.markdown("""
                                    <style>
                                    /* Adjust tooltip width and positioning to prevent overlapping */
                                    .tooltip .tooltiptext {
                                        width: 600px; /* Reduced width from 600px to 300px */
                                        left: 0;      /* Align tooltip to the left */
                                        margin-left: 0; /* Remove negative margin */
                                        white-space: pre-wrap; /* Allow text to wrap within tooltip */
                                        word-wrap: break-word; /* Break long words */
                                    }
                                    </style>
                                    """, unsafe_allow_html=True)

                                    # 7) Display the results in two columns
                                    col1, col2 = st.columns(2)

                                    with col1:
                                        st.subheader("In Favor")
                                        if in_favor_results:
                                            for doc in in_favor_results:
                                                filename = doc.get("filename")
                                                similarity = doc.get("similarity")

                                                summary_obj = doc.get("summary", {})
                                                if isinstance(summary_obj, str):
                                                    tooltip_content = summary_obj
                                                else:
                                                    tooltip_content = summary_obj.get("answer") or summary_obj.get(
                                                        "message", "No summary available.")

                                                # Use existing tooltip classes without inline styles
                                                display_filename = (filename[:45] + '...') if len(
                                                    filename) > 30 else filename

                                                tooltip_html = f"""
                                                <div class="tooltip">{display_filename}
                                                    <span class="tooltiptext">{tooltip_content}</span>
                                                </div>
                                                """
                                                st.markdown(tooltip_html, unsafe_allow_html=True)
                                                st.write(f"Similarity: {similarity}%")

                                                # Pre-signed URL logic if needed
                                                s3_key = f"documents/{filename}"
                                                url_resp = st.session_state.session.post(
                                                    f"{API_BASE_URL}/generate_presigned_url",
                                                    json={"object_key": s3_key}
                                                )
                                                if url_resp.status_code == 200:
                                                    presigned_url = url_resp.json().get("url")
                                                    st.markdown(
                                                        f'<a href="{presigned_url}" target="_blank">View Document</a>',
                                                        unsafe_allow_html=True
                                                    )
                                                else:
                                                    st.error("Failed to generate a pre-signed URL for the document.")
                                                st.markdown("---")
                                        else:
                                            st.info("No results in favor.")

                                    with col2:
                                        st.subheader("Not in Favor")
                                        if not_in_favor_results:
                                            for doc in not_in_favor_results:
                                                filename = doc.get("filename")
                                                similarity = doc.get("similarity")

                                                summary_obj = doc.get("summary", {})
                                                if isinstance(summary_obj, str):
                                                    tooltip_content = summary_obj
                                                else:
                                                    tooltip_content = summary_obj.get("answer") or summary_obj.get(
                                                        "message", "No summary available.")

                                                # Use existing tooltip classes without inline styles
                                                tooltip_html = f"""
                                                <div class="tooltip">{filename}
                                                    <span class="tooltiptext">{tooltip_content}</span>
                                                </div>
                                                """
                                                st.markdown(tooltip_html, unsafe_allow_html=True)
                                                st.write(f"Similarity: {similarity}%")

                                                # Pre-signed URL logic if needed
                                                s3_key = f"documents/{filename}"
                                                url_resp = st.session_state.session.post(
                                                    f"{API_BASE_URL}/generate_presigned_url",
                                                    json={"object_key": s3_key}
                                                )
                                                if url_resp.status_code == 200:
                                                    presigned_url = url_resp.json().get("url")
                                                    st.markdown(
                                                        f'<a href="{presigned_url}" target="_blank">View Document</a>',
                                                        unsafe_allow_html=True
                                                    )
                                                else:
                                                    st.error("Failed to generate a pre-signed URL for the document.")
                                                st.markdown("---")
                                        else:
                                            st.info("No results not in favor.")
                            else:
                                st.error(result.get("message"))
                        except requests.exceptions.ConnectionError:
                            st.error("Could not connect to the server. Please ensure the backend is running.")
                        except Exception as e:
                            st.error(f"An unexpected error occurred: {e}")





    elif selection == "Chat":

        if not st.session_state.logged_in:

            st.warning("Please log in to access chat functionality.")

        else:

            st.title("Chat with LegalKare")

            # ---------------------------- Prompt Selection ---------------------------- #

            st.subheader("Select a Prompt")

            # Dropdown to select prompt type

            prompt_type = st.selectbox(

                "Select Prompt Type",

                ["Default", "Private", "Public"],

                index=0

            )

            # Fetch prompts from the backend

            with st.spinner("Fetching prompts..."):

                try:

                    # Pass 'type' as a query parameter to fetch specific prompts

                    response = st.session_state.session.get(f"{API_BASE_URL}/get_prompts",

                                                            params={"type": prompt_type.lower()})

                    if response.status_code == 200:

                        prompts_data = response.json()  # This should be a list

                        if isinstance(prompts_data, list):  # Check if it's a list

                            prompts = prompts_data  # Directly assign the list to prompts

                        else:

                            st.error("Unexpected response format.")

                            prompts = []

                    else:

                        st.error("Failed to fetch prompts from the server.")

                        prompts = []

                except Exception as e:

                    st.error(f"An error occurred while fetching prompts: {e}")

                    prompts = []

            if prompts:

                prompt_titles = [f"{p['title']} (ID: {p['prompt_id']})" for p in prompts]

                selected_prompt = st.selectbox("Select a Prompt", prompt_titles)

                # Retrieve the selected prompt's content

                selected_prompt_obj = next(

                    (p for p in prompts if f"{p['title']} (ID: {p['prompt_id']})" == selected_prompt), None)

                if selected_prompt_obj:
                    st.markdown(f"**Prompt Content:** {selected_prompt_obj.get('content')}")

            else:

                st.info(f"No prompts available for type '{prompt_type}'.")

            # ---------------------------- Use Prompt in Chat ---------------------------- #

            if prompts:

                use_prompt = st.checkbox("Use this prompt in chat")

                if use_prompt and selected_prompt_obj:
                    # Prefill the existing chat input with the selected prompt content

                    prompt_content = selected_prompt_obj.get("content")

                    # Modify the existing chat input field (chat_query) to prefill with the prompt content

                    chat_query = st.session_state.get("chat_input", "")  # Get the current chat input if exists

                    chat_query = st.text_input("Please change the content if needed", value=prompt_content)

                    # Store the input in session state to persist it between reruns

                    st.session_state.chat_input = chat_query  # Update the session state with the new chat input

            # ---------------------------- Add Custom Prompt ---------------------------- #

            st.markdown("---")

            st.subheader("Add a New Custom Prompt")

            add_prompt_button = st.button("Add New Prompt")
            if add_prompt_button:
                # Display the form when the button is clicked
                with st.form("add_prompt_form"):
                    prompt_title = st.text_input("Prompt Title")
                    prompt_description = st.text_area("Prompt Description")
                    prompt_content = st.text_area("Prompt Content")
                    submit_add_prompt = st.form_submit_button("Add Prompt")

                # Process the form submission
                if submit_add_prompt:
                    if not prompt_title.strip() or not prompt_content.strip():
                        st.error("Please provide both a title and content for the prompt.")
                    else:
                        add_prompt_data = {
                            "type_of_prompt": "Private",  # Assuming users can only add private prompts
                            "title": prompt_title.strip(),
                            "description": prompt_description.strip(),
                            "content": prompt_content.strip()
                        }
                        try:
                            add_prompt_resp = st.session_state.session.post(
                                f"{API_BASE_URL}/add_prompt",
                                json=add_prompt_data
                            )
                            if add_prompt_resp.status_code == 201:
                                add_prompt_result = add_prompt_resp.json()
                                if add_prompt_result.get("status") == "success":
                                    st.success(
                                        f"Prompt added successfully with ID: {add_prompt_result.get('prompt')['prompt_id']}")
                                else:
                                    st.error(add_prompt_result.get("message", "Failed to add prompt."))
                            else:
                                try:
                                    error_message = add_prompt_resp.json().get("message", "Failed to add prompt.")
                                except:
                                    error_message = "Failed to add prompt."
                                st.error(error_message)
                        except Exception as e:
                            st.error(f"An error occurred while adding the prompt: {e}")

            # ---------------------------- Existing Chat Functionality ---------------------------- #

            # Initialize chat_history and add default message if empty

            if not st.session_state.chat_history:
                st.session_state.chat_history.append({

                    "role": "assistant",

                    "content": f"Hello! I'm {BOT_NAME}, your legal assistant. How can I help you today?"

                })

            # Fetch user's documents for selection

            try:

                response = st.session_state.session.get(f"{API_BASE_URL}/my_documents")

                if response.headers.get('Content-Type') == 'application/json':

                    result = response.json()

                    if response.status_code == 200 and result.get("status") == "success":

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

                else:

                    st.error("Received an invalid response from the server.")

                    st.write("**Response Status Code:**", response.status_code)

                    st.write("**Response Content:**", response.text)

                    st.stop()

            except requests.exceptions.ConnectionError:

                st.error("Could not connect to the server. Please ensure the backend is running.")

                selected_doc = None

            except Exception as e:

                st.error(f"An error occurred: {e}")

                selected_doc = None

            # ---------------------------- Chat Input ---------------------------- #

            chat_query = st.text_input("Enter your question or query", key="chat_input")
            st.write(f"Selected doc: {selected_doc!r}")

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

                            if chat_response.status_code == 200:

                                chat_result = chat_response.json()

                                if chat_result.get("status") == "success":

                                    assistant_reply = chat_result.get("answer", "")

                                    st.session_state.chat_history.append({

                                        "role": "assistant",

                                        "content": assistant_reply

                                    })

                                else:

                                    st.error(
                                        chat_result.get("message", "An error occurred while generating the response."))

                            else:

                                try:

                                    error_message = chat_response.json().get("message", "Failed to generate response.")

                                except:

                                    error_message = "Failed to generate response."

                                st.error(error_message)

                        except Exception as e:

                            st.error(f"An error occurred: {e}")

            # ---------------------------- Display Conversation History ---------------------------- #

            st.subheader("Conversation History")

            if st.session_state.chat_history:

                for msg in st.session_state.chat_history:

                    if msg["role"] == "user":

                        st.markdown(f"**You:** {msg['content']}")

                    else:

                        st.markdown(f"**{BOT_NAME}:** {msg['content']}")

            else:

                st.info("No conversation yet. Type something above.")

            # ---------------------------- Download Conversation ---------------------------- #

            if st.session_state.chat_history:

                # Convert chat to a single string

                chat_text = []

                for entry in st.session_state.chat_history:
                    role = "You" if entry["role"] == "user" else BOT_NAME

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




    elif selection == "Teams":
        if not st.session_state.logged_in:
            st.warning("Please log in to manage your teams.")
        else:
            st.title("Teams Management")
            # ---------------------------- Create Team ---------------------------- #
            st.subheader("Create a New Team")
            with st.form("create_team_form"):
                team_name = st.text_input("Team Name", placeholder="e.g., Legal Team A")
                member_user_ids = st.text_area(
                    "Add Members (Enter User IDs separated by commas)",
                    placeholder="UID0001, UID0002"
                )
                submit_create_team = st.form_submit_button("Create Team")
            if submit_create_team:
                if not team_name.strip():
                    st.error("Please enter a valid team name.")
                else:
                    # Parse member_user_ids
                    member_ids = [uid.strip() for uid in member_user_ids.split(",") if uid.strip()]
                    if not member_ids:
                        st.error("Please enter at least one member User ID.")
                    else:
                        create_team_data = {
                            "team_name": team_name.strip(),
                            "member_user_ids": member_ids
                        }
                        try:
                            create_team_resp = st.session_state.session.post(
                                f"{API_BASE_URL}/documents/create_team",
                                json=create_team_data
                            )
                            create_team_result = create_team_resp.json()
                            if create_team_resp.status_code == 201 and create_team_result.get("status") == "success":
                                st.success(create_team_result.get("message"))
                                st.info(f"New Team ID: {create_team_result.get('team_id')}")
                            else:
                                st.error(create_team_result.get("message", "Failed to create team."))
                        except Exception as e:
                            st.error(f"An error occurred: {e}")
            st.markdown("---")
            # ---------------------------- List Teams ---------------------------- #
            st.subheader("My Teams")
            try:
                response = st.session_state.session.get(f"{API_BASE_URL}/documents/get_teams")
                if response.headers.get('Content-Type') == 'application/json':
                    result = response.json()
                    if response.status_code == 200 and result.get("status") == "success":
                        teams = result.get("teams", [])
                        if teams:
                            # Display teams in a table
                            team_df = pd.DataFrame(teams)
                            # Rename columns for better readability
                            team_df = team_df.rename(columns={
                                "team_id": "Team ID",
                                "team_name": "Team Name",
                                "created_at": "Created At",
                                "created_by": "Created By",
                                "members": "Member IDs"
                            })
                            # Display only relevant columns
                            display_columns = ["Team ID", "Team Name", "Created At", "Created By"]
                            st.dataframe(team_df[display_columns].sort_values(by="Created At", ascending=False))
                            # ---------------------------- Actions ---------------------------- #
                            st.markdown("---")
                            st.subheader("Actions")
                            # Select a team for actions
                            selected_team_id = st.selectbox("Select Team ID for Actions", team_df["Team ID"])
                            # Fetch the selected team's details
                            selected_team = next((team for team in teams if team["team_id"] == selected_team_id), None)
                            if selected_team:
                                team_action = st.selectbox("Choose Action", ["View Team", "Add Team Member"])
                                if team_action == "View Team":
                                    if st.button("View Team Details"):
                                        st.session_state.selected_team = selected_team
                                        st.session_state.current_view = "Team Details"

                                elif team_action == "Add Team Member":
                                    with st.form("add_member_form"):
                                        new_member_id = st.text_input("Enter User ID to Add")
                                        submit_add_member = st.form_submit_button("Add Member")
                                    if submit_add_member:
                                        if not new_member_id.strip():
                                            st.error("Please enter a valid User ID.")
                                        else:
                                            add_member_data = {
                                                "team_id": selected_team_id,
                                                "member_user_id": new_member_id.strip()
                                            }
                                            try:
                                                add_member_resp = st.session_state.session.post(
                                                    f"{API_BASE_URL}/documents/add_team_member",
                                                    json=add_member_data
                                                )
                                                add_member_result = add_member_resp.json()
                                                if add_member_resp.status_code == 200 and add_member_result.get(
                                                        "status") == "success":
                                                    st.success(add_member_result.get("message"))
                                                else:
                                                    st.error(
                                                        add_member_result.get("message", "Failed to add team member."))
                                            except Exception as e:
                                                st.error(f"An error occurred: {e}")
                            else:
                                st.error("Selected team not found.")
                    else:
                        st.error(result.get("message", "Failed to fetch teams."))
                else:
                    st.error("Received an invalid response from the server.")
                    st.write("**Response Status Code:**", response.status_code)
                    st.write("**Response Content:**", response.text)
                    st.stop()
            except requests.exceptions.ConnectionError:
                st.error("Could not connect to the server. Please ensure the backend is running.")
            except Exception as e:
                st.error(f"An error occurred while fetching teams: {e}")
            # ---------------------------- Team Details Page ---------------------------- #
            if st.session_state.current_view == "Team Details":
                team = st.session_state.selected_team
                if team:
                    st.markdown("---")
                    st.subheader(f"Team Details: {team.get('team_name')} ({team.get('team_id')})")
                    st.write(f"**Created By:** {team.get('created_by')}")
                    st.write(f"**Created At:** {team.get('created_at')}")
                    # Fetch team members' details
                    member_ids = team.get("members", [])
                    if member_ids:
                        try:
                            members_resp = st.session_state.session.get(
                                f"{API_BASE_URL}/documents/get_team_members",
                                params={"team_id": team.get("team_id")}
                            )
                            if members_resp.headers.get('Content-Type') == 'application/json':
                                members_result = members_resp.json()
                                if members_resp.status_code == 200 and members_result.get("status") == "success":
                                    members = members_result.get("members", [])
                                    if members:
                                        st.markdown("### Team Members")
                                        for member in members:
                                            member_col1, member_col2 = st.columns([1, 3])
                                            with member_col1:
                                                # Display member's profile picture
                                                if member.get("profile_picture_url"):
                                                    user_id = member["user_id"]
                                                    profile_url_response = st.session_state.session.get(f"{API_BASE_URL}/get_team_member_profile_picture?user_id={user_id}")
                                                    if profile_url_response.headers.get('Content-Type') == 'application/json':
                                                        profile_result = profile_url_response.json()
                                                    if profile_result:
                                                        profile_picture_url = profile_result.get("url", "")
                                                        st.image(
                                                            profile_picture_url,
                                                            width=100,
                                                            caption=member.get("name"),
                                                            use_container_width=True
                                                        )
                                                    else:
                                                        st.image(
                                                            "https://via.placeholder.com/100",
                                                            width=100,
                                                            caption=member.get("name"),
                                                            use_container_width=True
                                                        )
                                            with member_col2:

                                                st.markdown(f"**Name:** {member.get('name')}")

                                                st.markdown(f"**User ID:** {member.get('user_id')}")

                                                st.markdown(f"**Email:** {member.get('email')}")

                                                st.markdown(f"**Role:** {member.get('role', '').capitalize()}")

                                                st.markdown("---")

                                    else:

                                        st.info("No members found in this team.")

                                else:

                                    st.error(members_result.get("message", "Failed to fetch team members."))

                            else:

                                st.error("Received an invalid response from the server while fetching team members.")

                                st.write("**Response Status Code:**", members_resp.status_code)

                                st.write("**Response Content:**", members_resp.text)

                                st.stop()

                        except requests.exceptions.ConnectionError:

                            st.error("Could not connect to the server while fetching team members.")

                        except Exception as e:

                            st.error(f"An error occurred while fetching team members: {e}")

                    else:

                        st.info("No members in this team.")

                    # Option to go back to Teams list

                    if st.button("Back to Teams"):
                        st.session_state.current_view = "Teams"

                        st.session_state.selected_team = None

                else:

                    st.error("Team details not found.")

                    if st.button("Back to Teams"):
                        st.session_state.current_view = "Teams"

                        st.session_state.selected_team = None


    elif selection == "Notifications":

        if not st.session_state.get('logged_in', False):

            st.warning("Please log in to view notifications.")

        else:

            st.title("Notifications")

            user_id = st.session_state.get('user_id')  # Ensure 'user_id' is set in session_state

            if not user_id:

                st.error("User ID not found in session. Please log in again.")

            else:

                with st.spinner("Fetching your notifications..."):

                    try:

                        # Fetch notifications from the backend

                        response = st.session_state.session.get(

                            f"{API_BASE_URL}/notifications",

                            # If using token-based auth, include headers

                            # headers={"Authorization": f"Bearer {st.session_state.get('token')}"}

                        )

                        try:

                            result = response.json()

                        except ValueError:

                            st.error("Received an invalid response from the server.")

                            st.write("**Response Status Code:**", response.status_code)

                            st.write("**Response Content:**", response.text)

                            st.stop()

                        if response.status_code == 200 and result.get("status") == "success":

                            notifications = result.get("notifications", [])

                            if notifications:

                                # Display notifications

                                st.markdown("## Team Invitations")

                                for notif in notifications:

                                    st.markdown("---")

                                    st.markdown(f"### Team Name: {notif['team_name']}")

                                    st.write(f"**Team ID:** {notif['team_id']}")

                                    st.write(f"**Invited By:** {notif['invited_by']}")

                                    st.write(f"**Invited At:** {notif['invited_at']}")

                                    # Action Buttons: Join or Exit

                                    action = st.radio(

                                        label="Choose Action",

                                        options=["Select Action", "Join Team", "Exit Team"],

                                        key=f"action_radio_{notif['notification_id']}",

                                        horizontal=True

                                    )

                                    if action == "Join Team":

                                        if st.button("Confirm Join", key=f"join_button_{notif['notification_id']}"):

                                            with st.spinner("Joining the team..."):

                                                try:

                                                    respond_data = {

                                                        "notification_id": notif['notification_id'],

                                                        "response": "join"

                                                    }

                                                    respond_resp = st.session_state.session.post(

                                                        f"{API_BASE_URL}/notifications/respond",

                                                        json=respond_data

                                                        # If using token-based auth, include headers

                                                        # headers={"Authorization": f"Bearer {st.session_state.get('token')}"}

                                                    )

                                                    try:

                                                        respond_result = respond_resp.json()

                                                    except ValueError:

                                                        st.error("Received an invalid response from the server.")

                                                        st.write("**Response Status Code:**", respond_resp.status_code)

                                                        st.write("**Response Content:**", respond_resp.text)

                                                        st.stop()

                                                    if respond_resp.status_code == 200 and respond_result.get(
                                                            "status") == "success":

                                                        st.success(respond_result.get("message",
                                                                                      "Successfully joined the team."))

                                                          # Refresh notifications

                                                    else:

                                                        st.error(
                                                            respond_result.get("message", "Failed to join the team."))

                                                except Exception as e:

                                                    st.error(f"An error occurred: {e}")


                                    elif action == "Exit Team":

                                        if st.button("Confirm Exit", key=f"exit_button_{notif['notification_id']}"):

                                            with st.spinner("Exiting the team..."):

                                                try:

                                                    respond_data = {

                                                        "notification_id": notif['notification_id'],

                                                        "response": "exit"

                                                    }

                                                    respond_resp = st.session_state.session.post(

                                                        f"{API_BASE_URL}/notifications/respond",

                                                        json=respond_data

                                                        # If using token-based auth, include headers

                                                        # headers={"Authorization": f"Bearer {st.session_state.get('token')}"}

                                                    )

                                                    try:

                                                        respond_result = respond_resp.json()

                                                    except ValueError:

                                                        st.error("Received an invalid response from the server.")

                                                        st.write("**Response Status Code:**", respond_resp.status_code)

                                                        st.write("**Response Content:**", respond_resp.text)

                                                        st.stop()

                                                    if respond_resp.status_code == 200 and respond_result.get(
                                                            "status") == "success":

                                                        st.success(respond_result.get("message",
                                                                                      "Successfully exited the team."))

                                                          # Refresh notifications

                                                    else:

                                                        st.error(
                                                            respond_result.get("message", "Failed to exit the team."))

                                                except Exception as e:

                                                    st.error(f"An error occurred: {e}")

                            else:

                                st.info("You have no new notifications.")

                        else:

                            st.error(result.get("message", "Failed to fetch notifications."))

                    except requests.exceptions.ConnectionError:

                        st.error("Could not connect to the server. Please ensure the backend is running.")

                    except Exception as e:

                        st.error(f"An error occurred while fetching notifications: {e}")



    elif selection == "Book Appointment":

        # 1) Check login & role

        if not st.session_state.logged_in:

            st.warning("Please log in to book appointments.")

            st.stop()

        elif st.session_state.role != "client":

            st.error("Only clients can book appointments.")

            st.stop()

        st.title("Book an Appointment")

        # 2) Maintain session state for selected lawyer & cached list

        if "selected_lawyer_id" not in st.session_state:
            st.session_state.selected_lawyer_id = None

        if "lawyers_cache" not in st.session_state:
            st.session_state.lawyers_cache = []

        # 3) If no lawyer is selected, show the "case details" or "view all" interface

        if st.session_state.selected_lawyer_id is None:

            st.subheader("Find a Lawyer")

            # --- Text area for user’s case details (the "query") ---

            case_details = st.text_area(

                "Describe your case (optional if you just want to see all lawyers)",

                help="Type your case details to get lawyer recommendations."

            )

            # --- Buttons ---

            colA, colB = st.columns(2)

            with colA:

                recommend_clicked = st.button("Recommend a Lawyer")

            with colB:

                view_all_clicked = st.button("View All Lawyers")

            # --- Logic to clear or populate st.session_state.lawyers_cache ---

            # If neither button was clicked, we clear or skip showing lawyers:

            if not recommend_clicked and not view_all_clicked:

                # We don't show any lawyers yet. Possibly clear existing cache if you want a fresh start:

                # st.session_state.lawyers_cache = []

                # st.write("Please either enter a case query or click 'View All Lawyers'.")

                pass

            else:

                # If "Recommend a Lawyer" is clicked:

                if recommend_clicked:

                    if not case_details.strip():

                        st.warning("Please enter some case details before requesting recommendations.")

                    else:

                        try:

                            response = st.session_state.session.post(

                                f"{API_BASE_URL}/recommend_lawyer",

                                json={"case_details": case_details}

                            )

                            result = response.json()

                            if response.status_code == 200 and result.get("status") == "success":

                                st.session_state.lawyers_cache = result.get("recommendations", [])

                                if not st.session_state.lawyers_cache:

                                    st.warning("No relevant lawyers found for your query.")

                                else:

                                    st.success("Showing recommended lawyers based on your case details.")

                            else:

                                st.error(result.get("message", "Failed to get recommendations."))

                        except Exception as e:

                            st.error(f"An error occurred while recommending a lawyer: {e}")

                # If "View All Lawyers" is clicked:

                if view_all_clicked:

                    try:

                        response = st.session_state.session.get(f"{API_BASE_URL}/profile/list_lawyers")

                        result = response.json()

                        if response.status_code == 200 and result.get("status") == "success":

                            st.session_state.lawyers_cache = result.get("lawyers", [])

                        else:

                            st.error(result.get("message", "Failed to fetch lawyers."))

                    except Exception as e:

                        st.error(f"An error occurred while fetching lawyers: {e}")

            # --- Now display the lawyers in the cache (if any) ---

            lawyers = st.session_state.lawyers_cache

            if lawyers:

                import math

                num_cols = 3

                total_lawyers = len(lawyers)

                rows_needed = math.ceil(total_lawyers / num_cols)

                st.write(f"**Showing {total_lawyers} lawyer(s).**")

                for row_idx in range(rows_needed):

                    cols = st.columns(num_cols, gap="large")

                    for col_idx in range(num_cols):

                        index = row_idx * num_cols + col_idx

                        if index < total_lawyers:

                            lawyer = lawyers[index]

                            with cols[col_idx]:

                                # Show lawyer's picture

                                pic_url = lawyer.get("profile_picture_url")

                                if pic_url:

                                    st.image(pic_url, use_column_width=True)

                                else:

                                    st.image("https://via.placeholder.com/150", use_column_width=True)

                                st.write(f"**Name:** {lawyer.get('name')}")

                                st.write(f"**Location:** {lawyer.get('location', 'N/A')}")

                                st.write(f"**Specialization:** {lawyer.get('specialization', 'N/A')}")

                                st.write(f"**Experience:** {lawyer.get('years_of_experience', 0)} years")

                                # Use lawyer["lawyer_id"] if your backend returns "lawyer_id"

                                lawyer_id = lawyer.get("lawyer_id")

                                if not lawyer_id:

                                    st.warning("This lawyer record has no 'lawyer_id'.")

                                else:

                                    if st.button(f"View Details {lawyer_id}", key=f"view_{lawyer_id}"):
                                        st.session_state.selected_lawyer_id = lawyer_id

                                        st.experimental_rerun()


        else:

            # 4) If a lawyer is selected, show detail view & booking form

            selected_lawyer_id = st.session_state.selected_lawyer_id

            lawyers = st.session_state.lawyers_cache

            selected_lawyer = next((lw for lw in lawyers if lw.get("lawyer_id") == selected_lawyer_id), None)

            if not selected_lawyer:

                st.error("Selected lawyer not found. Please go back and choose again.")

                if st.button("Back to List"):
                    st.session_state.selected_lawyer_id = None

                st.stop()

            st.subheader(f"Lawyer Details: {selected_lawyer.get('name')}")

            detail_col1, detail_col2 = st.columns([1, 2])

            with detail_col1:

                pic_url = selected_lawyer.get("profile_picture_url")

                if pic_url:

                    st.image(pic_url, use_column_width=True)

                else:

                    st.image("https://via.placeholder.com/150", use_column_width=True)

            with detail_col2:

                st.write(f"**Name:** {selected_lawyer.get('name')}")

                st.write(f"**Location:** {selected_lawyer.get('location', 'N/A')}")

                st.write(f"**Specialization:** {selected_lawyer.get('specialization', 'N/A')}")

                st.write(f"**Court:** {selected_lawyer.get('court', 'N/A')}")

                st.write(f"**Experience:** {selected_lawyer.get('years_of_experience', 0)} years")

                st.write(f"**Email:** {selected_lawyer.get('email', 'N/A')}")

            st.markdown("---")

            if st.button("Back to List"):
                st.session_state.selected_lawyer_id = None

                st.experimental_rerun()

            st.subheader("Book an Appointment")

            from datetime import date

            selected_date = st.date_input("Choose a Date", min_value=date.today())

            time_slot_options = [f"{hour}:00-{hour + 1}:00" for hour in range(9, 18)]

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

                            st.error(result.get("message", "Appointment booking failed."))


                    except Exception as e:

                        st.error(f"An error occurred while booking the appointment: {e}")


    # View Appointments Page (For Lawyers)
    elif selection == "Dashboard":
        st.title("My Dashboard")

        if st.session_state.get('logged_in', False) and st.session_state.get('role', '') == 'lawyer':
            user_id = st.session_state['user_id']

            # Multi-select for which widgets to display
            selected_widgets = st.multiselect(
                'Select widgets to display:',
                ['Appointments', 'Profile Reviews'],
                default=st.session_state.get('selected_widgets', [])
            )
        if "Appointments" in selected_widgets:
            if not st.session_state.get('logged_in', False):
                st.warning("Please log in to view appointments.")
            elif st.session_state.get('role', '').lower() != "lawyer":
                st.error("Only lawyers can view appointments.")
            else:
                st.title("View Appointments")
                with st.spinner("Fetching your appointments..."):
                    try:
                        # Fetch appointments from the backend
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

                                display_columns = ['appointment_id', 'client_name', 'Appointment Time', 'status',
                                                   'Created At']

                                # Ensure necessary columns exist
                                for col in ['client_name', 'status']:
                                    if col not in df.columns:
                                        df[col] = 'N/A'

                                # Sort appointments by time
                                df = df[display_columns].sort_values(by='Appointment Time', ascending=False)

                                # Initialize Session State Variables Before Widget Creation
                                for _, appointment in df.iterrows():
                                    update_key = f"show_update_form_{appointment['appointment_id']}"
                                    if update_key not in st.session_state:
                                        st.session_state[update_key] = False

                                # Display appointments in a table-like format with action dropdowns
                                st.markdown("## Manage Appointments")

                                # Create header row using st.columns with numerical widths
                                header_cols = st.columns([1.5, 2, 2.5, 1.5, 2.5, 2])
                                with header_cols[0]:
                                    st.markdown("**Appointment ID**")
                                with header_cols[1]:
                                    st.markdown("**Client Name**")
                                with header_cols[2]:
                                    st.markdown("**Appointment Time**")
                                with header_cols[3]:
                                    st.markdown("**Status**")
                                with header_cols[4]:
                                    st.markdown("**Created At**")
                                with header_cols[5]:
                                    st.markdown("**Actions**")

                                # Iterate over each appointment to create rows
                                for _, appointment in df.iterrows():
                                    appointment_id = appointment['appointment_id']
                                    client_name = appointment['client_name']
                                    appointment_time = appointment['Appointment Time']
                                    status = appointment['status']
                                    created_at = appointment['Created At']

                                    # Color-coded status with emojis
                                    status_lower = status.lower()
                                    if status_lower == 'accepted':
                                        status_display = f":green[{status.capitalize()}] ✅"
                                    elif status_lower == 'rejected':
                                        status_display = f":red[{status.capitalize()}] ❌"
                                    else:
                                        status_display = f":yellow[{status.capitalize()}] ⏳"

                                    # Create columns for each row with numerical widths
                                    row_cols = st.columns([1.5, 2, 2.5, 1.5, 2.5, 2])
                                    with row_cols[0]:
                                        st.markdown(appointment_id)
                                    with row_cols[1]:
                                        st.markdown(client_name)
                                    with row_cols[2]:
                                        st.markdown(appointment_time)
                                    with row_cols[3]:
                                        st.markdown(status_display)
                                    with row_cols[4]:
                                        st.markdown(created_at)
                                    with row_cols[5]:
                                        # Define allowed actions based on current status
                                        allowed_actions = []
                                        if status_lower in ['booked', 'pending']:
                                            allowed_actions = ['Accept', 'Reject', 'Update']
                                        elif status_lower == 'accepted':
                                            allowed_actions = ['Reject', 'Update']
                                        elif status_lower == 'rejected':
                                            allowed_actions = ['Accept', 'Update']

                                        if allowed_actions:
                                            # Create a unique key for the action dropdown to avoid conflicts
                                            action_key = f"action_dropdown_{appointment_id}"
                                            action = st.selectbox(
                                                "",
                                                ["Select Action"] + allowed_actions,
                                                key=action_key
                                            )

                                            if action != "Select Action":
                                                if action == "Accept":
                                                    # Perform Accept Action
                                                    accept_data = {
                                                        "appointment_id": appointment_id,
                                                        "action": "accept"
                                                    }
                                                    with st.spinner("Accepting appointment..."):
                                                        try:
                                                            accept_response = st.session_state.session.post(
                                                                f"{API_BASE_URL}/profile/update_appointment",
                                                                json=accept_data
                                                            )
                                                            if accept_response.status_code == 200:
                                                                action_result = accept_response.json()
                                                                if action_result.get("status") == "success":
                                                                    st.success(
                                                                        f"Appointment {appointment_id} accepted successfully.")
                                                                    # Refresh the appointments data
                                                                    appointments = None  # Reset to trigger data fetching
                                                                else:
                                                                    st.error(action_result.get("message",
                                                                                               f"Failed to {action} appointment."))
                                                            else:
                                                                # Attempt to parse error message from backend
                                                                try:
                                                                    error_result = accept_response.json()
                                                                    st.error(
                                                                        f"Error {accept_response.status_code}: {error_result.get('message', 'Unknown error.')}")
                                                                except:
                                                                    st.error(
                                                                        f"Error {accept_response.status_code}: {accept_response.text}")
                                                        except Exception as e:
                                                            st.error(f"An error occurred: {e}")

                                                elif action == "Reject":
                                                    # Perform Reject Action
                                                    reject_data = {
                                                        "appointment_id": appointment_id,
                                                        "action": "reject"
                                                    }
                                                    with st.spinner("Rejecting appointment..."):
                                                        try:
                                                            reject_response = st.session_state.session.post(
                                                                f"{API_BASE_URL}/profile/update_appointment",
                                                                json=reject_data
                                                            )
                                                            if reject_response.status_code == 200:
                                                                action_result = reject_response.json()
                                                                if action_result.get("status") == "success":
                                                                    st.success(
                                                                        f"Appointment {appointment_id} rejected successfully.")
                                                                    # Refresh the appointments data
                                                                    appointments = None  # Reset to trigger data fetching
                                                                else:
                                                                    st.error(action_result.get("message",
                                                                                               f"Failed to {action} appointment."))
                                                            else:
                                                                # Attempt to parse error message from backend
                                                                try:
                                                                    error_result = reject_response.json()
                                                                    st.error(
                                                                        f"Error {reject_response.status_code}: {error_result.get('message', 'Unknown error.')}")
                                                                except:
                                                                    st.error(
                                                                        f"Error {reject_response.status_code}: {reject_response.text}")
                                                        except Exception as e:
                                                            st.error(f"An error occurred: {e}")

                                                elif action == "Update":
                                                    # Toggle the update form for this appointment
                                                    update_key = f"show_update_form_{appointment_id}"
                                                    st.session_state[update_key] = True

                                    # Display the update form if toggled on
                                    update_key = f"show_update_form_{appointment_id}"
                                    if st.session_state.get(update_key, False):
                                        with st.form(key=f"update_form_{appointment_id}"):
                                            # Attempt to parse 'date'; handle missing or invalid 'date'
                                            try:
                                                min_date = datetime.strptime(appointment['date'], "%Y-%m-%d").date()
                                            except KeyError:
                                                st.warning(
                                                    f"Appointment {appointment_id} is missing the 'date' field. Using today's date as minimum.")
                                                min_date = datetime.now().date()
                                            except ValueError:
                                                st.warning(
                                                    f"Appointment {appointment_id} has an invalid 'date' format. Using today's date as minimum.")
                                                min_date = datetime.now().date()

                                            # New Date Input
                                            new_date = st.date_input(
                                                "Choose a New Date",
                                                min_value=min_date,
                                                key=f"new_date_{appointment_id}"
                                            )

                                            # New Time Slot Selection
                                            try:
                                                current_time_slot = appointment['time_slot']
                                                time_slots = [f"{hour}:00-{hour + 1}:00" for hour in range(9, 18)]
                                                if current_time_slot in time_slots:
                                                    default_index = time_slots.index(current_time_slot)
                                                else:
                                                    default_index = 0
                                            except KeyError:
                                                st.warning(
                                                    f"Appointment {appointment_id} is missing the 'time_slot' field. Setting default time slot.")
                                                time_slots = [f"{hour}:00-{hour + 1}:00" for hour in range(9, 18)]
                                                default_index = 0

                                            new_time_slot = st.selectbox(
                                                "Choose a New Time Slot",
                                                time_slots,
                                                index=default_index,
                                                key=f"new_time_slot_{appointment_id}"
                                            )

                                            # Submit and Cancel Buttons
                                            submit_button = st.form_submit_button("Submit Update")
                                            cancel_button = st.form_submit_button("Cancel")

                                            if submit_button:
                                                update_data = {
                                                    "appointment_id": appointment_id,
                                                    "action": "update",
                                                    "date": new_date.strftime("%Y-%m-%d"),
                                                    "time_slot": new_time_slot
                                                }
                                                with st.spinner("Updating appointment..."):
                                                    try:
                                                        update_response = st.session_state.session.post(
                                                            f"{API_BASE_URL}/profile/update_appointment",
                                                            json=update_data
                                                        )
                                                        if update_response.status_code == 200:
                                                            update_result = update_response.json()
                                                            if update_result.get("status") == "success":
                                                                st.success(
                                                                    f"Appointment {appointment_id} updated successfully.")
                                                                st.session_state[update_key] = False
                                                                # Refresh the appointments data
                                                                appointments = None  # Reset to trigger data fetching
                                                            else:
                                                                st.error(update_result.get("message",
                                                                                           "Failed to update appointment."))
                                                        else:
                                                            # Attempt to parse error message from backend
                                                            try:
                                                                error_result = update_response.json()
                                                                st.error(
                                                                    f"Error {update_response.status_code}: {error_result.get('message', 'Unknown error.')}")
                                                            except:
                                                                st.error(
                                                                    f"Error {update_response.status_code}: {update_response.text}")
                                                    except Exception as e:
                                                        st.error(f"An error occurred: {e}")

                                            if cancel_button:
                                                st.session_state[update_key] = False

                    except Exception as e:
                        st.error(f"An error occurred: {e}")
        if "Profile Reviews" in selected_widgets:
            st.header("Client Reviews")
            reviews_data = fetch_data('get_reviews', user_id)  # <-- Your existing helper
            if reviews_data and isinstance(reviews_data, list):
                # Convert reviews_data into a DataFrame
                df_reviews = process_reviews(reviews_data)  # your function that normalizes date, etc.

                # 1) Display raw reviews in a table
                st.dataframe(df_reviews)

                # 2) Example: Plot a histogram of rating distribution
                if 'rating' in df_reviews.columns:
                    st.subheader("Rating Distribution")
                    fig_dist = px.histogram(
                        df_reviews,
                        x='rating',
                        nbins=5,  # Adjust as needed
                        title='Rating Frequency',
                        color='rating'
                    )
                    st.plotly_chart(fig_dist, use_container_width=True)

                # 3) Example: Plot rating vs time to see how ratings change over time (if you have a 'date' column)
                if 'date' in df_reviews.columns and 'rating' in df_reviews.columns:
                    # Ensure date column is actually datetime
                    df_reviews['date'] = pd.to_datetime(df_reviews['date'])
                    df_reviews.sort_values('date', inplace=True)

                    st.subheader("Rating Over Time")
                    fig_time = px.line(
                        df_reviews,
                        x='date',
                        y='rating',
                        title='Rating Trend Over Time',
                        markers=True
                    )
                    st.plotly_chart(fig_time, use_container_width=True)

                # 4) Optional: Show average rating or other stats
                if 'rating' in df_reviews.columns:
                    avg_rating = df_reviews['rating'].mean()
                    st.metric(label="Average Rating", value=f"{avg_rating:.2f}")
            else:
                st.write("No reviews available.")

    # ---------------------------- Create Court Document Page ---------------------------- #

    elif selection == "Create Court Document":
        st.title("Create Court Document")
        st.markdown("---")

        # 1. Select Template
        st.subheader("Select a Court Document Template")
        try:
            templates = [f for f in os.listdir(COURT_TEMPLATES_FOLDER) if f.endswith('.txt')]
            if not templates:
                st.warning(f"No templates found in the '{COURT_TEMPLATES_FOLDER}' folder.")
                st.stop()

            template_choice = st.selectbox("Choose a Template", templates)
        except FileNotFoundError:
            st.error(f"The folder '{COURT_TEMPLATES_FOLDER}' does not exist. Please create it and add .txt templates.")
            st.stop()
        except Exception as e:
            st.error(f"An error occurred while fetching templates: {e}")
            st.stop()

        # 2. Read Template
        template_path = os.path.join(COURT_TEMPLATES_FOLDER, template_choice)
        try:
            with open(template_path, 'r', encoding='utf-8') as file:
                template_text = file.read()

            # Find placeholders
            placeholders = re.findall(r'\{(.*?)\}', template_text)
            unique_placeholders = list(dict.fromkeys(placeholders))  # Remove duplicates while preserving order

            if not unique_placeholders:
                st.info("The selected template has no placeholders to fill.")
                st.stop()
        except UnicodeDecodeError as e:
            st.error(f"An encoding error occurred while reading the template: {e}")
            st.info("Please ensure the template is saved in UTF-8 without BOM.")
            st.stop()
        except Exception as e:
            st.error(f"An error occurred while reading the template: {e}")
            st.stop()

        # 3. Generate Form
        if unique_placeholders:
            st.subheader("Fill in the Details")
            with st.form("court_document_form"):
                filled_data = {}
                for placeholder in unique_placeholders:
                    display_name = placeholder.replace('_', ' ').capitalize()
                    if 'date' in placeholder.lower():
                        filled_data[placeholder] = st.date_input(f"{display_name}", value=date.today())
                    elif 'email' in placeholder.lower():
                        filled_data[placeholder] = st.text_input(f"{display_name}", value="",
                                                                 help="Enter a valid email address.")
                    elif 'number' in placeholder.lower() or 'no' in placeholder.lower():
                        filled_data[placeholder] = st.text_input(f"{display_name}", value="", help="Enter a number.")
                    else:
                        filled_data[placeholder] = st.text_input(f"{display_name}", value="")

                submit_doc = st.form_submit_button("Generate .txt Document")

            if submit_doc:
                # Validate inputs
                missing_fields = [key for key, value in filled_data.items() if not value]
                if missing_fields:
                    st.error(f"Please fill in all required fields: {', '.join(missing_fields)}")
                    st.stop()

                # Replace placeholders
                filled_text = template_text
                for key, value in filled_data.items():
                    if isinstance(value, date):
                        value = value.strftime("%d-%m-%Y")
                    filled_text = filled_text.replace(f"{{{key}}}", str(value))

                # Check for unreplaced placeholders
                unreplaced_placeholders = re.findall(r'\{(.*?)\}', filled_text)
                if unreplaced_placeholders:
                    st.error(f"The following placeholders were not filled: {', '.join(unreplaced_placeholders)}")
                    st.stop()

                # Encode as UTF-8
                encoded_text = filled_text.encode('utf-8')
                txt_buffer = io.BytesIO(encoded_text)

                # Provide download
                st.download_button(
                    label="Download Generated .txt Document",
                    data=txt_buffer,
                    file_name=f"{os.path.splitext(template_choice)[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain"
                )
        else:
            st.info("No placeholders found in the selected template. You can directly download the document.")

    # ---------------------------- FAQs Viewer Page ---------------------------- #
    elif selection == "FAQs":
        st.title("Frequently Asked Questions")

        try:
            response = requests.get(f"{API_BASE_URL}/get_faqs")
            if response.status_code == 200:
                # Parse the JSON string
                faqs = response.json()
                if isinstance(faqs, list):
                    for faq in faqs:
                        with st.expander(f"{faq['question']}"):
                            st.write(f"{faq['answer']}")
                else:
                    st.error("FAQ data is not a list. Please check the API response.")
            else:
                st.error(f"Failed to load FAQs, status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            st.error(f"An error occurred while fetching FAQs: {str(e)}")






    elif selection == "Submit Review":
        st.title("Submit a Review")

        if not st.session_state.logged_in or st.session_state.role != 'client':
            st.error("You must be logged in as a client to submit reviews.")
        else:
            # Assuming the client knows their lawyer's ID or you fetch it based on past appointments
            lawyer_id = st.text_input("Lawyer ID", "Enter your lawyer's ID here")
            review_text = st.text_area("Review")
            rating = st.slider("Rating", 1, 5, 3)
            submit_button = st.button("Submit Review")

            if submit_button:
                if not review_text or not lawyer_id:
                    st.error("Please fill in all fields.")
                else:
                    review_data = {
                        "lawyer_id": lawyer_id,
                        "client_id": st.session_state.user_id,  # Assume user ID is stored in session upon login
                        "review": review_text,
                        "rating": rating
                    }
                    # POST request to Flask API
                    response = requests.post(f'{API_BASE_URL}/add_review', json=review_data)
                    if response.status_code == 201:
                        st.success("Your review has been submitted successfully!")
                    else:
                        st.error("Failed to submit review. Please try again.")
    # ---------------------------- Document Viewer Page ---------------------------- #
    elif st.session_state.current_view == "Document Viewer":
        if st.session_state.selected_document:
            view_document_page(st.session_state.selected_document)
        else:
            st.error("No document selected to view.")