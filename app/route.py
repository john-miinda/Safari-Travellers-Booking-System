import os
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    abort,
    jsonify,
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

        if not travel_date or not bus_id:
            referrer = request.referrer
            if referrer:
                try:
                    params = parse_qs(urlparse(referrer).query)
                    travel_date = travel_date or params.get('travel_date', [None])[0]
                    bus_id = bus_id or params.get('bus_id', [None])[0]
                except Exception:
                    pass

        missing_fields = []
        if not passenger_name:
            missing_fields.append('passenger name')
        if not seat_number:
            missing_fields.append('seat')
        if not travel_date:
            missing_fields.append('travel date')
        if not bus_id:
            missing_fields.append('bus')

        if missing_fields:
            if len(missing_fields) == 1:
                message = f'{missing_fields[0].capitalize()} is required'
            else:
                message = ', '.join(missing_fields[:-1]) + f' and {missing_fields[-1]}'
                message = f'{message.capitalize()} are required'
            flash(message, 'warning')
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


@main.route('/about')
def about():
    paragraphs = [
        'Safari Travellers makes bus booking fast, simple and secure.',
        'Compare routes, choose a seat, and receive an instant confirmation email.',
        'Our service is designed to keep every journey comfortable and reliable.',
    ]
    return render_template('static_page.html', title='About Us', heading='About Safari Travellers', paragraphs=paragraphs)


@main.route('/faq')
def faq():
    faqs = [
        {'question': 'How do I book a bus?', 'answer': 'Search for a route, choose your bus, select a seat, and confirm your booking.'},
        {'question': 'Can I cancel a booking?', 'answer': 'Yes. Visit your bookings page to cancel before departure.'},
        {'question': 'Do you offer round-trip tickets?', 'answer': 'Yes. Select a return date during booking to enable a round trip.'},
        {'question': 'How do I reset my password?', 'answer': 'Use the forgot password page and follow the email instructions.'},
    ]
    return render_template('static_page.html', title='FAQ', heading='Frequently Asked Questions', items=faqs)


@main.route('/terms')
def terms():
    paragraphs = [
        'All bookings are subject to our terms and conditions.',
        'Please review your itinerary carefully before confirming your ticket.',
        'Safari Travellers reserves the right to modify schedules and services as needed.',
    ]
    return render_template('static_page.html', title='Terms & Conditions', heading='Terms and Conditions', paragraphs=paragraphs)


@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        fullname = request.form.get('fullname')
        if not fullname:
            flash('Full name cannot be empty.', 'warning')
            return redirect(url_for('main.profile'))
        current_user.fullname = fullname
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('main.profile'))

    return render_template('profile.html', user=current_user)


@main.route('/profile/edit')
@login_required
def edit_profile():
    return render_template('profile.html', user=current_user, edit_mode=True)


@main.route('/settings')
@login_required
def settings():
    preferences = {'email_notifications': True, 'sms_alerts': False}
    return render_template('settings.html', preferences=preferences, section='general')


@main.route('/settings/notifications', methods=['GET', 'POST'])
@login_required
def settings_notifications():
    preferences = {'email_notifications': True, 'sms_alerts': False}
    if request.method == 'POST':
        email_notifications = request.form.get('email_notifications') == 'on'
        sms_alerts = request.form.get('sms_alerts') == 'on'
        flash('Your notification preferences have been saved.', 'success')
        preferences['email_notifications'] = email_notifications
        preferences['sms_alerts'] = sms_alerts
    return render_template('settings.html', preferences=preferences, section='notifications')


@main.route('/bus/<int:bus_id>')
@login_required
def bus_detail(bus_id):
    bus = Bus.query.get_or_404(bus_id)
    selected_date = request.args.get('travel_date', '')
    available = None
    if selected_date:
        try:
            travel_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            available = bus.available_seats(travel_date)
        except ValueError:
            available = None
    return render_template('bus_detail.html', bus=bus, travel_date=selected_date, available=available)


