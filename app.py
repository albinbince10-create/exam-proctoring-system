import cv2
import numpy as np
import base64

import os
import json
import requests
from PyPDF2 import PdfReader
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
from flask import Flask, render_template, request, redirect, session
from db import get_db
from datetime import datetime
from werkzeug.security import check_password_hash, generate_password_hash
import hashlib

app = Flask(__name__)
app.secret_key = "quiz_secret_key"


# HOME PAGE
@app.route("/")
def home():
    return render_template("home.html", year=datetime.now().year)


# LOGIN PAGE
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"].strip()

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if user:
            role = user["role"].strip().lower()

            if role == "admin":
                error = "Admin users cannot login here. Please use the admin login page."
            else:
                db_pass = user["password"]

                # bcrypt OR sha256 (same as PHP)
                if (
                    check_password_hash(db_pass, password)
                    or hashlib.sha256(password.encode()).hexdigest() == db_pass
                ):
                    session["user_id"] = user["id"]
                    session["user_name"] = user["name"]
                    session["role"] = user["role"]
                    return redirect("/user_dashboard")
                else:
                    error = "Invalid Email or Password!"
        else:
            error = "No user found with this email!"

    return render_template("login.html", error=error)

# --- ADMIN DASHBOARD ---
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/admin")
    
    db = get_db()
    
    # 1. Fetch all exams
    quizzes = db.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    
    # 2. Fetch all students
    users = db.execute("SELECT id, name, email FROM users WHERE role='user' ORDER BY id DESC").fetchall()
    
    # 3. Fetch all test results
    results = db.execute("""
        SELECT r.id, u.name as student_name, q.title as quiz_title, r.score, r.attempted_on 
        FROM results r
        JOIN users u ON r.user_id = u.id
        JOIN quizzes q ON r.quiz_id = q.id
        ORDER BY r.attempted_on DESC
    """).fetchall()

    return render_template("dashboard.html", quizzes=quizzes, users=users, results=results)

from flask import Response

@app.route("/download_results")
def download_results():
    if session.get("role") != "admin":
        return redirect("/admin")
    
    db = get_db()
    results = db.execute("""
        SELECT u.name, q.title, r.score, r.attempted_on 
        FROM results r
        JOIN users u ON r.user_id = u.id
        JOIN quizzes q ON r.quiz_id = q.id
        ORDER BY r.attempted_on DESC
    """).fetchall()

    def generate():
        # Column Headers
        yield 'Student Name,Exam Title,Score,Date & Time\n'
        # Data Rows
        for r in results:
            yield f"{r['name']},{r['title']},{r['score']},{r['attempted_on']}\n"

    return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=exam_results.csv'})

# --- ADMIN MANAGEMENT CONTROLS ---
@app.route("/delete_quiz/<int:quiz_id>")
def delete_quiz(quiz_id):
    if session.get("role") != "admin": 
        return redirect("/admin")
    
    db = get_db()
    db.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
    db.execute("DELETE FROM questions WHERE quiz_id=?", (quiz_id,))
    db.execute("DELETE FROM results WHERE quiz_id=?", (quiz_id,))
    db.commit()
    return redirect("/dashboard")

@app.route("/delete_user/<int:user_id>")
def delete_user(user_id):
    if session.get("role") != "admin": 
        return redirect("/admin")
    
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.execute("DELETE FROM results WHERE user_id=?", (user_id,))
    db.commit()
    return redirect("/dashboard")

# ADD QUIZ (MANUAL)
@app.route("/add_quiz", methods=["GET", "POST"])
def add_quiz():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/login")

    if request.method == "POST":
        title = request.form["title"]
        time_limit = request.form.get("time_limit", 10) 
        
        db = get_db()
        
        # --- THE FIX: Assign a category just like the AI generator does! ---
        cat = db.execute("SELECT id FROM categories LIMIT 1").fetchone()
        if not cat:
            cursor = db.execute("INSERT INTO categories (name) VALUES ('General')")
            category_id = cursor.lastrowid
        else:
            category_id = cat['id']
        
        # Now we save the quiz with the category_id included
        cursor = db.execute(
            "INSERT INTO quizzes (category_id, title, time_limit) VALUES (?, ?, ?)", 
            (category_id, title, time_limit)
        )
        quiz_id = cursor.lastrowid 
        db.commit()
        
        return redirect(f"/add_question/{quiz_id}")

    return render_template("add_quiz.html")

