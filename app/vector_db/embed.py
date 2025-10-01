from langchain_google_genai import GoogleGenerativeAIEmbeddings
import os
import sys
import dotenv
dotenv.load_dotenv()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from config.config import GOOGLE_API_KEY, EMBEDDING_MODEL_NAME

embedding_model = GoogleGenerativeAIEmbeddings(
    model=EMBEDDING_MODEL_NAME, 
    api_key=GOOGLE_API_KEY
)

def get_embedding_model():
    return embedding_model

if __name__ == "__main__":
    model = get_embedding_model()
    text = "Hello, world!"
    embedding = model.embed_query(text)
    print(f"Embedding for '{text}': {embedding}")
    print(f"Embedding dimension: {len(embedding)}")