@main.route('/booking/<int:booking_id>')
@login_required
def booking_detail(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id and not current_user.is_admin_user:
        abort(403)
    return render_template('booking_detail.html', booking=booking)


@main.route('/booking/<int:booking_id>/print')
@login_required
def booking_print(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id and not current_user.is_admin_user:
        abort(403)
    return render_template('booking_print.html', booking=booking)


@main.route('/admin/messages')
@login_required
def admin_messages():
    if not current_user.is_admin_user:
        abort(403)
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template('admin_messages.html', messages=messages)


@main.route('/admin/message/<int:message_id>/delete', methods=['POST'])
@login_required
def delete_message(message_id):
    if not current_user.is_admin_user:
        abort(403)
    message = ContactMessage.query.get_or_404(message_id)
    db.session.delete(message)
    db.session.commit()
    flash('Message deleted successfully.', 'success')
    return redirect(url_for('main.admin_messages'))


@main.route('/admin/reviews')
@login_required
def admin_reviews():
    if not current_user.is_admin_user:
        abort(403)
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    return render_template('admin_reviews.html', reviews=reviews)


@main.route('/admin/review/<int:review_id>/delete', methods=['POST'])
@login_required
def delete_review(review_id):
    if not current_user.is_admin_user:
        abort(403)
    review = Review.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash('Review deleted successfully.', 'success')
    return redirect(url_for('main.admin_reviews'))


@main.route('/admin/route-summary')
@login_required
def admin_route_summary():
    if not current_user.is_admin_user:
        abort(403)
    route_stats = db.session.query(
        Booking.route,
        db.func.count(Booking.id).label('bookings'),
        db.func.sum(Booking.total_price).label('revenue')
    ).group_by(Booking.route).order_by(db.func.count(Booking.id).desc()).all()
    route_summary = [
        {'route': r[0], 'bookings': r[1], 'revenue': r[2] or 0} for r in route_stats
    ]
    return render_template('admin_route_summary.html', route_summary=route_summary)


@main.route('/api/buses')
def api_buses():
    route_filter = request.args.get('route')
    query = Bus.query
    if route_filter:
        query = query.filter_by(route=route_filter)
    buses = query.order_by(Bus.route, Bus.departure_time).all()
    return jsonify([
        {
            'id': bus.id,
            'bus_name': bus.bus_name,
            'route': bus.route,
            'departure_time': bus.departure_time,
            'total_seats': bus.total_seats,
            'price': bus.price,
        }
        for bus in buses
    ])


@main.route('/api/bookings')
@login_required
def api_bookings():
    if current_user.is_admin_user:
        bookings = Booking.query.order_by(Booking.travel_date.desc()).all()
    else:
        bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.travel_date.desc()).all()
    return jsonify([
        {
            'id': booking.id,
            'bus_name': booking.bus.bus_name,
            'route': booking.route,
            'seat_number': booking.seat_number,
            'travel_date': booking.travel_date.isoformat(),
            'return_date': booking.return_date.isoformat() if booking.return_date else None,
            'total_price': booking.total_price,
        }
        for booking in bookings
    ])


@main.route('/api/reports')
@login_required
def api_reports():
    if not current_user.is_admin_user:
        abort(403)
    total_bookings = Booking.query.count()
    total_revenue = db.session.query(db.func.sum(Booking.total_price)).scalar() or 0
    top_routes = db.session.query(
        Booking.route,
        db.func.count(Booking.id).label('bookings'),
        db.func.sum(Booking.total_price).label('revenue')
    ).group_by(Booking.route).order_by(db.func.count(Booking.id).desc()).limit(5).all()
    return jsonify({
        'total_bookings': total_bookings,
        'total_revenue': total_revenue,
        'top_routes': [
            {'route': r[0], 'bookings': r[1], 'revenue': r[2] or 0} for r in top_routes
        ],
    })


@main.route('/admin/overview')
@login_required
def admin_overview():
    if not current_user.is_admin_user:
        abort(403)
    total_users = User.query.count()
    total_buses = Bus.query.count()
    total_bookings = Booking.query.count()
    return render_template('static_page.html', title='Admin Overview', heading='Admin Overview', paragraphs=[
        f'Total users: {total_users}',
        f'Total buses: {total_buses}',
        f'Total bookings: {total_bookings}',
    ])


@main.route('/help')
def help_page():
    paragraphs = [
        'Visit the FAQ page for answers to common questions.',
        'Use contact if you need personal support with your journey.',
    ]
    return render_template('static_page.html', title='Help', heading='Help Center', paragraphs=paragraphs)


@main.route('/privacy')
def privacy():
    paragraphs = [
        'Safari Travellers values your privacy and protects your personal information.',
        'We only use collected data to process bookings and communicate service updates.',
    ]
    return render_template('static_page.html', title='Privacy Policy', heading='Privacy Policy', paragraphs=paragraphs)


@main.route('/newsletter-signup', methods=['GET', 'POST'])
def newsletter_signup():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash('Email is required to sign up for the newsletter.', 'warning')
            return redirect(url_for('main.newsletter_signup'))
        flash('Thanks for signing up for the newsletter.', 'success')
        return redirect(url_for('main.home'))
    return render_template('static_page.html', title='Newsletter Signup', heading='Newsletter Signup', paragraphs=['Enter your email to receive trip alerts and promotions.'])


@main.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        name = request.form.get('name')
        message = request.form.get('message')
        if not name or not message:
            flash('Please provide both name and feedback message.', 'warning')
            return redirect(url_for('main.feedback'))
        flash('Thank you for your feedback.', 'success')
        return redirect(url_for('main.home'))
    return render_template('static_page.html', title='Feedback', heading='Send Feedback', paragraphs=['Share your feedback so we can improve the booking experience.'])


@main.route('/travel-tips')
def travel_tips():
    tips = [
        'Arrive at the bus station 30 minutes before departure.',
        'Carry a valid ID and your booking confirmation.',
        'Keep a small travel bag with essentials for the journey.',
    ]
    return render_template('static_page.html', title='Travel Tips', heading='Travel Tips', items=[{'question': tip, 'answer': ''} for tip in tips])


@main.route('/safety')
def safety():
    points = [
        'There is onboard security for all long-distance routes.',
        'Emergency contact numbers are provided on every ticket.',
    ]
    return render_template('static_page.html', title='Safety Information', heading='Safety Information', items=[{'question': point, 'answer': ''} for point in points])


@main.route('/mobile-app')
def mobile_app():
    paragraphs = [
        'Download the Safari Travellers mobile app to manage bookings on the go.',
        'Available for both Android and iOS devices.',
    ]
    return render_template('static_page.html', title='Mobile App', heading='Mobile App', paragraphs=paragraphs)


@main.route('/partners')
def partners():
    paragraphs = [
        'Safari Travellers works with vetted bus operators across the region.',
        'We partner with local carriers to keep routes reliable and affordable.',
    ]
    return render_template('static_page.html', title='Partners', heading='Our Partners', paragraphs=paragraphs)


@main.route('/terms-of-service')
def terms_of_service():
    return redirect(url_for('main.terms'))


@main.route('/support')
def support():
    return redirect(url_for('main.contact'))


@main.route('/route-map')
def route_map():
    return render_template('static_page.html', title='Route Map', heading='Route Map', paragraphs=['Explore all available routes and bus schedules before you book.'])


@main.route('/driver-info')
def driver_info():
    paragraphs = [
        'All drivers are certified and comply with local transport regulations.',
        'Driver information is available on your booking confirmation.',
    ]
    return render_template('static_page.html', title='Driver Information', heading='Driver Information', paragraphs=paragraphs)


@main.route('/travel-alerts')
def travel_alerts():
    paragraphs = [
        'Subscribe to travel alerts to receive updates about delays or changes.',
        'Alerts are sent by email and SMS when available.',
    ]
    return render_template('static_page.html', title='Travel Alerts', heading='Travel Alerts', paragraphs=paragraphs)


@main.route('/ticket-faq')
def ticket_faq():
    faqs = [
        {'question': 'What happens if my bus is delayed?', 'answer': 'We will notify you as soon as we receive an update.'},
        {'question': 'Can I change my seat after booking?', 'answer': 'Seat changes are subject to availability and may require support assistance.'},
    ]
    return render_template('static_page.html', title='Ticket FAQ', heading='Ticket FAQ', items=faqs)


@main.route('/sitemap')
def sitemap():
    return render_template('static_page.html', title='Sitemap', heading='Sitemap', paragraphs=['This page lists core application sections for easy navigation.'])


@main.route('/faq/general')
def faq_general():
    return redirect(url_for('main.faq'))


@main.route('/faq/booking')
def faq_booking():
    return render_template('static_page.html', title='Booking FAQ', heading='Booking FAQ', paragraphs=['Answers to the most common questions about booking a bus ticket.'])


@main.route('/faq/cancellations')
def faq_cancellations():
    return render_template('static_page.html', title='Cancellation FAQ', heading='Cancellation FAQ', paragraphs=['Learn about our cancellation policy and timelines.'])


@main.route('/faq/payments')
def faq_payments():
    return render_template('static_page.html', title='Payment FAQ', heading='Payment FAQ', paragraphs=['Information on accepted payment methods and refund processing.'])


@main.route('/service-status')
def service_status():
    return render_template('static_page.html', title='Service Status', heading='Service Status', paragraphs=['All systems are operational. Please check back later for updates.'])


@main.route('/newsletter')
def newsletter():
    return redirect(url_for('main.newsletter_signup'))


@main.route('/special-offers')
def special_offers():
    return render_template('static_page.html', title='Special Offers', heading='Special Offers', paragraphs=['Check this page for discounts and promotional fare bundles.'])


@main.route('/customer-care')
def customer_care():
    return redirect(url_for('main.contact'))


@main.route('/report-issue', methods=['GET', 'POST'])
def report_issue():
    if request.method == 'POST':
        issue = request.form.get('issue')
        if not issue:
            flash('Please describe the issue you are reporting.', 'warning')
            return redirect(url_for('main.report_issue'))
        flash('Your issue has been submitted. Thank you.', 'success')
        return redirect(url_for('main.home'))
    return render_template('static_page.html', title='Report an Issue', heading='Report an Issue', paragraphs=['Tell us what went wrong and our team will review it.'])


@main.route('/system-updates')
def system_updates():
    return render_template('static_page.html', title='System Updates', heading='System Updates', paragraphs=['We post important updates and maintenance notices here.'])


@main.route('/partner-offers')
def partner_offers():
    return render_template('static_page.html', title='Partner Offers', heading='Partner Offers', paragraphs=['Exclusive offers from our travel partners and service providers.'])


@main.route('/user-guides')
def user_guides():
    return render_template('static_page.html', title='User Guides', heading='User Guides', paragraphs=['Helpful guides to make booking and travelling easier.'])


@main.route('/arrival-guide')
def arrival_guide():
    return render_template('static_page.html', title='Arrival Guide', heading='Arrival Guide', paragraphs=['Tips for arriving at the bus station and boarding your bus.'])


@main.route('/departure-guide')
def departure_guide():
    return render_template('static_page.html', title='Departure Guide', heading='Departure Guide', paragraphs=['Instructions for departure day to ensure a smooth journey.'])


@main.route('/local-guides')
def local_guides():
    return render_template('static_page.html', title='Local Guides', heading='Local Guides', paragraphs=['Information about popular destinations and travel advice.'])


@main.route('/travel-checklist')
def travel_checklist():
    checklist = [
        'Valid ID',
        'Booking confirmation',
        'Medication and essentials',
    ]
    return render_template('static_page.html', title='Travel Checklist', heading='Travel Checklist', items=[{'question': item, 'answer': ''} for item in checklist])


@main.route('/bus-rules')
def bus_rules():
    rules = [
        'Arrive early to board on time.',
        'No smoking onboard.',
        'Keep luggage secure at all times.',
    ]
    return render_template('static_page.html', title='Bus Rules', heading='Bus Rules', items=[{'question': rule, 'answer': ''} for rule in rules])


@main.route('/route-updates')
def route_updates():
    return render_template('static_page.html', title='Route Updates', heading='Route Updates', paragraphs=['Check for the latest route and schedule changes here.'])


@main.route('/coach-facilities')
def coach_facilities():
    return render_template('static_page.html', title='Coach Facilities', heading='Coach Facilities', paragraphs=['Learn about onboard amenities and passenger comfort features.'])


@main.route('/contact-support')
def contact_support():
    return redirect(url_for('main.contact'))


@main.route('/travel-insurance')
def travel_insurance():
    return render_template('static_page.html', title='Travel Insurance', heading='Travel Insurance', paragraphs=['Learn about optional travel insurance for your bus journeys.'])


@main.route('/vip-services')
def vip_services():
    return render_template('static_page.html', title='VIP Services', heading='VIP Services', paragraphs=['Premium services for business and corporate travellers.'])


@main.route('/community')
def community():
    return render_template('static_page.html', title='Community', heading='Community', paragraphs=['Join our travel community for tips and shared experiences.'])


@main.route('/support-center')
def support_center():
    return redirect(url_for('main.contact'))


@main.route('/bus-safety')
def bus_safety():
    return render_template('static_page.html', title='Bus Safety', heading='Bus Safety', paragraphs=['Safety procedures and guidance for every passenger.'])


@main.route('/help-center')
def help_center():
    return redirect(url_for('main.help'))


@main.route('/bookings/summary')
@login_required
def bookings_summary():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.travel_date.desc()).all()
    return render_template('bookings.html', bookings=bookings)


