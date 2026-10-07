import csv, io, os, sqlite3, psycopg2, psycopg2.extras, requests
from datetime import datetime
from decimal import Decimal, InvalidOperation
from dotenv import load_dotenv
load_dotenv()
from functools import wraps
from flask import Flask, abort, render_template, request, redirect, session, flash, url_for
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder=".")
app.secret_key = os.getenv("SECRET_KEY", "change-me")
DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = Path(os.getenv("DATABASE_PATH", str(Path(app.instance_path) / "school.sqlite3")))
DSN = os.getenv("DATABASE_URL", "dbname=school user=postgres password=postgres host=localhost")
DEFAULT_EXAMS = ["Quarterly", "Half Yearly", "Annual"]

def db(q, a=(), one=False, write=False):
    if DATABASE_URL:
        with psycopg2.connect(DATABASE_URL) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(q, a)
                if write: return None
                return cursor.fetchone() if one else cursor.fetchall()

    connection = sqlite3.connect(SQLITE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        cursor = connection.cursor()
        values = tuple(float(value) if isinstance(value, Decimal) else value for value in a)
        cursor.execute(q.replace("%s", "?"), values)
        if write:
            connection.commit()
            return None
        return cursor.fetchone() if one else cursor.fetchall()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def _initialize_sqlite():
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).with_name("schema.sqlite.sql")
    with sqlite3.connect(SQLITE_PATH, detect_types=sqlite3.PARSE_DECLTYPES) as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))

if not DATABASE_URL:
    _initialize_sqlite()

def _migrate_schema():
    db("""CREATE TABLE IF NOT EXISTS school_classes (
        id SERIAL PRIMARY KEY, standard TEXT NOT NULL, section TEXT NOT NULL, year TEXT NOT NULL,
        UNIQUE (standard, section, year))""", write=True)
    subject_teacher_id = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    db(f"""CREATE TABLE IF NOT EXISTS class_subject_teachers (
        id {subject_teacher_id}, class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
        name TEXT NOT NULL, subject TEXT NOT NULL, UNIQUE (class_id, name, subject))""", write=True)
    db("""CREATE TABLE IF NOT EXISTS exam_types (
        id SERIAL PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
        name TEXT NOT NULL, UNIQUE (class_id, name))""", write=True)
    db("""CREATE TABLE IF NOT EXISTS exam_papers (
        id SERIAL PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
        exam TEXT NOT NULL, paper TEXT NOT NULL, UNIQUE (class_id, exam, paper))""", write=True)
    db("""CREATE TABLE IF NOT EXISTS reviews (
        id SERIAL PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        body TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""", write=True)
    db("""CREATE TABLE IF NOT EXISTS student_delete_requests (
        id SERIAL PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        teacher_id INTEGER NOT NULL REFERENCES teachers(id), status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""", write=True)
    if DATABASE_URL:
        for table, column, definition in (
            ("teachers", "class_id", "INTEGER REFERENCES school_classes(id)"),
            ("teachers", "subject", "TEXT"),
            ("students", "class_id", "INTEGER REFERENCES school_classes(id)"),
            ("students", "age", "INTEGER"),
            ("students", "date_of_birth", "TEXT"),
            ("students", "blood_group", "TEXT"),
            ("students", "gender", "TEXT"),
        ):
            db(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}", write=True)
    else:
        for table, column, definition in (
            ("teachers", "class_id", "INTEGER REFERENCES school_classes(id)"),
            ("teachers", "subject", "TEXT"),
            ("students", "class_id", "INTEGER REFERENCES school_classes(id)"),
            ("students", "age", "INTEGER"),
            ("students", "date_of_birth", "TEXT"),
            ("students", "blood_group", "TEXT"),
            ("students", "gender", "TEXT"),
        ):
            columns = {row["name"] for row in db(f"PRAGMA table_info({table})")}
            if column not in columns:
                db(f"ALTER TABLE {table} ADD COLUMN {column} {definition}", write=True)
        roster_columns = {row["name"]: row for row in db("PRAGMA table_info(class_subject_teachers)")}
        if roster_columns["id"]["type"].upper() != "INTEGER" or roster_columns["id"]["pk"] != 1:
            with sqlite3.connect(SQLITE_PATH) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN")
                connection.execute("""CREATE TABLE class_subject_teachers_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    UNIQUE (class_id, name, subject))""")
                connection.execute("""INSERT INTO class_subject_teachers_migrated(class_id,name,subject)
                    SELECT class_id,name,subject FROM class_subject_teachers""")
                connection.execute("DROP TABLE class_subject_teachers")
                connection.execute("""ALTER TABLE class_subject_teachers_migrated
                    RENAME TO class_subject_teachers""")
                connection.commit()
    for t in db("SELECT * FROM teachers"):
        standard, section, year = t["standard"] or "Unassigned", t["section"] or "A", t["year"] or "Current"
        db("INSERT INTO school_classes(standard,section,year) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
           (standard, section, year), write=True)
        cls = db("SELECT id FROM school_classes WHERE standard=%s AND section=%s AND year=%s",
                 (standard, section, year), one=True)
        if not t["class_id"]:
            db("UPDATE teachers SET class_id=%s WHERE id=%s", (cls["id"], t["id"]), write=True)
        db("UPDATE students SET class_id=%s WHERE teacher_id=%s AND class_id IS NULL",
           (cls["id"], t["id"]), write=True)
        for exam in DEFAULT_EXAMS:
            db("INSERT INTO exam_types(class_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING",
               (cls["id"], exam), write=True)

_migrate_schema()

def exams_for_teacher(teacher_id):
    t = db("SELECT class_id FROM teachers WHERE id=%s", (teacher_id,), one=True)
    if not t or not t["class_id"]:
        return []
    return [row["name"] for row in db(
        "SELECT name FROM exam_types WHERE class_id=%s ORDER BY id", (t["class_id"],))]

