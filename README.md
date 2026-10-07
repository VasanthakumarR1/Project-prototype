# Vidya Connect

Vidya Connect is a Flask school portal for principals, teachers, and parents. Principals organize classes and teacher accounts; teachers maintain class lists and academic records; parents can view a student's progress and send feedback to the teacher.

## Features

- **Principal:** Create and remove classes (standard, section, and academic year); create the class teacher login; list additional subject teachers by name and subject without creating login accounts; inspect and edit student profiles and academic records; approve or reject teacher student-removal requests; send school announcements.
- **Teacher:** Manage student details; import student lists; configure class-wide exams with subject lists; enter marks and rank on each student's exam rank card; upload attendance and ranks from a separate records page; maintain monthly attendance and assignments; send class-wide or individual parent messages; read parent reviews.
- **Parent:** Sign in with the student's ID and registered parent phone number; read student details, exam results, ranks, overall and monthly attendance, assignments, and school messages; send a review to the teacher.
- **Storage:** SQLite is used by default. PostgreSQL can be selected with `DATABASE_URL`.

## Requirements

- Python 3.10 or newer
- The packages listed in [`requirements.txt`](requirements.txt)
- PostgreSQL only if using it instead of the default SQLite database

## Run locally

From the project directory, create and activate a virtual environment, then install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with:

```sh
source .venv/bin/activate
```

Create a `.env` file in the project directory if you want to configure the application:

```dotenv
SECRET_KEY=replace-with-a-long-random-secret
# Optional: SQLite database path (defaults to instance/school.sqlite3)
# DATABASE_PATH=instance/school.sqlite3
# Optional: use PostgreSQL instead of SQLite
# DATABASE_URL=postgresql://DB_USER:DB_PASS@DB_HOST:5432/school
# Optional: enable SMS through Fast2SMS
# SMS_API_KEY=your-provider-api-key
```

For the default SQLite setup, the application creates and migrates the database automatically. Seed initial demo accounts with:

```sh
python seed.py
```

The seed script prints its demo login credentials. Change or replace these credentials before using the application with real data, and do not use demo passwords in a deployed environment.

Start the development server:

```sh
python app.py
```

Open <http://127.0.0.1:5000/>.

### PostgreSQL setup

Create an empty PostgreSQL database, apply [`schema.sql`](schema.sql) to it, set `DATABASE_URL` in `.env`, then run `python seed.py` and `python app.py`. The application applies subsequent schema migrations at startup.

## CSV formats

CSV column headers must match the names below. Student imports also accept a UTF-8 CSV file with a byte-order mark.

**Students** — `name`, `roll_no`, and `parent_phone` are required. Other columns are optional:

```csv
name,roll_no,parent_phone,parent_name,age,date_of_birth,blood_group,gender,address
Ananya Rao,1,9876543210,Ravi Rao,14,2012-04-03,B+,F,12 Lake Road
```

**Attendance or rank uploads:**

```csv
roll_no,value
1,95
2,3
```

Open **Upload records** from the teacher dashboard. Choose attendance or rank. Attendance values are percentages and require selecting a month; rank values are positive whole-number positions and require choosing an exam.

Configure an exam by entering its name and subjects (comma-separated or one per line). The exam and its subject rows appear in every student's folder. Enter or update marks for each configured subject and the class rank directly in that student's exam rank card; marks are not imported through CSV.

Teachers record attendance monthly from each student's record (or use the separate CSV upload page). Overall attendance is calculated automatically as the arithmetic average of the student's recorded monthly percentages and is displayed in teacher, parent, and principal views. If a month is corrected, saving that month again updates its existing record and recalculates the average.

## Messaging and privacy

Without `SMS_API_KEY`, messages are saved in the portal but SMS messages are not delivered. Configure a Fast2SMS API key to enable the existing SMS integration. Use test phone numbers during development; the no-key development path logs message content and phone numbers to the application console.

Student and parent details are personal information. Keep `.env` and the local database out of source control, restrict access to deployments and backups, and use a strong `SECRET_KEY` outside local development.