@main.route('/travel-guides')
def travel_guides():
    return render_template('static_page.html', title='Travel Guides', heading='Travel Guides', paragraphs=['Explore travel tips, destination guides and local recommendations.'])


@main.route('/service-guidelines')
def service_guidelines():
    return render_template('static_page.html', title='Service Guidelines', heading='Service Guidelines', paragraphs=['Important guidance for using our booking and travel services.'])


@main.route('/special-routes')
def special_routes():
    return render_template('static_page.html', title='Special Routes', heading='Special Routes', paragraphs=['Discover special seasonal routes and promotional trips.'])


@main.route('/driver-guidelines')
def driver_guidelines():
    return render_template('static_page.html', title='Driver Guidelines', heading='Driver Guidelines', paragraphs=['Standards and expectations for our drivers on every journey.'])


@main.route('/bus-policy')
def bus_policy():
    return render_template('static_page.html', title='Bus Policy', heading='Bus Policy', paragraphs=['Policies that govern travel, baggage, cancellations, and conduct onboard.'])


@main.route('/routine-notices')
def routine_notices():
    return render_template('static_page.html', title='Routine Notices', heading='Routine Notices', paragraphs=['General notices about service updates and customer information.'])


@main.route('/events')
def events():
    return render_template('static_page.html', title='Events', heading='Events', paragraphs=['Information about travel-related events and promotions.'])


@main.route('/travel-news')
def travel_news():
    return render_template('static_page.html', title='Travel News', heading='Travel News', paragraphs=['Latest news and announcements from Safari Travellers.'])


@main.route('/help-topics')
def help_topics():
    return render_template('static_page.html', title='Help Topics', heading='Help Topics', paragraphs=['Common support topics and how-to articles.'])


@main.route('/tips')
def tips():
    return redirect(url_for('main.travel_tips'))


@main.route('/bus-faq')
def bus_faq():
    return redirect(url_for('main.faq_booking'))


@main.route('/passenger-guide')
def passenger_guide():
    return render_template('static_page.html', title='Passenger Guide', heading='Passenger Guide', paragraphs=['Helpful guidance for passengers before, during, and after the journey.'])


@main.route('/support-tickets')
def support_tickets():
    return redirect(url_for('main.contact'))


@main.route('/help-request', methods=['GET', 'POST'])
def help_request():
    if request.method == 'POST':
        request_text = request.form.get('request_text')
        if not request_text:
            flash('Please enter your request.', 'warning')
            return redirect(url_for('main.help_request'))
        flash('Your request has been submitted.', 'success')
        return redirect(url_for('main.home'))
    return render_template('static_page.html', title='Help Request', heading='Help Request', paragraphs=['Send us a help request and we will follow up shortly.'])


@main.route('/service-centers')
def service_centers():
    return render_template('static_page.html', title='Service Centers', heading='Service Centers', paragraphs=['Locations and details for our bus service centers across the region.'])


@main.route('/customer-feedback')
def customer_feedback():
    return redirect(url_for('main.reviews'))


@main.route('/support-updates')
def support_updates():
    return render_template('static_page.html', title='Support Updates', heading='Support Updates', paragraphs=['Updates about customer support and system improvements.'])


@main.route('/user-support')
def user_support():
    return redirect(url_for('main.contact'))


@main.route('/bus-information')
def bus_information():
    return redirect(url_for('main.route_map'))


@main.route('/group-booking')
def group_booking():
    return render_template('static_page.html', title='Group Booking', heading='Group Booking', paragraphs=['Ask our support team about group booking discounts and corporate trips.'])


@main.route('/student-discount')
def student_discount():
    return render_template('static_page.html', title='Student Discount', heading='Student Discount', paragraphs=['Learn about available student discount programs for selected routes.'])


@main.route('/corporate-travel')
def corporate_travel():
    return render_template('static_page.html', title='Corporate Travel', heading='Corporate Travel', paragraphs=['Corporate travel plans and business-friendly bus services.'])


@main.route('/family-packages')
def family_packages():
    return render_template('static_page.html', title='Family Packages', heading='Family Packages', paragraphs=['Family travel packages with special fares and seat allocation.'])


@main.route('/holiday-routes')
def holiday_routes():
    return render_template('static_page.html', title='Holiday Routes', heading='Holiday Routes', paragraphs=['Seasonal routes to popular holiday destinations.'])


@main.route('/travel-alerts/signup')
def travel_alerts_signup():
    return redirect(url_for('main.newsletter_signup'))


@main.route('/mobile-updates')
def mobile_updates():
    return render_template('static_page.html', title='Mobile Updates', heading='Mobile Updates', paragraphs=['Stay informed about app updates and new mobile features.'])


@main.route('/contact-us')
def contact_us():
    return redirect(url_for('main.contact'))


@main.route('/bus-schedules')
def bus_schedules():
    return redirect(url_for('main.search_buses'))


@main.route('/bookings/history')
@login_required
def bookings_history():
    return redirect(url_for('main.travel_history'))


@main.route('/user-terms')
def user_terms():
    return redirect(url_for('main.terms'))


@main.route('/privacy-policy')
def privacy_policy():
    return redirect(url_for('main.privacy'))


@main.route('/cookie-policy')
def cookie_policy():
    paragraphs = [
        'We use cookies to improve your browsing experience and remember your preferences.',
    ]
    return render_template('static_page.html', title='Cookie Policy', heading='Cookie Policy', paragraphs=paragraphs)


@main.route('/accessibility')
def accessibility():
    paragraphs = [
        'Safari Travellers is committed to accessibility for all customers.',
    ]
    return render_template('static_page.html', title='Accessibility', heading='Accessibility', paragraphs=paragraphs)


@main.route('/press')
def press():
    paragraphs = [
        'Press inquiries and media contacts are handled by our communications team.',
    ]
    return render_template('static_page.html', title='Press', heading='Press', paragraphs=paragraphs)


@main.route('/careers')
def careers():
    paragraphs = [
        'Explore career opportunities with Safari Travellers.',
    ]
    return render_template('static_page.html', title='Careers', heading='Careers', paragraphs=paragraphs)


@main.route('/travel-authority')
def travel_authority():
    paragraphs = [
        'Information from regulatory authorities for bus travel.',
    ]
    return render_template('static_page.html', title='Travel Authority', heading='Travel Authority', paragraphs=paragraphs)


@main.route('/customer-terms')
def customer_terms():
    return redirect(url_for('main.terms'))


@main.route('/bus-privacy')
def bus_privacy():
    return redirect(url_for('main.privacy'))


@main.route('/service-feedback')
def service_feedback():
    return redirect(url_for('main.feedback'))


@main.route('/travel-guide')
def travel_guide():
    return redirect(url_for('main.travel_guides'))


@main.route('/trip-planner')
def trip_planner():
    paragraphs = [
        'Plan your next trip with our route and seat selection tools.',
    ]
    return render_template('static_page.html', title='Trip Planner', heading='Trip Planner', paragraphs=paragraphs)


@main.route('/contact-team')
def contact_team():
    return redirect(url_for('main.contact'))


@main.route('/bus-updates')
def bus_updates():
    return render_template('static_page.html', title='Bus Updates', heading='Bus Updates', paragraphs=['Latest news about our bus fleet and route operations.'])


@main.route('/route-finder')
def route_finder():
    return redirect(url_for('main.search_buses'))


@main.route('/help-docs')
def help_docs():
    return render_template('static_page.html', title='Help Documents', heading='Help Documents', paragraphs=['Download brochures and guides for using the service.'])


@main.route('/site-support')
def site_support():
    return redirect(url_for('main.contact'))


@main.route('/trucked-safety')
def trucked_safety():
    paragraphs = [
        'Shared coach safety rules for commercial bus routes.',
    ]
    return render_template('static_page.html', title='Trucked Safety', heading='Trucked Safety', paragraphs=paragraphs)


@main.route('/bus-contacts')
def bus_contacts():
    return redirect(url_for('main.contact'))


@main.route('/travel-conditions')
def travel_conditions():
    paragraphs = [
        'Terms and conditions for passenger travel on all routes.',
    ]
    return render_template('static_page.html', title='Travel Conditions', heading='Travel Conditions', paragraphs=paragraphs)


@main.route('/complaints')
def complaints():
    paragraphs = [
        'Report complaints so we can address service issues quickly.',
    ]
    return render_template('static_page.html', title='Complaints', heading='Complaints', paragraphs=paragraphs)


