import os
import sys
for key in ['http_proxy', 'https_proxy', 'all_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    if key in os.environ:
        del os.environ[key]

import json
import time
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv
from query_system import get_cypher_query, run_query, generate_answer

load_dotenv()

if not os.getenv("GOOGLE_API_KEY"):
    print("❌ Error: GOOGLE_API_KEY not found!")

judge_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite", 
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

def ask_bot(question):
    """取得 Bot 的回答"""
    try:
        cypher = get_cypher_query(question)
        context = run_query(cypher)
        final_answer = generate_answer(question, context)
        return final_answer
    except Exception as e:
        return f"Error: {str(e)}"

def evaluate_with_llm(question, expected, actual):
    judge_template = """
    You are an impartial judge evaluating a Q&A system for university regulations.
    
    Question: {question}
    Expected Answer: {expected}
    Actual Answer from Bot: {actual}
    
    Task:
    Determine if the 'Actual Answer' conveys the same key information as the 'Expected Answer'.
    1. If the bot says "I couldn't find information" or gives a wrong number/fact, mark as FAIL.
    2. Ignore minor wording differences (e.g., "20 mins" vs "twenty minutes" is PASS).
    3. If the bot provides MORE details than expected but the core fact is correct, mark as PASS.
    
    Return strictly only one word: PASS or FAIL.
    """
    
    prompt = PromptTemplate(template=judge_template, input_variables=["question", "expected", "actual"])
    chain = prompt | judge_llm
    
    try:
        result = chain.invoke({
            "question": question, 
            "expected": expected, 
            "actual": actual
        }).content.strip()
        
        if "PASS" in result.upper():
            return "PASS"
        return "FAIL"
    except Exception as e:
        return f"FAIL (Judge Error: {str(e)})"

def run_llm_evaluation():
    try:
        with open("test_data.json", "r", encoding="utf-8") as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print("❌ Error: test_data.json not found!")
        return

    print(f"🚀 Starting LLM-based Evaluation for {len(test_cases)} Questions...\n")
    
    passed_count = 0
    results_log = []

    for i, case in enumerate(test_cases):
        qid = case["id"]
        question = case["question"]
        expected_answer = case["answer"]
        
        print(f"Testing Q{qid}: {question}")
        
        start_time = time.time()
        bot_answer = ask_bot(question)
        
        verdict = evaluate_with_llm(question, expected_answer, bot_answer)
        duration = time.time() - start_time
        
        status_icon = "✅" if "PASS" in verdict else "❌"
        if "PASS" in verdict:
            passed_count += 1
            
        print(f"  -> Bot Says: {bot_answer.strip()}")
        print(f"  -> Judge: {status_icon} {verdict} (Time: {duration:.2f}s)")
        print("-" * 50)
        
        results_log.append({
            "id": qid,
            "question": question,
            "expected": expected_answer,
            "bot_response": bot_answer,
            "result": verdict
        })

    print("\n" + "="*30)
    print(f"📊 Evaluation Summary")
    print(f"Total: {len(test_cases)}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {len(test_cases) - passed_count}")
    if len(test_cases) > 0:
        print(f"Accuracy: {(passed_count / len(test_cases)) * 100:.1f}%")
    print("="*30)

if __name__ == "__main__":
    run_llm_evaluation()