def delete_student(sid):
    for table in ("marks", "attendance", "ranks", "messages", "reviews", "student_delete_requests"):
        db(f"DELETE FROM {table} WHERE student_id=%s", (sid,), write=True)
    db("DELETE FROM students WHERE id=%s", (sid,), write=True)

def send_sms(numbers, body):
    """Fast2SMS quick route. Without SMS_API_KEY in .env it only prints (safe testing).
    Check Fast2SMS docs for DLT / route rules; swap this function for MSG91/Twilio if needed."""
    numbers = [n for n in numbers if n]
    key = os.getenv("SMS_API_KEY")
    if not key:
        print(f"[SMS not configured] {numbers}: {body}"); return False
    try:
        r = requests.post("https://www.fast2sms.com/dev/bulkV2", timeout=20,
            headers={"authorization": key},
            json={"route": "q", "message": body, "language": "english", "numbers": ",".join(numbers)})
        return r.ok and r.json().get("return") is True
    except Exception as e:
        print("SMS error:", e); return False

def need(role):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if session.get("role") != role: return redirect("/")
            return f(*a, **k)
        return w
    return deco

def own_student(sid):
    s = db("SELECT * FROM students WHERE id=%s AND teacher_id=%s", (sid, session["uid"]), one=True)
    if not s: abort(404)
    return s

@app.route("/")
def home(): return render_template("login.html")

@app.post("/login/teacher")
def login_teacher():
    t = db("SELECT * FROM teachers WHERE username=%s", (request.form["username"],), one=True)
    if t and check_password_hash(t["pw_hash"], request.form["password"]):
        session.clear()
        session.update(role="teacher", uid=t["id"]); return redirect("/teacher")
    flash("Wrong username or password."); return redirect("/")

@app.post("/login/parent")
def login_parent():
    s = db("SELECT * FROM students WHERE code=%s AND parent_phone=%s",
           (request.form["code"].strip(), request.form["phone"].strip()), one=True)
    if s:
        session.clear()
        session.update(role="parent", uid=s["id"])
        return redirect("/parent")
    flash("Student ID or parent number does not match."); return redirect("/")

@app.route("/logout")
def logout(): session.clear(); return redirect("/")

@app.route("/teacher")
@need("teacher")
def teacher():
    t = db("SELECT * FROM teachers WHERE id=%s", (session["uid"],), one=True)
    filters = {
        "blood_group": request.args.get("blood_group", "").strip(),
        "age_min": request.args.get("age_min", "").strip(),
        "age_max": request.args.get("age_max", "").strip(),
        "attendance_min": request.args.get("attendance_min", "").strip(),
        "attendance_max": request.args.get("attendance_max", "").strip(),
        "rank": request.args.get("rank", "").strip(),
        "exam": request.args.get("exam", "").strip(),
        "attendance_month": request.args.get("attendance_month", "").strip(),
        "sort": request.args.get("sort", "roll"),
    }
    where, params = ["teacher_id=%s"], [t["id"]]
    if filters["blood_group"]:
        where.append("blood_group=%s"); params.append(filters["blood_group"])
    for key, operator in (("age_min", ">="), ("age_max", "<=")):
        if filters[key].isdigit():
            where.append(f"age {operator} %s"); params.append(int(filters[key]))
    if filters["rank"].isdigit():
        where.append("EXISTS (SELECT 1 FROM ranks r WHERE r.student_id=students.id AND r.pos=%s)")
        params.append(int(filters["rank"]))
    attendance_min = filters["attendance_min"].replace(".", "", 1).isdigit()
    attendance_max = filters["attendance_max"].replace(".", "", 1).isdigit()
    if attendance_min or attendance_max:
        if filters["attendance_month"]:
            attendance = "EXISTS (SELECT 1 FROM attendance a WHERE a.student_id=students.id AND a.month=%s"
            params.append(filters["attendance_month"])
            if attendance_min:
                attendance += " AND a.percent >= %s"; params.append(float(filters["attendance_min"]))
            if attendance_max:
                attendance += " AND a.percent <= %s"; params.append(float(filters["attendance_max"]))
            where.append(attendance + ")")
        else:
            overall = "(SELECT AVG(a.percent) FROM attendance a WHERE a.student_id=students.id)"
            if attendance_min:
                where.append(overall + " >= %s"); params.append(float(filters["attendance_min"]))
            if attendance_max:
                where.append(overall + " <= %s"); params.append(float(filters["attendance_max"]))
    sort_by = {"name": "LOWER(name)", "recent": "id DESC", "roll": "roll_no"}
    order = sort_by.get(filters["sort"], "roll_no")
    ss = db(f"""SELECT students.*,(SELECT AVG(a.percent) FROM attendance a
        WHERE a.student_id=students.id) AS overall_attendance
        FROM students WHERE {' AND '.join(where)} ORDER BY {order}""", params)
    asg = db("SELECT * FROM assignments WHERE teacher_id=%s ORDER BY due DESC", (t["id"],))
    review_rows = db("""SELECT r.*, s.name AS student_name, s.roll_no FROM reviews r
        JOIN students s ON s.id=r.student_id WHERE s.teacher_id=%s ORDER BY r.created_at DESC""", (t["id"],))
    exams = exams_for_teacher(t["id"])
    configured_subjects = db("SELECT exam,paper FROM exam_papers WHERE class_id=%s ORDER BY exam,id",
                            (t["class_id"],))
    subjects_by_exam = {exam: [] for exam in exams}
    for row in configured_subjects:
        subjects_by_exam[row["exam"]].append(row["paper"])
    pending = db("SELECT student_id FROM student_delete_requests WHERE teacher_id=%s AND status='pending'", (t["id"],))
    return render_template("teacher.html", t=t, students=ss, assignments=asg, exams=exams,
                           exam_subjects=subjects_by_exam, filters=filters, reviews=review_rows,
                           pending_deletions={r["student_id"] for r in pending})

