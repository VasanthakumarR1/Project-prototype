CREATE TABLE IF NOT EXISTS teachers(id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, name TEXT,
  standard TEXT, section TEXT, year TEXT, class_id INT, subject TEXT);
CREATE TABLE IF NOT EXISTS students(id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, roll_no INT,
  parent_name TEXT, parent_phone TEXT, address TEXT, teacher_id INT REFERENCES teachers(id),
  class_id INT, age INT, date_of_birth TEXT, blood_group TEXT, gender TEXT);
CREATE TABLE IF NOT EXISTS marks(id SERIAL PRIMARY KEY, student_id INT REFERENCES students(id) ON DELETE CASCADE,
  exam TEXT, subject TEXT, score NUMERIC, max_score NUMERIC DEFAULT 100);
CREATE TABLE IF NOT EXISTS assignments(id SERIAL PRIMARY KEY, teacher_id INT REFERENCES teachers(id),
  title TEXT, details TEXT, due DATE);
CREATE TABLE IF NOT EXISTS messages(id SERIAL PRIMARY KEY, teacher_id INT, student_id INT REFERENCES students(id) ON DELETE CASCADE,
  kind TEXT, body TEXT, phone TEXT, sent_at TIMESTAMP DEFAULT now());
CREATE TABLE IF NOT EXISTS admins(id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attendance(
  student_id INT REFERENCES students(id) ON DELETE CASCADE,
  month TEXT NOT NULL,
  percent NUMERIC NOT NULL CHECK (percent >= 0 AND percent <= 100),
  PRIMARY KEY(student_id, month)
);
CREATE TABLE IF NOT EXISTS ranks(
  student_id INT REFERENCES students(id) ON DELETE CASCADE,
  exam TEXT NOT NULL,
  pos INT NOT NULL CHECK (pos > 0),
  PRIMARY KEY(student_id, exam)
);
CREATE TABLE IF NOT EXISTS school_classes (
  id SERIAL PRIMARY KEY,
  standard TEXT NOT NULL,
  section TEXT NOT NULL,
  year TEXT NOT NULL,
  UNIQUE (standard, section, year)
);
CREATE TABLE IF NOT EXISTS class_subject_teachers (
  id SERIAL PRIMARY KEY,
  class_id INT NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  UNIQUE (class_id, name, subject)
);
CREATE TABLE IF NOT EXISTS exam_types (
  id SERIAL PRIMARY KEY,
  class_id INT NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  UNIQUE (class_id, name)
);
CREATE TABLE IF NOT EXISTS exam_papers (
  id SERIAL PRIMARY KEY,
  class_id INT NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  exam TEXT NOT NULL,
  paper TEXT NOT NULL,
  UNIQUE (class_id, exam, paper)
);
CREATE TABLE IF NOT EXISTS reviews (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT now()
);
CREATE TABLE IF NOT EXISTS student_delete_requests (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  teacher_id INT NOT NULL REFERENCES teachers(id),
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT now()
);
