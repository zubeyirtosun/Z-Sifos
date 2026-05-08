"""
RAG Test Suite — Tests document upload, indexing, and retrieval.
Run: python test_rag.py
"""

import os
import json
import tempfile
import shutil
from pathlib import Path
from backend.database import SessionLocal, engine
from backend import models
from backend.rag import index_document, retrieve_chunks


def setup_test_db():
    """Create test database and tables."""
    models.Base.metadata.create_all(bind=engine)
    return SessionLocal()


def create_test_files(tmpdir):
    """Create test documents."""
    files = {}
    
    # Test 1: Simple Text File
    txt_file = Path(tmpdir) / "test.txt"
    txt_file.write_text("""
    Python is a high-level programming language known for its simplicity.
    It is widely used in web development, data science, and artificial intelligence.
    Python developers appreciate its clean syntax and extensive libraries.
    The Python community is active and supportive.
    """)
    files['txt'] = txt_file
    
    # Test 2: Markdown File
    md_file = Path(tmpdir) / "test.md"
    md_file.write_text("""
    # Machine Learning Guide
    
    Machine learning enables computers to learn from data.
    
    ## Supervised Learning
    - Classification: predicting categories
    - Regression: predicting continuous values
    
    ## Unsupervised Learning
    - Clustering: grouping similar data
    - Dimensionality reduction: feature extraction
    
    Deep learning uses neural networks for complex data.
    """)
    files['md'] = md_file
    
    # Test 3: CSV File
    csv_file = Path(tmpdir) / "test.csv"
    csv_file.write_text("""
    name,age,profession,experience
    Alice,30,Software Engineer,8
    Bob,25,Data Scientist,3
    Charlie,35,DevOps Engineer,10
    Diana,28,ML Engineer,5
    """)
    files['csv'] = csv_file
    
    return files


def test_single_document_index():
    """Test: Index a single document."""
    print("\n[TEST 1] Single Document Indexing")
    db = setup_test_db()
    
    # Create agent
    agent = models.AgentModel(
        name="test-agent-1",
        model_name="test-model",
        provider="ollama",
        document_enabled=True,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    tmpdir = tempfile.mkdtemp()
    try:
        files = create_test_files(tmpdir)
        
        # Index TXT file
        txt_path = files['txt']
        index_document(agent.id, txt_path, "test.txt")
        
        # Check if embeddings were created
        embed_dir = Path(__file__).parent.parent / "data" / "embeddings" / str(agent.id)
        meta_file = embed_dir / "meta.json"
        
        if meta_file.exists():
            with open(meta_file) as f:
                metadata = json.load(f)
            print(f"✅ Indexed {len(metadata)} chunks from test.txt")
            assert len(metadata) > 0, "No chunks created"
        else:
            print("❌ Meta file not created")
            return False
        
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        db.delete(agent)
        db.commit()


def test_retrieval_accuracy():
    """Test: Query-based retrieval accuracy."""
    print("\n[TEST 2] Retrieval Accuracy")
    db = setup_test_db()
    
    agent = models.AgentModel(
        name="test-agent-2",
        model_name="test-model",
        provider="ollama",
        document_enabled=True,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    tmpdir = tempfile.mkdtemp()
    try:
        files = create_test_files(tmpdir)
        
        # Index MD file (ML content)
        md_path = files['md']
        index_document(agent.id, md_path, "test.md")
        
        # Test retrieval
        queries = [
            ("machine learning clustering", "Unsupervised Learning"),
            ("neural networks deep learning", "Deep learning"),
            ("supervised classification regression", "Supervised"),
        ]
        
        passed = 0
        for query, expected_keyword in queries:
            chunks = retrieve_chunks(agent.id, query, top_k=3)
            if chunks:
                combined_text = " ".join([c['text'] for c in chunks])
                if expected_keyword.lower() in combined_text.lower():
                    print(f"  ✅ Query '{query}' → Found '{expected_keyword}'")
                    passed += 1
                else:
                    print(f"  ⚠️  Query '{query}' → Missing '{expected_keyword}'")
            else:
                print(f"  ❌ Query '{query}' → No results")
        
        accuracy = (passed / len(queries)) * 100
        print(f"Retrieval Accuracy: {accuracy:.1f}% ({passed}/{len(queries)})")
        return accuracy >= 60  # 60% threshold
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        db.delete(agent)
        db.commit()


def test_multi_format_indexing():
    """Test: Index multiple document formats."""
    print("\n[TEST 3] Multi-Format Indexing")
    db = setup_test_db()
    
    agent = models.AgentModel(
        name="test-agent-3",
        model_name="test-model",
        provider="ollama",
        document_enabled=True,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    tmpdir = tempfile.mkdtemp()
    try:
        files = create_test_files(tmpdir)
        
        indexed = 0
        for fmt, path in files.items():
            try:
                index_document(agent.id, path, f"test.{fmt}")
                print(f"  ✅ Indexed {fmt.upper()} file")
                indexed += 1
            except Exception as e:
                print(f"  ❌ Failed to index {fmt.upper()}: {e}")
        
        print(f"Multi-format: {indexed}/{len(files)} formats indexed")
        return indexed >= 2  # At least 2 formats
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        db.delete(agent)
        db.commit()


def test_chunk_metadata():
    """Test: Verify chunk metadata structure."""
    print("\n[TEST 4] Chunk Metadata Structure")
    db = setup_test_db()
    
    agent = models.AgentModel(
        name="test-agent-4",
        model_name="test-model",
        provider="ollama",
        document_enabled=True,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    
    tmpdir = tempfile.mkdtemp()
    try:
        files = create_test_files(tmpdir)
        index_document(agent.id, files['txt'], "test.txt")
        
        embed_dir = Path(__file__).parent.parent / "data" / "embeddings" / str(agent.id)
        meta_file = embed_dir / "meta.json"
        
        with open(meta_file) as f:
            metadata = json.load(f)
        
        # Verify structure
        required_fields = ['filename', 'chunk_index', 'text_length', 'text']
        if metadata:
            chunk = metadata[0]
            missing = [f for f in required_fields if f not in chunk]
            if missing:
                print(f"  ❌ Missing fields: {missing}")
                return False
            
            print(f"  ✅ Metadata structure is valid")
            print(f"  - Chunk count: {len(metadata)}")
            print(f"  - Sample chunk: {len(chunk['text'])} chars")
            return True
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        db.delete(agent)
        db.commit()


def run_all_tests():
    """Run all RAG tests."""
    print("=" * 60)
    print("RAG TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Document Indexing", test_single_document_index),
        ("Retrieval Accuracy", test_retrieval_accuracy),
        ("Multi-Format Support", test_multi_format_indexing),
        ("Metadata Structure", test_chunk_metadata),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = test_func()
            results[name] = result
        except Exception as e:
            print(f"❌ Error in {name}: {e}")
            results[name] = False
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} — {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