@main.route('/faq/support')
def faq_support():
    return redirect(url_for('main.help'))


@main.route('/faq/routes')
def faq_routes():
    return render_template('static_page.html', title='Route FAQ', heading='Route FAQ', paragraphs=['Common questions about available routes and schedules.'])


@main.route('/faq/boarding')
def faq_boarding():
    return render_template('static_page.html', title='Boarding FAQ', heading='Boarding FAQ', paragraphs=['Boarding procedures and requirements for your journey.'])


@main.route('/faq/payments/general')
def faq_payments_general():
    return redirect(url_for('main.faq_payments'))


@main.route('/faq/cancellation-policy')
def faq_cancellation_policy():
    return redirect(url_for('main.faq_cancellations'))


@main.route('/faq/terms')
def faq_terms():
    return redirect(url_for('main.terms'))


@main.route('/bus-info')
def bus_info():
    return redirect(url_for('main.bus_information'))


@main.route('/travel-support')
def travel_support():
    return redirect(url_for('main.support'))


@main.route('/ticket-support')
def ticket_support():
    return redirect(url_for('main.contact'))


@main.route('/route-planner')
def route_planner():
    return redirect(url_for('main.route_map'))


@main.route('/booking-support')
def booking_support():
    return redirect(url_for('main.contact'))


@main.route('/travel-advice')
def travel_advice():
    paragraphs = [
        'Advice to help you travel safer and more comfortably.',
    ]
    return render_template('static_page.html', title='Travel Advice', heading='Travel Advice', paragraphs=paragraphs)


@main.route('/coach-safety')
def coach_safety():
    return redirect(url_for('main.bus_safety'))


@main.route('/service-terms')
def service_terms():
    return redirect(url_for('main.terms'))


@main.route('/user-support/contact')
def user_support_contact():
    return redirect(url_for('main.contact'))


@main.route('/ticket-info')
def ticket_info():
    return redirect(url_for('main.booking_detail', booking_id=1))


@main.route('/bus-checklist')
def bus_checklist():
    return redirect(url_for('main.travel_checklist'))


@main.route('/customer-service')
def customer_service():
    return redirect(url_for('main.contact'))


@main.route('/travel-landing')
def travel_landing():
    return render_template('static_page.html', title='Travel Landing', heading='Travel Landing', paragraphs=['Welcome to our travel landing page.'])


@main.route('/support-resources')
def support_resources():
    return render_template('static_page.html', title='Support Resources', heading='Support Resources', paragraphs=['Useful links and resources for planning your trip.'])


@main.route('/faq/privacy')
def faq_privacy():
    return redirect(url_for('main.privacy'))


@main.route('/faq/contact')
def faq_contact():
    return redirect(url_for('main.contact'))


@main.route('/support-guides')
def support_guides():
    return render_template('static_page.html', title='Support Guides', heading='Support Guides', paragraphs=['Download support guides for booking and travel procedures.'])


@main.route('/booking-resources')
def booking_resources():
    return redirect(url_for('main.bookings_summary'))


@main.route('/travel-resources')
def travel_resources():
    return render_template('static_page.html', title='Travel Resources', heading='Travel Resources', paragraphs=['Travel tools, checklists, and planning advice.'])


@main.route('/bus-fleet')
def bus_fleet():
    return render_template('static_page.html', title='Bus Fleet', heading='Bus Fleet', paragraphs=['Details about our modern fleet and onboard amenities.'])


@main.route('/route-services')
def route_services():
    return render_template('static_page.html', title='Route Services', heading='Route Services', paragraphs=['Service details for each route and trip type.'])


@main.route('/travel-programs')
def travel_programs():
    return render_template('static_page.html', title='Travel Programs', heading='Travel Programs', paragraphs=['Special programs for frequent travelers and loyalty members.'])


@main.route('/driver-support')
def driver_support():
    return redirect(url_for('main.contact'))


@main.route('/bus-safety-guidelines')
def bus_safety_guidelines():
    return render_template('static_page.html', title='Bus Safety Guidelines', heading='Bus Safety Guidelines', paragraphs=['Safety guidelines for travelling with Safari Travellers.'])


@main.route('/bookings/confirmation')
def bookings_confirmation():
    return redirect(url_for('main.home'))


@main.route('/trip-updates')
def trip_updates():
    return render_template('static_page.html', title='Trip Updates', heading='Trip Updates', paragraphs=['Latest updates on scheduled trips and services.'])


@main.route('/customer-advice')
def customer_advice():
    return render_template('static_page.html', title='Customer Advice', heading='Customer Advice', paragraphs=['Helpful advice for every passenger before and during travel.'])


@main.route('/travel-support-center')
def travel_support_center():
    return redirect(url_for('main.support'))


@main.route('/guide-lines')
def guide_lines():
    return render_template('static_page.html', title='Guide Lines', heading='Guide Lines', paragraphs=['Helpful guidelines for travellers using our service.'])


@main.route('/faq/usage')
def faq_usage():
    return render_template('static_page.html', title='Usage FAQ', heading='Usage FAQ', paragraphs=['Answers to how to use the booking platform.'])


@main.route('/faq/booking-tips')
def faq_booking_tips():
    return render_template('static_page.html', title='Booking Tips', heading='Booking Tips', paragraphs=['Tips to book the best bus seat and schedule.'])


@main.route('/faq/customer-service')
def faq_customer_service():
    return redirect(url_for('main.contact'))


@main.route('/faq/general-support')
def faq_general_support():
    return redirect(url_for('main.help'))


@main.route('/travel-documents')
def travel_documents():
    paragraphs = [
        'Carry all required travel documents when boarding your bus.',
    ]
    return render_template('static_page.html', title='Travel Documents', heading='Travel Documents', paragraphs=paragraphs)


@main.route('/travel-plans')
def travel_plans():
    return render_template('static_page.html', title='Travel Plans', heading='Travel Plans', paragraphs=['Plan and manage your upcoming trips with confidence.'])


@main.route('/service-quality')
def service_quality():
    paragraphs = [
        'We are committed to service quality, timeliness, and customer care.',
    ]
    return render_template('static_page.html', title='Service Quality', heading='Service Quality', paragraphs=paragraphs)


@main.route('/user-experience')
def user_experience():
    paragraphs = [
        'Share your experience to help us improve the booking platform.',
    ]
    return render_template('static_page.html', title='User Experience', heading='User Experience', paragraphs=paragraphs)


@main.route('/faq/payments/online')
def faq_payments_online():
    return render_template('static_page.html', title='Online Payments FAQ', heading='Online Payments FAQ', paragraphs=['Information on online payment security and available methods.'])


@main.route('/faq/covid')
def faq_covid():
    return render_template('static_page.html', title='COVID FAQ', heading='COVID FAQ', paragraphs=['Safety measures and travel advice during COVID-19.'])


@main.route('/safety-guides')
def safety_guides():
    return render_template('static_page.html', title='Safety Guides', heading='Safety Guides', paragraphs=['Practical safety guides for all passengers.'])


@main.route('/road-safety')
def road_safety():
    return render_template('static_page.html', title='Road Safety', heading='Road Safety', paragraphs=['Information about road safety on long distance routes.'])


@main.route('/service-notices')
def service_notices():
    return render_template('static_page.html', title='Service Notices', heading='Service Notices', paragraphs=['Official notices about service changes and important updates.'])


@main.route('/route-notices')
def route_notices():
    return render_template('static_page.html', title='Route Notices', heading='Route Notices', paragraphs=['Notices for route changes, delays, and schedule updates.'])


@main.route('/booking-advice')
def booking_advice():
    paragraphs = [
        'Follow our booking advice to select the best route and seat.',
    ]
    return render_template('static_page.html', title='Booking Advice', heading='Booking Advice', paragraphs=paragraphs)


@main.route('/passenger-services')
def passenger_services():
    return render_template('static_page.html', title='Passenger Services', heading='Passenger Services', paragraphs=['Services available to make passenger travel more comfortable.'])


@main.route('/travel-support/faq')
def travel_support_faq():
    return redirect(url_for('main.faq'))


@main.route('/customer-support/faq')
def customer_support_faq():
    return redirect(url_for('main.faq'))


@main.route('/travel-information')
def travel_information():
    return render_template('static_page.html', title='Travel Information', heading='Travel Information', paragraphs=['Essential information for planning your trip.'])


@main.route('/help-links')
def help_links():
    return render_template('static_page.html', title='Help Links', heading='Help Links', paragraphs=['Useful help and support links for travellers.'])


@main.route('/service-links')
def service_links():
    return render_template('static_page.html', title='Service Links', heading='Service Links', paragraphs=['Quick links to key service pages.'])


