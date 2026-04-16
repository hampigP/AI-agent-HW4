"""Minimal KG query template for Assignment 4.

Keep these APIs unchanged for auto-test:
- generate_text(messages, max_new_tokens=220)
- get_relevant_articles(question)
- generate_answer(question, rule_results)

Keep Rule fields aligned with build_kg output:
rule_id, type, action, result, art_ref, reg_name
"""

import os
import re
import sqlite3
from typing import Any

from neo4j import GraphDatabase
from dotenv import load_dotenv

from llm_loader import load_local_llm, get_tokenizer, get_raw_pipeline


# ========== 0) Initialization ==========
load_dotenv()

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (
	os.getenv("NEO4J_USER", "neo4j"),
	os.getenv("NEO4J_PASSWORD", "password"),
)

# Avoid local proxy settings interfering with model/Neo4j access.
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
	if key in os.environ:
		del os.environ[key]


try:
	driver = GraphDatabase.driver(URI, auth=AUTH)
	driver.verify_connectivity()
except Exception as e:
	print(f"⚠️ Neo4j connection warning: {e}")
	driver = None


# ========== 1) Public API (query flow order) ==========

def generate_text(messages: list[dict[str, str]], max_new_tokens: int = 220) -> str:
	"""
	Call local HF model via chat template + raw pipeline.
	"""
	tok = get_tokenizer()
	pipe = get_raw_pipeline()
	if tok is None or pipe is None:
		load_local_llm()
		tok = get_tokenizer()
		pipe = get_raw_pipeline()
	prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
	return pipe(prompt, max_new_tokens=max_new_tokens)[0]["generated_text"].strip()


def extract_entities(question: str) -> dict[str, Any]:
	"""Parse question to extract search keywords and intent."""
	q_lower = question.lower()

	# Determine question type
	question_type = "general"
	if any(w in q_lower for w in ["penalty", "penalt", "punish", "deduct", "zero score", "disciplin"]):
		question_type = "penalty"
	elif any(w in q_lower for w in ["fee", "cost", "pay", "ntd", "nt$", "price", "charge"]):
		question_type = "fee"
	elif any(w in q_lower for w in ["how many", "how long", "duration", "days", "minutes", "years", "semester", "credits"]):
		question_type = "duration"
	elif any(w in q_lower for w in ["can i", "is it allowed", "allowed", "permit", "may i"]):
		question_type = "permission"
	elif any(w in q_lower for w in ["what happens", "what is the", "what if"]):
		question_type = "consequence"

	# Extract subject terms (key phrases for search)
	# Remove common question words to get subject terms
	subject = q_lower
	for stop in ["what is the", "what are the", "how many", "how long", "can i", "can a",
				  "is a", "is it", "what happens if", "what happens when",
				  "under what condition", "for a", "for the", "does it", "do i",
				  "will a", "will the", "?"]:
		subject = subject.replace(stop, " ")

	# Clean and split into meaningful terms
	terms = [t.strip() for t in subject.split() if len(t.strip()) > 2]

	# Build search keywords by combining important terms
	subject_terms = []
	# Keep multi-word phrases that are meaningful
	important_phrases = [
		"student id", "exam", "examination", "late", "leave", "cheat", "cheating",
		"electronic device", "question paper", "invigilator", "threaten",
		"easycard", "mifare", "replace", "replacement", "lost",
		"credit", "graduation", "pe", "physical education", "military",
		"bachelor", "undergraduate", "graduate", "master", "phd",
		"passing score", "dismiss", "expel", "make-up exam", "makeup",
		"leave of absence", "suspension", "working days",
		"forgetting", "forget", "penalty", "fee", "duration",
		"communication", "copy", "copying", "notes", "score",
	]
	for phrase in important_phrases:
		if phrase in q_lower:
			subject_terms.append(phrase)

	# Also add individual significant words from the question
	for t in terms:
		if t not in ["the", "for", "and", "that", "this", "with", "from", "are", "was",
					  "were", "been", "being", "have", "has", "had", "will", "would",
					  "could", "should", "may", "might", "shall", "must", "need",
					  "student", "students", "before", "after", "during", "about",
					  "their", "they", "them", "more", "than"] and len(t) > 3:
			if t not in subject_terms:
				subject_terms.append(t)

	return {
		"question_type": question_type,
		"subject_terms": subject_terms[:8],  # limit to top 8 terms
		"aspect": question_type,
	}


