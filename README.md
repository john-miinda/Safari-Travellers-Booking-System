# Safari Travellers Booking System

Safari Travellers Booking System is a web-based bus reservation application built with Flask, Bootstrap, PostgreSQL, and SQLAlchemy. It allows users to register, view available buses by route and date, select seats, and book tickets. Each booking is linked to a specific bus and date, ensuring accurate seat management and preventing double bookings.

## Features

- User registration and authentication
- Route and date-based bus search
- Seat selection interface
- Ticket booking with validation
- Booking records tied to a specific bus and date
- Prevention of duplicate seat bookings
- Clean, responsive UI with Bootstrap

## Tech Stack

- Python
- Flask
- SQLAlchemy
- PostgreSQL
- Bootstrap
- HTML / CSS / JavaScript

## Project Structure

```text
.
├── app/
│   ├── __init__.py
│   ├── models.py
│   ├── routes.py
│   ├── forms.py
│   └── templates/
├── migrations/
├── instance/
├── requirements.txt
├── config.py
├── run.py
├── README.md
└── .env.example
```

## Getting Started

### Prerequisites

- Python 3.x
- PostgreSQL
- Virtual environment tool such as `venv` or `virtualenv`

### Installation

1. Clone the repository:

```bash
git clone https://github.com/john-miinda/Safari-Travellers-Booking-System.git
cd Safari-Travellers-Booking-System
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate   # On macOS/Linux
venv\Scripts\activate     # On Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure the database environment variables.

5. Run the application:

```bash
python run.py
```

Then open the app in your browser at `http://localhost:5000`.

## Database

This project uses PostgreSQL with SQLAlchemy for database management. Ensure your database is created and configured before running the app.

## License

This project is provided as-is for learning and development purposes.
