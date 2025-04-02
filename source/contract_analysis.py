import os
import json
import datetime
import difflib
import logging
import re
import time
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, Blueprint, request, jsonify, session
from pymongo import MongoClient
from bson import ObjectId
from llm_general import *

import openai

# --------------------------- Configuration & Logging ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

# --------------------------- MongoDB Setup ---------------------------
mongo_client = MongoClient(os.getenv("Mongo_Client"))
db = mongo_client["legalaid"]

# --------------------------- Flask App Setup ---------------------------
app = Flask(__name__)
# In production, ensure you set a strong secret key and handle sessions securely
app.secret_key = "some_super_secret_key_for_sessions"

# --------------------------- Helper Functions ---------------------------

def extract_text(file_bytes: bytes, content_type: str) -> str:
    """
    Extract text from file bytes.
    Currently supports text files; extend to support PDFs, DOCX, etc.
    """
    try:
        text = file_bytes.decode("utf-8", errors="ignore")
        return text
    except Exception as e:
        logger.error("Error extracting text: %s", e)
        return ""

def advanced_chunk_text(text: str, max_chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """
    Split text into semantically coherent chunks using sentence boundaries.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= max_chunk_size:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            # Start new chunk with an overlap from the previous chunk
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + sentence + " "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def generate_text_diff(old_text: str, new_text: str) -> str:
    """
    Generate a unified diff between two versions of text.
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff_lines = difflib.unified_diff(old_lines, new_lines,
                                      fromfile='Old Version', tofile='New Version', lineterm='')
    return "\n".join(diff_lines)

# --------------------------- Blueprint and Endpoints ---------------------------
contract_bp = Blueprint('contract_bp', __name__)

@contract_bp.route('/analyze_contract', methods=['POST'])
def analyze_contract():
    """
    Analyze a contract:
      1. Acquire contract (via file upload or by contract_id)
      2. Chunk text
      3. Extract clauses in parallel
      4. Detect risks in each clause in parallel
      5. Extract metadata from the contract text
    """
    contract_id = request.form.get('contract_id')
    uploaded_file = request.files.get('file')
    user_id = session.get("user_id")  # Ensure user_id is set via your login flow

    if not contract_id and not uploaded_file:
        return jsonify({"status": "error", "message": "Provide either contract_id or file."}), 400

    contracts_collection = db['contracts']
    clauses_collection = db['contract_clauses']
    risk_collection = db['contract_risks']

    # 1) Acquire or create contract
    if uploaded_file:
        file_bytes = uploaded_file.read()
        text = extract_text(file_bytes, uploaded_file.content_type)
        contract_doc = {
            "user_id": user_id,
            "filename": uploaded_file.filename,
            "text": text,
            "created_at": datetime.datetime.utcnow()
        }
        contract_id = str(contracts_collection.insert_one(contract_doc).inserted_id)
    else:
        existing_contract = contracts_collection.find_one({"_id": ObjectId(contract_id), "user_id": user_id})
        if not existing_contract:
            return jsonify({"status": "error", "message": "Contract not found or unauthorized."}), 404
        text = existing_contract["text"]

    # 2) Chunk text
    chunks = advanced_chunk_text(text, max_chunk_size=2000, overlap=200)
    if not chunks:
        return jsonify({"status": "error", "message": "No text extracted or chunked."}), 400

    # 3) Clause extraction in parallel
    extracted_clauses = []
    import json
    import re
    import logging
    from typing import List, Dict, Any

    logger = logging.getLogger(__name__)

    def extract_clauses_from_chunk(chunk: str) -> List[Dict[str, Any]]:
        prompt = f"""
    You are a contract analysis assistant.
    Extract distinct clauses from the text below.
    Each clause must be output as a JSON object with the following keys:
    - "clause_title": a short title for the clause,
    - "clause_text": the full text of the clause,
    - "start": the starting character index of the clause in the text,
    - "end": the ending character index of the clause in the text.
    Return ONLY a JSON array of these clause objects. Do not include any extra commentary, markdown formatting, or code block markers.
    TEXT:
    {chunk}
    """
        response_str = call_llm_api(prompt)

        # Remove possible markdown/code block markers.
        response_str = re.sub(r"^```(?:json)?", "", response_str)
        response_str = re.sub(r"```$", "", response_str).strip()

        try:
            clauses = json.loads(response_str)
        except json.JSONDecodeError:
            logger.warning("JSON decode error for clause extraction in chunk. Response was: %s", response_str)
            clauses = []

        # Ensure all keys exist in each clause
        for clause in clauses:
            clause.setdefault("clause_title", "Untitled Clause")
            clause.setdefault("clause_text", "")
            clause.setdefault("start", 0)
            clause.setdefault("end", 0)
        return clauses

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(extract_clauses_from_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            try:
                clauses = future.result()
                extracted_clauses.extend(clauses)
            except Exception as e:
                logger.error("Error in clause extraction: %s", e)

    # 4) Store extracted clauses
    for clause in extracted_clauses:
        clause["contract_id"] = contract_id
        clause["created_at"] = datetime.datetime.utcnow()
    if extracted_clauses:
        clauses_collection.insert_many(extracted_clauses)
    logger.info("Extracted %d clauses.", len(extracted_clauses))

    # 5) Risk detection in parallel
    risk_flags = []
    def analyze_risk(clause: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""
You're a legal text analyzer.
Evaluate the following clause for potential risks or red flags.
Return JSON in the format:
{{
  "contains_risk": true or false,
  "risk_description": "..."
}}

Clause:
{clause.get("clause_text", "")}
"""
        response = call_llm_api(prompt)
        try:
            risk_data = json.loads(response)
        except json.JSONDecodeError:
            logger.warning("JSON decode error during risk detection.")
            risk_data = {"contains_risk": False, "risk_description": ""}
        return risk_data

    with ThreadPoolExecutor(max_workers=4) as executor:
        risk_futures = {executor.submit(analyze_risk, clause): clause for clause in extracted_clauses}
        for future in as_completed(risk_futures):
            clause = risk_futures[future]
            try:
                risk_data = future.result()
                if risk_data.get("contains_risk"):
                    risk_flags.append({
                        "contract_id": contract_id,
                        "clause_title": clause.get("clause_title", "Untitled Clause"),
                        "clause_text": clause.get("clause_text", ""),
                        "created_at": datetime.datetime.utcnow(),
                        "risk_description": risk_data.get("risk_description", "")
                    })
            except Exception as e:
                logger.error("Error analyzing risk for clause: %s", e)

    if risk_flags:
        risk_collection.insert_many(risk_flags)
    logger.info("Identified %d risk clauses.", len(risk_flags))

    # 6) Metadata extraction from contract text
    prompt_meta = f"""
Extract the following metadata from the contract text:
- Effective date
- Parties involved
- Governing law
- Payment schedules

Return valid JSON with keys: effective_date, parties, governing_law, payment_schedules.

TEXT:
{text}
"""
    meta_response = call_llm_api(prompt_meta)
    try:
        metadata = json.loads(meta_response)
    except json.JSONDecodeError:
        metadata = {"effective_date": "unknown", "parties": [], "governing_law": "unknown", "payment_schedules": []}

    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {"metadata": metadata}}
    )
    logger.info("Metadata extracted.")

    return jsonify({
        "status": "success",
        "contract_id": contract_id,
        "clause_count": len(extracted_clauses),
        "risk_count": len(risk_flags),
        "metadata": metadata
    }), 200

@contract_bp.route('/compare_standard_templates', methods=['POST'])
def compare_standard_templates():
    """
    Compare clauses from a contract with ideal template clauses.
    """
    clauses_collection = db['contract_clauses']
    templates_collection = db['standard_templates']

    data = request.get_json() or {}
    contract_id = data.get('contract_id')
    template_id = data.get('template_id')
    user_id = session.get("user_id")

    contract_clauses = list(clauses_collection.find({"contract_id": contract_id}))
    if not contract_clauses:
        return jsonify({"status": "error", "message": "No clauses found or invalid contract_id."}), 404

    template = templates_collection.find_one({"_id": ObjectId(template_id)})
    if not template:
        return jsonify({"status": "error", "message": "Template not found."}), 404

    # Compare clauses using a naive text similarity measure
    results = []
    def naive_distance(a: str, b: str) -> float:
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        return 1.0 - ratio

    for c_clause in contract_clauses:
        best_match = None
        best_score = float('inf')
        for t_clause in template.get("ideal_clauses", []):
            dist = naive_distance(c_clause.get("clause_text", ""), t_clause.get("clause_text", ""))
            if dist < best_score:
                best_score = dist
                best_match = t_clause
        if best_match:
            results.append({
                "contract_clause": c_clause.get("clause_text", ""),
                "template_clause": best_match.get("clause_text", ""),
                "distance": best_score
            })

    return jsonify({"status": "success", "comparisons": results}), 200

@contract_bp.route('/summarize_clauses', methods=['POST'])
def summarize_clauses():
    """
    Rewrite each clause into a concise summary in the desired style.
    """
    clauses_collection = db['contract_clauses']
    data = request.get_json() or {}
    contract_id = data.get('contract_id')
    style = data.get('style', 'plain_english')
    user_id = session.get("user_id")

    contract_clauses = list(clauses_collection.find({"contract_id": contract_id}))
    if not contract_clauses:
        return jsonify({"status": "error", "message": "No clauses found or invalid contract_id."}), 404

    summaries = []
    for clause_doc in contract_clauses:
        clause_text = clause_doc.get("clause_text", "")
        prompt = f"""
Rewrite the following clause in {style} style.
Keep it concise (1-2 sentences).

Clause:
{clause_text}
"""
        summary_text = call_llm_api(prompt).strip()
        summaries.append({
            "clause_title": clause_doc.get("clause_title", "Untitled Clause"),
            "clause_text": clause_text,
            "summary": summary_text
        })

    return jsonify({"status": "success", "summaries": summaries}), 200

@contract_bp.route('/extract_metadata', methods=['POST'])
def extract_metadata():
    """
    Extract metadata fields from a contract.
    """
    contracts_collection = db['contracts']
    data = request.get_json() or {}
    contract_id = data.get('contract_id')
    user_id = session.get("user_id")

    contract_doc = contracts_collection.find_one({"_id": ObjectId(contract_id), "user_id": user_id})
    if not contract_doc:
        return jsonify({"status": "error", "message": "Contract not found."}), 404

    text = contract_doc.get("text", "")
    prompt = f"""
Extract the following fields from the contract text below:
- Effective date
- Parties involved
- Governing law
- Payment schedules
Return a JSON object like:
{{
  "effective_date": "...",
  "parties": ["...", "..."],
  "governing_law": "...",
  "payment_schedules": ["..."]
}}
Text:
{text}
"""
    response = call_llm_api(prompt)
    try:
        metadata = json.loads(response)
    except json.JSONDecodeError:
        metadata = {
            "effective_date": "unknown",
            "parties": [],
            "governing_law": "unknown",
            "payment_schedules": []
        }
    contracts_collection.update_one(
        {"_id": ObjectId(contract_id)},
        {"$set": {"metadata": metadata}}
    )
    return jsonify({"status": "success", "metadata": metadata}), 200

@contract_bp.route('/upload_new_version', methods=['POST'])
def upload_new_version():
    """
    Upload a new version of a contract, generate a diff summary and store the version.
    """
    contract_versions_collection = db['contract_versions']
    contracts_collection = db['contracts']
    user_id = session.get("user_id")

    contract_id = request.form.get("contract_id")
    file = request.files.get("file")
    if not contract_id or not file:
        return jsonify({"status": "error", "message": "Missing contract_id or file."}), 400

    file_bytes = file.read()
    new_text = extract_text(file_bytes, file.content_type)
    old_contract = contracts_collection.find_one({"_id": ObjectId(contract_id), "user_id": user_id})
    if not old_contract:
        return jsonify({"status": "error", "message": "Contract not found or unauthorized."}), 404

    old_text = old_contract.get("text", "")
    diff_result = generate_text_diff(old_text, new_text)
    prompt = f"""
Summarize the differences between the old contract version and the new one:
OLD:
{old_text}
NEW:
{new_text}
Provide a short bullet point list of changes.
"""
    summary_of_changes = call_llm_api(prompt).strip()
    version_doc = {
        "contract_id": contract_id,
        "uploaded_by": user_id,
        "uploaded_at": datetime.datetime.utcnow(),
        "file_name": file.filename,
        "diff": diff_result,
        "summary_of_changes": summary_of_changes,
        "new_text": new_text
    }
    version_id = contract_versions_collection.insert_one(version_doc).inserted_id
    return jsonify({
        "status": "success",
        "version_id": str(version_id),
        "diff_summary": summary_of_changes
    }), 200


@contract_bp.route('/confidence_explanation/<contract_id>', methods=['GET'])
def confidence_explanation(contract_id):
    """
    Retrieve the risk analysis flags (if any) for a given contract.
    """
    risk_collection = db['contract_risks']
    risk_flags = list(risk_collection.find({"contract_id": contract_id}))

    # Convert ObjectId fields to string
    for flag in risk_flags:
        flag['_id'] = str(flag['_id'])
        # If you have other ObjectId fields, convert them too.

    if not risk_flags:
        return jsonify({"status": "success", "message": "No flagged risks found."}), 200

    return jsonify({"status": "success", "risks": risk_flags}), 200


# --------------------------- Register Blueprint ---------------------------
app.register_blueprint(contract_bp, url_prefix="/contract_analysis")

# --------------------------- Main ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)
