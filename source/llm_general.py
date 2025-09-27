import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

load_dotenv()

# Get the API key and model name from the environment.
openai_api_key = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL_NAME")


def call_llm_api(prompt: str,
                 temperature: float = 0.3,
                 max_tokens: int = 3000) -> str:
    """
    A helper function that calls the language model using LangChain's ChatOpenAI.

    :param prompt: The text prompt to send to the model.
    :param temperature: Controls randomness (default 0.3).
    :param max_tokens: Maximum number of tokens in the response.
    :return: The model's output as a string.
    """
    # Initialize the ChatOpenAI model with provided parameters.
    model_llm = ChatOpenAI(
        model=MODEL,
        openai_api_key=openai_api_key,
        temperature=temperature,
        max_tokens=max_tokens
    )

    # Use a string output parser to return a plain string.
    parser = StrOutputParser()

    # Create a list of messages including a system instruction and the user prompt.
    messages = [
        SystemMessage(content="You are a helpful legal expert AI. Answer as concisely and accurately as possible."),
        HumanMessage(content=prompt)
    ]

    # Create a chain by piping the model into the parser.
    chain = model_llm | parser

    # Invoke the chain with the messages.
    result = chain.invoke(messages)

    return result