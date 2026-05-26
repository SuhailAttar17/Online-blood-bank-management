from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
import re

app = Flask(__name__, static_folder='public')
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), 'lifeflow.db')

# ─────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Donors table
    c.execute('''CREATE TABLE IF NOT EXISTS donors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        dob TEXT NOT NULL,
        gender TEXT NOT NULL,
        blood_type TEXT,
        city TEXT,
        donation_date TEXT,
        status TEXT DEFAULT 'pending',
        registered_at TEXT DEFAULT (datetime('now'))
    )''')

    # Blood inventory table
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        blood_type TEXT UNIQUE NOT NULL,
        units INTEGER NOT NULL DEFAULT 0,
        target INTEGER NOT NULL DEFAULT 200,
        last_updated TEXT DEFAULT (datetime('now'))
    )''')

    # Blood requests table
    c.execute('''CREATE TABLE IF NOT EXISTS blood_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_name TEXT NOT NULL,
        blood_type TEXT NOT NULL,
        units_needed INTEGER NOT NULL,
        hospital TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        contact_phone TEXT NOT NULL,
        contact_email TEXT,
        urgency TEXT DEFAULT 'normal',
        notes TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # Contact messages table
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reason TEXT,
        full_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT NOT NULL,
        organization TEXT,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'unread',
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # Donation appointments table
    c.execute('''CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER,
        donor_name TEXT NOT NULL,
        blood_type TEXT,
        scheduled_date TEXT NOT NULL,
        scheduled_time TEXT DEFAULT '10:00',
        status TEXT DEFAULT 'scheduled',
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )''')

    # Donation history table
    c.execute('''CREATE TABLE IF NOT EXISTS donation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        donor_id INTEGER,
        donor_name TEXT NOT NULL,
        blood_type TEXT NOT NULL,
        units_donated REAL DEFAULT 1.0,
        donated_at TEXT DEFAULT (datetime('now')),
        notes TEXT,
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )''')

    # Password column for donor portal
    try:
        c.execute('ALTER TABLE donors ADD COLUMN password_hash TEXT')
    except Exception:
        pass

    # Admin sessions
    c.execute('''CREATE TABLE IF NOT EXISTS admin_sessions (
        token TEXT PRIMARY KEY,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # Donor sessions
    c.execute('''CREATE TABLE IF NOT EXISTS donor_sessions (
        token TEXT PRIMARY KEY,
        donor_id INTEGER NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )''')

    # Donation camps
    c.execute('''CREATE TABLE IF NOT EXISTS camps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        camp_date TEXT NOT NULL,
        start_time TEXT DEFAULT '09:00',
        end_time TEXT DEFAULT '17:00',
        organizer TEXT NOT NULL,
        contact_phone TEXT,
        target_donors INTEGER DEFAULT 50,
        actual_donors INTEGER DEFAULT 0,
        units_collected REAL DEFAULT 0,
        status TEXT DEFAULT 'upcoming',
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # Camp registrations
    c.execute('''CREATE TABLE IF NOT EXISTS camp_registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camp_id INTEGER NOT NULL,
        donor_id INTEGER,
        donor_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        blood_type TEXT,
        attended INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (camp_id) REFERENCES camps(id),
        FOREIGN KEY (donor_id) REFERENCES donors(id)
    )''')

    # Notifications
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        type TEXT DEFAULT 'info',
        audience TEXT DEFAULT 'admin',
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    # Seed sample camps
    sample_camps = [
        ('Pune City Blood Drive', 'Shivajinagar Ground, Pune', '2026-05-10', '09:00', '17:00', 'LifeFlow Team', '9800000001', 100, 'upcoming'),
        ('Baner Community Camp', 'Baner Gaon, Pune', '2026-05-24', '10:00', '16:00', 'Rotary Club Baner', '9800000002', 60, 'upcoming'),
        ('Wakad Tech Park Drive', 'Wakad IT Park', '2026-04-05', '09:00', '15:00', 'TechCorp HR', '9800000003', 80, 'completed'),
    ]
    for camp in sample_camps:
        c.execute('''INSERT OR IGNORE INTO camps (name,location,camp_date,start_time,end_time,organizer,contact_phone,target_donors,status)
                     VALUES (?,?,?,?,?,?,?,?,?)''', camp)

    # Seed sample notifications
    sample_notifs = [
        ('New Donor Registered', 'Priya Sharma has registered as a new donor.', 'success'),
        ('Critical Stock: O−', 'O− blood type is critically low (18 units). Urgent donors needed.', 'warning'),
        ('Blood Request Received', 'Jehangir Hospital requested 3 units of AB+.', 'info'),
        ('Camp Completed', 'Wakad Tech Park Drive collected 62 units from 68 donors.', 'success'),
    ]
    for n in sample_notifs:
        c.execute("INSERT OR IGNORE INTO notifications (title, body, type) VALUES (?,?,?)", n)

    # Admin table
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )''')

    # Seed initial blood inventory
    blood_types = [
        ('A+', 142, 200), ('A-', 31, 100), ('B+', 98, 160), ('B-', 14, 100),
        ('AB+', 67, 100), ('AB-', 22, 80), ('O+', 44, 160), ('O-', 18, 100)
    ]
    for bt, units, target in blood_types:
        c.execute('''INSERT OR IGNORE INTO inventory (blood_type, units, target)
                     VALUES (?, ?, ?)''', (bt, units, target))

    # Seed admin account (password: admin123)
    pw_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute('''INSERT OR IGNORE INTO admins (username, password_hash)
                 VALUES (?, ?)''', ('admin', pw_hash))

    # Seed sample donors
    sample_donors = [
        ('Priya', 'Sharma', 'priya@example.com', '9876543210', '1992-04-15', 'Female', 'O+', 'Pune'),
        ('Rohit', 'Mehta', 'rohit@example.com', '9123456780', '1988-09-22', 'Male', 'A+', 'Pune'),
        ('Anita', 'Desai', 'anita@example.com', '9988776655', '1995-01-08', 'Female', 'B-', 'Pimpri'),
        ('Kiran', 'Patil', 'kiran@example.com', '9765432100', '1990-07-30', 'Male', 'AB+', 'Wakad'),
        ('Sneha', 'Joshi', 'sneha@example.com', '9654321098', '1998-12-05', 'Female', 'O-', 'Baner'),
    ]
    for d in sample_donors:
        c.execute('''INSERT OR IGNORE INTO donors (first_name, last_name, email, phone, dob, gender, blood_type, city, status)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved')''', d)

    # Seed sample donation history
    sample_history = [
        (1, 'Priya Sharma', 'O+', 1.0, '2026-01-15'),
        (2, 'Rohit Mehta', 'A+', 1.0, '2026-02-10'),
        (3, 'Anita Desai', 'B-', 1.0, '2026-03-05'),
        (4, 'Kiran Patil', 'AB+', 1.0, '2026-01-28'),
        (5, 'Sneha Joshi', 'O-', 1.0, '2026-02-20'),
    ]
    for h in sample_history:
        c.execute('''INSERT OR IGNORE INTO donation_history (donor_id, donor_name, blood_type, units_donated, donated_at)
                     VALUES (?, ?, ?, ?, ?)''', h)

    conn.commit()
    conn.close()

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]