@app.route("/teacher/uploads")
@need("teacher")
def teacher_uploads():
    return render_template("teacher_uploads.html", exams=exams_for_teacher(session["uid"]))

@app.post("/teacher/announce")
@need("teacher")
def announce():
    body = request.form["body"]
    ss = db("SELECT * FROM students WHERE teacher_id=%s", (session["uid"],))
    ok = send_sms([s["parent_phone"] for s in ss], body)
    for s in ss:
        db("INSERT INTO messages(teacher_id,student_id,kind,body,phone) VALUES(%s,%s,'Class',%s,%s)",
           (session["uid"], s["id"], body, s["parent_phone"]), write=True)
    flash("Sent to every parent in your class." if ok else "Saved, but SMS not sent. Check SMS_API_KEY in .env."); return redirect("/teacher")

@app.post("/teacher/students")
@need("teacher")
def add_students():
    rows = []
    f = request.files.get("file")
    if f and f.filename:
        try:
            rows = list(csv.DictReader(io.StringIO(f.read().decode("utf-8-sig"))))
        except UnicodeDecodeError:
            flash("The CSV file must be UTF-8 encoded.")
            return redirect("/teacher")
        if rows and not {"name", "roll_no", "parent_phone"}.issubset(rows[0]):
            flash("Student CSV must include name, roll_no, and parent_phone columns.")
            return redirect("/teacher")
    else: rows = [request.form]
    if not rows:
        flash("The CSV contains no student rows.")
        return redirect("/teacher")
    t = db("SELECT class_id FROM teachers WHERE id=%s", (session["uid"],), one=True)
    saved = 0
    for r in rows:
        try:
            name, roll_no, phone = r["name"].strip(), int(r["roll_no"]), r["parent_phone"].strip()
            if not name or roll_no < 1 or not phone:
                raise ValueError
            age = int(r["age"]) if r.get("age") else None
        except (KeyError, TypeError, ValueError, AttributeError):
            flash("Student upload stopped: each row needs a name, positive roll number, and parent phone; age must be a whole number.")
            return redirect("/teacher")
        code = f"S{session['uid']}{roll_no:03d}"
        db("""INSERT INTO students(code,name,roll_no,parent_name,parent_phone,address,teacher_id,class_id,
              age,date_of_birth,blood_group,gender)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(code) DO NOTHING""",
           (code, name, roll_no, r.get("parent_name"), phone, r.get("address"), session["uid"], t["class_id"],
            age, r.get("date_of_birth") or r.get("dob"), r.get("blood_group"), r.get("gender")), write=True)
        saved += 1
    flash(f"{saved} student records saved. Student IDs are generated as S + teacher number + roll number.")
    return redirect("/teacher")

@app.post("/teacher/assignment")
@need("teacher")
def add_assignment():
    db("INSERT INTO assignments(teacher_id,title,details,due) VALUES(%s,%s,%s,%s)",
       (session["uid"], request.form["title"], request.form["details"], request.form["due"]), write=True)
    return redirect("/teacher")

@app.route("/teacher/student/<int:sid>")
@need("teacher")
def student(sid):
    s = own_student(sid)
    marks = db("SELECT * FROM marks WHERE student_id=%s ORDER BY id", (sid,))
    msgs = db("SELECT * FROM messages WHERE student_id=%s ORDER BY sent_at DESC", (sid,))
    att = db("SELECT * FROM attendance WHERE student_id=%s ORDER BY month DESC", (sid,))
    overall_attendance = db("SELECT AVG(percent) AS average FROM attendance WHERE student_id=%s",
                            (sid,), one=True)["average"]
    rk = {r["exam"]: r["pos"] for r in db("SELECT * FROM ranks WHERE student_id=%s", (sid,))}
    reviews = db("SELECT * FROM reviews WHERE student_id=%s ORDER BY created_at DESC", (sid,))
    delete_pending = db("SELECT id FROM student_delete_requests WHERE student_id=%s AND status='pending'",
                        (sid,), one=True)
    exams = exams_for_teacher(session["uid"])
    teacher = db("SELECT class_id FROM teachers WHERE id=%s", (session["uid"],), one=True)
    exam_subjects = {
        exam: db("SELECT id,paper FROM exam_papers WHERE class_id=%s AND exam=%s ORDER BY id",
                 (teacher["class_id"], exam))
        for exam in exams
    }
    marks_by_subject = {}
    for mark in marks:
        marks_by_subject.setdefault((mark["exam"], mark["subject"]), mark)
    return render_template("student.html", s=s, marks=marks, msgs=msgs,
                           exams=exams, exam_subjects=exam_subjects,
                           marks_by_subject=marks_by_subject, att=att,
                           overall_attendance=overall_attendance, ranks=rk, reviews=reviews,
                           delete_pending=bool(delete_pending))

