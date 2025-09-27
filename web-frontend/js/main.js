// ------------------------- Global Variables & Utilities -------------------------
const API_BASE_URL = "http://127.0.0.1:5002";

// Utility function to safely parse JSON responses
async function parseJsonOrThrow(response) {
  try {
    return await response.json();
  } catch (err) {
    throw new Error("Invalid JSON response.");
  }
}

// Simple markdown converter for bold text (converts **text** into <strong>text</strong>)
function convertMarkdown(md) {
  return md.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
}

// ------------------------- Login Functionality -------------------------
document.addEventListener("DOMContentLoaded", () => {
  const loginForm = document.getElementById("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", handleLogin);
  }
});

async function handleLogin(event) {
  event.preventDefault(); // Prevent page refresh
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value.trim();
  if (!username || !password) {
    alert("Please fill in both username and password.");
    return;
  }
  try {
    const response = await fetch(`${API_BASE_URL}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      credentials: "include"
    });
    const data = await parseJsonOrThrow(response);
    console.log("Login response data:", data);
    if (response.ok) {
      // Use the top-level user_id from the response
      const userId = data.user_id;
      if (!userId) {
        alert("Error: No valid user ID found in the login response.");
        return;
      }
      localStorage.setItem("username", username);
      localStorage.setItem("user_id", userId);
      localStorage.setItem("role", data.role || data.data.role || "client");
      window.location.href = "home.html";
    } else {
      alert("Login failed: " + (data.error || data.message));
    }
  } catch (err) {
    console.error(err);
    alert("Error during login: " + err.message);
  }
}



// ------------------------- Logout Functionality -------------------------
async function handleLogout() {
  try {
    const response = await fetch(`${API_BASE_URL}/logout`, {
      method: "POST",
      credentials: "include"
    });
    if (response.ok) {
    }
  } catch (err) {
    console.error(err);
  }
  localStorage.removeItem("username");
  localStorage.removeItem("user_id");
  localStorage.removeItem("role");
  window.location.href = "login.html";
}

// ------------------------- File Explorer Functions (Documents Page) -------------------------
let fileSystem = {
  name: "/",
  path: "",
  folders: {},
  files: []
};

let currentFolderPath = "";

async function fetchFileSystem() {
  try {
    const response = await fetch(`${API_BASE_URL}/my_documents`, { credentials: "include" });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      const documents = result.documents;
      fileSystem = { name: "/", path: "", folders: {}, files: [] };
      documents.forEach(doc => {
        let folderPath = doc.folder ? doc.folder.trim() : "General";
        const parts = folderPath.split("/");
        let currentLevel = fileSystem;
        parts.forEach(part => {
          if (!currentLevel.folders[part]) {
            currentLevel.folders[part] = {
              name: part,
              path: (currentLevel.path ? currentLevel.path + "/" : "") + part,
              folders: {},
              files: []
            };
          }
          currentLevel = currentLevel.folders[part];
        });
        currentLevel.files.push(doc);
      });
    } else {
      alert("Failed to fetch documents.");
    }
  } catch (err) {
    console.error(err);
    alert("Error fetching documents: " + err.message);
  }
}

function displayFileSystem() {
  const fileList = document.getElementById("fileList");
  fileList.innerHTML = "";
  let currentFolder = fileSystem;
  if (currentFolderPath !== "") {
    const parts = currentFolderPath.split("/");
    parts.forEach(part => {
      if (currentFolder.folders[part]) {
        currentFolder = currentFolder.folders[part];
      }
    });
  }
  document.getElementById("currentPath").textContent = "/" + currentFolderPath;
  const backButton = document.getElementById("backButton");
  backButton.style.display = currentFolderPath === "" ? "none" : "block";
  for (let folderName in currentFolder.folders) {
    const folder = currentFolder.folders[folderName];
    const folderItem = document.createElement("div");
    folderItem.className = "file-item";
    folderItem.innerHTML = `<img src="https://img.icons8.com/fluency/100/000000/folder-invoices.png" alt="Folder"><span>${folder.name}</span>`;
    folderItem.ondblclick = () => {
      currentFolderPath = currentFolderPath === "" ? folder.name : currentFolderPath + "/" + folder.name;
      displayFileSystem();
    };
    fileList.appendChild(folderItem);
  }
  currentFolder.files.forEach(file => {
    const fileItem = document.createElement("div");
    fileItem.className = "file-item";
    fileItem.innerHTML = `<img src="https://img.icons8.com/fluency/100/000000/document.png" alt="File"><span>${file.doc_filename}</span>`;
    fileItem.onclick = () => {
      window.location.href = `view_document.html?document_key=${encodeURIComponent(file.s3_key)}`;
    };
    fileList.appendChild(fileItem);
  });
}

function navigateBack() {
  if (currentFolderPath === "") return;
  const parts = currentFolderPath.split("/");
  parts.pop();
  currentFolderPath = parts.join("/");
  displayFileSystem();
}

async function loadDocumentsFS() {
  await fetchFileSystem();
  displayFileSystem();
}

// ------------------------- Document Viewer & Chat Functions -------------------------
let chatHistoryArray = [];

function loadDocumentViewer() {
  const params = new URLSearchParams(window.location.search);
  let documentKey = params.get("document_key");
  if (!documentKey) {
    document.getElementById("documentContent").innerText = "No document selected.";
    return;
  }
  console.log("Raw Document Key from URL:", documentKey);
  documentKey = decodeURIComponent(documentKey);
  console.log("Decoded Document Key:", documentKey);
  document.getElementById("docTitle").innerText = "Viewing Document: " + documentKey;
  fetch(`${API_BASE_URL}/serve_document?document_key=${encodeURIComponent(documentKey)}`, { credentials: "include" })
    .then(response => {
      if (!response.ok) {
        throw new Error("Failed to fetch document content.");
      }
      return response.text();
    })
    .then(text => {
      document.getElementById("documentContent").innerText = text;
    })
    .catch(error => {
      console.error(error);
      document.getElementById("documentContent").innerText = "Error loading document.";
    });
  if (chatHistoryArray.length === 0) {
    const welcomeMsg = "Hello! I'm Gavel, your legal assistant. How can I assist you today?";
    chatHistoryArray.push({ role: "assistant", content: welcomeMsg });
    addChatMessage("Gavel", welcomeMsg);
  }
  const chatForm = document.getElementById("chatForm");
  chatForm.addEventListener("submit", function(event) {
    event.preventDefault();
    const docFilename = documentKey.split("/").pop();
    sendChatQuery(docFilename);
  });
  const fetchPromptsBtn = document.getElementById("fetchPromptsBtn");
  if (fetchPromptsBtn) {
    fetchPromptsBtn.addEventListener("click", loadPrompts);
  }
  const downloadChatBtn = document.getElementById("downloadChatBtn");
  if (downloadChatBtn) {
    downloadChatBtn.addEventListener("click", downloadConversation);
  }
}

async function sendChatQuery(documentName) {
  const queryInput = document.getElementById("chatQuery");
  const queryText = queryInput.value.trim();
  if (!queryText) {
    alert("Please enter a question.");
    return;
  }
  addChatMessage("You", queryText);
  chatHistoryArray.push({ role: "user", content: queryText });
  queryInput.value = "";
  const chatHistoryDiv = document.getElementById("chatHistory");
  const loadingIndicator = document.createElement("p");
  loadingIndicator.innerHTML = `<strong>Gavel:</strong> <span class="spinner"></span>`;
  chatHistoryDiv.appendChild(loadingIndicator);
  chatHistoryDiv.scrollTop = chatHistoryDiv.scrollHeight;
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ query: queryText, document_name: documentName })
    });
    const result = await parseJsonOrThrow(response);
    loadingIndicator.remove();
    if (response.ok && result.status === "success") {
      const answer = result.answer || "No answer provided.";
      addChatMessage("Gavel", answer);
      chatHistoryArray.push({ role: "assistant", content: answer });
    } else {
      const errorMsg = "Error: " + (result.message || "Failed to get response.");
      addChatMessage("Gavel", errorMsg);
      chatHistoryArray.push({ role: "assistant", content: errorMsg });
    }
  } catch (err) {
    console.error(err);
    loadingIndicator.remove();
    addChatMessage("Gavel", "Error sending query.");
    chatHistoryArray.push({ role: "assistant", content: "Error sending query." });
  }
}

function addChatMessage(sender, message) {
  const chatHistoryDiv = document.getElementById("chatHistory");
  const messageElement = document.createElement("p");
  const formattedMessage = convertMarkdown(message).replace(/\n/g, "<br>");
  messageElement.innerHTML = `<strong>${sender}:</strong> ${formattedMessage}`;
  chatHistoryDiv.appendChild(messageElement);
  chatHistoryDiv.scrollTop = chatHistoryDiv.scrollHeight;
}

// ------------------------- Chat Prompt Functions -------------------------
async function loadPrompts() {
  const promptTypeSelect = document.getElementById("promptTypeSelect");
  const promptType = promptTypeSelect.value.toLowerCase();
  const promptListDiv = document.getElementById("promptList");
  promptListDiv.innerHTML = "Loading prompts...";
  try {
    const response = await fetch(`${API_BASE_URL}/get_prompts?type=${promptType}`, { credentials: "include" });
    const result = await parseJsonOrThrow(response);
    if (response.ok) {
      if (Array.isArray(result)) {
        promptListDiv.innerHTML = "";
        result.forEach(prompt => {
          const label = document.createElement("label");
          label.style.display = "block";
          label.style.marginBottom = "5px";
          const radio = document.createElement("input");
          radio.type = "radio";
          radio.name = "promptOption";
          radio.value = prompt.content;
          label.appendChild(radio);
          label.append(" " + prompt.title + " (ID: " + prompt.prompt_id + ")");
          promptListDiv.appendChild(label);
        });
      } else {
        promptListDiv.innerText = "Unexpected response format.";
      }
    } else {
      promptListDiv.innerText = "Failed to fetch prompts.";
    }
  } catch (err) {
    console.error(err);
    promptListDiv.innerText = "Error fetching prompts: " + err.message;
  }
}

function useSelectedPrompt() {
  const usePromptCheckbox = document.getElementById("usePromptCheckbox");
  if (usePromptCheckbox.checked) {
    const radios = document.getElementsByName("promptOption");
    let selectedPromptContent = "";
    for (let radio of radios) {
      if (radio.checked) {
        selectedPromptContent = radio.value;
        break;
      }
    }
    if (selectedPromptContent) {
      document.getElementById("chatQuery").value = selectedPromptContent;
    }
  }
}

function downloadConversation() {
  const chatHistoryDiv = document.getElementById("chatHistory");
  const messages = chatHistoryDiv.getElementsByTagName("p");
  let conversation = "";
  for (let msg of messages) {
    conversation += msg.innerText + "\n\n";
  }
  const blob = new Blob([conversation], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "conversation.txt";
  a.click();
  URL.revokeObjectURL(url);
}

// ------------------------- Profile Functions -------------------------
async function loadProfile() {
  try {
    const response = await fetch(`${API_BASE_URL}/profile/get_profile`, { credentials: "include" });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      const profile = result.profile;
      let detailsHTML = "";
      detailsHTML += `<p><strong>Name:</strong> ${profile.name || ""}</p>`;
      detailsHTML += `<p><strong>Email:</strong> ${profile.email || ""}</p>`;
      detailsHTML += `<p><strong>Gender:</strong> ${profile.gender || ""}</p>`;
      detailsHTML += `<p><strong>Addresses:</strong> ${profile.addresses || ""}</p>`;
      document.getElementById("profileInfo").innerHTML = detailsHTML;
      if (profile.profile_picture_url) {
        document.getElementById("profilePic").src = profile.profile_picture_url;
      } else {
        document.getElementById("profilePic").src = "https://via.placeholder.com/150";
      }
      document.getElementById("editName").value = profile.name || "";
      document.getElementById("editEmail").value = profile.email || "";
      document.getElementById("editGender").value = profile.gender || "";
      document.getElementById("editAddresses").value = profile.addresses || "";
    } else {
      alert("Failed to load profile: " + (result.message || "Unknown error."));
    }
  } catch (err) {
    console.error(err);
    alert("Error loading profile: " + err.message);
  }
}

function toggleEditMode() {
  const editForm = document.getElementById("editFormContainer");
  if (editForm.style.display === "none" || editForm.style.display === "") {
    editForm.style.display = "block";
  } else {
    editForm.style.display = "none";
  }
}

async function saveProfileEdits() {
  const updatedData = {
    name: document.getElementById("editName").value.trim(),
    email: document.getElementById("editEmail").value.trim(),
    gender: document.getElementById("editGender").value.trim(),
    addresses: document.getElementById("editAddresses").value.trim()
  };
  try {
    const response = await fetch(`${API_BASE_URL}/profile/update_profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(updatedData)
    });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      alert("Profile details updated successfully!");
    } else {
      alert("Failed to update profile details: " + (result.message || "Unknown error."));
    }
  } catch (err) {
    console.error(err);
    alert("Error updating profile details: " + err.message);
  }
  const newPic = document.getElementById("editProfilePic").files[0];
  if (newPic) {
    const formData = new FormData();
    formData.append("profile_picture", newPic);
    try {
      const picResponse = await fetch(`${API_BASE_URL}/profile/update_profile_picture`, {
        method: "POST",
        credentials: "include",
        body: formData
      });
      const picResult = await parseJsonOrThrow(picResponse);
      if (picResponse.ok && picResult.status === "success") {
        alert("Profile picture updated successfully!");
      } else {
        alert("Failed to update profile picture: " + (picResult.message || "Unknown error."));
      }
    } catch (err) {
      console.error(err);
      alert("Error updating profile picture: " + err.message);
    }
  }
  toggleEditMode();
  loadProfile();
}

