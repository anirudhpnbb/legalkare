import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv
import textwrap  # for wrapping text into manageable sizes

load_dotenv()

# Load API Key from the environment variable
openai_api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("OPENAI_MODEL_NAME")  # Ensure this model name is correct and available

def tokenize(text):
    """Estimate the number of tokens using a simple heuristic based on OpenAI's tokenizer behavior."""
    return len(text.split())

def llm_summariser(documents_list, model_name, user_query, remaining_tokens):
    model_llm = ChatOpenAI(model=model_name, openai_api_key=openai_api_key)
    parser = StrOutputParser()

    if isinstance(documents_list, list):
        documents = " ".join(documents_list)
    else:
        documents = documents_list

    # Split large document into smaller parts if necessary
    max_segment_size = os.getenv("SEGMENT_SIZE")  # Adjust as necessary for model's token capacity
    segments = textwrap.wrap(documents, max_segment_size, break_long_words=False, replace_whitespace=False)

    results = []
    for segment in segments:
        input_tokens = tokenize(segment)
        max_output_tokens = max(50, min(30000 - input_tokens, remaining_tokens // len(segments)))

        model_llm.max_tokens = max_output_tokens

        prompt = f"Summarize the following content: {segment}"
        messages = [
            SystemMessage(content="You are an AI trained to summarize documents efficiently."),
            HumanMessage(content=prompt)
        ]

        chain = model_llm | parser
        result = chain.invoke(messages)
        results.append(result)

    # Combine results or process them as needed
    combined_result = " ".join(results)
    return combined_result

# Example usage:
# documents_list = ["Very large document text..."]
# summarized_content = llm_summariser(documents_list, model_name, "Please summarize", 25000)
# print(summarized_content)
