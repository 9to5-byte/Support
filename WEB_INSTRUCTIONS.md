# Support Q&A Web Interface

## Quick Start

1. **Install dependencies** (if not already installed):
   ```bash
   pip install -r requirements.txt
   ```

2. **Make sure Ollama is running**:
   - The system expects Ollama at `http://127.0.0.1:11434`
   - You can change this with environment variable: `OLLAMA_HOST`

3. **Start the web server**:
   ```bash
   python web.py
   ```

4. **Open your browser**:
   - Navigate to: `http://localhost:5000`

## How to Use

1. Select a project (DependQ, Revenue, Regard, or Hubble)
2. Type your question in the text area
3. Click "Ask Question" or press Ctrl+Enter / Cmd+Enter
4. Wait for the answer to appear with source links

## Features

- 🎨 Modern, responsive design
- 🚀 Fast vector search with FAISS
- 🤖 Powered by local Ollama models
- 🔗 Clickable source references
- ⌨️ Keyboard shortcuts (Ctrl+Enter to submit)

## Environment Variables

You can customize the following:

- `OLLAMA_HOST` - Ollama server URL (default: http://127.0.0.1:11434)
- `EMBED_MODEL` - Embedding model (default: bge-m3)
- `LLM_MODEL` - Chat model (default: llama2:13b-chat)

Example:
```bash
OLLAMA_HOST=http://192.168.1.100:11434 python web.py
```

## Troubleshooting

**Port already in use?**
Change the port in `web.py`:
```python
app.run(host="0.0.0.0", port=5001, debug=True)
```

**Missing index files?**
Make sure you've built the indices first using the build scripts in `SUPPORT/build/`

**Ollama not responding?**
Check that Ollama is running: `ollama list`