@main.route('/customer-links')
def customer_links():
    return render_template('static_page.html', title='Customer Links', heading='Customer Links', paragraphs=['Quick links for customers to manage their bookings and account.'])


@main.route('/travel-links')
def travel_links():
    return redirect(url_for('main.travel_guides'))


@main.route('/holiday-tips')
def holiday_tips():
    return render_template('static_page.html', title='Holiday Tips', heading='Holiday Tips', paragraphs=['Travel tips for holiday season trips.'])


@main.route('/route-guides')
def route_guides():
    return redirect(url_for('main.travel_guides'))


@main.route('/bus-advice')
def bus_advice():
    paragraphs = [
        'Helpful advice about travelling on Safari Travellers buses.',
    ]
    return render_template('static_page.html', title='Bus Advice', heading='Bus Advice', paragraphs=paragraphs)


@main.route('/trip-resources')
def trip_resources():
    return render_template('static_page.html', title='Trip Resources', heading='Trip Resources', paragraphs=['Resources to help you plan and enjoy your trip.'])


@main.route('/travel-checks')
def travel_checks():
    return render_template('static_page.html', title='Travel Checks', heading='Travel Checks', paragraphs=['Checklist items to verify before departure.'])


@main.route('/support-checks')
def support_checks():
    return redirect(url_for('main.help'))


@main.route('/payment-info')
def payment_info():
    paragraphs = [
        'Payment information for booking your bus ticket securely.',
    ]
    return render_template('static_page.html', title='Payment Info', heading='Payment Info', paragraphs=paragraphs)


@main.route('/discounts')
def discounts():
    paragraphs = [
        'Discover current discounts and promotional fares.',
    ]
    return render_template('static_page.html', title='Discounts', heading='Discounts', paragraphs=paragraphs)


@main.route('/services-overview')
def services_overview():
    return render_template('static_page.html', title='Services Overview', heading='Services Overview', paragraphs=['Overview of available booking and travel services.'])


@main.route('/user-help')
def user_help():
    return redirect(url_for('main.help'))


@main.route('/booking-help')
def booking_help():
    return redirect(url_for('main.help'))


@main.route('/travel-help')
def travel_help():
    return redirect(url_for('main.help'))


@main.route('/user-guides/faq')
def user_guides_faq():
    return redirect(url_for('main.faq'))


@main.route('/ticket-guides')
def ticket_guides():
    return render_template('static_page.html', title='Ticket Guides', heading='Ticket Guides', paragraphs=['Guides to help manage your ticket details and travel plans.'])


@main.route('/route-info')
def route_info():
    return redirect(url_for('main.route_map'))


@main.route('/booking-faqs')
def booking_faqs():
    return redirect(url_for('main.faq_booking'))


@main.route('/ticket-guidelines')
def ticket_guidelines():
    return render_template('static_page.html', title='Ticket Guidelines', heading='Ticket Guidelines', paragraphs=['Important ticket usage guidelines and policies.'])


@main.route('/travel-guidance')
def travel_guidance():
    return render_template('static_page.html', title='Travel Guidance', heading='Travel Guidance', paragraphs=['Guidance for planning your journey and staying informed.'])


@main.route('/support-guidance')
def support_guidance():
    return redirect(url_for('main.contact'))


@main.route('/booking-guidance')
def booking_guidance():
    return redirect(url_for('main.help'))


@main.route('/service-guidance')
def service_guidance():
    return render_template('static_page.html', title='Service Guidance', heading='Service Guidance', paragraphs=['Details that explain how our services work and what to expect.'])


@main.route('/route-support')
def route_support():
    return redirect(url_for('main.contact'))


@main.route('/travel-centre')
def travel_centre():
    return render_template('static_page.html', title='Travel Centre', heading='Travel Centre', paragraphs=['Your central destination for travel tools, tips, and support.'])


@main.route('/ticket-centre')
def ticket_centre():
    return render_template('static_page.html', title='Ticket Centre', heading='Ticket Centre', paragraphs=['Manage your tickets and see important ticketing information.'])


@main.route('/booking-centre')
def booking_centre():
    return redirect(url_for('main.search_buses'))


@main.route('/travel-support-centre')
def travel_support_centre():
    return redirect(url_for('main.help'))


@main.route('/online-support')
def online_support():
    return redirect(url_for('main.contact'))


@main.route('/customer-news')
def customer_news():
    return render_template('static_page.html', title='Customer News', heading='Customer News', paragraphs=['Updates and news for our customer community.'])


@main.route('/route-news')
def route_news():
    return render_template('static_page.html', title='Route News', heading='Route News', paragraphs=['News specific to route changes and service announcements.'])


@main.route('/booking-status')
def booking_status():
    return redirect(url_for('main.my_bookings'))


@main.route('/travel-status')
def travel_status():
    return render_template('static_page.html', title='Travel Status', heading='Travel Status', paragraphs=['Check the status of your journey and service alerts.'])


@main.route('/support-status')
def support_status():
    return render_template('static_page.html', title='Support Status', heading='Support Status', paragraphs=['Current support availability and response time information.'])


@main.route('/faq/partners')
def faq_partners():
    return render_template('static_page.html', title='Partners FAQ', heading='Partners FAQ', paragraphs=['Information about our partnership programs and partner services.'])


@main.route('/faq/company')
def faq_company():
    return render_template('static_page.html', title='Company FAQ', heading='Company FAQ', paragraphs=['Questions about Safari Travellers and our services.'])


@main.route('/faq/security')
def faq_security():
    paragraphs = [
        'Learn more about how we keep your booking and payment information secure.',
    ]
    return render_template('static_page.html', title='Security FAQ', heading='Security FAQ', paragraphs=paragraphs)


@main.route('/trip-plans')
def trip_plans():
    return render_template('static_page.html', title='Trip Plans', heading='Trip Plans', paragraphs=['Create and manage travel plans using our booking tools.'])


@main.route('/customer-journey')
def customer_journey():
    return render_template('static_page.html', title='Customer Journey', heading='Customer Journey', paragraphs=['Learn about the customer journey from booking to arrival.'])


@main.route('/support-journey')
def support_journey():
    return redirect(url_for('main.contact'))


@main.route('/faq/terms-of-service')
def faq_terms_of_service():
    return redirect(url_for('main.terms'))


@main.route('/faq/privacy-policy')
def faq_privacy_policy():
    return redirect(url_for('main.privacy'))


@main.route('/faq/cookie-policy')
def faq_cookie_policy():
    return redirect(url_for('main.cookie_policy'))


@main.route('/faq/accessibility')
def faq_accessibility():
    return redirect(url_for('main.accessibility'))


@main.route('/faq/careers')
def faq_careers():
    return render_template('static_page.html', title='Careers FAQ', heading='Careers FAQ', paragraphs=['Information about working with Safari Travellers.'])


@main.route('/support-articles')
def support_articles():
    return render_template('static_page.html', title='Support Articles', heading='Support Articles', paragraphs=['Browse support articles to learn how to use the service.'])


@main.route('/customer-articles')
def customer_articles():
    return render_template('static_page.html', title='Customer Articles', heading='Customer Articles', paragraphs=['Articles to help customers book and travel with confidence.'])


@main.route('/travel-articles')
def travel_articles():
    return render_template('static_page.html', title='Travel Articles', heading='Travel Articles', paragraphs=['Useful travel articles and destination tips.'])


@main.route('/bus-articles')
def bus_articles():
    return render_template('static_page.html', title='Bus Articles', heading='Bus Articles', paragraphs=['Content about bus safety, amenities, and travel services.'])


@main.route('/admin/settings')
@login_required
def admin_settings():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Admin Settings', heading='Admin Settings', paragraphs=['Administrative settings for Safari Travellers platform.'])


@main.route('/admin/support')
@login_required
def admin_support():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Admin Support', heading='Admin Support', paragraphs=['Admin support resources and guidelines.'])


@main.route('/admin/operations')
@login_required
def admin_operations():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Admin Operations', heading='Admin Operations', paragraphs=['Operations page for administrative users and system monitoring.'])


@main.route('/admin/notifications')
@login_required
def admin_notifications():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Admin Notifications', heading='Admin Notifications', paragraphs=['Review system notifications and admin alerts.'])


@main.route('/admin/contacts')
@login_required
def admin_contacts():
    if not current_user.is_admin_user:
        abort(403)
    return redirect(url_for('main.admin_messages'))


@main.route('/admin/bookings')
@login_required
def admin_bookings():
    if not current_user.is_admin_user:
        abort(403)
    bookings = Booking.query.order_by(Booking.travel_date.desc()).all()
    return render_template('admin_bookings.html', bookings=bookings)


