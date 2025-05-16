from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, flash, session
import sqlite3
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
import os
import uuid

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
DB_NAME = os.path.join(os.path.dirname(__file__), 'plantcare.db')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = datetime.today().date().isoformat()
    c.execute("""
        SELECT 
            p.id,
            p.name,
            COUNT(t.id) as task_count,
            p.image_path,
            EXISTS (
                SELECT 1 FROM tasks t2 
                WHERE t2.plant_id = p.id 
                AND t2.type = 'watering' 
                AND t2.date = ? 
                AND t2.done = 0
            ) as needs_watering_today,
            SUM(CASE WHEN t.done = 1 THEN 1 ELSE 0 END) as done_count
        FROM plants p
        LEFT JOIN tasks t ON p.id = t.plant_id
        GROUP BY p.id, p.name
    """, (today,))
    plants = c.fetchall()
    conn.close()
    return render_template('index.html', plants=plants)


@app.route('/add', methods=['GET', 'POST'])
def add_plant():
    if request.method == 'POST':
        name = request.form['name']
        water = int(request.form['watering_interval'])
        fert = int(request.form['fertilizing_interval'])

        image_path = None
        if 'image' in request.files:
            image = request.files['image']
            if image and image.filename:
                ext = os.path.splitext(image.filename)[1]
                unique_name = f"{uuid.uuid4().hex}{ext}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                image.save(save_path)
                image_path = f'static/uploads/{unique_name}'

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS plants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                watering_interval INTEGER,
                fertilizing_interval INTEGER,
                image_path TEXT
            )
        """)
        c.execute("INSERT INTO plants (name, watering_interval, fertilizing_interval, image_path) VALUES (?, ?, ?, ?)",
                  (name, water, fert, image_path))
        plant_id = c.lastrowid

        today = datetime.today()
        for i in range(0, 365, water):
            task_date = today + timedelta(days=i)
            c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                      (plant_id, 'watering', task_date.date().isoformat()))
        for i in range(0, 365, fert):
            task_date = today + timedelta(days=i)
            c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                      (plant_id, 'fertilizing', task_date.date().isoformat()))

        conn.commit()
        conn.close()
        return redirect(url_for('index', message='Plant added successfully'))

    return render_template('add_plant.html')

@app.route('/plant/<int:plant_id>')
def plant_detail(plant_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, watering_interval, fertilizing_interval, image_path FROM plants WHERE id = ?", (plant_id,))
    plant = c.fetchone()
    c.execute("SELECT id, date, type, done FROM tasks WHERE plant_id = ? ORDER BY date", (plant_id,))
    tasks = c.fetchall()
    conn.close()
    message = request.args.get("message")
    return render_template('plant_detail.html', plant=plant, tasks=tasks, plant_id=plant_id, message=message)


@app.route('/mark_done/<int:task_id>')
def mark_done(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer)

@app.route('/unmark_done/<int:task_id>')
def unmark_done(task_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE tasks SET done = 0 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer)

@app.route('/edit/<int:plant_id>', methods=['POST'])
def edit_plant(plant_id):
    watering = int(request.form['watering_interval'])
    fertilizing = int(request.form['fertilizing_interval'])
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE plants SET watering_interval = ?, fertilizing_interval = ? WHERE id = ?",
              (watering, fertilizing, plant_id))
    c.execute("DELETE FROM tasks WHERE plant_id = ?", (plant_id,))
    today = datetime.today()
    for i in range(0, 365, watering):
        task_date = today + timedelta(days=i)
        c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                  (plant_id, 'watering', task_date.date().isoformat()))
    for i in range(0, 365, fertilizing):
        task_date = today + timedelta(days=i)
        c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                  (plant_id, 'fertilizing', task_date.date().isoformat()))
    conn.commit()
    conn.close()
    return redirect(url_for('plant_detail', plant_id=plant_id, message='Intervals updated successfully'))

@app.route('/delete/<int:plant_id>', methods=['POST'])
def delete_plant(plant_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE plant_id = ?", (plant_id,))
    c.execute("DELETE FROM plants WHERE id = ?", (plant_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index', message='Plant deleted successfully'))

@app.route('/import_excel', methods=['GET', 'POST'])
def import_excel():
    import pandas as pd
    from werkzeug.utils import secure_filename
    from flask import request, flash

    if request.method == 'POST':
        if 'file' not in request.files:
            return "No file part"
        file = request.files['file']
        if file.filename == '':
            return "No selected file"
        if file:
            filename = secure_filename(file.filename)
            df = pd.read_excel(file)
            if 'name' not in df.columns:
                return "Missing required 'name' column in Excel file"
            df['watering_interval'] = df.get('watering_interval', 7).fillna(7).astype(int)
            df['fertilizing_interval'] = df.get('fertilizing_interval', 30).fillna(30).astype(int)

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            for _, row in df.iterrows():
                c.execute("INSERT INTO plants (name, watering_interval, fertilizing_interval) VALUES (?, ?, ?)",
                          (row['name'], int(row['watering_interval']), int(row['fertilizing_interval'])))
                plant_id = c.lastrowid
                today = datetime.today()
                for i in range(0, 365, int(row['watering_interval'])):
                    task_date = today + timedelta(days=i)
                    c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                              (plant_id, 'watering', task_date.date().isoformat()))
                for i in range(0, 365, int(row['fertilizing_interval'])):
                    task_date = today + timedelta(days=i)
                    c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                              (plant_id, 'fertilizing', task_date.date().isoformat()))
            conn.commit()
            conn.close()
            return redirect(url_for('index', message='Plants imported successfully.'))

    return '''
    <!doctype html>
    <title>Import Excel</title>
    <h1>Import Plants from Excel</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=submit value=Upload>
    </form>
    <a href="/">Back</a>
    '''

@app.route('/export_excel')
def export_excel():
    import pandas as pd
    from io import BytesIO

    conn = sqlite3.connect(DB_NAME)
    plants_df = pd.read_sql_query("SELECT * FROM plants", conn)
    tasks_df = pd.read_sql_query("SELECT * FROM tasks", conn)
    conn.close()

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        plants_df.to_excel(writer, sheet_name='Plants', index=False)
        tasks_df.to_excel(writer, sheet_name='Tasks', index=False)

    output.seek(0)
    return send_file(output, download_name="plantcare_export.xlsx", as_attachment=True)

@app.route('/export_pdf')
def export_pdf():
    from fpdf import FPDF
    from io import BytesIO

    plant_id = request.args.get('plant_id')
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if plant_id:
        c.execute("SELECT name FROM plants WHERE id = ?", (plant_id,))
        plant_name = c.fetchone()[0]
        c.execute("SELECT date, type, done FROM tasks WHERE plant_id = ? ORDER BY date", (plant_id,))
        tasks = c.fetchall()
    else:
        c.execute("SELECT p.name, t.date, t.type, t.done FROM tasks t JOIN plants p ON t.plant_id = p.id ORDER BY p.name, t.date")
        tasks = c.fetchall()

    conn.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    title = f"Tasks for {plant_name}" if plant_id else "Plant Tasks Overview"
    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", size=10)
    for task in tasks:
        if plant_id:
            date, type_, done = task
            line = f"{date} - {type_} [{'✓' if done else '✗'}]"
        else:
            name, date, type_, done = task
            line = f"{name}: {date} - {type_} [{'✓' if done else '✗'}]"
        pdf.cell(0, 8, line, ln=True)

    output = BytesIO()
    pdf.output(output)
    output.seek(0)
    filename = f"tasks_{plant_name}.pdf" if plant_id else "plantcare_export.pdf"
    return send_file(output, download_name=filename, as_attachment=True)

@app.route('/delete_database')
def delete_database():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
    return redirect(url_for('index', message='Database deleted.'))

@app.route('/new_database')
def new_database():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS plants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    watering_interval INTEGER,
                    fertilizing_interval INTEGER
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plant_id INTEGER,
                    type TEXT,
                    date TEXT,
                    done INTEGER DEFAULT 0,
                    FOREIGN KEY(plant_id) REFERENCES plants(id)
                )''')
    conn.commit()
    conn.close()
    return redirect(url_for('index', message='New database created.'))

@app.route("/calendar")
def calendar_view():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name, id FROM plants")
    plants = c.fetchall()
    conn.close()
    return render_template("calendar.html", plants=plants)

@app.route("/api/events")
def get_events():
    plant_id = request.args.get('plant_id')

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if plant_id:
        c.execute("SELECT t.id, p.name, t.date, t.type, t.done FROM tasks t JOIN plants p ON t.plant_id = p.id WHERE p.id = ?", (plant_id,))
    else:
        c.execute("SELECT t.id, p.name, t.date, t.type, t.done FROM tasks t JOIN plants p ON t.plant_id = p.id")
    tasks = c.fetchall()
    conn.close()

    events = []
    for task_id, plant_name, date, task_type, done in tasks:
        events.append({
            "id": task_id,
            "title": f"{plant_name} - {task_type.capitalize()} {'✓' if done else ''}",
            "start": date,
            "color": "#28a745" if task_type == 'watering' else "#ffc107"
        })
    return jsonify(events)  # ✅ správne – vracia priamo []

from flask import redirect, url_for
import sqlite3
from datetime import datetime, timedelta

@app.route('/generate_tasks_all')
def generate_tasks_all():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, watering_interval, fertilizing_interval FROM plants")
    plants = c.fetchall()
    today = datetime.today()

    for plant_id, w_int, f_int in plants:
        if not isinstance(w_int, int) or not isinstance(f_int, int):
            continue

        # Watering tasks
        for i in range(0, 365, w_int):
            task_date = (today + timedelta(days=i)).date().isoformat()
            c.execute("""
                SELECT 1 FROM tasks 
                WHERE plant_id = ? AND type = 'watering' AND date = ?
            """, (plant_id, task_date))
            if not c.fetchone():
                c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                          (plant_id, 'watering', task_date))

        # Fertilizing tasks
        for i in range(0, 365, f_int):
            task_date = (today + timedelta(days=i)).date().isoformat()
            c.execute("""
                SELECT 1 FROM tasks 
                WHERE plant_id = ? AND type = 'fertilizing' AND date = ?
            """, (plant_id, task_date))
            if not c.fetchone():
                c.execute("INSERT INTO tasks (plant_id, type, date) VALUES (?, ?, ?)",
                          (plant_id, 'fertilizing', task_date))

    conn.commit()
    conn.close()
    return redirect(url_for('index', message="Úlohy boli úspešne vygenerované bez duplikátov."))

@app.route('/cleanup_duplicates')
def cleanup_duplicates():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Vyhľadá duplicity podľa plant_id, type a date
    c.execute("""
        SELECT plant_id, type, date, COUNT(*) as count
        FROM tasks
        GROUP BY plant_id, type, date
        HAVING count > 1
    """)
    duplicates = c.fetchall()

    removed_count = 0

    for plant_id, type_, date, count in duplicates:
        # Získaj všetky ID úloh s rovnakými hodnotami
        c.execute("""
            SELECT id FROM tasks
            WHERE plant_id = ? AND type = ? AND date = ?
            ORDER BY id
        """, (plant_id, type_, date))
        ids = [row[0] for row in c.fetchall()]

        # ponechaj prvý ID, ostatné vymaž
        for dup_id in ids[1:]:
            c.execute("DELETE FROM tasks WHERE id = ?", (dup_id,))
            removed_count += 1

    conn.commit()
    conn.close()
    return redirect(url_for('index', message=f"Odstránených duplikátov: {removed_count}"))

@app.route('/update_image/<int:plant_id>', methods=['POST'])
def update_image(plant_id):
    if 'image' not in request.files:
        return redirect(url_for('plant_detail', plant_id=plant_id, message="No image uploaded"))

    image = request.files['image']
    if image.filename == '':
        return redirect(url_for('plant_detail', plant_id=plant_id, message="No selected file"))

    if image:
        ext = os.path.splitext(image.filename)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        image.save(save_path)
        image_path = f"static/uploads/{unique_name}"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE plants SET image_path = ? WHERE id = ?", (image_path, plant_id))
        conn.commit()
        conn.close()

        return redirect(url_for('plant_detail', plant_id=plant_id, message="Image updated successfully"))

    return redirect(url_for('plant_detail', plant_id=plant_id, message="Failed to upload image"))

@app.route('/rename/<int:plant_id>', methods=['POST'])
def rename_plant(plant_id):
    new_name = request.form.get('new_name')
    if not new_name:
        return "Missing name", 400

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE plants SET name = ? WHERE id = ?", (new_name, plant_id))
    conn.commit()
    conn.close()

    return "OK", 200

@app.route('/water/<int:plant_id>', methods=['POST'])
def quick_water(plant_id):
    today = datetime.today().date().isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Skús nájsť dnešnú nezalievanú úlohu
    c.execute("""
        SELECT id FROM tasks
        WHERE plant_id = ? AND type = 'watering' AND date = ? AND done = 0
    """, (plant_id, today))
    existing = c.fetchone()

    if existing:
        c.execute("UPDATE tasks SET done = 1 WHERE id = ?", (existing[0],))
    else:
        # Ak úloha neexistuje, vytvor ju ako hotovú
        c.execute("""
            INSERT INTO tasks (plant_id, type, date, done)
            VALUES (?, 'watering', ?, 1)
        """, (plant_id, today))

    conn.commit()
    conn.close()
    return '', 204

@app.route('/fertilize/<int:plant_id>', methods=['POST'])
def quick_fertilize(plant_id):
    today = datetime.today().date().isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Skontroluj, či už dnes existuje záznam o hnojení
    c.execute("""
        SELECT 1 FROM tasks
        WHERE plant_id = ? AND type = 'fertilizing' AND date = ?
    """, (plant_id, today))
    exists = c.fetchone()

    if not exists:
        c.execute("""
            INSERT INTO tasks (plant_id, type, date, done)
            VALUES (?, 'fertilizing', ?, 1)
        """, (plant_id, today))

    conn.commit()
    conn.close()
    return '', 204

if __name__ == '__main__':
    app.run(debug=True)
