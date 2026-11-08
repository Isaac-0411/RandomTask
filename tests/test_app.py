"""Behavioral regression checks for account isolation and daily task tracking.

Run with: python -m unittest discover -s tests -v
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import os
import unittest
from unittest.mock import patch

from flask import template_rendered
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


# Importing the WSGI entry point also constructs its default app. Keep that app
# isolated from a developer's database and production environment variables.
with patch.dict(os.environ, {
    'DATABASE_URL': 'sqlite:///:memory:',
    'SECRET_KEY': 'isolated-test-import-secret',
    'APP_TIMEZONE': 'Asia/Bangkok',
}):
    from app import DailyTask, Task, User, create_app, db


@contextmanager
def rendered_context(app):
    contexts = []

    def record(_sender, template, context, **_extra):
        contexts.append(context)

    template_rendered.connect(record, app)
    try:
        yield contexts
    finally:
        template_rendered.disconnect(record, app)


class AppTests(unittest.TestCase):
    today = date(2026, 11, 8)

    def setUp(self):
        self.app = create_app({
            'TESTING': True,
            'SECRET_KEY': 'isolated-test-session-secret',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'APP_TIMEZONE': 'Asia/Bangkok',
        })
        self.client = self.app.test_client()
        self.addCleanup(self.close_app)

    def close_app(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def make_user(self, username='alice'):
        with self.app.app_context():
            user = User(
                username=username,
                password=generate_password_hash('test-password', method='pbkdf2:sha256:1000'),
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    def sign_in(self, user_id, client=None):
        with (client or self.client).session_transaction() as session:
            session['user_id'] = user_id

    def make_day(self, user_id, tasks, day=None, total=None):
        with self.app.app_context():
            daily = DailyTask(
                user_id=user_id,
                date=day or self.today,
                task_number=len(tasks) if total is None else total,
                tasks=[Task(content=content, completed=completed) for content, completed in tasks],
            )
            db.session.add(daily)
            db.session.commit()
            return daily.id, [task.id for task in daily.tasks]

    @contextmanager
    def at_day(self, day=None):
        with patch('app.datetime') as clock:
            # Use a time well within the chosen day, independent of the host's
            # clock. The timezone-boundary behavior has a separate check below.
            chosen = day or self.today
            clock.now.return_value = datetime(
                chosen.year, chosen.month, chosen.day, 12, tzinfo=timezone.utc,
            )
            yield clock

    def test_registration_validates_fields_without_creating_accounts(self):
        invalid_forms = [
            {},
            {'username': 'ab', 'password': 'abcd'},
            {'username': 'a' * 81, 'password': 'abcd'},
            {'username': '   ', 'password': 'abcd'},
            {'username': 'alice'},
            {'username': 'alice', 'password': 'abc'},
            {'username': 'alice', 'password': 'a' * 129},
            {'username': 'alice', 'password': '    '},
        ]
        for form in invalid_forms:
            with self.subTest(form=form):
                response = self.client.post('/register', data=form)
                self.assertEqual(response.status_code, 400)
                with self.app.app_context():
                    self.assertEqual(User.query.count(), 0)

    def test_registration_hashes_password_trims_username_and_rejects_duplicate(self):
        response = self.client.post('/register', data={
            'username': '  alice  ', 'password': 'test-password',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/dashboard'))
        with self.app.app_context():
            user = User.query.one()
            self.assertEqual(user.username, 'alice')
            self.assertNotEqual(user.password, 'test-password')
            self.assertTrue(check_password_hash(user.password, 'test-password'))
            user_id = user.id
        with self.client.session_transaction() as session:
            self.assertEqual(session['user_id'], user_id)
        self.client.get('/logout')
        duplicate = self.client.post('/register', data={
            'username': 'alice', 'password': 'another-password',
        })
        self.assertEqual(duplicate.status_code, 409)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 1)

    def test_login_logout_and_invalid_credentials(self):
        user_id = self.make_user()
        for fields in ({}, {'username': 'alice', 'password': 'wrong-password'}):
            with self.subTest(fields=fields):
                self.assertEqual(self.client.post('/login', data=fields).status_code, 401)
                with self.client.session_transaction() as session:
                    self.assertNotIn('user_id', session)
        response = self.client.post('/login', data={
            'username': ' alice ', 'password': 'test-password',
        })
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['user_id'], user_id)
        self.assertTrue(self.client.get('/').location.endswith('/dashboard'))
        self.client.get('/logout')
        self.assertTrue(self.client.get('/dashboard').location.endswith('/login'))

    def test_stale_and_malformed_sessions_are_cleared(self):
        for user_id in (999999, 'deleted-user', True, {'id': 1}, None):
            for path in ('/', '/dashboard', '/history', '/update_task', '/profile'):
                with self.subTest(user_id=user_id, path=path):
                    client = self.app.test_client()
                    self.sign_in(user_id, client)
                    if path in ('/update_task', '/profile'):
                        response = client.post(path, json={})
                        self.assertEqual(response.status_code, 401)
                        self.assertIn('error', response.json)
                    else:
                        response = client.get(path)
                        self.assertEqual(response.status_code, 302)
                        self.assertTrue(response.location.endswith('/login'))
                    with client.session_transaction() as session:
                        self.assertNotIn('user_id', session)

    def test_another_users_tasks_cannot_be_changed(self):
        alice_id = self.make_user('alice')
        bob_id = self.make_user('bob')
        _, (bob_task_id,) = self.make_day(bob_id, [('Bob private task', False)])
        self.sign_in(alice_id)
        response = self.client.post('/update_task', json={
            'task_id': bob_task_id, 'content': 'tampered', 'completed': True,
        })
        self.assertEqual(response.status_code, 404)
        with self.app.app_context():
            task = db.session.get(Task, bob_task_id)
            self.assertEqual(task.content, 'Bob private task')
            self.assertFalse(task.completed)
        missing = self.client.post('/update_task', json={
            'task_id': 999999, 'content': 'missing',
        })
        self.assertEqual(missing.status_code, 404)

    def test_task_api_rejects_malformed_json_and_wrong_types_without_mutating(self):
        user_id = self.make_user()
        _, (task_id,) = self.make_day(user_id, [('Keep this task', False)])
        self.sign_in(user_id)
        bodies = [
            [], 'text', 42, True, {},
            {'task_id': True, 'content': 'changed'},
            {'task_id': str(task_id), 'content': 'changed'},
            {'task_id': 0, 'content': 'changed'},
            {'task_id': task_id},
            {'task_id': task_id, 'content': None},
            {'task_id': task_id, 'content': []},
            {'task_id': task_id, 'content': 10},
            {'task_id': task_id, 'content': 'a' * 1001},
            {'task_id': task_id, 'completed': 'false'},
            {'task_id': task_id, 'completed': 1},
            {'task_id': task_id, 'completed': None},
        ]
        for body in bodies:
            with self.subTest(body=body):
                response = self.client.post('/update_task', json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json)
        for malformed in ('{', 'null'):
            response = self.client.post(
                '/update_task', data=malformed, content_type='application/json',
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn('error', response.json)
        with self.app.app_context():
            task = db.session.get(Task, task_id)
            self.assertEqual(task.content, 'Keep this task')
            self.assertFalse(task.completed)

    def test_blank_tasks_cannot_be_completed(self):
        user_id = self.make_user()
        _, (task_id,) = self.make_day(user_id, [('', False)])
        self.sign_in(user_id)
        for changes in ({'completed': True}, {'content': ' \t\n ', 'completed': True}):
            with self.subTest(changes=changes):
                response = self.client.post('/update_task', json={
                    'task_id': task_id, **changes,
                })
                self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            task = db.session.get(Task, task_id)
            self.assertEqual(task.content, '')
            self.assertFalse(task.completed)

    def test_updates_return_saved_state_and_clearing_text_resets_completion(self):
        user_id = self.make_user()
        _, task_ids = self.make_day(user_id, [('', False), ('Another task', False)])
        task_id = task_ids[0]
        self.sign_in(user_id)
        response = self.client.post('/update_task', json={
            'task_id': task_id, 'content': 'Take a walk', 'completed': True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['completed_count'], 1)
        self.assertEqual(response.json['total'], 2)
        self.assertEqual(response.json['task'], {
            'id': task_id, 'content': 'Take a walk', 'completed': True,
        })
        cleared = self.client.post('/update_task', json={'task_id': task_id, 'content': '   '})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json['completed_count'], 0)
        self.assertFalse(cleared.json['task']['completed'])
        with self.app.app_context():
            self.assertFalse(db.session.get(Task, task_id).completed)

    def test_task_text_at_the_limit_is_saved(self):
        user_id = self.make_user()
        _, (task_id,) = self.make_day(user_id, [('', False)])
        self.sign_in(user_id)
        content = 'a' * 1000
        response = self.client.post('/update_task', json={'task_id': task_id, 'content': content})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['task']['content'], content)
        with self.app.app_context():
            self.assertEqual(db.session.get(Task, task_id).content, content)

    def test_daily_allocation_survives_refresh_and_resets_on_new_day(self):
        user_id = self.make_user()
        self.sign_in(user_id)
        with self.at_day() as clock, patch('app.random.randint', side_effect=[4, 6]) as draw:
            self.assertEqual(self.client.get('/dashboard').status_code, 200)
            with self.app.app_context():
                first = DailyTask.query.one()
                first_id = first.id
                first_task_ids = [task.id for task in first.tasks]
                self.assertEqual(first.task_number, 4)
                self.assertEqual(len(first.tasks), 4)
            self.client.post('/update_task', json={
                'task_id': first_task_ids[0], 'content': 'Saved work', 'completed': True,
            })
            self.assertEqual(self.client.get('/dashboard').status_code, 200)
            with self.app.app_context():
                refreshed = DailyTask.query.one()
                self.assertEqual(refreshed.id, first_id)
                self.assertEqual([task.id for task in refreshed.tasks], first_task_ids)
                self.assertTrue(refreshed.tasks[0].completed)
            self.assertEqual(draw.call_count, 1)
            tomorrow = self.today + timedelta(days=1)
            clock.now.return_value = datetime(
                tomorrow.year, tomorrow.month, tomorrow.day, 12, tzinfo=timezone.utc,
            )
            self.assertEqual(self.client.get('/dashboard').status_code, 200)
            with self.app.app_context():
                days = DailyTask.query.order_by(DailyTask.date).all()
                self.assertEqual(len(days), 2)
                self.assertEqual(days[1].task_number, 6)
                self.assertEqual(len(days[1].tasks), 6)
            self.assertEqual(draw.call_count, 2)

    def test_daily_uniqueness_prevents_duplicate_allocations(self):
        user_id = self.make_user()
        self.make_day(user_id, [('', False), ('', False)])
        with self.app.app_context():
            db.session.add(DailyTask(user_id=user_id, date=self.today, task_number=3))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            self.assertEqual(DailyTask.query.count(), 1)
            self.assertEqual(Task.query.count(), 2)

    def test_daily_allocation_rolls_back_if_task_creation_fails(self):
        user_id = self.make_user()
        self.sign_in(user_id)

        def reject_task_insert(*_args, **_kwargs):
            raise RuntimeError('Simulated task write failure')

        event.listen(Task, 'before_insert', reject_task_insert)
        try:
            with self.at_day(), self.assertRaisesRegex(RuntimeError, 'Simulated task write failure'):
                self.client.get('/dashboard')
        finally:
            event.remove(Task, 'before_insert', reject_task_insert)
        with self.app.app_context():
            self.assertEqual(DailyTask.query.count(), 0)
            self.assertEqual(Task.query.count(), 0)
        with self.at_day():
            self.assertEqual(self.client.get('/dashboard').status_code, 200)
        with self.app.app_context():
            daily = DailyTask.query.one()
            self.assertEqual(len(daily.tasks), daily.task_number)

    def test_daily_date_uses_bangkok_timezone_after_utc_day_boundary(self):
        user_id = self.make_user()
        self.sign_in(user_id)

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                utc_time = datetime(2026, 11, 7, 18, 30, tzinfo=timezone.utc)
                return utc_time.astimezone(tz) if tz else utc_time.replace(tzinfo=None)

        with patch('app.datetime', FixedDatetime):
            self.assertEqual(self.client.get('/dashboard').status_code, 200)
        with self.app.app_context():
            self.assertEqual(DailyTask.query.one().date, date(2026, 11, 8))

    def test_dashboard_repairs_partial_legacy_allocation_without_losing_work(self):
        user_id = self.make_user()
        day_id, original_ids = self.make_day(
            user_id, [('Keep my completed task', True), (' \t ', True)], total=4,
        )
        self.sign_in(user_id)
        with self.at_day(), rendered_context(self.app) as contexts:
            response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(contexts[-1]['completed_count'], 1)
        with self.app.app_context():
            daily = db.session.get(DailyTask, day_id)
            self.assertEqual(len(daily.tasks), 4)
            self.assertEqual([task.id for task in daily.tasks[:2]], original_ids)
            self.assertEqual(daily.tasks[0].content, 'Keep my completed task')
            self.assertTrue(daily.tasks[0].completed)
            self.assertFalse(daily.tasks[1].completed)

    def test_history_matches_dashboard_counts_and_only_lists_completed_work(self):
        user_id = self.make_user()
        self.make_day(user_id, [('Today win', True), ('Not done', False), ('  ', True)])
        yesterday = self.today - timedelta(days=1)
        self.make_day(user_id, [('Yesterday win', True), ('Second win', True)], day=yesterday)
        self.sign_in(user_id)
        with self.at_day(), rendered_context(self.app) as contexts:
            self.assertEqual(self.client.get('/dashboard').status_code, 200)
            self.assertEqual(self.client.get('/history').status_code, 200)
        dashboard = contexts[-2]
        history = contexts[-1]['history']
        self.assertEqual(dashboard['completed_count'], 1)
        self.assertEqual([day['completed'] for day in history], [1, 2])
        self.assertEqual([day['total'] for day in history], [3, 2])
        self.assertEqual([task.content for task in history[0]['tasks']], ['Today win'])
        self.assertFalse(history[0]['fully_completed'])
        self.assertTrue(history[1]['fully_completed'])

    def test_history_is_limited_to_the_signed_in_account(self):
        alice_id = self.make_user('alice')
        bob_id = self.make_user('bob')
        self.make_day(alice_id, [('Alice completed work', True)])
        self.make_day(bob_id, [('Bob private work', True)])
        self.sign_in(alice_id)
        with rendered_context(self.app) as contexts:
            response = self.client.get('/history')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(contexts[-1]['history']), 1)
        self.assertIn('Alice completed work', response.get_data(as_text=True))
        self.assertNotIn('Bob private work', response.get_data(as_text=True))

    def test_profile_rejects_invalid_json_and_only_updates_current_account(self):
        alice_id = self.make_user('alice')
        bob_id = self.make_user('bob')
        self.sign_in(alice_id)
        for body in ([], {}, {'avatar': []}, {'avatar': 'unexpected'}):
            response = self.client.post('/profile', json=body)
            self.assertEqual(response.status_code, 400)
            self.assertIn('error', response.json)
        response = self.client.post('/profile', json={'avatar': 'female'})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, alice_id).avatar, 'female')
            self.assertEqual(db.session.get(User, bob_id).avatar, 'anonymous')

    def test_health_get_and_head_do_not_query_the_database(self):
        self.sign_in(999999)
        with self.app.app_context():
            engine = db.engine

        def reject_database_work(*_args, **_kwargs):
            raise AssertionError('The health endpoint must not query the database')

        event.listen(engine, 'before_cursor_execute', reject_database_work)
        try:
            for method in ('GET', 'HEAD'):
                response = self.client.open('/health', method=method)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                if method == 'GET':
                    self.assertEqual(response.json, {'status': 'ok'})
                else:
                    self.assertEqual(response.data, b'')
        finally:
            event.remove(engine, 'before_cursor_execute', reject_database_work)


if __name__ == '__main__':
    unittest.main()
