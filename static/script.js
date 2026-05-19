function selectSeat(seat, el) {
    if (!el || el.disabled) return;
    const hidden = document.getElementById('seat_number');
    if (hidden) hidden.value = seat;
    document.querySelectorAll('.seat-btn').forEach(btn => {
        btn.classList.remove('seat-selected');
        btn.classList.remove('btn-success');
        btn.classList.add('btn-outline-primary');
    });
    el.classList.remove('btn-outline-primary');
    el.classList.add('btn-success');
    el.classList.add('seat-selected');
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

document.addEventListener('DOMContentLoaded', initSeatSelection);

function autoRefresh() {
    const route = document.querySelector('[name="route"]').value;
    const date = document.querySelector('[name="travel_date"]').value;
    if (route && date) {
        window.location.href = `/search-buses?route=${encodeURIComponent(route)}&travel_date=${date}`;
    }
}
