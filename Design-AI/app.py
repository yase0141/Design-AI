from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime
import json

# =============================
# CONFIG
# =============================

DEV_MODE = True

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# =============================
# MODELS
# =============================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    plan = db.Column(db.String(50), default="free")
    generations_left = db.Column(db.Integer, default=5)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(10))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)


class ProjectFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    filename = db.Column(db.String(255))
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# =============================
# ROUTES
# =============================

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            return "Email already exists"

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        user = User(name=name, email=email, password=hashed_password)
        db.session.add(user)
        db.session.commit()

        project = Project(name="My First Project", user_id=user.id)
        db.session.add(project)
        db.session.commit()

        return redirect(url_for("signin"))

    return render_template("signup.html")


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))

        return "Invalid credentials"

    return render_template("signin.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("signin"))

    user = User.query.get(session["user_id"])
    if not user:
        session.clear()
        return redirect(url_for("signin"))

    project = Project.query.filter_by(user_id=user.id).first()
    if not project:
        project = Project(name="My First Project", user_id=user.id)
        db.session.add(project)
        db.session.commit()

    messages = Message.query.filter_by(project_id=project.id)\
        .order_by(Message.timestamp).all()

    files = ProjectFile.query.filter_by(project_id=project.id).all()

    return render_template(
        "dashboard.html",
        user=user,
        messages=messages,
        project=project,
        files=files
    )


# =============================
# CHAT GENERATION
# =============================

@app.route("/api/chat", methods=["POST"])
def api_chat():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user = User.query.get(session["user_id"])
    project = Project.query.filter_by(user_id=user.id).first()

    data = request.get_json()
    user_message = data.get("message")

    db.session.add(Message(role="user", content=user_message, project_id=project.id))
    db.session.commit()

    # DEV MODE RESPONSE
    ai_response = """
    {
      "files": [
        {
          "filename": "index.html",
          "content": "<!DOCTYPE html><html><head><title>Builder</title></head><body><h1>Hello Builder</h1><p>This is your generated site.</p></body></html>"
        },
        {
          "filename": "styles.css",
          "content": "body { background:#111; color:white; font-family:Arial; padding:50px;} h1{color:#ff18c8;}"
        },
        {
          "filename": "script.js",
          "content": "console.log('Builder loaded');"
        }
      ]
    }
    """

    parsed = json.loads(ai_response)

    for file in parsed["files"]:
        existing = ProjectFile.query.filter_by(
            project_id=project.id,
            filename=file["filename"]
        ).first()

        if existing:
            existing.content = file["content"]
        else:
            db.session.add(ProjectFile(
                project_id=project.id,
                filename=file["filename"],
                content=file["content"]
            ))

    db.session.commit()

    db.session.add(Message(
        role="assistant",
        content="Site generated.",
        project_id=project.id
    ))
    db.session.commit()

    return jsonify({"ai": "Site generated."})


# =============================
# FILE FETCH
# =============================

@app.route("/file/<int:file_id>")
def get_file(file_id):
    if "user_id" not in session:
        return "Not authorized", 401

    file = ProjectFile.query.get(file_id)
    if not file:
        return "File not found", 404

    return file.content


# =============================
# SAVE FILE (LIVE EDITOR)
# =============================

@app.route("/save-file/<int:file_id>", methods=["POST"])
def save_file(file_id):
    if "user_id" not in session:
        return jsonify({"error": "Not authorized"}), 401

    file = ProjectFile.query.get(file_id)
    if not file:
        return jsonify({"error": "File not found"}), 404

    data = request.get_json()
    file.content = data.get("content")
    db.session.commit()

    return jsonify({"success": True})


# =============================
# PREVIEW (HTML + CSS + JS INJECTION)
# =============================

@app.route("/preview/<int:project_id>")
def preview(project_id):
    files = ProjectFile.query.filter_by(project_id=project_id).all()

    html_file = next((f for f in files if f.filename == "index.html"), None)
    css_file = next((f for f in files if f.filename == "styles.css"), None)
    js_file = next((f for f in files if f.filename == "script.js"), None)

    if not html_file:
        return "No generated site yet."

    html = html_file.content
    css = css_file.content if css_file else ""
    js = js_file.content if js_file else ""

    # Always inject CSS at top of <head>
    injection_css = f"<style>{css}</style>"
    injection_js = f"<script>{js}</script>"

    if "<head>" in html:
        html = html.replace("<head>", f"<head>{injection_css}")
    else:
        html = injection_css + html

    if "</body>" in html:
        html = html.replace("</body>", f"{injection_js}</body>")
    else:
        html += injection_js

    return html

# =============================
# RUN
# =============================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)