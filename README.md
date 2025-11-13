# Support - Documentation Search System

A RAG (Retrieval-Augmented Generation) based documentation search system using FAISS for vector indexing and Ollama for embeddings and language model inference.

## Overview

This system indexes markdown documentation from multiple projects and provides semantic search capabilities powered by AI models.

## Prerequisites

- Python 3.14+ (installed)
- Ollama (for embeddings and LLM inference)

## Setup

### 1. Python Environment

A virtual environment has been created with all required dependencies:

```bash
# Activate the virtual environment
# On Windows:
venv\Scripts\activate

# On Linux/Mac:
source venv/bin/activate
```

### 2. Ollama Setup

Ollama is required for embeddings and language model inference:

1. Ollama is installed at: `C:\Users\<username>\AppData\Local\Programs\Ollama`
2. Required models:
   - `bge-m3` (for embeddings)
   - `llama2:13b-chat` (for LLM responses)

To pull the models:
```bash
ollama pull bge-m3
ollama pull llama2:13b-chat
```

### 3. Documentation Structure

Documentation files are stored in:
```
SUPPORT/docs/
├── dependq/md/       # DependQ documentation
├── hubble/md/        # Hubble documentation
├── regard/md/        # Regard documentation
└── revenue/md/       # Revenue documentation
```

### 4. Building Indices

Run the build scripts to create search indices:

```bash
# Build all indices
python SUPPORT/build/build_dependq.py
python SUPPORT/build/build_hubble.py
python SUPPORT/build/build_regard.py
python SUPPORT/build/build_revenue.py

# Or use the PowerShell script (Windows)
.\rebuild_support.ps1
```

## Usage

### Searching Documentation

Use the `ask.py` script to search across indexed documentation:

```bash
python SUPPORT/ask.py --project dependq --query "How do I install?"
```

Available projects:
- `dependq`
- `hubble`
- `regard`
- `revenue`

## Project Structure

```
├── SUPPORT/
│   ├── ask.py                 # Main query interface
│   ├── build/                  # Index building scripts
│   │   ├── build_dependq.py
│   │   ├── build_hubble.py
│   │   ├── build_regard.py
│   │   └── build_revenue.py
│   ├── docs/                   # Source markdown files
│   └── index/                  # Generated FAISS indices
├── config/
│   └── app.yaml               # Configuration file
├── scripts/                    # Utility scripts
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

## Configuration

Edit `config/app.yaml` to customize:
- Ollama URL and models
- Retrieval parameters
- Index directories

## Dependencies

Key Python packages:
- `faiss-cpu` - Vector similarity search
- `numpy` - Numerical operations
- `httpx` - HTTP client for Ollama API
- `beautifulsoup4`, `lxml` - HTML/Markdown parsing
- `rich` - CLI formatting

## Notes

- The system requires Ollama to be running on `localhost:11434`
- Indices are rebuilt from scratch when running build scripts with `--force`
- Embedding model must match between build time and query time
