//  static/js/script.js
// Client-side JavaScript for the admin dashboard
$(document).ready(function() {
    // Example: Add confirmation for cancelling orders
    $('.cancel-order-btn').on('click', function(e) {
        if (!confirm('Are you sure you want to cancel this order?')) {
            e.preventDefault();
        }
    });
    
    // Example: Auto-refresh dashboard data every 60 seconds
    if ($('#dashboard-stats').length) {
        setInterval(function() {
            location.reload();
        }, 60000);
    }
});