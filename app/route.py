import os
from datetime import datetime
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    abort,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Message

from app import db, login_manager, mail
from app.models import User, Booking, Bus, ContactMessage, Review

main = Blueprint('main', __name__)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def send_email(subject, recipients, body, html=None):
    if not current_app.config.get('MAIL_USERNAME'):
        current_app.logger.warning('Email not sent: MAIL_USERNAME is not configured')
        return
    msg = Message(subject, recipients=recipients, body=body, html=html)
    mail.send(msg)


def build_seat_map(total_seats=18):
    rows = ['A', 'B', 'C', 'D', 'E']
    seat_map = []
    seat_number = 1
    for row in rows:
        if seat_number > total_seats:
            break
        left = [f'{row}{seat_number}', f'{row}{seat_number + 1}']
        seat_number += 2
        right = [f'{row}{seat_number}', f'{row}{seat_number + 1}']
        seat_number += 2
        row_layout = [left[0], left[1], None, right[0], right[1]]
        seat_map.append([seat for seat in row_layout if seat is None or int(seat[1:]) <= total_seats])
    return seat_map


def get_route_options():
    routes = [bus.route for bus in Bus.query.distinct(Bus.route).all()]
    if not routes:
        return [
            'Nairobi - Mombasa',
            'Nairobi - Kisumu',
            'Nairobi - Nakuru',
            'Nakuru - Eldoret',
            'Mombasa - Malindi',
        ]
    return sorted(set(routes))


@main.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('main.login'))


