import os
import uuid
from collections import defaultdict

import spacy
from spacy.pipeline import EntityRuler
from spacy.language import Language
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# ---------------------------- Configuration and Setup ---------------------------- #

# Load environment variables from a .env file
load_dotenv()

# Load API Key and Model Name from the environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("OPENAI_MODEL_NAME")  # Ensure this model name is correct and available

# Initialize spaCy transformer-based English model for better NER accuracy
try:
    nlp = spacy.load("en_core_web_trf")
except OSError:
    # If the transformer model is not installed, fall back to the smaller model
    print("Transformer-based spaCy model not found. Falling back to 'en_core_web_sm'.")
    nlp = spacy.load("en_core_web_sm")

# ---------------------------- Register Custom EntityRuler ---------------------------- #

@Language.factory("custom_entity_ruler")
def create_custom_entity_ruler(nlp, name):
    ruler = EntityRuler(nlp, overwrite_ents=True)
    patterns = [
        {"label": "PERSON", "pattern": [{"LOWER": "sri"}, {"IS_TITLE": True}, {"IS_TITLE": True}, {"IS_PUNCT": True, "OP": "?"}, {"IS_TITLE": True}]},
        {"label": "PERSON", "pattern": [{"LOWER": "smt"}, {"IS_TITLE": True}, {"IS_TITLE": True}, {"IS_PUNCT": True, "OP": "?"}, {"IS_TITLE": True}]},
        # Add more patterns as needed to capture complex names
    ]
    ruler.add_patterns(patterns)
    return ruler

# Add the EntityRuler to the pipeline with a unique name
nlp.add_pipe("custom_entity_ruler", before="ner")

# Define sensitive entity types to be replaced with placeholders
SENSITIVE_ENTITIES = ["PERSON", "ORG", "GPE", "DATE", "LOC", "MONEY", "EMAIL", "PHONE"]

# Initialize MongoDB connection for storing placeholder mappings
mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
mongodb_db = os.getenv("MONGODB_DB", "legal_documents")
mongodb_collection = os.getenv("MONGODB_COLLECTION", "placeholder_mappings")

try:
    mongo_client = MongoClient(mongodb_uri)
    db = mongo_client[mongodb_db]
    collection = db[mongodb_collection]
    print("Connected to MongoDB successfully.")
except PyMongoError as e:
    print(f"Failed to connect to MongoDB: {e}")
    exit(1)

# ---------------------------- Placeholder Functions ---------------------------- #

def sanitize_text(text, doc_id):
    """
    Replace sensitive entities in the text with placeholders.

    Args:
        text (str): The original text.
        doc_id (str): A unique identifier for the document/session.

    Returns:
        str: The sanitized text with placeholders.
    """
    doc = nlp(text)
    mapping = {}
    entity_counters = defaultdict(int)

    # Collect all entities that need to be sanitized
    entities = [ent for ent in doc.ents if ent.label_ in SENSITIVE_ENTITIES]

    # Sort entities by their start character position
    # Prioritize longer entities to handle nested entities
    entities = sorted(entities, key=lambda x: (x.start_char, -x.end_char))

    # Replace entities from the end to avoid shifting positions
    sanitized_text = text
    for ent in reversed(entities):
        entity_type = ent.label_
        entity_text = ent.text

        # Increment counter for this entity type to ensure unique placeholders
        entity_counters[entity_type] += 1
        placeholder = f"{{{entity_type}_{entity_counters[entity_type]}}}"

        # Replace the exact span of the entity with the placeholder
        start = ent.start_char
        end = ent.end_char
        sanitized_text = sanitized_text[:start] + placeholder + sanitized_text[end:]

        # Store the mapping of placeholder to original entity
        mapping[placeholder] = entity_text

    # Store the mapping with the doc_id in MongoDB
    try:
        collection.insert_one({
            "_id": doc_id,
            "mapping": mapping
        })
    except PyMongoError as e:
        print(f"Failed to insert mapping into MongoDB: {e}")
        return text  # Return original text if mapping storage fails

    return sanitized_text

def restore_text(text, doc_id):
    """
    Replace placeholders in the text with the original sensitive entities.

    Args:
        text (str): The text containing placeholders.
        doc_id (str): The unique identifier for the document/session.

    Returns:
        str: The text with placeholders replaced by original entities.
    """
    try:
        record = collection.find_one({"_id": doc_id})
        if record and "mapping" in record:
            mapping = record["mapping"]
        else:
            mapping = {}
    except PyMongoError as e:
        print(f"Failed to retrieve mapping from MongoDB: {e}")
        mapping = {}

    restored_text = text
    for placeholder, original in mapping.items():
        restored_text = restored_text.replace(placeholder, original)

    # Optionally, delete the mapping from MongoDB after restoration to free up space
    try:
        collection.delete_one({"_id": doc_id})
    except PyMongoError as e:
        print(f"Failed to delete mapping from MongoDB: {e}")

    return restored_text

# ---------------------------- LLM Processing Function ---------------------------- #

def llm_process_chat(documents_list, model_name, user_query):
    """
    Process the user query against the provided documents, handling sensitive information.

    Args:
        documents_list (list): List of document texts.
        model_name (str): Name of the OpenAI model to use.
        user_query (str): The user's query.

    Returns:
        str: The LLM's response with sensitive information restored.
    """
    # Initialize ChatOpenAI model with the specified model and API key
    try:
        model_llm = ChatOpenAI(model=model_name, openai_api_key=openai_api_key)
    except Exception as e:
        return f"Failed to initialize ChatOpenAI model: {e}"

    # Initialize the output parser to extract string responses
    parser = StrOutputParser()

    # Combine all documents into a single context string
    context = " ".join(documents_list)

    # Generate a unique document session ID using UUID
    doc_session_id = str(uuid.uuid4())

    # Sanitize the context by replacing sensitive entities with placeholders
    sanitized_context = sanitize_text(context, doc_session_id)
    print(sanitized_context)

    # Construct the prompt with sanitized context and user query
    prompt = f"The user is asking: '{user_query}'. Based on the following legal cases: {sanitized_context}, please answer the user's query."

    # Define the system and human messages for the chat
    messages = [
        SystemMessage(
            content="You are a legal expert AI. Analyze the documents below and answer the user's question accurately and concisely."
        ),
        HumanMessage(content=prompt)
    ]

    # Create a processing chain using LangChain's pipeline (LLM followed by parser)
    try:
        chain = model_llm | parser
    except Exception as e:
        return f"Failed to create processing chain: {e}"

    try:
        # Invoke the chain with the messages to get the sanitized response
        sanitized_response = chain.invoke(messages)
    except Exception as e:
        # Handle exceptions (logging can be added here)
        return f"An error occurred during LLM processing: {e}"

    # Restore the original sensitive information in the LLM's response
    final_response = restore_text(sanitized_response, doc_session_id)

    return final_response
