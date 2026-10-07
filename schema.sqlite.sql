PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teachers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL,
  name TEXT,
  standard TEXT,
  section TEXT,
  year TEXT,
  class_id INTEGER,
  subject TEXT
);

CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  roll_no INTEGER,
  parent_name TEXT,
  parent_phone TEXT,
  address TEXT,
  teacher_id INTEGER REFERENCES teachers(id),
  class_id INTEGER,
  age INTEGER,
  date_of_birth TEXT,
  blood_group TEXT,
  gender TEXT
);

CREATE TABLE IF NOT EXISTS marks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
  exam TEXT,
  subject TEXT,
  score NUMERIC,
  max_score NUMERIC DEFAULT 100
);

CREATE TABLE IF NOT EXISTS assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER REFERENCES teachers(id),
  title TEXT,
  details TEXT,
  due DATE
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER,
  student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
  kind TEXT,
  body TEXT,
  phone TEXT,
  sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  pw_hash TEXT NOT NULL,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
  student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
  month TEXT NOT NULL,
  percent NUMERIC NOT NULL CHECK (percent >= 0 AND percent <= 100),
  PRIMARY KEY (student_id, month)
);

CREATE TABLE IF NOT EXISTS ranks (
  student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
  exam TEXT NOT NULL,
  pos INTEGER NOT NULL CHECK (pos > 0),
  PRIMARY KEY (student_id, exam)
);

CREATE TABLE IF NOT EXISTS school_classes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  standard TEXT NOT NULL,
  section TEXT NOT NULL,
  year TEXT NOT NULL,
  UNIQUE (standard, section, year)
);

CREATE TABLE IF NOT EXISTS class_subject_teachers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  subject TEXT NOT NULL,
  UNIQUE (class_id, name, subject)
);

CREATE TABLE IF NOT EXISTS exam_types (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  UNIQUE (class_id, name)
);

CREATE TABLE IF NOT EXISTS exam_papers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES school_classes(id) ON DELETE CASCADE,
  exam TEXT NOT NULL,
  paper TEXT NOT NULL,
  UNIQUE (class_id, exam, paper)
);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS student_delete_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  teacher_id INTEGER NOT NULL REFERENCES teachers(id),
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
