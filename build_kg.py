import sqlite3
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
AUTH = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))

def build_graph():
    sql_conn = sqlite3.connect("ncu_regulations.db")
    cursor = sql_conn.cursor()
    driver = GraphDatabase.driver(URI, auth=AUTH)

    print("🚀 Building Knowledge Graph (English)...")

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

        # ==========================================
        # Step 1: Create Regulation Nodes
        # ==========================================
        cursor.execute("SELECT reg_id, name, category FROM regulations")
        regs = cursor.fetchall()
        for r in regs:
            reg_id, reg_name, reg_category = r
            # [TODO: Student Task 1]
            # Write a Cypher query to create a 'Regulation' node.
            #
            # Requirements:
            # 1. Use `MERGE` to ensure we don't create duplicate nodes if run multiple times.
            # 2. The node must have the label `Regulation`.
            # 3. Match/Create by the `id` property (using the parameter $rid).
            # 4. Set the `name` property to $name.
            # 5. Set the `category` property to $cat.
            #
            # Hint:
            # MERGE (n:Label {key: $param}) SET n.prop = $val
            
            cypher_regulation = """
            
            """
            if cypher_regulation.strip():
                session.run(cypher_regulation, rid=reg_id, name=reg_name, cat=reg_category)

        # ==========================================
        # Step 2: Create Article Nodes & Relationships
        # ==========================================
        cursor.execute("SELECT reg_id, article_number, content FROM articles")
        arts = cursor.fetchall()
        count = 0
        for a in arts:
            reg_id, art_num, content = a
            
            # [TODO: Student Task 2]
            # Write a Cypher query to:
            # 1. Find the parent Regulation node (using MATCH).
            # 2. Create a new Article node (using CREATE).
            # 3. Link them with a relationship (using MERGE).
            #
            # Requirements:
            # A. MATCH the Regulation node `r` where `id` equals $rid.
            # B. CREATE an Article node `a` with properties:
            #    - `number`: $num
            #    - `content`: $content
            # C. Create a relationship `HAS_ARTICLE` from `r` to `a`.
            #    - Pattern: (Regulation)-[:HAS_ARTICLE]->(Article)
            #
            # Hint:
            # MATCH (p:Parent {id: $pid})
            # CREATE (c:Child {prop: $val})
            # MERGE (p)-[:REL_NAME]->(c)

            cypher_article = """
            
            """
            if cypher_article.strip():
                session.run(cypher_article, rid=reg_id, num=art_num, content=content)
            count += 1

    print(f"✅ Knowledge Graph Built! ({count} articles imported)")
    driver.close()
    sql_conn.close()

if __name__ == "__main__":
    build_graph()