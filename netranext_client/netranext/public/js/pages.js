// NetraNext Client pages registration
// This file helps register custom pages in Frappe

frappe.pages['netranext-dashboard'].title = 'NetraNext Dashboard';
frappe.pages['netranext-mapview'].title = 'Journey Map';

// Add pages to desk
$(document).ready(function() {
    if (frappe.boot.user.all_pages && frappe.boot.user.all_pages.includes('netranext-dashboard')) {
        // Pages are properly registered
        console.log('NetraNext pages registered successfully');
    }
});
