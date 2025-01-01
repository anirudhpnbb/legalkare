import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

load_dotenv()

# Load API Key from the environment variable
openai_api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("OPENAI_MODEL_NAME")  # Ensure this model name is correct and available


def llm_process(documents_list, model_name, user_query):
    model_llm = ChatOpenAI(model=model_name, openai_api_key=openai_api_key)
    parser = StrOutputParser()
    context = " ".join(documents_list)

    # Construct the prompt with context and user query
    prompt = f"The user is asking: '{user_query}'. Based on the following legal cases: {context}, please answer the user's query."

    messages = [
        SystemMessage(
            content="You are a legal expert AI. Analyze the documents below and answer the user's question accurately and concisely."),
        HumanMessage(content=prompt)
    ]

    # Create a processing chain
    chain = model_llm | parser
    result = chain.invoke(messages)
    return result
