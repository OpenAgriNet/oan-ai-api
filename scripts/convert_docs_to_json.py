#!/usr/bin/env python3
"""
Document Converter Script

Converts various document formats (Excel, DOCX) to JSON format for RAG indexing.

Usage:
    # Convert a single Excel file
    python scripts/convert_docs_to_json.py --excel assets/Maize.xlsx --output assets/maize_docs.json

    # Convert multiple Excel files
    python scripts/convert_docs_to_json.py --excel assets/Maize.xlsx assets/Tef.xlsx --output assets/crops_docs.json

    # Combine with existing JSON
    python scripts/convert_docs_to_json.py --excel assets/Maize.xlsx --combine assets/existing.json --output assets/combined.json

    # Specify source name and doc prefix
    python scripts/convert_docs_to_json.py --excel assets/Maize.xlsx --source "Maize Guide" --prefix maize --output assets/maize.json

Output Format:
    {
        "documents": [
            {"doc_id": "...", "type": "document", "name": "...", "text": "...", "source": "..."},
            ...
        ]
    }
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def read_excel_file(
    file_path: str,
    text_column: Optional[int] = None,
    name_column: Optional[int] = None,
    min_text_length: int = 50
) -> List[Dict[str, Any]]:
    """
    Read an Excel file and extract documents.

    Args:
        file_path: Path to Excel file
        text_column: Column index containing main text (auto-detected if None)
        name_column: Column index containing document name/category (auto-detected if None)
        min_text_length: Minimum text length to include a document

    Returns:
        List of document dictionaries
    """
    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas not installed. Run: pip install pandas openpyxl")
        sys.exit(1)

    logger.info(f"Reading Excel file: {file_path}")
    df = pd.read_excel(file_path)

    logger.info(f"  Shape: {df.shape}")
    logger.info(f"  Columns: {list(df.columns)}")

    # Auto-detect text column (longest average text length)
    if text_column is None:
        max_avg_len = 0
        for i, col in enumerate(df.columns):
            avg_len = df[col].astype(str).str.len().mean()
            if avg_len > max_avg_len:
                max_avg_len = avg_len
                text_column = i
        logger.info(f"  Auto-detected text column: {text_column} ({df.columns[text_column]})")

    # Auto-detect name column (column after text or one with "category" in name)
    if name_column is None:
        for i, col in enumerate(df.columns):
            col_lower = str(col).lower()
            if 'category' in col_lower or 'name' in col_lower or 'title' in col_lower:
                name_column = i
                break
        if name_column is None and text_column is not None:
            # Try the column after text column
            name_column = text_column + 1 if text_column + 1 < len(df.columns) else None
        if name_column is not None:
            logger.info(f"  Auto-detected name column: {name_column} ({df.columns[name_column]})")

    # Extract documents
    documents = []
    for idx, row in df.iterrows():
        if idx == 0:  # Often header row
            # Check if it looks like a header
            text_val = str(row.iloc[text_column]) if text_column is not None else ""
            if 'content' in text_val.lower() or 'message' in text_val.lower():
                continue

        text = str(row.iloc[text_column]) if text_column is not None and pd.notna(row.iloc[text_column]) else ""
        name = ""
        if name_column is not None and name_column < len(row) and pd.notna(row.iloc[name_column]):
            name = str(row.iloc[name_column])

        # Skip if text is too short or is "nan"
        if not text or text.lower() == "nan" or len(text) < min_text_length:
            continue

        # Clean up name
        if not name or name.lower() == "nan":
            name = f"Section {idx}"

        documents.append({
            "text": text.strip(),
            "name": name.strip(),
            "row_index": idx
        })

    logger.info(f"  Extracted {len(documents)} documents")
    return documents


def create_document_entries(
    raw_docs: List[Dict[str, Any]],
    source: str,
    prefix: str,
    doc_type: str = "document"
) -> List[Dict[str, str]]:
    """
    Create standardized document entries.

    Args:
        raw_docs: List of raw document dicts with 'text' and 'name'
        source: Source attribution
        prefix: Prefix for doc_id
        doc_type: Document type (default: "document")

    Returns:
        List of standardized document entries
    """
    documents = []
    for i, doc in enumerate(raw_docs):
        entry = {
            "doc_id": f"{prefix}_{i:03d}",
            "type": doc_type,
            "name": doc["name"],
            "text": doc["text"],
            "source": source
        }
        documents.append(entry)
    return documents


def load_existing_json(file_path: str) -> List[Dict[str, Any]]:
    """Load existing documents from JSON file."""
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict) and 'documents' in data:
        return data['documents']
    elif isinstance(data, list):
        return data
    return []


def save_documents(documents: List[Dict[str, Any]], output_path: str):
    """Save documents to JSON file."""
    output = {"documents": documents}
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(documents)} documents to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Convert documents (Excel, DOCX) to JSON format for RAG indexing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--excel',
        nargs='+',
        help='Excel file(s) to convert'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output JSON file path'
    )
    parser.add_argument(
        '--source',
        default='Agricultural Guide - Ministry of Agriculture',
        help='Source attribution for documents'
    )
    parser.add_argument(
        '--prefix',
        default='doc',
        help='Prefix for document IDs (e.g., "maize", "tef")'
    )
    parser.add_argument(
        '--combine',
        help='Existing JSON file to combine with'
    )
    parser.add_argument(
        '--text-column',
        type=int,
        help='Column index containing main text (0-based, auto-detected if not specified)'
    )
    parser.add_argument(
        '--name-column',
        type=int,
        help='Column index containing document name/category (0-based, auto-detected if not specified)'
    )
    parser.add_argument(
        '--min-length',
        type=int,
        default=50,
        help='Minimum text length to include a document (default: 50)'
    )

    args = parser.parse_args()

    if not args.excel:
        parser.error("At least one --excel file is required")

    all_documents = []

    # Load existing documents if combining
    if args.combine:
        existing = load_existing_json(args.combine)
        all_documents.extend(existing)
        logger.info(f"Loaded {len(existing)} existing documents from {args.combine}")

    # Process each Excel file
    for excel_file in args.excel:
        # Derive prefix from filename if not specified
        file_prefix = args.prefix
        if args.prefix == 'doc':
            file_prefix = Path(excel_file).stem.lower().replace(' ', '_').replace('translated', '').strip('_')

        # Derive source from filename
        source = args.source
        if 'maize' in excel_file.lower():
            source = "Maize Production Guide - Ministry of Agriculture"
            file_prefix = "maize"
        elif 'tef' in excel_file.lower():
            source = "Tef Production Guide - Ministry of Agriculture"
            file_prefix = "tef"

        raw_docs = read_excel_file(
            excel_file,
            text_column=args.text_column,
            name_column=args.name_column,
            min_text_length=args.min_length
        )

        documents = create_document_entries(
            raw_docs,
            source=source,
            prefix=file_prefix
        )

        all_documents.extend(documents)

    # Save output
    save_documents(all_documents, args.output)

    # Print summary
    print(f"\n{'='*50}")
    print(f"Conversion complete!")
    print(f"{'='*50}")
    print(f"Total documents: {len(all_documents)}")
    print(f"Output file: {args.output}")
    print(f"\nTo index into Cosdata:")
    print(f"  python scripts/index_cosdata.py --file {args.output} --recreate --verify")


if __name__ == '__main__':
    main()
