function selectSeat(seat, el) {
    if (!el || el.disabled) return;
    const hidden = document.getElementById('seat_number');
    if (hidden) {
        hidden.value = seat;
        hidden.dispatchEvent(new Event('change'));
    }
    document.querySelectorAll('.seat-btn').forEach(btn => {
        btn.classList.remove('seat-selected');
        btn.classList.remove('btn-success');
        btn.classList.add('btn-outline-primary');
    });
    el.classList.remove('btn-outline-primary');
    el.classList.add('btn-success');
    el.classList.add('seat-selected');
    
    const bookBtn = document.getElementById('book_btn');
    if (bookBtn) {
        bookBtn.disabled = false;
        bookBtn.classList.remove('disabled');
    }
}

function seatButtonClick(event) {
    const el = event.currentTarget;
    const seat = el.dataset.seat;
    if (!seat) return;
    selectSeat(seat, el);
}

function initSeatSelection() {
    document.querySelectorAll('.seat-btn[data-seat]:not(:disabled)').forEach(btn => {
        btn.removeEventListener('click', seatButtonClick);
        btn.addEventListener('click', seatButtonClick);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initSeatSelection();
    const bookBtn = document.getElementById('book_btn');
    const seatInput = document.getElementById('seat_number');
    
    if (bookBtn) {
        bookBtn.disabled = true;
        bookBtn.classList.add('disabled');
    }
    
    if (seatInput) {
        seatInput.addEventListener('change', function() {
            if (this.value.trim() && bookBtn) {
                bookBtn.disabled = false;
                bookBtn.classList.remove('disabled');
            } else if (bookBtn) {
                bookBtn.disabled = true;
                bookBtn.classList.add('disabled');
            }
        });
        seatInput.addEventListener('input', function() {
            if (this.value.trim() && bookBtn) {
                bookBtn.disabled = false;
                bookBtn.classList.remove('disabled');
            } else if (bookBtn) {
                bookBtn.disabled = true;
                bookBtn.classList.add('disabled');
            }
        });
    }
});


function validateBookingForm(event) {
    const seatInput = document.getElementById('seat_number');
    const passengerInput = document.querySelector('[name="passenger_name"]');
    
    if (!passengerInput || !passengerInput.value.trim()) {
        event.preventDefault();
        alert('Please enter your passenger name before booking.');
        return false;
    }
    
    if (!seatInput || !seatInput.value.trim()) {
        event.preventDefault();
        alert('Please select or type a seat number before booking.');
        return false;
    }
    
    return true;
}

document.addEventListener('DOMContentLoaded', function() {
    const form = document.querySelector('form[method="POST"]');
    if (form) {
        form.addEventListener('submit', validateBookingForm);
    }
});

function autoRefresh() {
    const route = document.querySelector('[name="route"]').value;
    const date = document.querySelector('[name="travel_date"]').value;
    if (route && date) {
        window.location.href = `/search-buses?route=${encodeURIComponent(route)}&travel_date=${date}`;
    }
}
