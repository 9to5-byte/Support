# How to Use the Documentation Search System

## 📂 Directory Structure

```
C:\code\Support\
├── venv/                          # Python virtual environment
├── config/
│   └── app.yaml                   # Configuration (optional)
├── SUPPORT/
│   ├── docs/                      # PUT YOUR MARKDOWN FILES HERE
│   │   ├── dependq/md/           # DependQ documentation
│   │   ├── hubble/md/            # Hubble documentation
│   │   ├── revenue/md/           # Revenue documentation
│   │   └── regard_depend/md/     # Regard documentation
│   ├── index/                     # Generated FAISS indices (auto-created)
│   ├── build/                     # Index builder scripts
│   ├── templates/                 # Web UI templates
│   └── ask.py                     # CLI query tool
└── requirements.txt
```

---

## 🚀 Step-by-Step Guide to Use With Your Real Documentation

### **Step 1: Add Your Markdown Documentation**

Place your `.md` files in the appropriate project directory:

```bash
# DependQ documentation
C:\code\Support\SUPPORT\docs\dependq\md\

# Hubble documentation
C:\code\Support\SUPPORT\docs\hubble\md\

# Revenue documentation
C:\code\Support\SUPPORT\docs\revenue\md\

# Regard documentation
C:\code\Support\SUPPORT\docs\regard_depend\md\
```

**Important Notes:**
- Remove or replace the sample files I created (they were just for testing)
- Files must be in `.md` (Markdown) format
- You can organize them in subdirectories if needed
- The system will recursively scan all `.md` files in these directories

---

### **Step 2: Start Ollama Service**

Open a terminal and start the Ollama service:

```bash
# Start Ollama (it will run in the background)
"$LOCALAPPDATA/Programs/Ollama/ollama.exe" serve
```

Or simply run:
```bash
ollama serve
```

Leave this running in a separate terminal window.

---

### **Step 3: Build Indices from Your Documentation**

Activate the virtual environment and run the build scripts:

```bash
# Navigate to the project directory
cd C:\code\Support

# Activate virtual environment
.\venv\Scripts\activate

# Build indices for each project (only build the ones you need)
python SUPPORT\build\build_dependq.py
python SUPPORT\build\build_hubble.py
python SUPPORT\build\build_revenue.py
python SUPPORT\build\build_regard.py
```

**What this does:**
- Scans all `.md` files in the project directory
- Chunks the content into searchable segments
- Generates embeddings using BGE-M3
- Creates FAISS vector index
- Saves to `SUPPORT/index/{project}/`

**Expected output:**
```
2025-11-13 21:34:49,362 [INFO] Scanning markdown files in directory: SUPPORT/docs/dependq/md
2025-11-13 21:34:49,377 [INFO] Processed configuration.md: 9 chunks
2025-11-13 21:34:49,390 [INFO] Processed getting_started.md: 11 chunks
2025-11-13 21:34:49,407 [INFO] Total documents processed: 3
2025-11-13 21:34:49,407 [INFO] Total chunks generated: 32
2025-11-13 21:34:49,407 [INFO] Embedding all chunks using model 'bge-m3'...
2025-11-13 21:34:58,255 [INFO] Index build complete. Files generated in SUPPORT/index/dependq
```

---

### **Step 4: Start the Web Interface**

```bash
# Make sure you're in the Support directory with venv activated
cd C:\code\Support
.\venv\Scripts\activate

# Start the web server (production version)
python web.py
```

**Output:**
```
============================================================
Starting Documentation Search Web Interface
============================================================
Server: http://localhost:5000
Ollama: http://127.0.0.1:11434
Projects: dependq, revenue, regard, hubble
============================================================
```

---

### **Step 5: Use the Web Interface**

1. Open your browser and go to: **http://localhost:5000**
2. Select your project (DependQ, Hubble, Revenue, or Regard)
3. Type your question
4. Click "Search Documentation"
5. View the AI-generated answer with source citations

---

## 🔧 Updating Documentation

When you add, remove, or update markdown files:

1. **Stop the web server** (Ctrl+C)
2. **Rebuild the index** for the affected project:
   ```bash
   python SUPPORT\build\build_dependq.py
   ```
3. **Restart the web server**:
   ```bash
   python web.py
   ```

---

## 💻 Alternative: CLI Interface

You can also use the command-line interface instead of the web UI:

```bash
# Activate virtual environment
.\venv\Scripts\activate

# Query using CLI
python SUPPORT\ask.py --dependq "How do I configure the database?"
python SUPPORT\ask.py --hubble "How do I create alerts?"
python SUPPORT\ask.py --revenue "How do I integrate with Stripe?"
python SUPPORT\ask.py --regard "What are the GDPR compliance features?"
```

---

## 📝 Configuration Options

### Custom Ollama Settings

Edit `SUPPORT/ask.py` to customize:

```python
OLLAMA_URL = "http://127.0.0.1:11434"  # Ollama server URL
EMBED_MODEL = "bge-m3"                  # Embedding model
LLM_MODEL = "llama2:13b-chat"           # Language model
```

### Retrieval Settings

In `SUPPORT/ask.py`, you can adjust:

```bash
# Change number of chunks to retrieve
python SUPPORT\ask.py --dependq --topk 12 "your question"

# Change max chunks per source file
python SUPPORT\ask.py --dependq --per-source-cap 3 "your question"
```

---

## 🛠️ Troubleshooting

### Issue: "Ollama connection failed"
**Solution:** Make sure Ollama is running:
```bash
ollama serve
```

### Issue: "Model not found"
**Solution:** Pull the required models:
```bash
ollama pull bge-m3
ollama pull llama2:13b-chat
```

### Issue: "No files found in directory"
**Solution:** Check that your `.md` files are in the correct directory:
- `SUPPORT/docs/{project}/md/`

### Issue: "Index files not found"
**Solution:** Build the indices first:
```bash
python SUPPORT\build\build_dependq.py
```

### Issue: "Dimension mismatch"
**Solution:** The embedding model changed. Rebuild all indices:
```bash
python SUPPORT\build\build_dependq.py
python SUPPORT\build\build_hubble.py
python SUPPORT\build\build_revenue.py
python SUPPORT\build\build_regard.py
```

---

## 🎯 Quick Start Summary

```bash
# 1. Add your .md files to SUPPORT/docs/{project}/md/

# 2. Start Ollama
ollama serve

# 3. Build indices (in new terminal)
cd C:\code\Support
.\venv\Scripts\activate
python SUPPORT\build\build_dependq.py

# 4. Start web interface
python web.py

# 5. Open browser
# Go to http://localhost:5000
```

---

## 📊 System Requirements

- **Python**: 3.14.0 (installed)
- **Ollama**: 0.12.10 (installed)
- **Models**:
  - BGE-M3 (1.2 GB) ✓
  - Llama2:13b-chat (7.4 GB) ✓
- **RAM**: 8GB minimum (16GB recommended for large documentation sets)
- **Disk**: ~10GB for models + space for your documentation

---

## 📞 Support

All services have been stopped. When you're ready with your real documentation:
1. Place `.md` files in the appropriate directories
2. Follow the steps above
3. Your documentation will be searchable via the web interface

Good luck with your documentation! 🚀
