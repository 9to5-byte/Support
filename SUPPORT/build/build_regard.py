#!/usr/bin/env python3
import os
import re
import json
import math
import datetime
import logging
import httpx
import numpy as np
import faiss
import yaml   # using pyyaml if needed for config (not strictly required here)

# Configure logging for clear progress output
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Parameters (could be made configurable via args or a YAML config)
INPUT_DIR = os.getenv("MARKDOWN_INPUT_DIR", "SUPPORT/docs/regard_depend/md")  # source markdown files directory
OUTPUT_DIR = os.getenv("INDEX_OUTPUT_DIR", "SUPPORT/index/regard_depend")     # output index directory
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")                        # embedding model name for Ollama
BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))                  # batch size for embedding API calls
CHUNK_TOKEN_LIMIT = int(os.getenv("CHUNK_TOKEN_LIMIT", "300"))         # approx token limit per chunk (for splitting large blocks)
CHUNK_CHAR_LIMIT = int(os.getenv("CHUNK_CHAR_LIMIT", "1200"))          # approx char limit (rough heuristic for token limit)
CHUNK_OVERLAP_CHARS = int(os.getenv("CHUNK_OVERLAP_CHARS", "100"))     # overlap in chars if chunk is split

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

def split_markdown_to_chunks(text, file_name):
    """Split a markdown text into chunks using headings and paragraphs."""
    chunks = []
    # Normalize newlines and collapse multiple blank lines to at most 2
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = text.split("\n")
    in_code = False
    code_buffer = ""
    current_paragraph = ""
    # Track heading context
    current_h1 = None
    current_h2 = None
    current_h3 = None
    current_h4 = None
    current_h5 = None
    current_h6 = None

    def finalize_paragraph():
        """Helper to finalize the current paragraph as a chunk (with context)."""
        nonlocal current_paragraph, current_h1, current_h2, current_h3, current_h4, current_h5, current_h6
        paragraph_text = current_paragraph.strip()
        if paragraph_text == "":
            return
        # Assemble metadata and content
        title = current_h1 or os.path.basename(file_name)
        # Headings list (exclude title to avoid duplication)
        headings = []
        for h in (current_h2, current_h3, current_h4, current_h5, current_h6):
            if h:
                headings.append(h)
        # Create chunk entry
        chunk = {
            "file": os.path.basename(file_name),
            "title": title,
            "headings": headings,
            "text": paragraph_text
        }
        chunks.append(chunk)
        current_paragraph = ""

    for line in lines:
        # Heading detection (if not inside a code block)
        if not in_code and line.strip().startswith("#"):
            # Finalize any paragraph/content collected so far before a new section starts
            if current_paragraph.strip():
                finalize_paragraph()
            # Count heading level (number of leading #)
            header_match = re.match(r"^(#{1,6})\s+(.*)", line.strip())
            if header_match:
                level = len(header_match.group(1))
                heading_text = header_match.group(2).strip()
                # Update heading context based on level
                if level == 1:
                    current_h1 = heading_text
                    current_h2 = current_h3 = current_h4 = current_h5 = current_h6 = None
                elif level == 2:
                    current_h2 = heading_text
                    current_h3 = current_h4 = current_h5 = current_h6 = None
                elif level == 3:
                    current_h3 = heading_text
                    current_h4 = current_h5 = current_h6 = None
                elif level == 4:
                    current_h4 = heading_text
                    current_h5 = current_h6 = None
                elif level == 5:
                    current_h5 = heading_text
                    current_h6 = None
                elif level == 6:
                    current_h6 = heading_text
            # Do not include the heading text itself in the chunk content (it's captured in metadata)
            continue

        # Code block start/end detection
        if line.strip().startswith("```"):
            if not in_code:
                # Starting a code block
                # Finalize any current paragraph before entering code block (so code becomes separate chunk)
                if current_paragraph.strip():
                    finalize_paragraph()
                in_code = True
                code_buffer = line.strip()  # include the ``` line (could include language)
            else:
                # Ending a code block
                code_buffer += "\n" + line.strip()
                # Finalize code block as a chunk
                if code_buffer.strip():
                    # Use the same heading context for this code block
                    title = current_h1 or os.path.basename(file_name)
                    headings = []
                    for h in (current_h2, current_h3, current_h4, current_h5, current_h6):
                        if h:
                            headings.append(h)
                    chunk = {
                        "file": os.path.basename(file_name),
                        "title": title,
                        "headings": headings,
                        "text": code_buffer
                    }
                    chunks.append(chunk)
                code_buffer = ""
                in_code = False
            continue

        # If currently inside a code block, accumulate code lines
        if in_code:
            code_buffer += "\n" + line
            continue

        # If we reach here, we're not in a code block, not a heading line
        if line.strip() == "":
            # Blank line indicates end of a paragraph/list section
            if current_paragraph.strip():
                finalize_paragraph()
            # else: multiple blank lines are already collapsed above, so just continue
        else:
            # Append line to current paragraph text
            # If the line is part of a list or table, keep the newline (so list items remain separate lines in text)
            if line.lstrip().startswith("-") or line.lstrip().startswith("*") or re.match(r"^\d+\.", line.lstrip()):
                # List item or numbered list – keep line breaks to preserve item separation
                current_paragraph += (("\n" if current_paragraph else "") + line.strip())
            elif line.strip().startswith("|"):
                # Table row – also preserve as-is (tables use '|' and newline for each row)
                current_paragraph += (("\n" if current_paragraph else "") + line)
            else:
                # Regular text line – combine with a space if continuing the same paragraph
                if current_paragraph.endswith("-"):
                    # If previous line ends with a hyphen (maybe a broken word or list indicator), just append
                    current_paragraph += line.strip()
                else:
                    # Otherwise, add a space before adding the next line to maintain spacing
                    current_paragraph += ((" " if current_paragraph else "") + line.strip())
    # End of for lines loop

    # Finalize any remaining paragraph after loop
    if current_paragraph.strip():
        finalize_paragraph()

    # Now apply chunk size limit splitting if any chunk text is very large
    # (We split those chunks by sentences or rough length, with overlap)
    refined_chunks = []
    for chunk in chunks:
        text = chunk["text"]
        if len(text) <= CHUNK_CHAR_LIMIT:
            refined_chunks.append(chunk)
        else:
            # If a chunk is too large, split it into sub-chunks
            # We'll split by sentences (naively by period) or by character length if no obvious sentence breaks.
            sentences = re.split(r'(?<=[.!?])\s+', text)
            sub_chunk_text = ""
            for sentence in sentences:
                if not sentence:
                    continue
                # If adding this sentence would exceed char limit, finalize current sub-chunk
                if sub_chunk_text and len(sub_chunk_text) + len(sentence) > CHUNK_CHAR_LIMIT:
                    # finalize sub-chunk
                    sub_chunk_text = sub_chunk_text.strip()
                    if sub_chunk_text:
                        new_chunk = chunk.copy()
                        new_chunk["text"] = sub_chunk_text
                        refined_chunks.append(new_chunk)
                    # start new sub-chunk with overlap: prepend last CHUNK_OVERLAP_CHARS of previous to next if available
                    if CHUNK_OVERLAP_CHARS > 0 and len(sub_chunk_text) > 0:
                        overlap = sub_chunk_text[-CHUNK_OVERLAP_CHARS:]
                    else:
                        overlap = ""
                    sub_chunk_text = overlap + " " + sentence
                else:
                    # continue accumulating
                    sub_chunk_text += (" " + sentence)
            # Add any remaining text as final chunk
            sub_chunk_text = sub_chunk_text.strip()
            if sub_chunk_text:
                new_chunk = chunk.copy()
                new_chunk["text"] = sub_chunk_text
                refined_chunks.append(new_chunk)
    return refined_chunks