// ------------------------- Appointments Functions -------------------------
async function loadAppointmentsPage() {
  // Check if the logged-in user is a lawyer by reading localStorage
  const role = localStorage.getItem("role");
  console.log("Role from localStorage:", role);
  if (!role || role.toLowerCase() !== "lawyer") {
    document.getElementById("appointmentsSection").innerHTML = "<p>You must be a lawyer to view appointments.</p>";
    return;
  }
  try {
    const response = await fetch(`${API_BASE_URL}/profile/view_appointments`, { credentials: "include" });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      const appointments = result.appointments;
      displayAppointments(appointments);
      renderAppointmentsChart(appointments);
    } else {
      document.getElementById("appointmentsSection").innerHTML = `<p>Error: ${result.message || "Failed to fetch appointments."}</p>`;
    }
  } catch (err) {
    console.error(err);
    document.getElementById("appointmentsSection").innerHTML = `<p>Error: ${err.message}</p>`;
  }
}

function displayAppointments(appointments) {
  if (!appointments || appointments.length === 0) {
    document.getElementById("appointmentsSection").innerHTML = "<p>No appointments found.</p>";
    return;
  }
  let html = "<table class='appointments-table'>";
  html += "<thead><tr><th>Appointment ID</th><th>Client Name</th><th>Date</th><th>Time Slot</th><th>Status</th><th>Created At</th><th>Actions</th></tr></thead><tbody>";
  appointments.forEach(app => {
    html += `<tr>
      <td>${app.appointment_id}</td>
      <td>${app.client_name || "Unknown"}</td>
      <td>${app.date || ""}</td>
      <td>${app.time_slot || ""}</td>
      <td>${app.status || ""}</td>
      <td>${app.created_at ? new Date(app.created_at).toLocaleString() : ""}</td>
      <td>
        <select id="actionSelect_${app.appointment_id}">
          <option value="">Select Action</option>
          <option value="accept">Accept</option>
          <option value="reject">Reject</option>
          <option value="update">Update</option>
        </select>
        <button onclick="handleAppointmentAction('${app.appointment_id}')">Submit</button>
      </td>
    </tr>`;
  });
  html += "</tbody></table>";
  document.getElementById("appointmentsSection").innerHTML = html;
}