@app.post("/teacher/student/<int:sid>/exam/<path:exam>/marks")
@need("teacher")
def save_exam_card(sid, exam):
    own_student(sid)
    exam = exam.strip()
    teacher = db("SELECT class_id FROM teachers WHERE id=%s", (session["uid"],), one=True)
    configured = db("SELECT id FROM exam_types WHERE class_id=%s AND name=%s",
                    (teacher["class_id"], exam), one=True)
    if not configured:
        abort(404)
    subjects = db("SELECT paper FROM exam_papers WHERE class_id=%s AND exam=%s ORDER BY id",
                  (teacher["class_id"], exam))
    if not subjects:
        flash("This exam has no configured subjects.")
        return redirect(url_for("student", sid=sid))
    records = []
    try:
        for subject_row in subjects:
            subject = subject_row["paper"]
            raw_score = request.form.get(f"score_{subject}", "").strip()
            raw_max = request.form.get(f"max_score_{subject}", "").strip()
            if not raw_score:
                if raw_max and Decimal(raw_max) != 100:
                    raise ValueError(f"Enter marks for {subject} or leave its row blank.")
                continue
            score = Decimal(raw_score)
            max_score = Decimal(raw_max or "100")
            if (not score.is_finite() or not max_score.is_finite() or score < 0
                    or max_score <= 0 or score > max_score):
                raise ValueError(f"Enter valid marks for {subject}; score must not exceed the maximum.")
            records.append((subject, score, max_score))
        raw_rank = request.form.get("rank", "").strip()
        if raw_rank:
            rank = int(raw_rank)
            if rank < 1:
                raise ValueError("Rank must be a positive whole number.")
    except (InvalidOperation, TypeError, ValueError) as exc:
        flash(str(exc) or "Enter valid marks and rank values.")
        return redirect(url_for("student", sid=sid))

    for subject, score, max_score in records:
        existing = db("SELECT id FROM marks WHERE student_id=%s AND exam=%s AND subject=%s ORDER BY id LIMIT 1",
                      (sid, exam, subject), one=True)
        if existing:
            db("UPDATE marks SET score=%s,max_score=%s WHERE id=%s",
               (score, max_score, existing["id"]), write=True)
        else:
            db("INSERT INTO marks(student_id,exam,subject,score,max_score) VALUES(%s,%s,%s,%s,%s)",
               (sid, exam, subject, score, max_score), write=True)
    if raw_rank:
        save_record("rank", sid, exam, raw_rank)
    flash(f"{exam} rank card saved.")
    return redirect(url_for("student", sid=sid))

@app.post("/teacher/mark/<int:mark_id>/edit")
@need("teacher")
def edit_mark(mark_id):
    mark = db("SELECT m.* FROM marks m JOIN students s ON s.id=m.student_id "
              "WHERE m.id=%s AND s.teacher_id=%s", (mark_id, session["uid"]), one=True)
    if not mark:
        abort(404)
    _update_mark(mark_id, request.form)
    return redirect(url_for("student", sid=mark["student_id"]))

@app.post("/teacher/mark/<int:mark_id>/delete")
@need("teacher")
def delete_mark(mark_id):
    mark = db("SELECT m.* FROM marks m JOIN students s ON s.id=m.student_id "
              "WHERE m.id=%s AND s.teacher_id=%s", (mark_id, session["uid"]), one=True)
    if not mark:
        abort(404)
    db("DELETE FROM marks WHERE id=%s", (mark_id,), write=True)
    flash("Exam mark removed.")
    return redirect(url_for("student", sid=mark["student_id"]))

def _update_mark(mark_id, form):
    student_row = db("SELECT s.teacher_id FROM marks m JOIN students s ON s.id=m.student_id WHERE m.id=%s",
                     (mark_id,), one=True)
    if not student_row or form.get("exam", "").strip() not in exams_for_teacher(student_row["teacher_id"]):
        flash("Choose an exam configured for this class.")
        return False
    try:
        score, max_score = Decimal(form["score"]), Decimal(form["max_score"])
    except (KeyError, InvalidOperation, ValueError):
        flash("Enter valid marks and maximum marks.")
        return False
    exam, subject = form.get("exam", "").strip(), form.get("subject", "").strip()
    if not exam or not subject or not score.is_finite() or not max_score.is_finite() or score < 0 or max_score <= 0 or score > max_score:
        flash("Marks must be non-negative and cannot exceed a positive maximum.")
        return False
    db("UPDATE marks SET exam=%s,subject=%s,score=%s,max_score=%s WHERE id=%s",
       (exam, subject, score, max_score, mark_id), write=True)
    flash("Exam mark updated.")
    return True

@app.post("/teacher/student/<int:sid>/edit")
@need("teacher")
def edit_student(sid):
    own_student(sid)
    if _update_student(sid, request.form):
        flash("Student details updated.")
    return redirect(url_for("student", sid=sid))

def _update_student(sid, form):
    try:
        name = form["name"].strip()
        roll_no = int(form["roll_no"])
        age = int(form["age"]) if form.get("age", "").strip() else None
    except (KeyError, ValueError):
        flash("Enter a student name, positive roll number, and valid age.")
        return False
    phone = form.get("parent_phone", "").strip()
    if not name or roll_no < 1 or not phone or (age is not None and age < 0):
        flash("Enter a student name, positive roll number, parent phone, and valid age.")
        return False
    db("""UPDATE students SET name=%s,roll_no=%s,parent_name=%s,parent_phone=%s,address=%s,
        age=%s,date_of_birth=%s,blood_group=%s,gender=%s WHERE id=%s""",
       (name, roll_no, form.get("parent_name", "").strip(), phone, form.get("address", "").strip(),
        age, form.get("date_of_birth", "").strip() or None, form.get("blood_group", "").strip() or None,
        form.get("gender", "").strip() or None, sid), write=True)
    return True

@app.post("/teacher/student/<int:sid>/delete-request")
@need("teacher")
def request_student_deletion(sid):
    own_student(sid)
    exists = db("SELECT id FROM student_delete_requests WHERE student_id=%s AND status='pending'", (sid,), one=True)
    if not exists:
        db("INSERT INTO student_delete_requests(student_id,teacher_id) VALUES(%s,%s)",
           (sid, session["uid"]), write=True)
    flash("Deletion request sent to the principal for approval.")
    return redirect(url_for("student", sid=sid))