def embed_chunks(chunk_texts):
    """Call the Ollama embedding API to embed a list of chunk texts. Returns list of embeddings."""
    embeddings = []
    url = "http://localhost:11434/api/embed"
    headers = {"Content-Type": "application/json"}
    # Ollama allows multiple inputs in one request
    for i in range(0, len(chunk_texts), BATCH_SIZE):
        batch = chunk_texts[i:i+BATCH_SIZE]
        data = {"model": EMBED_MODEL, "input": batch}
        try:
            resp = httpx.post(url, json=data, headers=headers, timeout=300.0)
        except Exception as e:
            logging.error(f"Embedding request failed for batch starting at index {i}: {e}")
            raise
        if resp.status_code != 200:
            logging.error(f"Embedding API returned status {resp.status_code}: {resp.text}")
            raise RuntimeError(f"Embedding API error: {resp.status_code}")
        result = resp.json()
        batch_embeddings = result.get("embeddings")
        if batch_embeddings is None:
            logging.error(f"No 'embeddings' in response for batch starting at index {i}: {result}")
            raise RuntimeError("Invalid response from embedding API")
        # Extend our list
        embeddings.extend(batch_embeddings)
        logging.info(f"Embedded batch {i//BATCH_SIZE + 1} / {math.ceil(len(chunk_texts)/BATCH_SIZE)}")
    return embeddings

