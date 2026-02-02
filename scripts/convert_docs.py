#!/usr/bin/env python3
"""
Convert agricultural documents (DOCX/DOC) to JSON format for Cosdata indexing.

Documents:
1. Diary Final Version.docx - Small-scale Dairy Farming
2. Maize Final Version.docx - Maize Production Guide
3. Teff Final version.doc - Teff Production Guide
"""

import json
import subprocess
from docx import Document
from pathlib import Path

def extract_docx_table_content(file_path: str) -> list:
    """Extract content from DOCX tables, splitting by sections."""
    doc = Document(file_path)
    sections = []

    for table in doc.tables:
        for row in table.rows:
            # Get all cell texts
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if not cells:
                continue

            # The last cell usually contains the main content
            # Other cells are navigation hints like "press 1", "press 2"
            main_content = cells[-1] if cells else ""

            # Skip very short entries or header-like rows
            if len(main_content) < 100:
                continue

            # Try to extract a title from the content
            lines = main_content.split('\n')
            title = lines[0][:80] if lines else "Agricultural Information"

            sections.append({
                "title": title,
                "content": main_content
            })

    return sections


def extract_doc_content(file_path: str) -> list:
    """Extract content from old .doc format using macOS textutil."""
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", file_path],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise Exception(f"Failed to convert {file_path}: {result.stderr}")

    text = result.stdout

    # Split by "To get information" markers to create sections
    sections = []
    current_section = []
    current_title = "Introduction"

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # Check for section markers
        if line.startswith("To get information"):
            # Save previous section if it has content
            if current_section and len("\n".join(current_section)) > 100:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_section)
                })
            current_section = [line]
            # Extract topic from "To get information about X, press N"
            if "about" in line.lower():
                parts = line.lower().split("about")
                if len(parts) > 1:
                    topic = parts[1].split(",")[0].strip()
                    current_title = f"Teff - {topic.title()}"
        else:
            current_section.append(line)

    # Add last section
    if current_section and len("\n".join(current_section)) > 100:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_section)
        })

    return sections


def create_documents_json(output_path: str = "assets/all_agricultural_docs.json"):
    """Process all 3 documents and create JSON output."""

    all_documents = []

    # 1. Process Dairy document
    print("Processing Dairy Final Version.docx...")
    dairy_sections = extract_docx_table_content("assets/Diary Final Version.docx")
    for i, section in enumerate(dairy_sections):
        all_documents.append({
            "doc_id": f"dairy_{i:03d}",
            "type": "document",
            "name": f"Dairy Farming - {section['title'][:50]}",
            "text": section['content'],
            "source": "Small-scale Improved Dairy Cattle Farming Guide - Ministry of Agriculture"
        })
    print(f"  Extracted {len(dairy_sections)} sections")

    # 2. Process Maize document
    print("Processing Maize Final Version.docx...")
    maize_sections = extract_docx_table_content("assets/Maize Final Version.docx")
    for i, section in enumerate(maize_sections):
        all_documents.append({
            "doc_id": f"maize_{i:03d}",
            "type": "document",
            "name": f"Maize Production - {section['title'][:50]}",
            "text": section['content'],
            "source": "Maize Production Guide - Ministry of Agriculture"
        })
    print(f"  Extracted {len(maize_sections)} sections")

    # 3. Process Teff document
    print("Processing Teff Final version.doc...")
    teff_sections = extract_doc_content("assets/Teff Final version.doc")
    for i, section in enumerate(teff_sections):
        all_documents.append({
            "doc_id": f"teff_{i:03d}",
            "type": "document",
            "name": section['title'][:60],
            "text": section['content'],
            "source": "Teff Production Guide - Ministry of Agriculture"
        })
    print(f"  Extracted {len(teff_sections)} sections")

    # Save to JSON
    output = {"documents": all_documents}
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"Total documents: {len(all_documents)}")
    print(f"Output saved to: {output_path}")
    print(f"\nDocument breakdown:")
    print(f"  - Dairy: {len([d for d in all_documents if d['doc_id'].startswith('dairy')])}")
    print(f"  - Maize: {len([d for d in all_documents if d['doc_id'].startswith('maize')])}")
    print(f"  - Teff: {len([d for d in all_documents if d['doc_id'].startswith('teff')])}")

    return all_documents


if __name__ == "__main__":
    create_documents_json()