@app.post("/teacher/exams")
@need("teacher")
def add_exam():
    name = request.form.get("name", "").strip()
    subjects = list(dict.fromkeys(
        subject.strip()
        for subject in request.form.get("subjects", "").replace("\r", "\n").replace(",", "\n").split("\n")
        if subject.strip()
    ))
    t = db("SELECT class_id FROM teachers WHERE id=%s", (session["uid"],), one=True)
    if not name or not subjects:
        flash("Enter an exam name and at least one subject.")
        return redirect("/teacher")
    try:
        existing_exam = db("SELECT id FROM exam_types WHERE class_id=%s AND name=%s",
                           (t["class_id"], name), one=True)
        if existing_exam:
            existing_subject = db("SELECT id FROM exam_papers WHERE class_id=%s AND exam=%s LIMIT 1",
                                  (t["class_id"], name), one=True)
            if existing_subject:
                flash("That exam already has configured subjects.")
                return redirect("/teacher")
        else:
            db("INSERT INTO exam_types(class_id,name) VALUES(%s,%s)", (t["class_id"], name), write=True)
        for subject in subjects:
            db("INSERT INTO exam_papers(class_id,exam,paper) VALUES(%s,%s,%s)",
               (t["class_id"], name, subject), write=True)
    except (psycopg2.errors.UniqueViolation, sqlite3.IntegrityError):
        flash("An exam with that name already exists.")
    else:
        action = "configured" if existing_exam else "added"
        flash(f"{name} exam {action} with {len(subjects)} subjects for every student in your class.")
    return redirect("/teacher")

@app.post("/teacher/student/<int:sid>/message")
@need("teacher")
def personal(sid):
    s = own_student(sid); body = request.form["body"]
    ok = send_sms([s["parent_phone"]], body)
    db("INSERT INTO messages(teacher_id,student_id,kind,body,phone) VALUES(%s,%s,'Personal',%s,%s)",
       (session["uid"], sid, body, s["parent_phone"]), write=True)
    flash("Message sent to parent." if ok else "Saved, but SMS not sent. Check SMS_API_KEY in .env."); return redirect(url_for("student", sid=sid))

@app.route("/parent")
@need("parent")
def parent():  # read-only: no edit routes exist for parents
    s = db("SELECT s.*, t.standard, t.section, t.year, t.name AS teacher FROM students s "
           "JOIN teachers t ON t.id=s.teacher_id WHERE s.id=%s", (session["uid"],), one=True)
    marks = db("SELECT * FROM marks WHERE student_id=%s ORDER BY id", (s["id"],))
    asg = db("SELECT * FROM assignments WHERE teacher_id=%s ORDER BY due DESC", (s["teacher_id"],))
    msgs = db("SELECT * FROM messages WHERE student_id=%s ORDER BY sent_at DESC", (s["id"],))
    att = db("SELECT * FROM attendance WHERE student_id=%s ORDER BY month DESC", (s["id"],))
    overall_attendance = db("SELECT AVG(percent) AS average FROM attendance WHERE student_id=%s",
                            (s["id"],), one=True)["average"]
    rk = {r["exam"]: r["pos"] for r in db("SELECT * FROM ranks WHERE student_id=%s", (s["id"],))}
    reviews = db("SELECT * FROM reviews WHERE student_id=%s ORDER BY created_at DESC", (s["id"],))
    exams = exams_for_teacher(s["teacher_id"])
    exam_subjects = {
        exam: db("SELECT paper FROM exam_papers WHERE class_id=%s AND exam=%s ORDER BY id",
                 (s["class_id"], exam))
        for exam in exams
    }
    marks_by_subject = {}
    for mark in marks:
        marks_by_subject.setdefault((mark["exam"], mark["subject"]), mark)
    return render_template("parent.html", s=s, marks=marks, assignments=asg, msgs=msgs,
                           exams=exams, exam_subjects=exam_subjects,
                           marks_by_subject=marks_by_subject, att=att,
                           overall_attendance=overall_attendance, ranks=rk, reviews=reviews)

@app.post("/parent/review")
@need("parent")
def parent_review():
    body = request.form.get("body", "").strip()
    if not body:
        flash("Write a review before submitting.")
    else:
        db("INSERT INTO reviews(student_id,body) VALUES(%s,%s)", (session["uid"], body), write=True)
        flash("Your review was sent to the class teacher.")
    return redirect("/parent")

def save_record(kind, sid, period, value):
    if kind == "attendance":
        try:
            datetime.strptime(period, "%Y-%m")
            percent = Decimal(value)
        except (ValueError, InvalidOperation):
            raise ValueError("Choose a valid month and attendance percentage.")
        if not percent.is_finite() or not 0 <= percent <= 100:
            raise ValueError("Attendance must be between 0 and 100 percent.")
        db("""INSERT INTO attendance(student_id,month,percent) VALUES(%s,%s,%s)
              ON CONFLICT(student_id,month) DO UPDATE SET percent=EXCLUDED.percent""",
           (sid, period, percent), write=True)
    elif kind == "rank":
        try:
            position = int(value)
        except (ValueError, TypeError):
            raise ValueError("Rank must be a positive whole number.")
        teacher_id = session["uid"] if session.get("role") == "teacher" else None
        if teacher_id is None:
            student_row = db("SELECT teacher_id FROM students WHERE id=%s", (sid,), one=True)
            teacher_id = student_row["teacher_id"] if student_row else None
        if period not in exams_for_teacher(teacher_id) or position < 1:
            raise ValueError("Choose an exam and enter a positive rank number.")
        db("""INSERT INTO ranks(student_id,exam,pos) VALUES(%s,%s,%s)
              ON CONFLICT(student_id,exam) DO UPDATE SET pos=EXCLUDED.pos""",
           (sid, period, position), write=True)
    else:
        raise ValueError("Choose attendance or rank.")

