#!/usr/bin/env python3
"""
Test 15 questions (5 per document type) against Cosdata search.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.tools.search_cosdata import search_documents_cosdata

# 5 Questions for Dairy Farming
DAIRY_QUESTIONS = [
    "What are the best housing requirements for dairy cattle?",
    "How do I detect heat in dairy cows for breeding?",
    "What is the importance of colostrum for newborn calves?",
    "How can I prevent mastitis in dairy cows?",
    "What are the characteristics of Holstein Friesian cattle?",
]

# 5 Questions for Maize Production
MAIZE_QUESTIONS = [
    "What is the recommended seed rate for maize planting?",
    "How do I prepare a field for maize cultivation?",
    "What fertilizers should I use for maize production?",
    "When is the best time to harvest maize?",
    "How should maize be stored after harvesting?",
]

# 5 Questions for Teff Production
TEFF_QUESTIONS = [
    "What is the recommended seeding rate for teff?",
    "How do I prepare land for teff planting?",
    "What is the row sowing method for teff?",
    "How do I control pests in teff fields?",
    "What is the proper threshing method for teff?",
]

def test_questions():
    """Test all 15 questions and print results."""
    all_questions = {
        "Dairy": DAIRY_QUESTIONS,
        "Maize": MAIZE_QUESTIONS,
        "Teff": TEFF_QUESTIONS,
    }

    results = []

    for category, questions in all_questions.items():
        print(f"\n{'='*60}")
        print(f"Testing {category} Questions")
        print('='*60)

        for i, question in enumerate(questions, 1):
            print(f"\n[{category} Q{i}] {question}")
            print("-" * 50)

            result = search_documents_cosdata(question, top_k=3)

            # Check if results were found
            has_results = "No results found" not in result and "Error" not in result

            if has_results:
                # Count number of results
                num_results = result.count("----") + 1 if "----" in result else 1
                print(f"✓ Found {num_results} result(s)")
                # Print first 300 chars of first result
                lines = result.split('\n')
                preview = '\n'.join(lines[:8])
                if len(preview) > 400:
                    preview = preview[:400] + "..."
                print(preview)
            else:
                print(f"✗ No results: {result[:200]}")

            results.append({
                "category": category,
                "question": question,
                "success": has_results,
                "result_preview": result[:500] if has_results else result
            })

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)

    success_count = sum(1 for r in results if r["success"])
    print(f"Total: {success_count}/{len(results)} questions returned results")

    for category in ["Dairy", "Maize", "Teff"]:
        cat_results = [r for r in results if r["category"] == category]
        cat_success = sum(1 for r in cat_results if r["success"])
        print(f"  {category}: {cat_success}/5")

    # List failures
    failures = [r for r in results if not r["success"]]
    if failures:
        print(f"\nFailed questions:")
        for r in failures:
            print(f"  - [{r['category']}] {r['question']}")

    return results

if __name__ == "__main__":
    test_questions()