@main.route('/admin/booking/<int:booking_id>/cancel', methods=['POST'])
@login_required
def admin_cancel_booking(booking_id):
    if not current_user.is_admin_user:
        abort(403)
    booking = Booking.query.get_or_404(booking_id)
    db.session.delete(booking)
    db.session.commit()
    flash('Booking cancelled successfully.', 'success')
    return redirect(url_for('main.admin_bookings'))


@main.route('/admin/booking/<int:booking_id>')
@login_required
def admin_booking_detail(booking_id):
    if not current_user.is_admin_user:
        abort(403)
    booking = Booking.query.get_or_404(booking_id)
    return render_template('booking_detail.html', booking=booking)


@main.route('/admin/bus/<int:bus_id>/bookings')
@login_required
def admin_bus_bookings(bus_id):
    if not current_user.is_admin_user:
        abort(403)
    bus = Bus.query.get_or_404(bus_id)
    bookings = Booking.query.filter_by(bus_id=bus.id).order_by(Booking.travel_date.desc()).all()
    return render_template('admin_route_summary.html', route_summary=[{'route': bus.route, 'bookings': len(bookings), 'revenue': sum(b.total_price for b in bookings)}])


@main.route('/admin/bus/<int:bus_id>/availability')
@login_required
def admin_bus_availability(bus_id):
    if not current_user.is_admin_user:
        abort(403)
    bus = Bus.query.get_or_404(bus_id)
    return render_template('static_page.html', title='Bus Availability', heading='Bus Availability', paragraphs=[f'Bus {bus.bus_name} route {bus.route} has {bus.total_seats} total seats.'])


@main.route('/admin/bus/<int:bus_id>/edit/confirm', methods=['POST'])
@login_required
def admin_edit_bus_confirm(bus_id):
    if not current_user.is_admin_user:
        abort(403)
    flash('Bus edit confirmation received.', 'info')
    return redirect(url_for('main.manage_buses'))


@main.route('/admin/bookings/summary')
@login_required
def admin_bookings_summary():
    if not current_user.is_admin_user:
        abort(403)
    total_bookings = Booking.query.count()
    return render_template('static_page.html', title='Bookings Summary', heading='Bookings Summary', paragraphs=[f'Total bookings: {total_bookings}'])


@main.route('/admin/alerts')
@login_required
def admin_alerts():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Admin Alerts', heading='Admin Alerts', paragraphs=['System alerts and administrator messages.'])


@main.route('/admin/reports/refresh')
@login_required
def admin_reports_refresh():
    if not current_user.is_admin_user:
        abort(403)
    flash('Reports refreshed.', 'success')
    return redirect(url_for('main.admin_reports'))


@main.route('/admin/dashboard-summary')
@login_required
def admin_dashboard_summary():
    if not current_user.is_admin_user:
        abort(403)
    total_buses = Bus.query.count()
    total_bookings = Booking.query.count()
    return render_template('static_page.html', title='Dashboard Summary', heading='Dashboard Summary', paragraphs=[f'Total buses: {total_buses}', f'Total bookings: {total_bookings}'])


@main.route('/admin/route-report')
@login_required
def admin_route_report():
    if not current_user.is_admin_user:
        abort(403)
    return redirect(url_for('main.admin_route_summary'))


@main.route('/admin/user-report')
@login_required
def admin_user_report():
    if not current_user.is_admin_user:
        abort(403)
    total_users = User.query.count()
    return render_template('static_page.html', title='User Report', heading='User Report', paragraphs=[f'Total users: {total_users}'])


@main.route('/admin/system-report')
@login_required
def admin_system_report():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='System Report', heading='System Report', paragraphs=['System report information is available here.'])


@main.route('/admin/analytics')
@login_required
def admin_analytics():
    if not current_user.is_admin_user:
        abort(403)
    total_revenue = db.session.query(db.func.sum(Booking.total_price)).scalar() or 0
    return render_template('static_page.html', title='Admin Analytics', heading='Admin Analytics', paragraphs=[f'Total revenue: KES {total_revenue:.2f}'])


@main.route('/admin/user-activity')
@login_required
def admin_user_activity():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='User Activity', heading='User Activity', paragraphs=['View user activity logs and booking trends.'])


@main.route('/admin/bus-analytics')
@login_required
def admin_bus_analytics():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Bus Analytics', heading='Bus Analytics', paragraphs=['Analytics for bus performance and loading.'])


@main.route('/admin/service-analytics')
@login_required
def admin_service_analytics():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Service Analytics', heading='Service Analytics', paragraphs=['Service analytics and performance reporting.'])


@main.route('/admin/ticket-analytics')
@login_required
def admin_ticket_analytics():
    if not current_user.is_admin_user:
        abort(403)
    return render_template('static_page.html', title='Ticket Analytics', heading='Ticket Analytics', paragraphs=['Analytics for ticket sales and passenger behavior.'])


@main.route('/community-feedback')
def community_feedback():
    return redirect(url_for('main.feedback'))


@main.route('/travel-community')
def travel_community():
    return render_template('static_page.html', title='Travel Community', heading='Travel Community', paragraphs=['Join our community for travel tips and shared experiences.'])


@main.route('/seat-map')
def seat_map():
    seat_layout = build_seat_map()
    return render_template('static_page.html', title='Seat Map', heading='Seat Map', paragraphs=['A sample seat map for the coach layout.'])


@main.route('/booking-details')
def booking_details():
    return redirect(url_for('main.my_bookings'))


@main.route('/travel-info-center')
def travel_info_center():
    return render_template('static_page.html', title='Travel Info Center', heading='Travel Info Center', paragraphs=['Central location for travel-related information.'])


@main.route('/route-safety')
def route_safety():
    return render_template('static_page.html', title='Route Safety', heading='Route Safety', paragraphs=['Safety information for route travel and passenger conduct.'])


@main.route('/booking-safety')
def booking_safety():
    return redirect(url_for('main.bus_safety'))


@main.route('/service-safety')
def service_safety():
    return redirect(url_for('main.bus_safety'))


@main.route('/planning-tools')
def planning_tools():
    return render_template('static_page.html', title='Planning Tools', heading='Planning Tools', paragraphs=['Tools and resources to plan your bus journey.'])


@main.route('/travel-tools')
def travel_tools():
    return render_template('static_page.html', title='Travel Tools', heading='Travel Tools', paragraphs=['Resources and tools to help manage your trip.'])


@main.route('/help-resources-center')
def help_resources_center():
    return redirect(url_for('main.help'))


@main.route('/support-center/home')
def support_center_home():
    return redirect(url_for('main.contact'))


@main.route('/customer-support-home')
def customer_support_home():
    return redirect(url_for('main.contact'))


@main.route('/travel-support-home')
def travel_support_home():
    return redirect(url_for('main.contact'))


@main.route('/route-support-home')
def route_support_home():
    return redirect(url_for('main.contact'))


@main.route('/ticket-support-home')
def ticket_support_home():
    return redirect(url_for('main.contact'))


@main.route('/service-support-home')
def service_support_home():
    return redirect(url_for('main.contact'))


@main.route('/user-support-home')
def user_support_home():
    return redirect(url_for('main.contact'))


@main.route('/support-portal')
def support_portal():
    return redirect(url_for('main.help'))


@main.route('/help-portal')
def help_portal():
    return redirect(url_for('main.help'))


@main.route('/booking-portal')
def booking_portal():
    return redirect(url_for('main.search_buses'))


@main.route('/travel-portal')
def travel_portal():
    return render_template('static_page.html', title='Travel Portal', heading='Travel Portal', paragraphs=['A hub for travel planning and support.'])


@main.route('/user-portal')
def user_portal():
    return redirect(url_for('main.dashboard'))


@main.route('/admin/portal')
@login_required
def admin_portal():
    if not current_user.is_admin_user:
        abort(403)
    return redirect(url_for('main.admin_dashboard'))


@main.route('/support-portal/home')
def support_portal_home():
    return redirect(url_for('main.contact'))


@main.route('/trip-assistance')
def trip_assistance():
    return render_template('static_page.html', title='Trip Assistance', heading='Trip Assistance', paragraphs=['Help and assistance for your journey.'])


@main.route('/route-assistance')
def route_assistance():
    return render_template('static_page.html', title='Route Assistance', heading='Route Assistance', paragraphs=['Assistance with planning and changing route bookings.'])


@main.route('/booking-assistance')
def booking_assistance():
    return redirect(url_for('main.help'))


@main.route('/travel-assistance')
def travel_assistance():
    return redirect(url_for('main.help'))