def validate_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email)

def validate_phone(phone):
    return re.match(r'^[\d\s\+\-\(\)]{7,15}$', phone)

VALID_BLOOD_TYPES = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

def check_admin(request):
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return False
    conn = get_db()
    row = conn.execute('SELECT token FROM admin_sessions WHERE token=?', (token,)).fetchone()
    conn.close()
    return row is not None

# ─────────────────────────────────────────
# SERVE FRONTEND
# ─────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('public', path)

# ─────────────────────────────────────────
# ADMIN AUTH
# ─────────────────────────────────────────

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    username = data.get('username', '')
    password = data.get('password', '')
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db()
    admin = conn.execute('SELECT * FROM admins WHERE username=? AND password_hash=?',
                         (username, pw_hash)).fetchone()
    if not admin:
        conn.close()
        return jsonify({'error': 'Invalid credentials'}), 401
    token = secrets.token_hex(32)
    conn.execute('INSERT INTO admin_sessions (token) VALUES (?)', (token,))
    conn.commit()
    conn.close()
    return jsonify({'token': token, 'message': 'Logged in successfully'})

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    conn = get_db()
    conn.execute('DELETE FROM admin_sessions WHERE token=?', (token,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Logged out'})

# ─────────────────────────────────────────
# DONOR ROUTES
# ─────────────────────────────────────────

@app.route('/api/donors/register', methods=['POST'])
def register_donor():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    required = ['first_name', 'last_name', 'email', 'phone', 'dob', 'gender']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400

    if not validate_email(data['email']):
        return jsonify({'error': 'Invalid email address'}), 400

    if not validate_phone(data['phone']):
        return jsonify({'error': 'Invalid phone number'}), 400

    blood_type = data.get('blood_type', '')
    if blood_type and blood_type not in VALID_BLOOD_TYPES:
        return jsonify({'error': 'Invalid blood type'}), 400

    conn = get_db()
    try:
        existing = conn.execute('SELECT id FROM donors WHERE email=?', (data['email'],)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Email already registered'}), 409

        conn.execute('''INSERT INTO donors
            (first_name, last_name, email, phone, dob, gender, blood_type, city, donation_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            data['first_name'].strip(),
            data['last_name'].strip(),
            data['email'].strip().lower(),
            data['phone'].strip(),
            data['dob'],
            data['gender'],
            blood_type or None,
            data.get('city', '').strip(),
            data.get('donation_date') or None
        ))

        donor_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        # Schedule appointment if date provided
        if data.get('donation_date'):
            full_name = f"{data['first_name']} {data['last_name']}"
            conn.execute('''INSERT INTO appointments (donor_id, donor_name, blood_type, scheduled_date)
                           VALUES (?, ?, ?, ?)''',
                        (donor_id, full_name, blood_type or None, data['donation_date']))

        conn.commit()
        conn.close()
        return jsonify({
            'message': 'Registration successful! We\'ll contact you within 24 hours.',
            'donor_id': donor_id
        }), 201

    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/donors', methods=['GET'])
def list_donors():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    donors = conn.execute('''SELECT * FROM donors ORDER BY registered_at DESC''').fetchall()
    conn.close()
    return jsonify(rows_to_list(donors))

@app.route('/api/donors/<int:donor_id>', methods=['GET'])
def get_donor(donor_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    donor = conn.execute('SELECT * FROM donors WHERE id=?', (donor_id,)).fetchone()
    history = conn.execute('SELECT * FROM donation_history WHERE donor_id=? ORDER BY donated_at DESC', (donor_id,)).fetchall()
    conn.close()
    if not donor:
        return jsonify({'error': 'Donor not found'}), 404
    result = row_to_dict(donor)
    result['history'] = rows_to_list(history)
    return jsonify(result)

@app.route('/api/donors/<int:donor_id>/status', methods=['PATCH'])
def update_donor_status(donor_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    status = data.get('status')
    if status not in ['pending', 'approved', 'rejected']:
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    conn.execute('UPDATE donors SET status=? WHERE id=?', (status, donor_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Status updated'})

@app.route('/api/donors/<int:donor_id>/donate', methods=['POST'])
def record_donation(donor_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    conn = get_db()
    donor = conn.execute('SELECT * FROM donors WHERE id=?', (donor_id,)).fetchone()
    if not donor:
        conn.close()
        return jsonify({'error': 'Donor not found'}), 404

    blood_type = data.get('blood_type', donor['blood_type'])
    units = float(data.get('units', 1.0))

    conn.execute('''INSERT INTO donation_history (donor_id, donor_name, blood_type, units_donated, notes)
                   VALUES (?, ?, ?, ?, ?)''',
                (donor_id, f"{donor['first_name']} {donor['last_name']}", blood_type, units, data.get('notes')))

    # Update inventory
    conn.execute('''UPDATE inventory SET units = units + ?, last_updated = datetime('now')
                   WHERE blood_type = ?''', (units, blood_type))

    conn.commit()
    conn.close()
    return jsonify({'message': f'Donation of {units} unit(s) of {blood_type} recorded successfully'})

# ─────────────────────────────────────────
# BLOOD INVENTORY ROUTES
# ─────────────────────────────────────────

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    conn = get_db()
    rows = conn.execute('SELECT * FROM inventory ORDER BY blood_type').fetchall()
    conn.close()
    inventory = []
    for r in rows:
        d = dict(r)
        pct = (d['units'] / d['target'] * 100) if d['target'] > 0 else 0
        if pct >= 50:
            d['status'] = 'sufficient'
            d['status_label'] = 'Sufficient'
        elif pct >= 20:
            d['status'] = 'moderate'
            d['status_label'] = 'Moderate'
        elif pct >= 10:
            d['status'] = 'low'
            d['status_label'] = 'Low'
        else:
            d['status'] = 'critical'
            d['status_label'] = 'Critical Low'
        d['percentage'] = round(pct, 1)
        inventory.append(d)
    return jsonify(inventory)

@app.route('/api/inventory/<blood_type>', methods=['GET'])
def get_inventory_by_type(blood_type):
    blood_type = blood_type.replace('pos', '+').replace('neg', '-').upper()
    conn = get_db()
    row = conn.execute('SELECT * FROM inventory WHERE blood_type=?', (blood_type,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'Blood type not found'}), 404
    return jsonify(row_to_dict(row))

@app.route('/api/inventory/<blood_type>', methods=['PATCH'])
def update_inventory(blood_type):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    blood_type = blood_type.replace('pos', '+').replace('neg', '-').upper()
    conn = get_db()
    if 'units' in data:
        conn.execute('''UPDATE inventory SET units=?, last_updated=datetime('now')
                       WHERE blood_type=?''', (int(data['units']), blood_type))
    if 'target' in data:
        conn.execute('UPDATE inventory SET target=? WHERE blood_type=?',
                    (int(data['target']), blood_type))
    conn.commit()
    row = conn.execute('SELECT * FROM inventory WHERE blood_type=?', (blood_type,)).fetchone()
    conn.close()
    return jsonify(row_to_dict(row))

# ─────────────────────────────────────────
# BLOOD REQUEST ROUTES
# ─────────────────────────────────────────

@app.route('/api/requests', methods=['POST'])
def create_blood_request():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    required = ['patient_name', 'blood_type', 'units_needed', 'hospital', 'contact_name', 'contact_phone']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {", ".join(missing)}'}), 400

    if data['blood_type'] not in VALID_BLOOD_TYPES:
        return jsonify({'error': 'Invalid blood type'}), 400

    urgency = data.get('urgency', 'normal')
    if urgency not in ['normal', 'urgent', 'critical']:
        urgency = 'normal'

    conn = get_db()
    conn.execute('''INSERT INTO blood_requests
        (patient_name, blood_type, units_needed, hospital, contact_name, contact_phone, contact_email, urgency, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
        data['patient_name'], data['blood_type'], int(data['units_needed']),
        data['hospital'], data['contact_name'], data['contact_phone'],
        data.get('contact_email', ''), urgency, data.get('notes', '')
    ))
    req_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'message': 'Blood request submitted successfully', 'request_id': req_id}), 201

@app.route('/api/requests', methods=['GET'])
def list_requests():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM blood_requests ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

@app.route('/api/requests/<int:req_id>/status', methods=['PATCH'])
def update_request_status(req_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    status = data.get('status')
    if status not in ['pending', 'approved', 'fulfilled', 'rejected']:
        return jsonify({'error': 'Invalid status'}), 400

    conn = get_db()
    req = conn.execute('SELECT * FROM blood_requests WHERE id=?', (req_id,)).fetchone()
    if not req:
        conn.close()
        return jsonify({'error': 'Request not found'}), 404

    conn.execute('UPDATE blood_requests SET status=? WHERE id=?', (status, req_id))

    # Deduct from inventory when fulfilled
    if status == 'fulfilled':
        conn.execute('''UPDATE inventory SET units = MAX(0, units - ?), last_updated=datetime('now')
                       WHERE blood_type=?''', (req['units_needed'], req['blood_type']))

    conn.commit()
    conn.close()
    return jsonify({'message': 'Request status updated'})

# ─────────────────────────────────────────
# MESSAGES / CONTACT
# ─────────────────────────────────────────

@app.route('/api/messages', methods=['POST'])
def send_message():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400

    required = ['full_name', 'phone', 'email', 'message']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {", ".join(missing)}'}), 400

    if not validate_email(data['email']):
        return jsonify({'error': 'Invalid email'}), 400

    conn = get_db()
    conn.execute('''INSERT INTO messages (reason, full_name, phone, email, organization, message)
                   VALUES (?, ?, ?, ?, ?, ?)''', (
        data.get('reason', 'Other'),
        data['full_name'], data['phone'], data['email'],
        data.get('organization', ''), data['message']
    ))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Message sent! We\'ll respond within 4 hours.'}), 201