# ADD QUESTION
@app.route("/add_question/<int:quiz_id>", methods=["GET", "POST"])
def add_question(quiz_id):
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/login")

    if request.method == "POST":
        db = get_db()
        db.execute("""
            INSERT INTO questions
            (quiz_id, question, option_a, option_b, option_c, option_d, correct_option)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            quiz_id,
            request.form["question"],
            request.form["a"],
            request.form["b"],
            request.form["c"],
            request.form["d"],
            request.form["correct"]
        ))
        db.commit()
        # Stay on the same page so the admin can keep adding more questions!
        return redirect(f"/add_question/{quiz_id}")

    return render_template("add_question.html", quiz_id=quiz_id)

# USER QUIZ LIST
@app.route("/quizzes")
def quizzes():
    db = get_db()
    quizzes = db.execute("SELECT * FROM quizzes").fetchall()
    return render_template("quizzes.html", quizzes=quizzes)


# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# USER REGISTER
@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]

        db = get_db()

        # check if email exists
        existing = db.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if existing:
            error = "Email already registered!"
        else:
            hashed = generate_password_hash(password)
            db.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                (name, email, hashed, "user")
            )
            db.commit()
            return redirect("/login")

    return render_template("register.html", error=error)


# ADMIN LOGIN
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    error = ""

    if session.get("role") == "admin":
        return redirect("/dashboard")

    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"].strip()

        db = get_db()
        admin = db.execute(
            "SELECT * FROM users WHERE LOWER(TRIM(role))='admin' AND email=?",
            (email,)
        ).fetchone()

        if admin:
            if password == admin["password"]:
                session["user_id"] = admin["id"]
                session["user_name"] = admin["name"]
                session["role"] = admin["role"]
                return redirect("/dashboard")
            else:
                error = "Invalid Email or Password!"
        else:
            error = "No admin found with this email!"

    return render_template("admin_login.html", error=error)

@app.route("/user_dashboard")
def user_dashboard():
    if "user_id" not in session or session.get("role") != "user":
        return redirect("/login")

    db = get_db()

    quizzes = db.execute("""
        SELECT q.*, c.name AS category_name
        FROM quizzes q
        LEFT JOIN categories c ON q.category_id = c.id
    """).fetchall()

    results = db.execute("""
        SELECT r.*, q.title
        FROM results r
        LEFT JOIN quizzes q ON r.quiz_id = q.id
        WHERE r.user_id = ?
        ORDER BY r.attempted_on DESC
        LIMIT 10
    """, (session["user_id"],)).fetchall()

    return render_template(
        "user_dashboard.html",
        quizzes=quizzes,
        results=results
    )


# --- FIXED: Only ONE start_quiz function here! ---
@app.route("/start_quiz/<int:quiz_id>")
def start_quiz(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    
    quiz = db.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    questions = db.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,)).fetchall()

    # Renders your AJAX take_quiz.html template and passes the time_limit
    return render_template("take_quiz.html", questions=questions, quiz_id=quiz_id, time_limit=quiz["time_limit"])

@app.route("/get_question")
def get_question():
    quiz_id = request.args.get("quiz_id")
    q = int(request.args.get("q"))

    db = get_db()
    questions = db.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,)).fetchall()

    if q >= len(questions):
        return ""

    question = questions[q]

    return f"""
    <h5 class='mb-3'>{question['question']}</h5>
    <button class='option-btn btn btn-outline-primary' data-option='a'>{question['option_a']}</button>
    <button class='option-btn btn btn-outline-primary' data-option='b'>{question['option_b']}</button>
    <button class='option-btn btn btn-outline-primary' data-option='c'>{question['option_c']}</button>
    <button class='option-btn btn btn-outline-primary' data-option='d'>{question['option_d']}</button>
    """


@app.route("/check_answer", methods=["POST"])
def check_answer():
    quiz_id = request.form.get("quiz_id")
    q = int(request.form.get("q"))
    answer = request.form.get("answer")

    db = get_db()
    questions = db.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,)).fetchall()

    correct = questions[q]["correct_option"]

    if answer == correct:
        return "correct"
    else:
        return "wrong"

    
@app.route("/result/<int:quiz_id>")
def result(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    score = db.execute(
        "SELECT score FROM results WHERE user_id=? AND quiz_id=? ORDER BY attempted_on DESC LIMIT 1",
        (session["user_id"], quiz_id)
    ).fetchone()

    return render_template("result.html", score=score)  

@app.route("/upload_pdf", methods=["GET", "POST"])
def upload_pdf():
    if session.get("role") != "admin":
        return redirect("/admin")

    if request.method == "POST":
        file = request.files.get("pdf")
        
        # --- NEW: Grab custom settings from the form ---
        num_questions = request.form.get("num_questions", "10")
        time_limit = request.form.get("time_limit", "10")
        
        if file and file.filename.endswith('.pdf'):
            import google.generativeai as genai
            
            # 1. Read PDF Text
            reader = PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            text = text[:8000] # Gemini can easily handle larger chunks of text

            # 2. Formulate the Prompt (DYNAMIC NUMBER OF QUESTIONS)
            prompt = f"""You are an expert quiz generator.
            Read the following text extracted from a PDF and create exactly {num_questions} multiple-choice questions strictly based on it.
            Return ONLY a valid JSON array. Each object in the array must have this exact structure:
            {{
              "question": "Question text",
              "options": {{ "a": "Option 1", "b": "Option 2", "c": "Option 3", "d": "Option 4" }},
              "answer": "a"
            }}
            
            Text to analyze:
            {text}
            """

            # 3. Call the Gemini API
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return render_template("upload_pdf.html", error="Missing GEMINI_API_KEY in .env file.")

            genai.configure(api_key=api_key)
            
            try:
                # Using gemini-2.5-flash with JSON mode enabled for guaranteed clean output
                model = genai.GenerativeModel('gemini-2.5-flash')
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                
                quiz_data = json.loads(response.text)
                
                # --- NEW: Pass time_limit to the review page so it gets saved! ---
                return render_template("review_ai_quiz.html", quiz_data=quiz_data, json_string=json.dumps(quiz_data), time_limit=time_limit)

            except Exception as e:
                return render_template("upload_pdf.html", error=f"Error connecting to Gemini AI: {str(e)}")
        else:
            return render_template("upload_pdf.html", error="Please upload a valid PDF file.")

    return render_template("upload_pdf.html")

@app.route("/save_ai_quiz", methods=["POST"])
def save_ai_quiz():
    if session.get("role") != "admin":
        return redirect("/admin")
    
    title = request.form.get("quiz_title")
    quiz_json_string = request.form.get("quiz_json")
    
    # --- NEW: Grab the time limit passed from the review page ---
    time_limit = request.form.get("time_limit", 10) 
    
    db = get_db()
    
    cat = db.execute("SELECT id FROM categories LIMIT 1").fetchone()
    if not cat:
        cursor = db.execute("INSERT INTO categories (name) VALUES ('General')")
        category_id = cursor.lastrowid
    else:
        category_id = cat['id']
    
    # --- NEW: Save the time_limit into the quizzes table! ---
    cursor = db.execute(
        "INSERT INTO quizzes (category_id, title, time_limit) VALUES (?, ?, ?)", 
        (category_id, title, time_limit)
    )
    quiz_id = cursor.lastrowid
    
    if quiz_json_string:
        questions = json.loads(quiz_json_string)
        for q in questions:
            opts = q["options"]
            db.execute("""
                INSERT INTO questions (quiz_id, question, option_a, option_b, option_c, option_d, correct_option)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                quiz_id, 
                q["question"], 
                opts.get("a", opts.get("A")), 
                opts.get("b", opts.get("B")), 
                opts.get("c", opts.get("C")), 
                opts.get("d", opts.get("D")), 
                q["answer"].lower()
            ))
            
    db.commit()
    return redirect("/dashboard")