@main.route('/user-assistance')
def user_assistance():
    return redirect(url_for('main.help'))


@main.route('/support-assistance')
def support_assistance():
    return redirect(url_for('main.help'))


@main.route('/bus-assistance')
def bus_assistance():
    return render_template('static_page.html', title='Bus Assistance', heading='Bus Assistance', paragraphs=['Support for bus travel and onboard needs.'])


@main.route('/route-help')
def route_help():
    return redirect(url_for('main.help'))


@main.route('/trip-help')
def trip_help():
    return redirect(url_for('main.help'))


@main.route('/service-help')
def service_help():
    return redirect(url_for('main.help'))


@main.route('/support-index')
def support_index():
    return render_template('static_page.html', title='Support Index', heading='Support Index', paragraphs=['Index of support pages and resources.'])


@main.route('/travel-index')
def travel_index():
    return render_template('static_page.html', title='Travel Index', heading='Travel Index', paragraphs=['Index of travel resources and planning tools.'])


@main.route('/booking-index')
def booking_index():
    return render_template('static_page.html', title='Booking Index', heading='Booking Index', paragraphs=['Index of booking resources and guides.'])


@main.route('/customer-index')
def customer_index():
    return render_template('static_page.html', title='Customer Index', heading='Customer Index', paragraphs=['Index of customer-related resources.'])


@main.route('/help-index')
def help_index():
    return render_template('static_page.html', title='Help Index', heading='Help Index', paragraphs=['Index of help-related pages.'])


@main.route('/route-directory')
def route_directory():
    return render_template('static_page.html', title='Route Directory', heading='Route Directory', paragraphs=['Directory of routes and services.'])


@main.route('/travel-directory')
def travel_directory():
    return render_template('static_page.html', title='Travel Directory', heading='Travel Directory', paragraphs=['Directory of travel guides and support.'])


@main.route('/booking-directory')
def booking_directory():
    return render_template('static_page.html', title='Booking Directory', heading='Booking Directory', paragraphs=['Directory of booking guides and tools.'])


@main.route('/customer-directory')
def customer_directory():
    return render_template('static_page.html', title='Customer Directory', heading='Customer Directory', paragraphs=['Directory of customer support pages.'])


@main.route('/user-directory')
def user_directory():
    return render_template('static_page.html', title='User Directory', heading='User Directory', paragraphs=['Directory of user resources and settings.'])


@main.route('/social')
def social():
    return render_template('static_page.html', title='Social', heading='Social', paragraphs=['Stay connected with Safari Travellers on social media.'])


@main.route('/events-calendar')
def events_calendar():
    return render_template('static_page.html', title='Events Calendar', heading='Events Calendar', paragraphs=['Upcoming events and promotions for travellers.'])


@main.route('/press-center')
def press_center():
    return redirect(url_for('main.press'))


@main.route('/careers-center')
def careers_center():
    return redirect(url_for('main.careers'))


@main.route('/travel-hub')
def travel_hub():
    return render_template('static_page.html', title='Travel Hub', heading='Travel Hub', paragraphs=['A hub for travel information, support, and planning.'])


@main.route('/guide-hub')
def guide_hub():
    return render_template('static_page.html', title='Guide Hub', heading='Guide Hub', paragraphs=['A central hub for travel guides and tips.'])


@main.route('/support-hub')
def support_hub():
    return redirect(url_for('main.contact'))


@main.route('/booking-hub')
def booking_hub():
    return redirect(url_for('main.search_buses'))


@main.route('/route-hub')
def route_hub():
    return render_template('static_page.html', title='Route Hub', heading='Route Hub', paragraphs=['Information about routes and travel services.'])


@main.route('/customer-hub')
def customer_hub():
    return render_template('static_page.html', title='Customer Hub', heading='Customer Hub', paragraphs=['Useful resources for customers and travellers.'])


@main.route('/travel-portal/home')
def travel_portal_home():
    return redirect(url_for('main.travel_portal'))


@main.route('/booking-portal/home')
def booking_portal_home():
    return redirect(url_for('main.booking_portal'))


@main.route('/support-portal/home2')
def support_portal_home2():
    return redirect(url_for('main.help'))


@main.route('/help-portal/home')
def help_portal_home():
    return redirect(url_for('main.help'))


@main.route('/travel-support-home2')
def travel_support_home2():
    return redirect(url_for('main.support'))


@main.route('/bus-route')
def bus_route():
    return redirect(url_for('main.route_map'))


@main.route('/route-updates/alerts')
def route_updates_alerts():
    return render_template('static_page.html', title='Route Updates Alerts', heading='Route Updates Alerts', paragraphs=['Alerts about route changes and travel conditions.'])


@main.route('/service-alerts')
def service_alerts():
    return render_template('static_page.html', title='Service Alerts', heading='Service Alerts', paragraphs=['Alerts for service disruptions, delays, and maintenance.'])


@main.route('/booking-alerts')
def booking_alerts():
    return redirect(url_for('main.support'))


@main.route('/travel-alerts/updates')
def travel_alerts_updates():
    return redirect(url_for('main.travel_alerts'))


@main.route('/bus-updates/latest')
def bus_updates_latest():
    return redirect(url_for('main.bus_updates'))


@main.route('/support-updates/latest')
def support_updates_latest():
    return redirect(url_for('main.support_updates'))


@main.route('/travel-news/latest')
def travel_news_latest():
    return redirect(url_for('main.travel_news'))


@main.route('/customer-news/latest')
def customer_news_latest():
    return redirect(url_for('main.customer_news'))


@main.route('/route-news/latest')
def route_news_latest():
    return redirect(url_for('main.route_news'))


@main.route('/trip-updates/latest')
def trip_updates_latest():
    return redirect(url_for('main.trip_updates'))


@main.route('/support-status/latest')
def support_status_latest():
    return redirect(url_for('main.support_status'))


@main.route('/service-status/latest')
def service_status_latest():
    return redirect(url_for('main.service_status'))


@main.route('/route-status')
def route_status():
    return render_template('static_page.html', title='Route Status', heading='Route Status', paragraphs=['Current status information for major routes.'])


@main.route('/bus-status')
def bus_status():
    return render_template('static_page.html', title='Bus Status', heading='Bus Status', paragraphs=['Status updates for individual buses and routes.'])


@main.route('/ticket-status')
def ticket_status():
    return redirect(url_for('main.booking_status'))


@main.route('/customer-status')
def customer_status():
    return render_template('static_page.html', title='Customer Status', heading='Customer Status', paragraphs=['Status updates for customer requests and travel issues.'])


@main.route('/travel-status/latest')
def travel_status_latest():
    return redirect(url_for('main.travel_status'))


@main.route('/support-center/latest')
def support_center_latest():
    return redirect(url_for('main.support'))


@main.route('/booking-center/latest')
def booking_center_latest():
    return redirect(url_for('main.booking_portal'))


@main.route('/help-center/latest')
def help_center_latest():
    return redirect(url_for('main.help'))


@main.route('/customer-service/latest')
def customer_service_latest():
    return redirect(url_for('main.contact'))


@main.route('/travel-support/latest')
def travel_support_latest():
    return redirect(url_for('main.support'))


@main.route('/route-planning')
def route_planning():
    return render_template('static_page.html', title='Route Planning', heading='Route Planning', paragraphs=['Plan your route with helpful tools and guidance.'])


@main.route('/station-info')
def station_info():
    paragraphs = [
        'Station information and tips for arriving at departure points.',
    ]
    return render_template('static_page.html', title='Station Information', heading='Station Information', paragraphs=paragraphs)


@main.route('/help-info')
def help_info():
    return render_template('static_page.html', title='Help Info', heading='Help Info', paragraphs=['General help information and instructions.'])


@main.route('/support-info')
def support_info():
    return redirect(url_for('main.contact'))


@main.route('/travel-info/latest')
def travel_info_latest():
    return redirect(url_for('main.travel_information'))


@main.route('/booking-info/latest')
def booking_info_latest():
    return redirect(url_for('main.booking_help'))


@main.route('/route-info/latest')
def route_info_latest():
    return redirect(url_for('main.route_map'))


@main.route('/service-info/latest')
def service_info_latest():
    return redirect(url_for('main.service_guidelines'))


@main.route('/customer-info/latest')
def customer_info_latest():
    return redirect(url_for('main.customer_support'))


@main.route('/support-direct')
def support_direct():
    return redirect(url_for('main.contact'))


@main.route('/travel-direct')
def travel_direct():
    return redirect(url_for('main.travel_guides'))


@main.route('/booking-direct')
def booking_direct():
    return redirect(url_for('main.search_buses'))