def main():
    logging.info(f"Scanning markdown files in directory: {INPUT_DIR}")
    if not os.path.isdir(INPUT_DIR):
        logging.error(f"Input directory not found: {INPUT_DIR}")
        return 1
    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".md") or f.endswith(".markdown")]
    files.sort()  # sort for consistency
    if not files:
        logging.error("No markdown files found in input directory.")
        return 1

    all_chunks = []
    total_docs = 0
    for file in files:
        file_path = os.path.join(INPUT_DIR, file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            logging.error(f"Failed to read file {file}: {e}")
            continue
        total_docs += 1
        # Split file into chunks
        chunks = split_markdown_to_chunks(text, file)
        logging.info(f"Processed {file}: {len(chunks)} chunks")
        # Assign unique IDs to chunks, e.g., <filename_without_ext>_<index>
        base_id = os.path.splitext(os.path.basename(file))[0]
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{base_id}_{idx}"
            chunk["id"] = chunk_id
            all_chunks.append(chunk)
    total_chunks = len(all_chunks)
    if total_chunks == 0:
        logging.error("No chunks generated from the files. Aborting.")
        return 1

    logging.info(f"Total documents processed: {total_docs}")
    logging.info(f"Total chunks generated: {total_chunks}")

    # Embed all chunk texts
    chunk_texts = [chunk["text"] for chunk in all_chunks]
    logging.info(f"Embedding all chunks using model '{EMBED_MODEL}' in batches of {BATCH_SIZE}...")
    try:
        embeddings = embed_chunks(chunk_texts)
    except Exception as e:
        logging.error(f"Embedding process failed: {e}")
        return 1
    if len(embeddings) != total_chunks:
        logging.error(f"Number of embeddings ({len(embeddings)}) does not match number of chunks ({total_chunks})")
        return 1

    # Convert embeddings to numpy array
    emb_array = np.array(embeddings, dtype='float32')
    dim = emb_array.shape[1]  # embedding dimension
    logging.info(f"Embedding dimension: {dim}. Building FAISS index...")

    # Build FAISS index (Inner Product for similarity)
    index = faiss.IndexFlatIP(dim)
    index.add(emb_array)
    faiss_index_path = os.path.join(OUTPUT_DIR, "chunks.faiss")
    try:
        faiss.write_index(index, faiss_index_path)
    except Exception as e:
        logging.error(f"Failed to write FAISS index to disk: {e}")
        return 1

    # Write chunks.json (list of chunk texts for quick reference)
    chunks_json_path = os.path.join(OUTPUT_DIR, "chunks.json")
    try:
        with open(chunks_json_path, "w", encoding="utf-8") as cj:
            # You can choose to write just texts or the whole chunk objects.
            # Here we'll write just the text list for memory efficiency.
            json.dump([chunk["text"] for chunk in all_chunks], cj, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to write chunks.json: {e}")
        return 1

    # Write corpus.jsonl (detailed chunk metadata and content)
    corpus_jsonl_path = os.path.join(OUTPUT_DIR, "corpus.jsonl")
    try:
        with open(corpus_jsonl_path, "w", encoding="utf-8") as cj:
            for chunk in all_chunks:
                # Write each chunk as a JSON line
                cj.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error(f"Failed to write corpus.jsonl: {e}")
        return 1

    # Write manifest.json (build metadata)
    manifest = {
        "built_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_directory": INPUT_DIR,
        "index_directory": OUTPUT_DIR,
        "documents_indexed": total_docs,
        "chunks_indexed": total_chunks,
        "embedding_model": EMBED_MODEL,
        "embedding_dimensions": dim,
        "chunking_strategy": "markdown_structured", 
        "chunk_token_limit": CHUNK_TOKEN_LIMIT,
        "chunk_char_limit": CHUNK_CHAR_LIMIT,
        "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
        "batch_size": BATCH_SIZE,
        "index_type": "IndexFlatIP",
        "faiss_metric": "inner_product"
    }
    manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
    try:
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2)
    except Exception as e:
        logging.error(f"Failed to write manifest.json: {e}")
        return 1

    logging.info(f"Index build complete. Files generated in {OUTPUT_DIR}")
    return 0

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