@app.post("/teacher/student/<int:sid>/record")
@need("teacher")
def record(sid):
    own_student(sid)
    try:
        save_record(request.form["kind"], sid, request.form["period"], request.form["value"])
        flash("Attendance saved." if request.form["kind"] == "attendance" else "Rank saved.")
    except ValueError as exc:
        flash(str(exc))
    return redirect(url_for("student", sid=sid))

@app.post("/teacher/bulk")
@need("teacher")
def bulk():
    kind = request.form.get("kind", "")
    period = request.form.get("month") if kind == "attendance" else request.form.get("exam")
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a CSV file to upload.")
        return redirect(url_for("teacher_uploads"))
    if kind not in ("attendance", "rank"):
        flash("Choose attendance or rank before uploading. Enter exam marks on each student's rank card.")
        return redirect(url_for("teacher_uploads"))
    try:
        rows = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")))
    except UnicodeDecodeError:
        flash("The CSV file must be UTF-8 encoded.")
        return redirect(url_for("teacher_uploads"))
    if rows.fieldnames:
        rows.fieldnames = [name.strip() if name else "" for name in rows.fieldnames]
    needed_columns = {"roll_no", "value"}
    if not rows.fieldnames or not needed_columns.issubset(rows.fieldnames):
        flash("Attendance and rank CSVs need roll_no and value.")
        return redirect(url_for("teacher_uploads"))
    if kind == "rank" and period not in exams_for_teacher(session["uid"]):
        flash("Choose an exam configured for this class.")
        return redirect(url_for("teacher_uploads"))
    n, skipped = 0, 0
    for r in rows:
        try:
            roll_no = int(r.get("roll_no", "").strip())
            if roll_no < 1:
                raise ValueError
        except (ValueError, AttributeError):
            skipped += 1
            continue
        s = db("SELECT id FROM students WHERE teacher_id=%s AND roll_no=%s",
               (session["uid"], roll_no), one=True)
        if not s:
            skipped += 1
            continue
        try:
            save_record(kind, s["id"], period or "", r.get("value", "").strip())
            n += 1
        except ValueError:
            skipped += 1
    flash(f"{n} {kind} records saved; {skipped} rows skipped.")
    return redirect(url_for("teacher_uploads"))

@app.post("/login/admin")
def login_admin():
    a = db("SELECT * FROM admins WHERE username=%s", (request.form["username"],), one=True)
    if a and check_password_hash(a["pw_hash"], request.form["password"]):
        session.clear()
        session.update(role="admin", uid=a["id"]); return redirect("/admin")
    flash("Wrong principal username or password."); return redirect("/")

@app.route("/admin")
@need("admin")
def admin():
    classes = db("""SELECT c.*, COUNT(DISTINCT s.id) AS student_count,
        COUNT(DISTINCT t.id) + COUNT(DISTINCT cst.id) AS teacher_count FROM school_classes c
        LEFT JOIN students s ON s.class_id=c.id LEFT JOIN teachers t ON t.class_id=c.id
        LEFT JOIN class_subject_teachers cst ON cst.class_id=c.id
        GROUP BY c.id ORDER BY c.standard,c.section,c.year""")
    requests = db("""SELECT d.id,d.student_id,d.teacher_id,d.created_at,s.name AS student_name,s.roll_no,
        t.name AS teacher_name,c.standard,c.section FROM student_delete_requests d
        JOIN students s ON s.id=d.student_id JOIN teachers t ON t.id=d.teacher_id
        LEFT JOIN school_classes c ON c.id=t.class_id WHERE d.status='pending' ORDER BY d.created_at""")
    reviews = db("""SELECT r.*,s.name AS student_name,s.roll_no,c.standard,c.section FROM reviews r
        JOIN students s ON s.id=r.student_id LEFT JOIN school_classes c ON c.id=s.class_id
        ORDER BY r.created_at DESC LIMIT 30""")
    return render_template("admin.html", classes=classes, deletion_requests=requests, reviews=reviews)