@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = request.form.get('fullname')
        email = request.form.get('email')
        password = request.form.get('password')

        if not fullname or not email or not password:
            flash('All fields are required', 'warning')
            return redirect(url_for('main.register'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already exists. Please login.', 'warning')
            return redirect(url_for('main.login'))

        is_admin = False
        admin_email = current_app.config.get('ADMIN_EMAIL')
        if admin_email and admin_email.lower() == email.lower():
            is_admin = True

        new_user = User(
            fullname=fullname,
            email=email,
            password=generate_password_hash(password),
            is_admin=is_admin,
        )

        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully. Please login.', 'success')
        return redirect(url_for('main.login'))

    return render_template('register.html')


@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Welcome back!', 'success')
            return redirect(url_for('main.dashboard'))

        flash('Invalid email or password', 'danger')
        return redirect(url_for('main.login'))

    return render_template('login.html')


@main.route('/dashboard')
@login_required
def dashboard():
    quick_routes = get_route_options()
    return render_template('dashboard.html', user=current_user, routes=quick_routes)


@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.login'))


@main.route('/search-buses')
@login_required
def search_buses():
    selected_route = request.args.get('route', '')
    selected_date = request.args.get('travel_date', '')
    buses = []

    if selected_route and selected_date:
        try:
            travel_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid travel date', 'warning')
            return redirect(url_for('main.search_buses'))

        buses = Bus.query.filter_by(route=selected_route).order_by(Bus.departure_time).all()
        for bus in buses:
            booked_count = Booking.query.filter_by(bus_id=bus.id, travel_date=travel_date).count()
            bus.available = max(0, bus.total_seats - booked_count)

    routes = get_route_options()
    return render_template(
        'search_buses.html',
        routes=routes,
        buses=buses,
        selected_route=selected_route,
        selected_date=selected_date,
    )


@main.route('/book_ticket', methods=['GET', 'POST'])
@login_required
def book_ticket():
    if request.method == 'POST':
        passenger_name = request.form.get('passenger_name')
        seat_number = request.form.get('seat_number')
        travel_date = request.form.get('travel_date')
        return_date = request.form.get('return_date')
        bus_id = request.form.get('bus_id')

        if not all([passenger_name, seat_number, travel_date, bus_id]):
            flash('Passenger name, seat, travel date and bus are required', 'warning')
            return redirect(request.referrer or url_for('main.search_buses'))

        bus = Bus.query.get(bus_id)
        if not bus:
            flash('Selected bus is not available', 'danger')
            return redirect(url_for('main.search_buses'))

        try:
            travel_date_obj = datetime.strptime(travel_date, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid departure date format', 'warning')
            return redirect(url_for('main.book_ticket', bus_id=bus_id, travel_date=travel_date))

        return_date_obj = None
        is_round_trip = False
        if return_date:
            try:
                return_date_obj = datetime.strptime(return_date, '%Y-%m-%d').date()
                is_round_trip = True
            except ValueError:
                flash('Invalid return date format', 'warning')
                return redirect(url_for('main.book_ticket', bus_id=bus_id, travel_date=travel_date))

        existing = Booking.query.filter_by(
            bus_id=bus.id,
            seat_number=seat_number,
            travel_date=travel_date_obj,
        ).first()
        if existing:
            flash('Seat already booked for this bus and date', 'danger')
            return redirect(url_for('main.book_ticket', bus_id=bus_id, travel_date=travel_date))

        base_price = float(bus.price or 1650.0)
        discount_percent = 5.0
        total_price = base_price * (1 - discount_percent / 100.0)
        if is_round_trip:
            total_price *= 2

        booking = Booking(
            user_id=current_user.id,
            bus_id=bus.id,
            passenger_name=passenger_name,
            route=bus.route,
            seat_number=seat_number,
            travel_date=travel_date_obj,
            return_date=return_date_obj,
            is_round_trip=is_round_trip,
            base_price=int(base_price),
            discount_percent=discount_percent,
            total_price=total_price,
        )
        db.session.add(booking)
        db.session.commit()

        try:
            body = (
                f'Hello {current_user.fullname},\n\n'
                f'Your booking for {bus.bus_name} on {travel_date_obj} is confirmed.\n'
                f'Route: {bus.route}\nSeat: {seat_number}\nDeparture: {bus.departure_time}\n'
                f'Price: KES {total_price:.2f}\n\n'
                'Thank you for choosing Safari Travellers.'
            )
            send_email(
                'Safari Travellers Booking Confirmation',
                [current_user.email],
                body,
            )
        except Exception:
            current_app.logger.warning('Booking confirmation email failed')

        flash('Booking successful!', 'success')
        return redirect(url_for('main.booking_confirmation', booking_id=booking.id))

    bus_id = request.args.get('bus_id')
    selected_date = request.args.get('travel_date', '')
    if not bus_id:
        return redirect(url_for('main.search_buses'))

    bus = Bus.query.get(bus_id)
    if not bus:
        flash('Bus was not found', 'warning')
        return redirect(url_for('main.search_buses'))

    booked_seats = []
    selected_route = bus.route
    selected_date_obj = None
    if selected_date:
        try:
            selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            selected_date_obj = None

    if selected_date_obj:
        bookings = Booking.query.filter_by(bus_id=bus.id, travel_date=selected_date_obj).all()
        booked_seats = [booking.seat_number for booking in bookings]

    seat_map = build_seat_map(bus.total_seats)

    return render_template(
        'book_ticket.html',
        bus=bus,
        seat_map=seat_map,
        booked_seats=booked_seats,
        selected_route=selected_route,
        selected_date=selected_date,
    )


@main.route('/booking-confirmation/<int:booking_id>')
@login_required
def booking_confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id and not current_user.is_admin_user:
        abort(403)
    return render_template('booking_confirmation.html', booking=booking)


@main.route('/booking/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id and not current_user.is_admin_user:
        abort(403)
    db.session.delete(booking)
    db.session.commit()
    flash('Booking cancelled successfully.', 'success')
    return redirect(url_for('main.my_bookings'))


@main.route('/my-bookings')
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.travel_date.desc()).all()
    return render_template('bookings.html', bookings=bookings)


@main.route('/travel-history')
@login_required
def travel_history():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.travel_date.desc()).all()
    return render_template('travel_history.html', bookings=bookings)


@main.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin_user:
        abort(403)

    total_buses = Bus.query.count()
    total_bookings = Booking.query.count()
    upcoming_trip_count = Booking.query.filter(Booking.travel_date >= datetime.utcnow().date()).count()
    buses = Bus.query.order_by(Bus.departure_time).all()
    return render_template(
        'admin_dashboard.html',
        total_buses=total_buses,
        total_bookings=total_bookings,
        upcoming_trip_count=upcoming_trip_count,
        buses=buses,
    )


@main.route('/admin/buses', methods=['GET', 'POST'])
@login_required
def manage_buses():
    if not current_user.is_admin_user:
        abort(403)

    if request.method == 'POST':
        bus_name = request.form.get('bus_name')
        route = request.form.get('route')
        departure_time = request.form.get('departure_time')
        total_seats = request.form.get('total_seats')
        price = request.form.get('price')

        if not all([bus_name, route, departure_time, total_seats, price]):
            flash('All fields are required to add a bus', 'warning')
            return redirect(url_for('main.manage_buses'))

        try:
            total_seats = int(total_seats)
            price = float(price)
        except ValueError:
            flash('Total seats and price must be numeric', 'warning')
            return redirect(url_for('main.manage_buses'))

        bus = Bus(
            bus_name=bus_name,
            route=route,
            departure_time=departure_time,
            total_seats=total_seats,
            price=price,
        )
        db.session.add(bus)
        db.session.commit()
        flash('Bus added successfully', 'success')
        return redirect(url_for('main.manage_buses'))

    buses = Bus.query.order_by(Bus.route, Bus.departure_time).all()
    return render_template('admin_buses.html', buses=buses)


@main.route('/admin/bus/<int:bus_id>/delete', methods=['POST'])
@login_required
def delete_bus(bus_id):
    if not current_user.is_admin_user:
        abort(403)

    bus = Bus.query.get_or_404(bus_id)
    db.session.delete(bus)
    db.session.commit()
    flash('Bus removed successfully', 'success')
    return redirect(url_for('main.manage_buses'))


@main.route('/admin/bus/<int:bus_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_bus(bus_id):
    if not current_user.is_admin_user:
        abort(403)

    bus = Bus.query.get_or_404(bus_id)
    if request.method == 'POST':
        bus.bus_name = request.form.get('bus_name')
        bus.route = request.form.get('route')
        bus.departure_time = request.form.get('departure_time')
        bus.price = float(request.form.get('price') or bus.price)
        try:
            bus.total_seats = int(request.form.get('total_seats') or bus.total_seats)
        except ValueError:
            flash('Total seats must be a number', 'warning')
            return redirect(url_for('main.edit_bus', bus_id=bus.id))

        db.session.commit()
        flash('Bus updated successfully', 'success')
        return redirect(url_for('main.manage_buses'))

    return render_template('admin_edit_bus.html', bus=bus)


@main.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')

        if not all([name, email, message]):
            flash('Please provide your name, email, and message.', 'warning')
            return redirect(url_for('main.contact'))

        contact_message = ContactMessage(
            name=name,
            email=email,
            subject=subject,
            message=message,
        )
        db.session.add(contact_message)
        db.session.commit()

        flash('Thank you for contacting us. We will respond soon.', 'success')
        return redirect(url_for('main.contact'))

    return render_template('contact.html')


@main.route('/reviews', methods=['GET', 'POST'])
def reviews():
    if request.method == 'POST':
        name = request.form.get('name')
        rating = request.form.get('rating')
        review_text = request.form.get('review_text')

        if not all([name, rating, review_text]):
            flash('Please complete all review fields before submitting.', 'warning')
            return redirect(url_for('main.reviews'))

        try:
            rating_value = int(rating)
        except ValueError:
            flash('Rating must be a number between 1 and 5.', 'warning')
            return redirect(url_for('main.reviews'))

        if rating_value < 1 or rating_value > 5:
            flash('Rating must be between 1 and 5.', 'warning')
            return redirect(url_for('main.reviews'))

        review = Review(
            name=name,
            rating=rating_value,
            review_text=review_text,
        )
        db.session.add(review)
        db.session.commit()

        flash('Thank you for your review.', 'success')
        return redirect(url_for('main.reviews'))

    recent_reviews = Review.query.order_by(Review.created_at.desc()).limit(10).all()
    return render_template('reviews.html', reviews=recent_reviews)


@main.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = user.get_reset_token()
            reset_url = url_for('main.reset_password', token=token, _external=True)
            body = (
                f'Hi {user.fullname},\n\n'
                'We received a request to reset your password. Click the link below to set a new password:\n\n'
                f'{reset_url}\n\n'
                'If you did not request this, please ignore this email.'
            )
            send_email('Safari Travellers Password Reset', [user.email], body)
            flash('A password reset link has been sent to your email.', 'info')
            return redirect(url_for('main.login'))

        flash('Email address not found', 'warning')
        return redirect(url_for('main.forgot_password'))

    return render_template('forgot_password.html')


@main.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.verify_reset_token(token)
    if not user:
        flash('The password reset link is invalid or expired', 'danger')
        return redirect(url_for('main.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if not password or not confirm_password:
            flash('All fields are required', 'warning')
            return redirect(url_for('main.reset_password', token=token))
        if password != confirm_password:
            flash('Passwords do not match', 'warning')
            return redirect(url_for('main.reset_password', token=token))
        user.password = generate_password_hash(password)
        db.session.commit()
        flash('Your password has been updated. Please login.', 'success')
        return redirect(url_for('main.login'))

    return render_template('reset_password.html')
