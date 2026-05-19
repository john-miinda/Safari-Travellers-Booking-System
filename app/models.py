from datetime import datetime
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer
from app import db
from flask_login import UserMixin


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    bookings = db.relationship('Booking', back_populates='user', cascade='all, delete-orphan')

    def get_reset_token(self, expires_sec=1800):
        s = Serializer(current_app.config['SECRET_KEY'], expires_sec)
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
        except Exception:
            return None
        return User.query.get(data.get('user_id'))

    @property
    def is_admin_user(self):
        admin_email = current_app.config.get('ADMIN_EMAIL')
        return self.is_admin or (admin_email and self.email == admin_email)


class Booking(db.Model):
    __tablename__ = 'bookings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bus_id = db.Column(db.Integer, db.ForeignKey('buses.id'), nullable=False)
    passenger_name = db.Column(db.String(255), nullable=False)
    route = db.Column(db.String(255), nullable=False)
    seat_number = db.Column(db.String(50), nullable=False)
    travel_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    is_round_trip = db.Column(db.Boolean, default=False)
    base_price = db.Column(db.Integer, default=1650)
    discount_percent = db.Column(db.Float, default=5.0)
    total_price = db.Column(db.Float, nullable=False, default=1650.0)
    booked_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', back_populates='bookings')
    bus = db.relationship('Bus', back_populates='bookings')


class Bus(db.Model):
    __tablename__ = 'buses'

    id = db.Column(db.Integer, primary_key=True)
    bus_name = db.Column(db.String(100), nullable=False)
    route = db.Column(db.String(255), nullable=False)
    departure_time = db.Column(db.String(50), nullable=False)
    total_seats = db.Column(db.Integer, default=18)
    price = db.Column(db.Float, default=1650.0)
    bookings = db.relationship('Booking', back_populates='bus', cascade='all, delete-orphan')

    def occupied_seats(self, travel_date):
        return Booking.query.filter_by(bus_id=self.id, travel_date=travel_date).count()

    def available_seats(self, travel_date):
        return max(0, self.total_seats - self.occupied_seats(travel_date))


class ContactMessage(db.Model):
    __tablename__ = 'contact_messages'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Review(db.Model):
    __tablename__ = 'reviews'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