def build_typed_cypher(entities: dict[str, Any]) -> tuple[str, str]:
	"""Return (typed_query, broad_query) Cypher queries."""
	terms = entities.get("subject_terms", [])
	qtype = entities.get("question_type", "general")

	if not terms:
		# Fallback: return all rules
		cypher_typed = """
		MATCH (r:Rule)
		RETURN r.rule_id AS rule_id, r.type AS type, r.action AS action,
			   r.result AS result, r.art_ref AS art_ref, r.reg_name AS reg_name,
			   1.0 AS score
		LIMIT 10
		"""
		cypher_broad = """
		CALL db.index.fulltext.queryNodes('article_content_idx', $query)
		YIELD node, score
		RETURN node.number AS number, node.content AS content,
			   node.reg_name AS reg_name, node.category AS category, score
		LIMIT 10
		"""
		return cypher_typed, cypher_broad

	# Build fulltext search string
	search_terms = " OR ".join(terms)

	# Typed query: search in Rule nodes via fulltext index
	cypher_typed = """
	CALL db.index.fulltext.queryNodes('rule_idx', $query)
	YIELD node, score
	WHERE score > 0.5
	RETURN node.rule_id AS rule_id, node.type AS type, node.action AS action,
		   node.result AS result, node.art_ref AS art_ref, node.reg_name AS reg_name,
		   score
	ORDER BY score DESC
	LIMIT 15
	"""

	# Broad query: search in Article content via fulltext index
	cypher_broad = """
	CALL db.index.fulltext.queryNodes('article_content_idx', $query)
	YIELD node, score
	WHERE score > 0.5
	RETURN node.number AS number, node.content AS content,
		   node.reg_name AS reg_name, node.category AS category, score
	ORDER BY score DESC
	LIMIT 10
	"""

	return cypher_typed, cypher_broad


def get_relevant_articles(question: str) -> list[dict[str, Any]]:
	"""Run typed+broad retrieval and return merged rule dicts."""
	if driver is None:
		return []

	entities = extract_entities(question)
	cypher_typed, cypher_broad = build_typed_cypher(entities)

	terms = entities.get("subject_terms", [])
	search_query = " OR ".join(terms) if terms else question

	results = []
	seen_ids = set()

	with driver.session() as session:
		# 1) Typed query: search Rule nodes
		try:
			typed_records = session.run(cypher_typed, query=search_query)
			for record in typed_records:
				rid = record.get("rule_id", "")
				if rid and rid not in seen_ids:
					seen_ids.add(rid)
					results.append({
						"rule_id": rid,
						"type": record.get("type", ""),
						"action": record.get("action", ""),
						"result": record.get("result", ""),
						"art_ref": record.get("art_ref", ""),
						"reg_name": record.get("reg_name", ""),
						"score": record.get("score", 0),
						"source": "rule_index",
					})
		except Exception as e:
			print(f"   ⚠️ Typed query error: {e}")

		# 2) Broad query: search Article content, then fetch linked rules
		try:
			broad_records = session.run(cypher_broad, query=search_query)
			article_refs = []
			for record in broad_records:
				art_num = record.get("number", "")
				reg_name = record.get("reg_name", "")
				content = record.get("content", "")
				if art_num:
					article_refs.append((art_num, reg_name, content))

			# For each matched article, fetch its rules
			for art_num, reg_name, content in article_refs:
				linked_rules = session.run(
					"""
					MATCH (a:Article {number: $num, reg_name: $reg})-[:CONTAINS_RULE]->(r:Rule)
					RETURN r.rule_id AS rule_id, r.type AS type, r.action AS action,
						   r.result AS result, r.art_ref AS art_ref, r.reg_name AS reg_name
					""",
					num=art_num, reg=reg_name,
				)
				for lr in linked_rules:
					rid = lr.get("rule_id", "")
					if rid and rid not in seen_ids:
						seen_ids.add(rid)
						results.append({
							"rule_id": rid,
							"type": lr.get("type", ""),
							"action": lr.get("action", ""),
							"result": lr.get("result", ""),
							"art_ref": lr.get("art_ref", ""),
							"reg_name": lr.get("reg_name", ""),
							"score": 0.5,
							"source": "article_linked",
						})

				# Also include the article content as supplemental context
				if content and len(results) < 20:
					results.append({
						"rule_id": f"ART_{art_num}",
						"type": "article_snippet",
						"action": content[:200],
						"result": content[:200],
						"art_ref": art_num,
						"reg_name": reg_name,
						"score": 0.3,
						"source": "article_content",
					})
		except Exception as e:
			print(f"   ⚠️ Broad query error: {e}")

		# 3) DB keyword fallback if results are sparse
		if len(results) < 3:
			try:
				db_conn = sqlite3.connect("ncu_regulations.db")
				db_cursor = db_conn.cursor()
				for term in terms[:3]:
					db_cursor.execute(
						"SELECT article_number, content, reg_id FROM articles WHERE content LIKE ? LIMIT 5",
						(f"%{term}%",),
					)
					for row in db_cursor.fetchall():
						art_num, content, _ = row
						results.append({
							"rule_id": f"DB_{art_num}",
							"type": "db_fallback",
							"action": content[:200],
							"result": content[:200],
							"art_ref": art_num,
							"reg_name": "",
							"score": 0.2,
							"source": "db_fallback",
						})
				db_conn.close()
			except Exception:
				pass

	# Sort by score descending
	results.sort(key=lambda x: x.get("score", 0), reverse=True)
	return results[:15]


