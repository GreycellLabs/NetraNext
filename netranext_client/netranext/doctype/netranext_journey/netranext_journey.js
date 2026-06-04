// NetraNext Journey Custom Script

frappe.ui.form.on('NetraNext Journey', {
    refresh: function(frm) {
        // Add a custom button to view this journey on the map if it's completed
        if (frm.doc.status === 'Completed') {
            frm.add_custom_button(__('View on Map'), function() {
                // Determine the correct date format
                var journeyDate = null;
                if (frm.doc.journey_date) {
                    journeyDate = frm.doc.journey_date;
                } else if (frm.doc.start_time) {
                    journeyDate = frm.doc.start_time.split(' ')[0];
                } else if (frm.doc.posting_date) {
                    journeyDate = frm.doc.posting_date.split(' ')[0];
                }

                // Set route options for the map view
                frappe.route_options = {
                    journey_id: frm.doc.name,
                    employee: frm.doc.employee,
                    date: journeyDate
                };

                // Navigate to the map view
                frappe.set_route('netranext-mapview');
            });
        }
    }
});
