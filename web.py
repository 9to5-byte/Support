#!/usr/bin/env python3
"""
Production Web interface for the Support Q&A system.
Run with: python web.py
"""
import os
import sys
import logging
import secrets
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Tuple, Optional, Dict, Any

from flask import Flask, render_template, request, jsonify  # type: ignore[import-untyped]
from flask_limiter import Limiter  # type: ignore[import-untyped]
from flask_limiter.util import get_remote_address  # type: ignore[import-untyped]
from flask_talisman import Talisman  # type: ignore[import-untyped]
from dotenv import load_dotenv
# Uncomment if behind a proxy: from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables
load_dotenv()

# Add SUPPORT directory to path so we can import ask module
sys.path.insert(0, str(Path(__file__).resolve().parent / "SUPPORT"))
from ask import ask_question, PROJECTS  # type: ignore[import-not-found]

# Initialize Flask app
app = Flask(__name__)

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# Secret key for session management
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))

# Security settings
app.config['SESSION_COOKIE_SECURE'] = os.getenv('HTTPS_ENABLED', 'False').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour

# JSON settings
app.config['JSON_SORT_KEYS'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

# If behind a proxy, uncomment this
# app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ============================================================================
# SECURITY HEADERS (Flask-Talisman)
# ============================================================================

# Content Security Policy
csp = {
    'default-src': "'self'",
    'script-src': [
        "'self'",
        "'unsafe-inline'",  # Required for inline scripts - consider removing in production
    ],
    'style-src': [
        "'self'",
        "'unsafe-inline'",  # Required for inline styles
    ],
    'img-src': "'self' data:",
    'font-src': "'self'",
    'connect-src': "'self'",
    'frame-ancestors': "'none'",
}

# Apply security headers
Talisman(
    app,
    force_https=os.getenv('HTTPS_ENABLED', 'False').lower() == 'true',
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,  # 1 year
    content_security_policy=csp,
    content_security_policy_nonce_in=['script-src'],
    referrer_policy='strict-origin-when-cross-origin',
    feature_policy={
        'geolocation': "'none'",
        'camera': "'none'",
        'microphone': "'none'",
    }
)

# ============================================================================
# RATE LIMITING
# ============================================================================

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.getenv('RATE_LIMIT_STORAGE', 'memory://'),
)

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

if not app.debug:
    # Create logs directory if it doesn't exist
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(exist_ok=True)

    # File handler for application logs
    file_handler = RotatingFileHandler(
        log_dir / 'app.log',
        maxBytes=10485760,  # 10MB
        backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)

    # Set log level
    app.logger.setLevel(logging.INFO)
    app.logger.info('Support Q&A Web Interface startup')

# ============================================================================
# INPUT VALIDATION AND SANITIZATION
# ============================================================================

def validate_project(project: Any) -> Tuple[bool, Optional[str]]:
    """Validate project name against allowed projects."""
    if not project or not isinstance(project, str):
        return False, "Invalid project parameter"

    if project not in PROJECTS:
        return False, f"Unknown project: {project}"

    return True, None

def validate_question(question: Any) -> Tuple[bool, Optional[str]]:
    """Validate and sanitize question input."""
    if not question or not isinstance(question, str):
        return False, "Invalid question parameter"

    # Remove leading/trailing whitespace
    question = question.strip()

    # Check length limits
    if len(question) < 3:
        return False, "Question too short (minimum 3 characters)"

    if len(question) > 1000:
        return False, "Question too long (maximum 1000 characters)"

    return True, None

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(400)
def bad_request(e):
    """Handle bad request errors."""
    app.logger.warning(f'Bad request: {e}')
    return jsonify({"error": "Bad request"}), 400

@app.errorhandler(404)
def not_found(e):
    """Handle not found errors."""
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded."""
    app.logger.warning(f'Rate limit exceeded: {get_remote_address()}')
    return jsonify({"error": "Rate limit exceeded. Please try again later."}), 429

@app.errorhandler(500)
def internal_error(e):
    """Handle internal server errors."""
    app.logger.error(f'Internal error: {e}')
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle unexpected exceptions."""
    app.logger.error(f'Unhandled exception: {e}', exc_info=True)
    return jsonify({"error": "An unexpected error occurred"}), 500

# ============================================================================
# ROUTES
# ============================================================================

@app.route("/")
@limiter.limit("30 per minute")
def index():
    """Serve the main page."""
    try:
        return render_template("index.html", projects=list(PROJECTS.keys()))
    except Exception as e:
        app.logger.error(f'Error rendering index: {e}')
        return jsonify({"error": "Error loading page"}), 500

@app.route("/ask", methods=["POST"])
@limiter.limit("10 per minute")
def ask():
    """Handle question requests with strict validation."""
    try:
        # Validate Content-Type
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        # Get and validate input
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON data"}), 400

        project = str(data.get("project", "")).strip()
        question = str(data.get("question", "")).strip()

        # Validate project
        valid, error = validate_project(project)
        if not valid:
            return jsonify({"error": error}), 400

        # Validate question
        valid, error = validate_question(question)
        if not valid:
            return jsonify({"error": error}), 400

        # Log the request (without sensitive data)
        app.logger.info(f'Question asked for project: {project}, length: {len(question)}')

        # Call the ask_question function from ask.py
        result = ask_question(project, question, topk=8, per_source_cap=2)

        if "error" in result:
            app.logger.warning(f'Error from ask_question: {result["error"]}')
            return jsonify(result), 500

        return jsonify(result)

    except Exception as e:
        app.logger.error(f'Error in ask endpoint: {e}', exc_info=True)
        return jsonify({"error": "Error processing request"}), 500

@app.route("/health")
@limiter.exempt
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200

# ============================================================================
# PRODUCTION SERVER
# ============================================================================

def run_production_server() -> None:
    """Run the application with Waitress production server."""
    from waitress import serve  # type: ignore[import-untyped]

    host: str = os.getenv('HOST', '0.0.0.0')
    port: int = int(os.getenv('PORT', '8000'))
    threads: int = int(os.getenv('THREADS', '4'))

    print("=" * 70)
    print("Starting Support Q&A Web Interface (PRODUCTION MODE)")
    print("=" * 70)
    print(f"Server: Waitress WSGI Server")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Threads: {threads}")
    print(f"Security Headers: Enabled")
    print(f"Rate Limiting: Enabled")
    print(f"HTTPS: {'Enabled' if app.config['SESSION_COOKIE_SECURE'] else 'Disabled'}")
    print("=" * 70)
    print(f"\nAccess the application at: http://localhost:{port}")
    print("Press Ctrl+C to stop the server\n")

    serve(
        app,
        host=host,
        port=port,
        threads=threads,
        channel_timeout=60,
        cleanup_interval=30,
        _quiet=False
    )

if __name__ == "__main__":
    # Always run in production mode
    run_production_server()