@main.route('/route-direct')
def route_direct():
    return redirect(url_for('main.route_map'))


@main.route('/support-direct/latest')
def support_direct_latest():
    return redirect(url_for('main.contact'))


@main.route('/customer-direct/latest')
def customer_direct_latest():
    return redirect(url_for('main.contact'))


@main.route('/travel-direct/latest')
def travel_direct_latest():
    return redirect(url_for('main.travel_guides'))


@main.route('/booking-direct/latest')
def booking_direct_latest():
    return redirect(url_for('main.search_buses'))


@main.route('/route-direct/latest')
def route_direct_latest():
    return redirect(url_for('main.route_map'))


@main.route('/news-center')
def news_center():
    return redirect(url_for('main.travel_news'))


@main.route('/article-center')
def article_center():
    return redirect(url_for('main.travel_articles'))


@main.route('/guide-center')
def guide_center():
    return redirect(url_for('main.travel_guides'))


@main.route('/support-center/articles')
def support_center_articles():
    return redirect(url_for('main.support_articles'))


@main.route('/tourist-info')
def tourist_info():
    paragraphs = [
        'Useful tourist information for passengers travelling between cities.',
    ]
    return render_template('static_page.html', title='Tourist Info', heading='Tourist Info', paragraphs=paragraphs)


@main.route('/operator-info')
def operator_info():
    paragraphs = [
        'Information about our bus operators and service standards.',
    ]
    return render_template('static_page.html', title='Operator Info', heading='Operator Info', paragraphs=paragraphs)


@main.route('/service-guide')
def service_guide():
    return redirect(url_for('main.service_guidelines'))


@main.route('/travel-guide/latest')
def travel_guide_latest():
    return redirect(url_for('main.travel_guides'))


@main.route('/booking-guide/latest')
def booking_guide_latest():
    return redirect(url_for('main.booking_help'))


@main.route('/help-guide/latest')
def help_guide_latest():
    return redirect(url_for('main.help'))


@main.route('/support-guide/latest')
def support_guide_latest():
    return redirect(url_for('main.contact'))


@main.route('/service-guide/latest')
def service_guide_latest():
    return redirect(url_for('main.service_guidelines'))


@main.route('/route-guide/latest')
def route_guide_latest():
    return redirect(url_for('main.route_map'))


@main.route('/travel-guide/tips')
def travel_guide_tips():
    return redirect(url_for('main.travel_tips'))


@main.route('/support/faq')
def support_faq():
    return redirect(url_for('main.faq'))


@main.route('/help/faq')
def help_faq():
    return redirect(url_for('main.faq'))


@main.route('/booking/faq')
def booking_faq():
    return redirect(url_for('main.faq_booking'))


@main.route('/travel/faq')
def travel_faq():
    return redirect(url_for('main.faq'))


@main.route('/contact/faq')
def contact_faq():
    return redirect(url_for('main.faq_contact'))


@main.route('/faq/news')
def faq_news():
    return redirect(url_for('main.travel_news'))


@main.route('/faq/alerts')
def faq_alerts():
    return redirect(url_for('main.travel_alerts'))


@main.route('/faq/updates')
def faq_updates():
    return redirect(url_for('main.travel_alerts'))


@main.route('/help/updates')
def help_updates():
    return redirect(url_for('main.support_updates'))


@main.route('/support/updates')
def support_updates_redirect():
    return redirect(url_for('main.support_updates'))


@main.route('/service/updates')
def service_updates_redirect():
    return redirect(url_for('main.service_updates'))


@main.route('/travel/updates')
def travel_updates_redirect():
    return redirect(url_for('main.travel_updates'))


@main.route('/booking/updates')
def booking_updates_redirect():
    return redirect(url_for('main.trip_updates'))


@main.route('/route/updates')
def route_updates_redirect():
    return redirect(url_for('main.route_updates'))


@main.route('/ticket/updates')
def ticket_updates_redirect():
    return redirect(url_for('main.travel_updates'))


@main.route('/customer/updates')
def customer_updates_redirect():
    return redirect(url_for('main.support_updates'))


@main.route('/route-status/latest')
def route_status_latest():
    return redirect(url_for('main.route_status'))


@main.route('/bus-status/latest')
def bus_status_latest():
    return redirect(url_for('main.bus_status'))


@main.route('/service-status/alerts')
def service_status_alerts():
    return redirect(url_for('main.service_alerts'))


@main.route('/customer-care/home')
def customer_care_home():
    return redirect(url_for('main.contact'))


@main.route('/travel-care/home')
def travel_care_home():
    return redirect(url_for('main.support'))


@main.route('/route-care/home')
def route_care_home():
    return redirect(url_for('main.contact'))


@main.route('/trip-care/home')
def trip_care_home():
    return redirect(url_for('main.contact'))


@main.route('/support-care/home')
def support_care_home():
    return redirect(url_for('main.contact'))


@main.route('/help-care/home')
def help_care_home():
    return redirect(url_for('main.help'))


@main.route('/ticket-care/home')
def ticket_care_home():
    return redirect(url_for('main.contact'))


@main.route('/service-care/home')
def service_care_home():
    return redirect(url_for('main.contact'))


@main.route('/travel-care/home2')
def travel_care_home2():
    return redirect(url_for('main.support'))


@main.route('/customer-service/home')
def customer_service_home():
    return redirect(url_for('main.contact'))


@main.route('/route-service/home')
def route_service_home():
    return redirect(url_for('main.contact'))


@main.route('/booking-service/home')
def booking_service_home():
    return redirect(url_for('main.contact'))


@main.route('/support-service/home')
def support_service_home():
    return redirect(url_for('main.contact'))


@main.route('/help-service/home')
def help_service_home():
    return redirect(url_for('main.help'))


@main.route('/travel-service/home')
def travel_service_home():
    return redirect(url_for('main.support'))


@main.route('/route-service/home2')
def route_service_home2():
    return redirect(url_for('main.contact'))


@main.route('/service-support/home2')
def service_support_home2():
    return redirect(url_for('main.contact'))


@main.route('/customer-support/home2')
def customer_support_home2():
    return redirect(url_for('main.contact'))


@main.route('/support-tool')
def support_tool():
    return render_template('static_page.html', title='Support Tool', heading='Support Tool', paragraphs=['Access tools that help with support and service requests.'])


@main.route('/travel-tool')
def travel_tool():
    return render_template('static_page.html', title='Travel Tool', heading='Travel Tool', paragraphs=['Tools to help you manage travel plans and route searches.'])


@main.route('/booking-tool')
def booking_tool():
    return render_template('static_page.html', title='Booking Tool', heading='Booking Tool', paragraphs=['Tools to help you manage your booking experience with ease.'])


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


@main.route('/admin/reports')
@login_required
def admin_reports():
    if not current_user.is_admin_user:
        abort(403)

    total_bookings = Booking.query.count()
    total_revenue = db.session.query(db.func.sum(Booking.total_price)).scalar() or 0

    completed_trips = Booking.query.filter(Booking.travel_date < datetime.utcnow().date()).count()
    upcoming_trips = Booking.query.filter(Booking.travel_date >= datetime.utcnow().date()).count()

    recent_bookings = Booking.query.order_by(Booking.booked_at.desc()).limit(10).all()

    route_stats = db.session.query(
        Booking.route,
        db.func.count(Booking.id).label('booking_count'),
        db.func.sum(Booking.total_price).label('revenue')
    ).group_by(Booking.route).all()
    route_stats = [{'route': r[0], 'booking_count': r[1], 'revenue': r[2] or 0} for r in route_stats]

    bus_stats = []
    for bus in Bus.query.all():
        booked_seats = Booking.query.filter_by(bus_id=bus.id).count()
        bus_stats.append({
            'bus_name': bus.bus_name,
            'route': bus.route,
            'total_seats': bus.total_seats,
            'booked_seats': booked_seats
        })

    daily_stats = db.session.query(
        db.func.date(Booking.booked_at).label('date'),
        db.func.count(Booking.id).label('count'),
        db.func.sum(Booking.total_price).label('revenue')
    ).group_by(db.func.date(Booking.booked_at)).order_by(db.func.date(Booking.booked_at).desc()).limit(7).all()
    daily_stats = [{'date': d[0], 'count': d[1], 'revenue': d[2] or 0} for d in daily_stats]

    return render_template(
        'admin_reports.html',
        total_bookings=total_bookings,
        total_revenue=total_revenue,
        completed_trips=completed_trips,
        upcoming_trips=upcoming_trips,
        recent_bookings=recent_bookings,
        route_stats=route_stats,
        bus_stats=bus_stats,
        daily_stats=daily_stats,
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