@app.route('/api/messages', methods=['GET'])
def list_messages():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM messages ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

@app.route('/api/messages/<int:msg_id>/read', methods=['PATCH'])
def mark_message_read(msg_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    conn.execute("UPDATE messages SET status='read' WHERE id=?", (msg_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Marked as read'})

# ─────────────────────────────────────────
# APPOINTMENTS
# ─────────────────────────────────────────

@app.route('/api/appointments', methods=['GET'])
def list_appointments():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM appointments ORDER BY scheduled_date ASC').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

@app.route('/api/appointments/<int:appt_id>/status', methods=['PATCH'])
def update_appointment(appt_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    status = data.get('status')
    if status not in ['scheduled', 'completed', 'cancelled', 'no-show']:
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    conn.execute('UPDATE appointments SET status=? WHERE id=?', (status, appt_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Appointment updated'})

# ─────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    total_donors = conn.execute('SELECT COUNT(*) FROM donors').fetchone()[0]
    pending_donors = conn.execute("SELECT COUNT(*) FROM donors WHERE status='pending'").fetchone()[0]
    total_donations = conn.execute('SELECT COUNT(*) FROM donation_history').fetchone()[0]
    total_requests = conn.execute('SELECT COUNT(*) FROM blood_requests').fetchone()[0]
    pending_requests = conn.execute("SELECT COUNT(*) FROM blood_requests WHERE status='pending'").fetchone()[0]
    unread_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE status='unread'").fetchone()[0]
    critical_types = conn.execute(
        "SELECT blood_type FROM inventory WHERE CAST(units AS REAL)/target < 0.15"
    ).fetchall()
    units_today = conn.execute(
        "SELECT COALESCE(SUM(units_donated),0) FROM donation_history WHERE date(donated_at)=date('now')"
    ).fetchone()[0]
    recent_donors = conn.execute(
        'SELECT first_name, last_name, blood_type, registered_at FROM donors ORDER BY registered_at DESC LIMIT 5'
    ).fetchall()
    recent_requests = conn.execute(
        'SELECT patient_name, blood_type, units_needed, status, created_at FROM blood_requests ORDER BY created_at DESC LIMIT 5'
    ).fetchall()
    conn.close()
    return jsonify({
        'total_donors': total_donors,
        'pending_donors': pending_donors,
        'total_donations': total_donations,
        'total_requests': total_requests,
        'pending_requests': pending_requests,
        'unread_messages': unread_messages,
        'critical_blood_types': [r['blood_type'] for r in critical_types],
        'units_donated_today': float(units_today),
        'recent_donors': rows_to_list(recent_donors),
        'recent_requests': rows_to_list(recent_requests),
    })

# ─────────────────────────────────────────
# DONATION HISTORY
# ─────────────────────────────────────────

@app.route('/api/donations', methods=['GET'])
def list_donations():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM donation_history ORDER BY donated_at DESC').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

# ─────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'LifeFlow Blood Bank API', 'version': '2.0.0'})

# ─────────────────────────────────────────
# DONOR PORTAL AUTH
# ─────────────────────────────────────────

@app.route('/api/donor/register', methods=['POST'])
def donor_portal_register():
    """Register + set password for donor portal access."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    required = ['first_name', 'last_name', 'email', 'phone', 'dob', 'gender', 'password']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {", ".join(missing)}'}), 400
    if not validate_email(data['email']):
        return jsonify({'error': 'Invalid email'}), 400
    if len(data['password']) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    pw_hash = hashlib.sha256(data['password'].encode()).hexdigest()
    blood_type = data.get('blood_type', '')
    conn = get_db()
    try:
        existing = conn.execute('SELECT id FROM donors WHERE email=?', (data['email'],)).fetchone()
        if existing:
            conn.close()
            return jsonify({'error': 'Email already registered'}), 409
        conn.execute('''INSERT INTO donors
            (first_name, last_name, email, phone, dob, gender, blood_type, city, donation_date, password_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            data['first_name'].strip(), data['last_name'].strip(),
            data['email'].strip().lower(), data['phone'].strip(),
            data['dob'], data['gender'],
            blood_type or None, data.get('city', '').strip(),
            data.get('donation_date') or None, pw_hash
        ))
        donor_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        if data.get('donation_date'):
            full_name = f"{data['first_name']} {data['last_name']}"
            conn.execute('''INSERT INTO appointments (donor_id, donor_name, blood_type, scheduled_date)
                           VALUES (?, ?, ?, ?)''',
                        (donor_id, full_name, blood_type or None, data['donation_date']))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Account created! You can now log in.', 'donor_id': donor_id}), 201
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/donor/login', methods=['POST'])
def donor_login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db()
    donor = conn.execute(
        'SELECT * FROM donors WHERE email=? AND password_hash=?', (email, pw_hash)
    ).fetchone()
    if not donor:
        conn.close()
        return jsonify({'error': 'Invalid email or password'}), 401
    token = secrets.token_hex(32)
    conn.execute('INSERT INTO donor_sessions (token, donor_id) VALUES (?, ?)', (token, donor['id']))
    conn.commit()
    d = row_to_dict(donor)
    d.pop('password_hash', None)
    conn.close()
    return jsonify({'token': token, 'donor': d})


@app.route('/api/donor/logout', methods=['POST'])
def donor_logout():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    conn = get_db()
    conn.execute('DELETE FROM donor_sessions WHERE token=?', (token,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Logged out'})


def get_donor_from_token(req):
    token = req.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        'SELECT d.* FROM donor_sessions s JOIN donors d ON s.donor_id=d.id WHERE s.token=?', (token,)
    ).fetchone()
    conn.close()
    return row_to_dict(row) if row else None


@app.route('/api/donor/me', methods=['GET'])
def donor_me():
    donor = get_donor_from_token(request)
    if not donor:
        return jsonify({'error': 'Unauthorized'}), 401
    donor.pop('password_hash', None)
    conn = get_db()
    history = conn.execute(
        'SELECT * FROM donation_history WHERE donor_id=? ORDER BY donated_at DESC', (donor['id'],)
    ).fetchall()
    appts = conn.execute(
        'SELECT * FROM appointments WHERE donor_id=? ORDER BY scheduled_date ASC', (donor['id'],)
    ).fetchall()
    conn.close()
    donor['donation_history'] = rows_to_list(history)
    donor['appointments'] = rows_to_list(appts)
    return jsonify(donor)


@app.route('/api/donor/me', methods=['PATCH'])
def donor_update_me():
    donor = get_donor_from_token(request)
    if not donor:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    allowed = ['phone', 'city', 'blood_type']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'Nothing to update'}), 400
    sets = ', '.join(f'{k}=?' for k in updates)
    vals = list(updates.values()) + [donor['id']]
    conn = get_db()
    conn.execute(f'UPDATE donors SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()
    return jsonify({'message': 'Profile updated'})


@app.route('/api/donor/book', methods=['POST'])
def donor_book_appointment():
    donor = get_donor_from_token(request)
    if not donor:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    date = data.get('date')
    time = data.get('time', '10:00')
    if not date:
        return jsonify({'error': 'Date required'}), 400
    full_name = f"{donor['first_name']} {donor['last_name']}"
    conn = get_db()
    conn.execute('''INSERT INTO appointments (donor_id, donor_name, blood_type, scheduled_date, scheduled_time, notes)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (donor['id'], full_name, donor.get('blood_type'), date, time, data.get('notes', '')))
    conn.commit()
    conn.close()
    return jsonify({'message': f'Appointment booked for {date} at {time}'}), 201

# ─────────────────────────────────────────
# BLOOD DONATION CAMPS
# ─────────────────────────────────────────

@app.route('/api/camps', methods=['GET'])
def list_camps():
    conn = get_db()
    rows = conn.execute('SELECT * FROM camps ORDER BY camp_date ASC').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/camps', methods=['POST'])
def create_camp():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    required = ['name', 'location', 'camp_date', 'organizer']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {", ".join(missing)}'}), 400
    conn = get_db()
    conn.execute('''INSERT INTO camps (name, location, camp_date, start_time, end_time, organizer, contact_phone, target_donors, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
        data['name'], data['location'], data['camp_date'],
        data.get('start_time', '09:00'), data.get('end_time', '17:00'),
        data['organizer'], data.get('contact_phone', ''), data.get('target_donors', 50),
        data.get('notes', '')
    ))
    camp_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({'message': 'Camp created', 'camp_id': camp_id}), 201


@app.route('/api/camps/<int:camp_id>', methods=['PATCH'])
def update_camp(camp_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    allowed = ['name', 'location', 'camp_date', 'start_time', 'end_time', 'organizer',
               'contact_phone', 'target_donors', 'actual_donors', 'units_collected', 'status', 'notes']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'Nothing to update'}), 400
    sets = ', '.join(f'{k}=?' for k in updates)
    vals = list(updates.values()) + [camp_id]
    conn = get_db()
    conn.execute(f'UPDATE camps SET {sets} WHERE id=?', vals)
    conn.commit()
    row = conn.execute('SELECT * FROM camps WHERE id=?', (camp_id,)).fetchone()
    conn.close()
    return jsonify(row_to_dict(row))


@app.route('/api/camps/<int:camp_id>/register', methods=['POST'])
def register_for_camp():
    data = request.get_json()
    donor = get_donor_from_token(request)
    name = donor['first_name'] + ' ' + donor['last_name'] if donor else data.get('name', '')
    phone = donor['phone'] if donor else data.get('phone', '')
    blood_type = donor.get('blood_type') if donor else data.get('blood_type', '')
    if not name or not phone:
        return jsonify({'error': 'Name and phone required'}), 400
    conn = get_db()
    conn.execute('''INSERT INTO camp_registrations (camp_id, donor_id, donor_name, phone, blood_type)
                   VALUES (?, ?, ?, ?, ?)''',
                (camp_id, donor['id'] if donor else None, name, phone, blood_type))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Registered for camp successfully!'}), 201


@app.route('/api/camps/<int:camp_id>/registrations', methods=['GET'])
def camp_registrations(camp_id):
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM camp_registrations WHERE camp_id=?', (camp_id,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

# ─────────────────────────────────────────
# ANALYTICS & REPORTS
# ─────────────────────────────────────────

@app.route('/api/admin/analytics', methods=['GET'])
def analytics():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()

    # Donations per month (last 6 months)
    monthly = conn.execute('''
        SELECT strftime('%Y-%m', donated_at) as month,
               COUNT(*) as count,
               SUM(units_donated) as units
        FROM donation_history
        WHERE donated_at >= date('now', '-6 months')
        GROUP BY month ORDER BY month
    ''').fetchall()

    # Blood type distribution of donors
    bt_dist = conn.execute('''
        SELECT blood_type, COUNT(*) as count
        FROM donors WHERE blood_type IS NOT NULL
        GROUP BY blood_type ORDER BY count DESC
    ''').fetchall()

    # Requests by urgency
    req_urgency = conn.execute('''
        SELECT urgency, COUNT(*) as count FROM blood_requests GROUP BY urgency
    ''').fetchall()

    # Requests by status
    req_status = conn.execute('''
        SELECT status, COUNT(*) as count FROM blood_requests GROUP BY status
    ''').fetchall()

    # Inventory trend (current snapshot)
    inv = conn.execute('SELECT blood_type, units, target FROM inventory ORDER BY blood_type').fetchall()

    # Top donor cities
    cities = conn.execute('''
        SELECT city, COUNT(*) as count FROM donors
        WHERE city IS NOT NULL AND city != ''
        GROUP BY city ORDER BY count DESC LIMIT 5
    ''').fetchall()

    # Gender breakdown
    gender = conn.execute('''
        SELECT gender, COUNT(*) as count FROM donors GROUP BY gender
    ''').fetchall()

    # Camp stats
    camps = conn.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
               SUM(COALESCE(actual_donors,0)) as total_donors,
               SUM(COALESCE(units_collected,0)) as total_units
        FROM camps
    ''').fetchone()

    # Donor registration trend (last 6 months)
    reg_trend = conn.execute('''
        SELECT strftime('%Y-%m', registered_at) as month, COUNT(*) as count
        FROM donors
        WHERE registered_at >= date('now', '-6 months')
        GROUP BY month ORDER BY month
    ''').fetchall()

    conn.close()
    return jsonify({
        'monthly_donations': rows_to_list(monthly),
        'blood_type_distribution': rows_to_list(bt_dist),
        'requests_by_urgency': rows_to_list(req_urgency),
        'requests_by_status': rows_to_list(req_status),
        'inventory_snapshot': rows_to_list(inv),
        'top_cities': rows_to_list(cities),
        'gender_breakdown': rows_to_list(gender),
        'camp_summary': row_to_dict(camps),
        'registration_trend': rows_to_list(reg_trend),
    })


@app.route('/api/admin/export/donors', methods=['GET'])
def export_donors():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    import csv, io
    conn = get_db()
    rows = conn.execute('SELECT id,first_name,last_name,email,phone,dob,gender,blood_type,city,status,registered_at FROM donors ORDER BY id').fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID','First Name','Last Name','Email','Phone','DOB','Gender','Blood Type','City','Status','Registered At'])
    for r in rows:
        writer.writerow(list(r))
    from flask import Response
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=donors.csv'})


@app.route('/api/admin/export/donations', methods=['GET'])
def export_donations():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    import csv, io
    conn = get_db()
    rows = conn.execute('SELECT id,donor_name,blood_type,units_donated,donated_at,notes FROM donation_history ORDER BY donated_at DESC').fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID','Donor Name','Blood Type','Units','Date','Notes'])
    for r in rows:
        writer.writerow(list(r))
    from flask import Response
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=donations.csv'})

# ─────────────────────────────────────────
# NOTIFICATIONS (IN-APP)
# ─────────────────────────────────────────

@app.route('/api/admin/notifications', methods=['GET'])
def get_notifications():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE audience='admin' ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/admin/notifications/read', methods=['POST'])
def mark_all_notifications_read():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read=1 WHERE audience='admin'")
    conn.commit()
    conn.close()
    return jsonify({'message': 'All marked read'})


def add_notification(conn, title, body, audience='admin', ntype='info'):
    conn.execute(
        "INSERT INTO notifications (title, body, audience, type) VALUES (?, ?, ?, ?)",
        (title, body, audience, ntype)
    )

# ─────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────

@app.route('/api/admin/search', methods=['GET'])
def global_search():
    if not check_admin(request):
        return jsonify({'error': 'Unauthorized'}), 401
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'donors': [], 'requests': [], 'messages': []})
    like = f'%{q}%'
    conn = get_db()
    donors = conn.execute(
        "SELECT id,first_name,last_name,email,blood_type,status FROM donors WHERE first_name LIKE ? OR last_name LIKE ? OR email LIKE ? OR blood_type LIKE ? LIMIT 8",
        (like, like, like, like)
    ).fetchall()
    requests_ = conn.execute(
        "SELECT id,patient_name,blood_type,hospital,status FROM blood_requests WHERE patient_name LIKE ? OR hospital LIKE ? OR blood_type LIKE ? LIMIT 5",
        (like, like, like)
    ).fetchall()
    messages = conn.execute(
        "SELECT id,full_name,email,reason,status FROM messages WHERE full_name LIKE ? OR email LIKE ? OR message LIKE ? LIMIT 5",
        (like, like, like)
    ).fetchall()
    conn.close()
    return jsonify({
        'donors': rows_to_list(donors),
        'requests': rows_to_list(requests_),
        'messages': rows_to_list(messages),
    })

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("\n🩸 LifeFlow Blood Bank API starting...")
    print("   API:      http://localhost:5000/api")
    print("   Frontend: http://localhost:5000")
    print("   Admin:    http://localhost:5000/admin.html")
    print("   Portal:   http://localhost:5000/portal.html")
    print("   Creds:    admin / admin123\n")
    app.run(debug=True, port=5000)
