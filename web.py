#!/usr/bin/env python3
"""
Web interface for the Support Q&A system.
Run with: python web.py
Access at: http://localhost:5000
"""
from flask import Flask, render_template, request, jsonify
import sys
from pathlib import Path

# Add SUPPORT directory to path so we can import ask module
sys.path.insert(0, str(Path(__file__).resolve().parent / "SUPPORT"))
from ask import ask_question, PROJECTS

app = Flask(__name__)

@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html", projects=list(PROJECTS.keys()))

@app.route("/ask", methods=["POST"])
def ask():
    """Handle question requests."""
    data = request.get_json()
    project = data.get("project")
    question = data.get("question")

    if not project or not question:
        return jsonify({"error": "Missing project or question"}), 400

    if project not in PROJECTS:
        return jsonify({"error": f"Unknown project: {project}"}), 400

    # Call the ask_question function from ask.py
    result = ask_question(project, question, topk=8, per_source_cap=2)

    if "error" in result:
        return jsonify(result), 500

    return jsonify(result)

if __name__ == "__main__":
    print("Starting Support Q&A Web Interface...")
    print("Access the application at: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