@app.post("/admin/class")
@need("admin")
def add_class():
    f = request.form
    standard, section, year = f["standard"].strip(), f["section"].strip(), f["year"].strip()
    if not all((standard, section, year, f["name"].strip(), f["username"].strip(), f["password"])):
        flash("Complete the class and class teacher login fields.")
        return redirect("/admin")
    if db("SELECT id FROM teachers WHERE username=%s", (f["username"].strip(),), one=True):
        flash("That username is already used.")
        return redirect("/admin")
    db("INSERT INTO school_classes(standard,section,year) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
       (standard, section, year), write=True)
    cls = db("SELECT id FROM school_classes WHERE standard=%s AND section=%s AND year=%s",
             (standard, section, year), one=True)
    try:
        db("""INSERT INTO teachers(username,pw_hash,name,standard,section,year,class_id,subject)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
           (f["username"].strip(), generate_password_hash(f["password"]), f["name"].strip(),
            standard, section, year, cls["id"], f.get("subject", "").strip()), write=True)
    except (psycopg2.errors.UniqueViolation, sqlite3.IntegrityError):
        flash("That username is already used.")
        return redirect("/admin")
    for exam in DEFAULT_EXAMS:
        db("INSERT INTO exam_types(class_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING",
           (cls["id"], exam), write=True)
    flash("Class and class teacher login account created.")
    return redirect("/admin")

@app.route("/admin/class/<int:class_id>")
@need("admin")
def admin_class(class_id):
    cls = db("SELECT * FROM school_classes WHERE id=%s", (class_id,), one=True)
    if not cls:
        abort(404)
    teachers = db("SELECT * FROM teachers WHERE class_id=%s ORDER BY name", (class_id,))
    subject_teachers = db("SELECT * FROM class_subject_teachers WHERE class_id=%s ORDER BY name,subject",
                          (class_id,))
    students = db("""SELECT s.*, t.name AS teacher_name FROM students s
        LEFT JOIN teachers t ON t.id=s.teacher_id WHERE s.class_id=%s ORDER BY s.roll_no""", (class_id,))
    return render_template("admin_class.html", cls=cls, teachers=teachers,
                           subject_teachers=subject_teachers, students=students)

@app.post("/admin/class/<int:class_id>/subject-teachers")
@need("admin")
def add_subject_teacher(class_id):
    cls = db("SELECT * FROM school_classes WHERE id=%s", (class_id,), one=True)
    if not cls:
        abort(404)
    f = request.form
    name, subject = f.get("name", "").strip(), f.get("subject", "").strip()
    if not name or not subject:
        flash("Enter both the teacher name and subject.")
        return redirect(url_for("admin_class", class_id=class_id))
    try:
        db("INSERT INTO class_subject_teachers(class_id,name,subject) VALUES(%s,%s,%s)",
           (class_id, name, subject), write=True)
    except (psycopg2.errors.UniqueViolation, sqlite3.IntegrityError):
        flash("That teacher and subject are already listed for this class.")
    else:
        flash(f"{name} ({subject}) added to this class. No login account was created.")
    return redirect(url_for("admin_class", class_id=class_id))

@app.post("/admin/class/<int:class_id>/subject-teacher/<int:staff_id>/delete")
@need("admin")
def delete_subject_teacher(class_id, staff_id):
    staff = db("SELECT id FROM class_subject_teachers WHERE id=%s AND class_id=%s",
               (staff_id, class_id), one=True)
    if not staff:
        abort(404)
    db("DELETE FROM class_subject_teachers WHERE id=%s", (staff_id,), write=True)
    flash("Teacher removed from the class teaching list.")
    return redirect(url_for("admin_class", class_id=class_id))

@app.post("/admin/teacher/<int:teacher_id>/edit")
@need("admin")
def edit_teacher(teacher_id):
    teacher_row = db("SELECT * FROM teachers WHERE id=%s", (teacher_id,), one=True)
    if not teacher_row:
        abort(404)
    form = request.form
    if not form.get("name", "").strip() or not form.get("username", "").strip():
        flash("Teacher name and username are required.")
        return redirect(url_for("admin_class", class_id=teacher_row["class_id"]))
    duplicate = db("SELECT id FROM teachers WHERE username=%s AND id<>%s",
                   (form["username"].strip(), teacher_id), one=True)
    if duplicate:
        flash("That username is already used.")
        return redirect(url_for("admin_class", class_id=teacher_row["class_id"]))
    if form.get("password"):
        db("UPDATE teachers SET name=%s,username=%s,subject=%s,pw_hash=%s WHERE id=%s",
           (form["name"].strip(), form["username"].strip(), form.get("subject", "").strip(),
            generate_password_hash(form["password"]), teacher_id), write=True)
    else:
        db("UPDATE teachers SET name=%s,username=%s,subject=%s WHERE id=%s",
           (form["name"].strip(), form["username"].strip(), form.get("subject", "").strip(),
            teacher_id), write=True)
    flash("Teacher account updated.")
    return redirect(url_for("admin_class", class_id=teacher_row["class_id"]))

@app.post("/admin/class/<int:class_id>/delete")
@need("admin")
def remove_class(class_id):
    cls = db("SELECT id FROM school_classes WHERE id=%s", (class_id,), one=True)
    if not cls:
        abort(404)
    teachers = db("SELECT id FROM teachers WHERE class_id=%s", (class_id,))
    for teacher in teachers:
        students = db("SELECT id FROM students WHERE teacher_id=%s", (teacher["id"],))
        for student_row in students:
            delete_student(student_row["id"])
        db("DELETE FROM assignments WHERE teacher_id=%s", (teacher["id"],), write=True)
    db("DELETE FROM teachers WHERE class_id=%s", (class_id,), write=True)
    db("DELETE FROM school_classes WHERE id=%s", (class_id,), write=True)
    flash("Class and its associated accounts and student records were removed.")
    return redirect("/admin")

@app.route("/admin/student/<int:sid>")
@need("admin")
def admin_student(sid):
    s = db("SELECT s.*,c.standard,c.section,c.year,t.name AS teacher_name,t.id AS teacher_id "
           "FROM students s LEFT JOIN school_classes c ON c.id=s.class_id "
           "LEFT JOIN teachers t ON t.id=s.teacher_id WHERE s.id=%s", (sid,), one=True)
    if not s:
        abort(404)
    marks = db("SELECT * FROM marks WHERE student_id=%s ORDER BY exam,id", (sid,))
    attendance = db("SELECT * FROM attendance WHERE student_id=%s ORDER BY month DESC", (sid,))
    overall_attendance = db("SELECT AVG(percent) AS average FROM attendance WHERE student_id=%s",
                            (sid,), one=True)["average"]
    ranks = db("SELECT * FROM ranks WHERE student_id=%s ORDER BY exam", (sid,))
    messages = db("SELECT * FROM messages WHERE student_id=%s ORDER BY sent_at DESC", (sid,))
    exams = exams_for_teacher(s["teacher_id"]) if s["teacher_id"] else []
    # Load configured subjects per exam (same as teacher view)
    exam_subjects = {}
    if s["class_id"]:
        exam_subjects = {
            exam: db("SELECT id,paper FROM exam_papers WHERE class_id=%s AND exam=%s ORDER BY id",
                     (s["class_id"], exam))
            for exam in exams
        }
    marks_by_subject = {}
    for mark in marks:
        marks_by_subject.setdefault((mark["exam"], mark["subject"]), mark)
    return render_template("admin_student.html", s=s, marks=marks, attendance=attendance,
                           overall_attendance=overall_attendance, ranks=ranks,
                           messages=messages, exams=exams,
                           exam_subjects=exam_subjects, marks_by_subject=marks_by_subject)

@app.post("/admin/student/<int:sid>/edit")
@need("admin")
def admin_edit_student(sid):
    if not db("SELECT id FROM students WHERE id=%s", (sid,), one=True):
        abort(404)
    if _update_student(sid, request.form):
        flash("Student details updated.")
    return redirect(url_for("admin_student", sid=sid))

@app.post("/admin/student/<int:sid>/delete")
@need("admin")
def admin_delete_student(sid):
    if not db("SELECT id FROM students WHERE id=%s", (sid,), one=True):
        abort(404)
    delete_student(sid)
    flash("Student record removed.")
    return redirect("/admin")

@app.post("/admin/student/<int:sid>/marks")
@need("admin")
def admin_add_marks(sid):
    s = db("SELECT * FROM students WHERE id=%s", (sid,), one=True)
    if not s:
        abort(404)
    exam = request.form["exam"].strip()
    if exam not in exams_for_teacher(s["teacher_id"]):
        flash("Choose an exam configured for this class.")
        return redirect(url_for("admin_student", sid=sid))
    # Use configured subjects like the teacher's save_exam_card route
    teacher = db("SELECT class_id FROM teachers WHERE id=%s", (s["teacher_id"],), one=True)
    if not teacher or not teacher["class_id"]:
        flash("No class configured for this student's teacher.")
        return redirect(url_for("admin_student", sid=sid))
    subjects = db("SELECT paper FROM exam_papers WHERE class_id=%s AND exam=%s ORDER BY id",
                  (teacher["class_id"], exam))
    if not subjects:
        flash("This exam has no configured subjects. Ask the teacher to configure subjects first.")
        return redirect(url_for("admin_student", sid=sid))
    records = []
    try:
        for subject_row in subjects:
            subject = subject_row["paper"]
            raw_score = request.form.get(f"score_{subject}", "").strip()
            raw_max = request.form.get(f"max_score_{subject}", "").strip()
            if not raw_score:
                continue
            score = Decimal(raw_score)
            max_score = Decimal(raw_max or "100")
            if (not score.is_finite() or not max_score.is_finite() or score < 0
                    or max_score <= 0 or score > max_score):
                raise ValueError(f"Enter valid marks for {subject}.")
            records.append((subject, score, max_score))
    except (InvalidOperation, TypeError, ValueError) as exc:
        flash(str(exc) or "Enter valid marks.")
        return redirect(url_for("admin_student", sid=sid))
    for subject, score, max_score in records:
        existing = db("SELECT id FROM marks WHERE student_id=%s AND exam=%s AND subject=%s ORDER BY id LIMIT 1",
                      (sid, exam, subject), one=True)
        if existing:
            db("UPDATE marks SET score=%s,max_score=%s WHERE id=%s",
               (score, max_score, existing["id"]), write=True)
        else:
            db("INSERT INTO marks(student_id,exam,subject,score,max_score) VALUES(%s,%s,%s,%s,%s)",
               (sid, exam, subject, score, max_score), write=True)
    flash(f"{exam} marks saved.")
    return redirect(url_for("admin_student", sid=sid))

@app.post("/admin/mark/<int:mark_id>/edit")
@need("admin")
def admin_edit_mark(mark_id):
    mark = db("SELECT * FROM marks WHERE id=%s", (mark_id,), one=True)
    if not mark:
        abort(404)
    _update_mark(mark_id, request.form)
    return redirect(url_for("admin_student", sid=mark["student_id"]))

@app.post("/admin/mark/<int:mark_id>/delete")
@need("admin")
def admin_delete_mark(mark_id):
    mark = db("SELECT * FROM marks WHERE id=%s", (mark_id,), one=True)
    if not mark:
        abort(404)
    db("DELETE FROM marks WHERE id=%s", (mark_id,), write=True)
    flash("Exam mark removed.")
    return redirect(url_for("admin_student", sid=mark["student_id"]))

@app.post("/admin/student/<int:sid>/record")
@need("admin")
def admin_save_record(sid):
    s = db("SELECT * FROM students WHERE id=%s", (sid,), one=True)
    if not s:
        abort(404)
    # Temporarily set session uid so save_record can look up exams via teacher_id
    original_uid = session.get("uid")
    session["uid"] = s["teacher_id"]
    try:
        save_record(request.form["kind"], sid, request.form["period"], request.form["value"])
        flash("Student academic record saved.")
    except ValueError as exc:
        flash(str(exc))
    finally:
        session["uid"] = original_uid
    return redirect(url_for("admin_student", sid=sid))

@app.post("/admin/delete-request/<int:request_id>")
@need("admin")
def resolve_delete_request(request_id):
    action = request.form.get("action")
    row = db("SELECT * FROM student_delete_requests WHERE id=%s AND status='pending'",
             (request_id,), one=True)
    if not row:
        abort(404)
    if action == "approve":
        delete_student(row["student_id"])
        flash("Deletion approved; the student record was removed.")
    elif action == "reject":
        db("UPDATE student_delete_requests SET status='rejected' WHERE id=%s", (request_id,), write=True)
        flash("Deletion request rejected.")
    else:
        abort(400)
    return redirect("/admin")

@app.post("/admin/announce")
@need("admin")
def admin_announce():
    ss = db("SELECT * FROM students")
    ok = send_sms([s["parent_phone"] for s in ss], request.form["body"])
    for s in ss:
        db("INSERT INTO messages(teacher_id,student_id,kind,body,phone) VALUES(%s,%s,'School',%s,%s)",
           (s["teacher_id"], s["id"], request.form["body"], s["parent_phone"]), write=True)
    flash("Sent to all parents." if ok else "Saved, but SMS not sent. Check SMS_API_KEY in .env."); return redirect("/admin")

if __name__ == "__main__": app.run(debug=True)
