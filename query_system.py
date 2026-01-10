import os
import sys
import json
for key in ['http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    if key in os.environ:
        del os.environ[key]
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

URI = "bolt://localhost:7687"
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

try:
    driver = GraphDatabase.driver(URI, auth=AUTH)
    driver.verify_connectivity()
except Exception as e:
    print(f"⚠️ Neo4j Connection Warning: {e}")

if not os.getenv("GOOGLE_API_KEY"):
    print("❌ Error: GOOGLE_API_KEY not found! Check your .env file.")

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)

def get_cypher_query():
    """
    Constructs the Cypher query to retrieve the Knowledge Graph data.
    
    Strategy: "Full Context Retrieval"
    Since our database is small (< 200 articles), we retrieve EVERYTHING.
    This ensures 100% recall and lets the LLM do the filtering.
    """
    
    # [TODO]
    # Write a Cypher query to retrieve ALL regulations and their articles.
    #
    # Requirements:
    # 1. Match the pattern: (Regulation) connected to (Article) via [:HAS_ARTICLE].
    # 2. Return three specific fields:
    #    - Regulation Name (e.g., r.name)
    #    - Article Number (e.g., a.number)
    #    - Article Content (e.g., a.content)
    #
    # Hint:
    # MATCH (n:Label)-[:REL]->(m:Label) RETURN n.prop, m.prop...
    
    cypher = ""
    return cypher

def run_query(cypher):
    try:
        with driver.session() as session:
            return [record.data() for record in session.run(cypher)]
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return []

def generate_answer(question, context):
    if not context:
        return "Database is empty."
    context_text = ""
    for item in context:
        reg = item.get('r.name', 'Unknown') #regulation's name
        art = item.get('a.number', 'N/A') #article's number
        text = item.get('a.content', '')
        context_text += f"[{reg}] {art}: {text}\n"

    context_text = context_text[:500000] 

    # [TODO: Student Task 2]
    # Design the Instructions for the LLM.
    # 
    # Your prompt must:
    #  Instruct the LLM to read the ENTIRE context to find the answer.
    #  Instruct the LLM to cite the source (Regulation Name + Article Number).
    #  Handle cases where the answer is not found (tell it to say "I cannot find...").

    template = """
    You are an expert NCU Regulation Assistant.
    You have access to the FULL university regulations below.
    Your job is to read them carefully and find the EXACT answer to the user's question.
    
    User Question: {q}
    
    --- BEGIN REGULATIONS ---
    {c}
    --- END REGULATIONS ---
    
    Instructions:
    [Todo: Fill in your instructions here]
    
    Answer:
    """
    prompt = PromptTemplate(template=template, input_variables=["q", "c"])
    chain = prompt | llm
    
    try:
        return chain.invoke({"q": question, "c": context_text}).content
    except Exception as e:
        return f"LLM Error: {e}"
    
if __name__ == "__main__":
    print("="*50)
    print("🎓 NCU Regulation Assistant")
    print("="*50)
    print("💡 Try asking: 'What is the penalty for cheating?' or 'Min credits for graduation?'")
    print("👉 Type 'exit' or 'quit' to leave.\n")

    print("⏳ Loading knowledge base...", end=" ", flush=True)
    full_context_data = run_query(get_cypher_query())
    print(f"Done! ({len(full_context_data)} articles loaded)")

    while True:
        try:
            user_q = input("\nUser: ").strip()
            if not user_q: continue
            if user_q.lower() in ['exit', 'quit']:
                print("👋 Bye!")
                break
            
            print("🤖 Thinking...")
            answer = generate_answer(user_q, full_context_data)
            print(f"Bot: {answer}")
            
        except KeyboardInterrupt:
            print("\n👋 Bye!")
            break
        except Exception as e:
            print(f"❌ Unexpected Error: {e}")

    driver.close()