@app.route("/save_score", methods=["POST"])
def save_score():
    if "user_id" not in session:
        return "error"
    
    quiz_id = request.form.get("quiz_id")
    score = request.form.get("score")
    
    db = get_db()
    db.execute(
        "INSERT INTO results (user_id, quiz_id, score, attempted_on) VALUES (?, ?, ?, ?)",
        (session["user_id"], quiz_id, score, datetime.now())
    )
    db.commit()
    return "success"

@app.route("/vision_check", methods=["POST"])
def vision_check():
    try:
        # 1. Get the base64 image from the Javascript frontend
        image_data = request.form.get("image")
        if not image_data:
            return "OK"

        # 2. Decode the base64 string into an OpenCV image
        encoded_data = image_data.split(',')[1]
        nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 3. Load OpenCV's built-in face detector
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

        # 4. Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # --- 🔥 NEW: NIGHT VISION (LOW LIGHT ENHANCEMENT) 🔥 ---
        # CLAHE forces high contrast on dark images so the AI can see your face structure
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced_gray = clahe.apply(gray)
        # --------------------------------------------------------

        # 5. Detect faces using the ENHANCED image instead of the dark one
        faces = face_cascade.detectMultiScale(enhanced_gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        face_count = len(faces)

        # 6. Return the result
        if face_count == 0:
            return "WARNING: No face detected! Please look at the screen or adjust lighting."
        elif face_count > 1:
            return "WARNING: Multiple faces detected! No cheating allowed."
        else:
            return "OK"

    except Exception as e:
        print(f"Camera Error: {e}")
        return "OK"
    
# --- LEADERBOARD ---
@app.route("/leaderboard/<int:quiz_id>")
def leaderboard(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db()
    
    # Get the name of the quiz
    quiz = db.execute("SELECT title FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    
    # Get the top 10 highest scores for this specific quiz
    # We use MAX(score) and GROUP BY u.id so one student doesn't take up the whole board!
    leaders = db.execute("""
        SELECT u.name, MAX(r.score) as best_score, r.attempted_on
        FROM results r
        JOIN users u ON r.user_id = u.id
        WHERE r.quiz_id = ?
        GROUP BY u.id
        ORDER BY best_score DESC, r.attempted_on ASC
        LIMIT 10
    """, (quiz_id,)).fetchall()

    return render_template("leaderboard.html", leaders=leaders, quiz=quiz)

if __name__ == "__main__":
    app.run(debug=True)