async function handleAppointmentAction(appointmentId) {
  const selectElem = document.getElementById("actionSelect_" + appointmentId);
  const action = selectElem.value;
  if (!action) {
    alert("Please select an action.");
    return;
  }
  if (action === "update") {
    showUpdateModal(appointmentId);
    return;
  }
  let payload = { appointment_id: appointmentId, action: action };
  try {
    const response = await fetch(`${API_BASE_URL}/profile/update_appointment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload)
    });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      alert(`Appointment ${appointmentId} ${action}ed successfully.`);
      loadAppointmentsPage();
    } else {
      alert(`Failed to ${action} appointment: ` + (result.message || "Unknown error."));
    }
  } catch (err) {
    console.error(err);
    alert("Error during appointment action: " + err.message);
  }
}

function showUpdateModal(appointmentId) {
  let modal = document.getElementById("updateModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "updateModal";
    modal.style.position = "fixed";
    modal.style.top = "0";
    modal.style.left = "0";
    modal.style.width = "100%";
    modal.style.height = "100%";
    modal.style.backgroundColor = "rgba(0,0,0,0.5)";
    modal.style.display = "flex";
    modal.style.alignItems = "center";
    modal.style.justifyContent = "center";
    modal.innerHTML = `
      <div style="background: #fff; padding: 20px; border-radius: 8px; width: 300px;">
        <h3>Update Appointment</h3>
        <label for="updateDate">New Date:</label>
        <input type="date" id="updateDate" style="width: 100%; padding: 8px; margin-bottom: 10px;" required>
        <label for="updateTimeSlot">New Time Slot:</label>
        <select id="updateTimeSlot" style="width: 100%; padding: 8px; margin-bottom: 10px;" required>
          <option value="09:00-10:00">09:00-10:00</option>
          <option value="10:00-11:00">10:00-11:00</option>
          <option value="11:00-12:00">11:00-12:00</option>
          <option value="12:00-13:00">12:00-13:00</option>
          <option value="13:00-14:00">13:00-14:00</option>
          <option value="14:00-15:00">14:00-15:00</option>
          <option value="15:00-16:00">15:00-16:00</option>
          <option value="16:00-17:00">16:00-17:00</option>
          <option value="17:00-18:00">17:00-18:00</option>
        </select>
        <div style="text-align: right;">
          <button id="updateCancelBtn" style="margin-right: 10px;">Cancel</button>
          <button id="updateSubmitBtn">Submit</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    document.getElementById("updateCancelBtn").addEventListener("click", function() {
      modal.style.display = "none";
    });
    document.getElementById("updateSubmitBtn").addEventListener("click", function() {
      submitUpdateAppointment(appointmentId);
    });
  } else {
    modal.style.display = "flex";
  }
}

async function submitUpdateAppointment(appointmentId) {
  const newDate = document.getElementById("updateDate").value;
  const newTimeSlot = document.getElementById("updateTimeSlot").value;
  if (!newDate || !newTimeSlot) {
    alert("Both new date and time slot are required for update.");
    return;
  }
  const payload = { appointment_id: appointmentId, action: "update", date: newDate, time_slot: newTimeSlot };
  try {
    const response = await fetch(`${API_BASE_URL}/profile/update_appointment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload)
    });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      alert(`Appointment ${appointmentId} updated successfully.`);
      document.getElementById("updateModal").style.display = "none";
      loadAppointmentsPage();
    } else {
      alert(`Failed to update appointment: ` + (result.message || "Unknown error."));
    }
  } catch (err) {
    console.error(err);
    alert("Error during appointment update: " + err.message);
  }
}

function renderAppointmentsChart(appointments) {
  const statusCounts = {};
  appointments.forEach(app => {
    const status = app.status ? app.status.toLowerCase() : "unknown";
    statusCounts[status] = (statusCounts[status] || 0) + 1;
  });
  const labels = Object.keys(statusCounts);
  const data = labels.map(label => statusCounts[label]);
  const ctx = document.getElementById("appointmentsChart").getContext("2d");
  if (window.appointmentsChartInstance) {
    window.appointmentsChartInstance.destroy();
  }
  window.appointmentsChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: "Number of Appointments",
        data: data,
        backgroundColor: [
          "rgba(75, 192, 192, 0.6)",
          "rgba(255, 159, 64, 0.6)",
          "rgba(153, 102, 255, 0.6)",
          "rgba(255, 99, 132, 0.6)",
          "rgba(54, 162, 235, 0.6)"
        ],
        borderColor: [
          "rgba(75, 192, 192, 1)",
          "rgba(255, 159, 64, 1)",
          "rgba(153, 102, 255, 1)",
          "rgba(255, 99, 132, 1)",
          "rgba(54, 162, 235, 1)"
        ],
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true,
          precision: 0
        }
      }
    }
  });
}

// ------------------------- Search Docs Functions -------------------------
async function loadClassificationData() {
  try {
    const response = await fetch("classified_results.xlsx");
    if (!response.ok) {
      throw new Error("Failed to load classification file.");
    }
    const data = await response.arrayBuffer();
    const workbook = XLSX.read(data, { type: "array" });
    const sheetName = workbook.SheetNames[0];
    const sheet = workbook.Sheets[sheetName];
    const jsonData = XLSX.utils.sheet_to_json(sheet, { header: 1 });
    const mapping = {};
    for (let i = 1; i < jsonData.length; i++) {
      const row = jsonData[i];
      if (row && row.length >= 2) {
        const filename = row[0].toString().trim();
        const classification = row[1].toString().toLowerCase();
        let winner = "unknown";
        if (classification.includes("winner:")) {
          const parts = classification.split("winner:");
          if (parts.length > 1) {
            winner = parts[1].split(",")[0].trim();
          }
        }
        mapping[filename] = winner;
      }
    }
    return mapping;
  } catch (err) {
    console.error(err);
    return {};
  }
}

async function searchDocuments() {
  const roleSelect = document.getElementById("roleSelect");
  const userRole = roleSelect.value.toLowerCase();
  const query = document.getElementById("query").value.trim();

  // Use Number() to force conversion; also log for debugging.
  const topKValue = document.getElementById("topK").value;
  const topK = Number(topKValue);
  console.log("topK type:", typeof topK, "value:", topK);

  if (!query) {
    alert("Please enter a search query.");
    return;
  }
  document.getElementById("searchSpinner").style.display = "block";
  const container = document.getElementById("resultsContainer");
  container.innerHTML = "";
  const searchData = { query: query, top_k: topK }; // now guaranteed to be a number

  try {
    const response = await fetch(`${API_BASE_URL}/search_docs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(searchData)
    });
    const result = await parseJsonOrThrow(response);
    document.getElementById("searchSpinner").style.display = "none";
    if (response.ok && result.status === "success") {
      const results = result.results || [];
      const resultsCount = results.length;
      container.innerHTML = `<p>Found ${resultsCount} result${resultsCount !== 1 ? "s" : ""}.</p>`;
      if (resultsCount > 0) {
        // Load classification data from your Excel file
        const classificationData = await loadClassificationData();

        // Separate results into two arrays based on classification,
        // processing each result individually.
        const inFavorResults = [];
        const notInFavorResults = [];
        results.forEach(doc => {
          let summaryText = "No summary available.";
          if (typeof doc.summary === "string") {
            summaryText = doc.summary;
          } else if (typeof doc.summary === "object" && doc.summary.answer) {
            summaryText = doc.summary.answer;
          }
          // Convert similarity to a number (if needed)
          const similarity = Number(doc.similarity) || 0;
          const displayDoc = {
            filename: doc.filename || "Unknown",
            similarity: similarity,
            summary: summaryText
          };
          const docWinner = classificationData[displayDoc.filename] || "unknown";
          if (docWinner === userRole) {
            inFavorResults.push(displayDoc);
          } else {
            notInFavorResults.push(displayDoc);
          }
        });

        // Create two columns for displaying results.
        const col1 = document.createElement("div");
        col1.className = "column";
        const col2 = document.createElement("div");
        col2.className = "column";

        // Build HTML for "In Favor" results.
        let inFavorHTML = "<h3>In Favor</h3>";
        if (inFavorResults.length > 0) {
          for (const doc of inFavorResults) {
            inFavorHTML += `
              <div class="result">
                <div class="tooltip">
                  <p class="result-filename">${doc.filename}</p>
                  <span class="tooltiptext">${doc.summary}</span>
                </div>
                <p>Similarity: ${doc.similarity}%</p>
                <p><a href="${await getPresignedUrl("documents/" + doc.filename)}" target="_blank">View Document</a></p>
              </div>
            `;
          }
        } else {
          inFavorHTML += "<p>No results in favor.</p>";
        }
        col1.innerHTML = inFavorHTML;

        // Build HTML for "Not In Favor" results.
        let notInFavorHTML = "<h3>Not In Favor</h3>";
        if (notInFavorResults.length > 0) {
          for (const doc of notInFavorResults) {
            notInFavorHTML += `
              <div class="result">
                <div class="tooltip">
                  <p class="result-filename">${doc.filename}</p>
                  <span class="tooltiptext">${doc.summary}</span>
                </div>
                <p>Similarity: ${doc.similarity}%</p>
                <p><a href="${await getPresignedUrl("documents/" + doc.filename)}" target="_blank">View Document</a></p>
              </div>
            `;
          }
        } else {
          notInFavorHTML += "<p>No results not in favor.</p>";
        }
        col2.innerHTML = notInFavorHTML;

        // Append the two columns to the container.
        const resultsWrapper = document.createElement("div");
        resultsWrapper.className = "clearfix";
        resultsWrapper.appendChild(col1);
        resultsWrapper.appendChild(col2);
        container.appendChild(resultsWrapper);
      }
    } else {
      alert("Search failed: " + (result.message || "Unknown error."));
    }
  } catch (err) {
    document.getElementById("searchSpinner").style.display = "none";
    console.error(err);
    alert("Error during search: " + err.message);
  }
}

