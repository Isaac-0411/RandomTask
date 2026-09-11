from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///randomtask.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(20), default='anonymous')
    tasks = db.relationship('DailyTask', backref='user', lazy=True)

class DailyTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    task_number = db.Column(db.Integer, nullable=False)
    tasks = db.relationship('Task', backref='daily_task', lazy=True, cascade='all, delete-orphan')

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    daily_task_id = db.Column(db.Integer, db.ForeignKey('daily_task.id'), nullable=False)
    content = db.Column(db.Text, default='')
    completed = db.Column(db.Boolean, default=False)

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Username already exists')
        
        user = User(
            username=username,
            password=generate_password_hash(password),
            avatar='anonymous'
        )
        db.session.add(user)
        db.session.commit()
        
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    today = date.today()
    
    daily_task = DailyTask.query.filter_by(user_id=user.id, date=today).first()
    
    if not daily_task:
        task_number = random.randint(2, 9)
        daily_task = DailyTask(user_id=user.id, date=today, task_number=task_number)
        db.session.add(daily_task)
        db.session.commit()
        
        for _ in range(task_number):
            task = Task(daily_task_id=daily_task.id)
            db.session.add(task)
        db.session.commit()
    
    tasks = Task.query.filter_by(daily_task_id=daily_task.id).all()
    completed_count = sum(1 for t in tasks if t.completed)
    
    return render_template('dashboard.html', 
                         user=user, 
                         tasks=tasks, 
                         task_number=daily_task.task_number,
                         completed_count=completed_count,
                         today=today.strftime('%B %d, %Y'))

@app.route('/update_task', methods=['POST'])
def update_task():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    task_id = data.get('task_id')
    content = data.get('content')
    completed = data.get('completed')
    
    task = Task.query.get(task_id)
    if task:
        if content is not None:
            task.content = content
        if completed is not None:
            task.completed = completed
        db.session.commit()
        
        daily_task = DailyTask.query.get(task.daily_task_id)
        tasks = Task.query.filter_by(daily_task_id=daily_task.id).all()
        completed_count = sum(1 for t in tasks if t.completed)
        
        return jsonify({
            'success': True,
            'completed_count': completed_count,
            'total': daily_task.task_number
        })
    
    return jsonify({'error': 'Task not found'}), 404

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    daily_tasks = DailyTask.query.filter_by(user_id=user.id).order_by(DailyTask.date.desc()).all()
    
    history_data = []
    for dt in daily_tasks:
        tasks = Task.query.filter_by(daily_task_id=dt.id).all()
        completed_tasks = [t for t in tasks if t.completed and t.content.strip()]
        history_data.append({
            'date': dt.date.strftime('%B %d, %Y'),
            'total': dt.task_number,
            'completed': len(completed_tasks),
            'tasks': completed_tasks
        })
    
    return render_template('history.html', user=user, history=history_data)

@app.route('/profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    avatar = data.get('avatar')
    
    if avatar in ['male', 'female', 'anonymous']:
        user = User.query.get(session['user_id'])
        user.avatar = avatar
        db.session.commit()
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid avatar'}), 400

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
