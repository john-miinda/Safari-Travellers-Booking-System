import os
import logging
from flask import Flask, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from sqlalchemy import text
from config import Config


db = SQLAlchemy()
mail = Mail()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message_category = 'info'


def ensure_database_schema():
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS bus_id INTEGER",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS booked_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS return_date DATE",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS is_round_trip BOOLEAN DEFAULT FALSE",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS base_price INTEGER DEFAULT 1650",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS discount_percent DOUBLE PRECISION DEFAULT 5.0",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS total_price DOUBLE PRECISION DEFAULT 1650.0",
        "ALTER TABLE buses ADD COLUMN IF NOT EXISTS price DOUBLE PRECISION DEFAULT 1650.0",
    ]
    try:
        with db.engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    except Exception as e:
        current_app.logger.error(f"Error ensuring database schema: {e}")


def seed_default_admin():
    from werkzeug.security import generate_password_hash
    from app.models import User

    admin_email = current_app.config.get('ADMIN_EMAIL')
    admin_password = current_app.config.get('ADMIN_PASSWORD')
    if not admin_email or not admin_password:
        return

    try:
        admin_user = User.query.filter_by(email=admin_email).first()
        if not admin_user:
            admin_user = User(
                fullname='Administrator',
                email=admin_email,
                password=generate_password_hash(admin_password),
                is_admin=True,
            )
            db.session.add(admin_user)
            db.session.commit()
        elif not admin_user.is_admin:
            admin_user.is_admin = True
            db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Error seeding admin user: {e}")


def seed_demo_buses():
    from app.models import Bus

    try:
        existing_count = Bus.query.count()
        if existing_count >= 50:
            return

        routes = [
            'Nairobi - Mombasa',
            'Nairobi - Kisumu',
            'Nairobi - Nakuru',
            'Nakuru - Eldoret',
            'Mombasa - Malindi',
        ]
        departure_times = [
            '05:30 AM', '07:00 AM', '08:30 AM', '10:00 AM', '11:30 AM',
            '01:00 PM', '02:30 PM', '04:00 PM', '05:30 PM', '07:00 PM',
        ]
        created = 0
        existing_names = {bus.bus_name for bus in Bus.query.all()}

        for route in routes:
            for departure in departure_times:
                if created >= 50 - existing_count:
                    break
                bus_name = f"Safari {route.split(' - ')[0]} {departure.replace(':', '').replace(' ', '')}"
                if bus_name in existing_names:
                    continue
                bus = Bus(
                    bus_name=bus_name,
                    route=route,
                    departure_time=departure,
                    total_seats=18,
                    price=1650.0,
                )
                db.session.add(bus)
                existing_names.add(bus_name)
                created += 1
            if created >= 50 - existing_count:
                break

        if created > 0:
            db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Error seeding demo buses: {e}")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    from app.route import main
    app.register_blueprint(main)

    if not app.debug and not app.testing:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        )
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Safari Travellers Booking System starting')

    with app.app_context():
        try:
            db.create_all()
            ensure_database_schema()
            seed_default_admin()
            seed_demo_buses()
        except Exception as e:
            app.logger.error(f"Error during app initialization: {e}")

    return app