def generate_answer(question: str, rule_results: list[dict[str, Any]]) -> str:
	"""Generate grounded answer from retrieved rules only."""
	if not rule_results:
		return "Insufficient rule evidence to answer this question."

	# Build evidence string
	evidence_parts = []
	for i, r in enumerate(rule_results[:8]):
		src = r.get("reg_name", "")
		ref = r.get("art_ref", "")
		action = r.get("action", "")
		result = r.get("result", "")
		evidence_parts.append(f"[{i+1}] ({src} {ref}) Action: {action} | Result: {result}")

	evidence_text = "\n".join(evidence_parts)

	messages = [
		{
			"role": "system",
			"content": (
				"You are an NCU regulation assistant. Answer the question using ONLY the evidence provided. "
				"Be concise and direct. Cite the source article when possible. "
				"If the evidence does not contain the answer, say 'Insufficient evidence.' "
				"Do NOT make up information."
			),
		},
		{
			"role": "user",
			"content": f"Question: {question}\n\nEvidence:\n{evidence_text}\n\nAnswer:",
		},
	]

	try:
		answer = generate_text(messages, max_new_tokens=200)
		# Clean the answer - remove the prompt echo if present
		if "Answer:" in answer:
			answer = answer.split("Answer:")[-1].strip()
		return answer
	except Exception as e:
		return f"Error generating answer: {e}"


def main() -> None:
	"""Interactive CLI (provided scaffold)."""
	if driver is None:
		return

	load_local_llm()

	print("=" * 50)
	print("🎓 NCU Regulation Assistant (Template)")
	print("=" * 50)
	print("💡 Try: 'What is the penalty for forgetting student ID?'")
	print("👉 Type 'exit' to quit.\n")

	while True:
		try:
			user_q = input("\nUser: ").strip()
			if not user_q:
				continue
			if user_q.lower() in {"exit", "quit"}:
				print("👋 Bye!")
				break

			results = get_relevant_articles(user_q)
			answer = generate_answer(user_q, results)
			print(f"Bot: {answer}")

		except KeyboardInterrupt:
			print("\n👋 Bye!")
			break
		except NotImplementedError as e:
			print(f"⚠️ {e}")
			break
		except Exception as e:
			print(f"❌ Error: {e}")

	driver.close()


if __name__ == "__main__":
	main()
