from app import db
from werkzeug.security import generate_password_hash as g
db("INSERT INTO teachers(username,pw_hash,name,standard,section,year) VALUES('teacher1',%s,'Mrs. Lakshmi','8','A','2026-27') ON CONFLICT DO NOTHING",(g('teacher123'),),write=True)
print("Teacher login: teacher1 / teacher123")
db("INSERT INTO admins(username,pw_hash,name) VALUES('principal',%s,'Principal') ON CONFLICT DO NOTHING",(g('admin123'),),write=True)
print("Principal login: principal / admin123  (change after first login)")
