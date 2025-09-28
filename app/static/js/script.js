//  static/js/script.js
// Client-side JavaScript for the admin dashboard
$(document).ready(function() {
    // Example: Add confirmation for cancelling orders
    $('.cancel-order-btn').on('click', function(e) {
        if (!confirm('Are you sure you want to cancel this order?')) {
            e.preventDefault();
        }
    });
    
    // Example: Auto-refresh dashboard stats using HTMX (already handled by HTMX in templates)
    // Dashboard stats are refreshed every 30 seconds via HTMX automatically
    // No need for full page reload
});