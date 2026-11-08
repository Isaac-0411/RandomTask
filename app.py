"""RandomTask: a small daily task planner with per-account task ownership."""

from datetime import datetime
import os
from pathlib import Path
import random
import secrets
import tempfile
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(20), default='anonymous')
    tasks = db.relationship('DailyTask', backref='user', lazy=True)


class DailyTask(db.Model):
    __table_args__ = (
        db.Index('uq_daily_task_user_date', 'user_id', 'date', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    task_number = db.Column(db.Integer, nullable=False)
    tasks = db.relationship(
        'Task', backref='daily_task', lazy='selectin', order_by='Task.id',
        cascade='all, delete-orphan',
    )


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    daily_task_id = db.Column(db.Integer, db.ForeignKey('daily_task.id'), nullable=False)
    content = db.Column(db.Text, default='')
    completed = db.Column(db.Boolean, default=False)


def _local_secret(instance_path):
    """Persist a private random development key, including across worker starts."""
    directory = Path(instance_path)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.secret_key'
    if not path.exists():
        # Link a fully written file atomically; another worker may win the race.
        with tempfile.NamedTemporaryFile(
            mode='w', dir=directory, prefix='.secret-key-', delete=False,
        ) as temporary:
            temporary.write(secrets.token_hex(32))
            temporary_path = Path(temporary.name)
        try:
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                pass
        finally:
            temporary_path.unlink(missing_ok=True)
    return path.read_text().strip()


def _current_user():
    user_id = session.get('user_id')
    user = db.session.get(User, user_id) if type(user_id) is int and user_id > 0 else None
    if user is None:
        session.pop('user_id', None)
    return user


def _completed(tasks):
    return [task for task in tasks if task.completed and (task.content or '').strip()]


def _daily_task(user_id, today):
    daily = DailyTask.query.filter_by(user_id=user_id, date=today).first()
    if daily is None:
        count = random.randint(2, 9)
        daily = DailyTask(
            user_id=user_id, date=today, task_number=count,
            tasks=[Task() for _ in range(count)],
        )
        db.session.add(daily)
        try:
            # The allocation and all its rows must succeed in one transaction.
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            # Concurrent dashboard requests use the allocation that committed first.
            daily = DailyTask.query.filter_by(user_id=user_id, date=today).first()
            if daily is None:
                raise

    changed = False
    # Repair an allocation left incomplete by an older version's two commits.
    for _ in range(max(0, daily.task_number - len(daily.tasks))):
        daily.tasks.append(Task())
        changed = True
    for task in daily.tasks:
        if task.completed and not (task.content or '').strip():
            task.completed = False
            changed = True
    if changed:
        db.session.commit()
    return daily


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///randomtask.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        APP_TIMEZONE=os.environ.get('APP_TIMEZONE', 'Asia/Bangkok'),
        MAX_TASK_LENGTH=1000,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config['SECRET_KEY']:
        app.config['SECRET_KEY'] = _local_secret(app.instance_path)
    # Validate the configured zone once rather than failing individual requests.
    timezone = ZoneInfo(app.config['APP_TIMEZONE'])
    db.init_app(app)

    @app.route('/')
    def index():
        return redirect(url_for('dashboard' if _current_user() else 'login'))

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if _current_user():
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if not 3 <= len(username) <= 80:
                return render_template(
                    'register.html', error='Choose a username with 3 to 80 characters.',
                ), 400
            if not 4 <= len(password) <= 128 or not password.strip():
                return render_template(
                    'register.html', error='Choose a password with 4 to 128 characters.',
                ), 400
            if User.query.filter_by(username=username).first():
                return render_template('register.html', error='Username already exists'), 409
            user = User(
                username=username, password=generate_password_hash(password), avatar='anonymous',
            )
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                return render_template('register.html', error='Username already exists'), 409
            session.clear()
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if _current_user():
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = None
            if 3 <= len(username) <= 80 and 4 <= len(password) <= 128:
                user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password, password):
                session.clear()
                session['user_id'] = user.id
                return redirect(url_for('dashboard'))
            return render_template('login.html', error='Invalid username or password'), 401
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/dashboard')
    def dashboard():
        user = _current_user()
        if user is None:
            return redirect(url_for('login'))
        today = datetime.now(timezone).date()
        daily = _daily_task(user.id, today)
        return render_template(
            'dashboard.html', user=user, tasks=daily.tasks,
            task_number=daily.task_number, completed_count=len(_completed(daily.tasks)),
            today=today.strftime('%B %d, %Y'),
        )

    @app.route('/update_task', methods=['POST'])
    def update_task():
        user = _current_user()
        if user is None:
            return jsonify(error='Not authenticated'), 401
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Send a JSON object.'), 400
        task_id = data.get('task_id')
        if type(task_id) is not int or task_id <= 0:
            return jsonify(error='A valid task ID is required.'), 400
        if not any(field in data for field in ('content', 'completed')):
            return jsonify(error='Provide task content or a completion status.'), 400
        if 'content' in data and (
            not isinstance(data['content'], str)
            or len(data['content']) > app.config['MAX_TASK_LENGTH']
        ):
            return jsonify(error='Task text must be at most 1000 characters.'), 400
        if 'completed' in data and type(data['completed']) is not bool:
            return jsonify(error='Completion status must be true or false.'), 400
        task = Task.query.join(DailyTask).filter(
            Task.id == task_id, DailyTask.user_id == user.id,
        ).first()
        if task is None:
            return jsonify(error='Task not found'), 404
        content = data.get('content', task.content or '')
        if data.get('completed') is True and not content.strip():
            return jsonify(error='Write a task before marking it complete.'), 400
        task.content = content
        task.completed = bool(data.get('completed', task.completed)) and bool(content.strip())
        db.session.commit()
        daily = task.daily_task
        return jsonify(
            success=True, completed_count=len(_completed(daily.tasks)), total=daily.task_number,
            task={'id': task.id, 'content': task.content, 'completed': task.completed},
        )

    @app.route('/history')
    def history():
        user = _current_user()
        if user is None:
            return redirect(url_for('login'))
        days = DailyTask.query.filter_by(user_id=user.id).order_by(DailyTask.date.desc()).all()
        history_data = []
        for daily in days:
            completed_tasks = _completed(daily.tasks)
            history_data.append({
                'date': daily.date.strftime('%B %d, %Y'),
                'total': daily.task_number,
                'completed': len(completed_tasks),
                'fully_completed': len(completed_tasks) == daily.task_number,
                'tasks': completed_tasks,
            })
        return render_template('history.html', user=user, history=history_data)

    @app.route('/profile', methods=['POST'])
    def update_profile():
        user = _current_user()
        if user is None:
            return jsonify(error='Not authenticated'), 401
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='Send a JSON object.'), 400
        avatar = data.get('avatar')
        if avatar not in ('male', 'female', 'anonymous'):
            return jsonify(error='Invalid avatar'), 400
        user.avatar = avatar
        db.session.commit()
        return jsonify(success=True, avatar=user.avatar)

    @app.route('/health', methods=['GET', 'HEAD'])
    def health():
        response = jsonify(status='ok')
        response.headers['Cache-Control'] = 'no-store'
        return response

    with app.app_context():
        db.create_all()
        # create_all does not add an index to an existing table. Preserve older
        # duplicate records rather than deleting anyone's saved task history.
        index = next(iter(DailyTask.__table__.indexes))
        try:
            index.create(db.engine, checkfirst=True)
        except IntegrityError:
            app.logger.warning(
                'Daily task uniqueness could not be added: existing duplicate days need review.',
            )
    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1')