async function getPresignedUrl(objectKey) {
  try {
    const response = await fetch(`${API_BASE_URL}/generate_presigned_url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ object_key: objectKey })
    });
    const result = await parseJsonOrThrow(response);
    if (response.ok && result.status === "success") {
      return result.url;
    } else {
      return "#";
    }
  } catch (err) {
    console.error(err);
    return "#";
  }
}
// Define the loadDashboard function which will be called when home.html loads.
function loadDashboard() {
  // For example, set the welcome message based on the username stored in localStorage.
  const welcomeUserElem = document.getElementById("welcomeUser");
  const username = localStorage.getItem("username") || "User";
  if (welcomeUserElem) {
    welcomeUserElem.textContent = username;
  }

  // (Optional) Add any additional dashboard initialization code here.
  console.log("Dashboard loaded for user:", username);
}
document.addEventListener("DOMContentLoaded", () => {
  // Role-based navigation setup
  const role = localStorage.getItem("role") ? localStorage.getItem("role").toLowerCase() : "";
  const sidebarNav = document.querySelector("aside.sidebar ul");
  if (sidebarNav) {
    if (role === "lawyer") {
      sidebarNav.innerHTML = `
        <li><a href="home.html">Home</a></li>
        <li><a href="profile.html">Profile</a></li>
        <li><a href="upload_document.html">Upload Document</a></li>
        <li><a href="documents.html">Documents</a></li>
        <li><a href="appointments.html">Appointments</a></li>
        <li><a href="notifications.html">Notifications</a></li>
        <li><a href="teams.html">Teams</a></li>
        <li><a href="judgement_search.html">Judgement Search</a></li>
        <li><a href="profile_reviews.html" class="lawyer-only">Profile Reviews</a></li>
        <li><a href="lawyer_online_consultation.html">Online consultation</a></li>
        <li><a href="#" onclick="handleLogout(); return false;">Logout</a></li>
      `;
    } else if (role === "client") {
      sidebarNav.innerHTML = `
        <li><a href="home.html">Home</a></li>
        <li><a href="profile.html">Profile</a></li>
        <li><a href="book_appointment.html">Book Appointment</a></li>
        <li><a href="submit_review.html">Submit a review</a></li>
        <li><a href="faqs.html">FAQs</a></li>
        <li><a href="initiate_call.html">Online consultation</a></li>
        <li><a href="#" onclick="handleLogout(); return false;">Logout</a></li>
      `;
    }
  }
});


// ------------------------- Duplicate Document Viewer & Chat Functions -------------------------
// (These are already defined above; ensure you do not redeclare duplicate functions)

// ------------------------- End of File -------------------------
