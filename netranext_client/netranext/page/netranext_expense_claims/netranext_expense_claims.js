frappe.pages['netranext-expense-claims'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Expense Claim List',
        single_column: true
    });

    page.set_title('Expense Claim List');

    page.add_button(__('Refresh'), function () {
        load_claims();
    }, 'refresh');

    page.add_button(__('Trip History'), function () {
        frappe.set_route('netranext-trip-history');
    }, 'list');

    var employee_field = page.add_field({
        fieldtype: 'Link',
        label: 'Employee',
        fieldname: 'employee',
        options: 'Employee',
        placeholder: 'All Employees',
        change: function () {
            load_claims();
        }
    });

    var style = `
        <style>
            .ec-list-wrap { padding: 0; }
            .ec-stats {
                display: flex; gap: 24px; align-items: center;
                padding: 12px 16px; margin-bottom: 12px;
                background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
                font-size: 13px; color: #475569;
            }
            .ec-stats b { color: #0f172a; font-size: 15px; }
            .ec-table { width: 100%; border-collapse: collapse; background: #fff;
                border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }
            .ec-table th {
                text-align: left; padding: 10px 14px; background: #f1f5f9;
                color: #334155; font-size: 12px; text-transform: uppercase;
                letter-spacing: 0.4px; border-bottom: 1px solid #e2e8f0;
            }
            .ec-table td { padding: 11px 14px; font-size: 13px; color: #1e293b;
                border-bottom: 1px solid #f1f5f9; }
            .ec-table tr:last-child td { border-bottom: none; }
            .ec-table tbody tr { cursor: pointer; }
            .ec-table tbody tr:hover { background: #f8fafc; }
            .ec-pill { display: inline-block; padding: 3px 10px; border-radius: 999px;
                font-size: 11px; font-weight: 600; }
            .ec-pill.draft { background: #f1f5f9; color: #475569; }
            .ec-pill.submitted, .ec-pill.pending { background: #fef3c7; color: #92400e; }
            .ec-pill.approved, .ec-pill.paid { background: #dcfce7; color: #166534; }
            .ec-pill.rejected { background: #fee2e2; color: #991b1b; }
            .ec-pill.cancelled { background: #fee2e2; color: #64748b; }
            .ec-empty { text-align: center; padding: 48px 20px; color: #64748b; }
            .ec-link { color: #4f46e5; font-weight: 600; }
        </style>
    `;

    var html = style + `
        <div class="ec-list-wrap">
            <div class="ec-stats" id="ec-stats" style="display:none;">
                <span><b id="ec-count">0</b> claims</span>
                <span>Total distance: <b id="ec-distance">0.00 km</b></span>
                <span>Total amount: <b id="ec-amount">0.00</b></span>
            </div>
            <div id="ec-table-wrap">
                <div class="ec-empty"><div class="loader-spinner" style="margin: 0 auto 12px;"></div>Loading expense claims...</div>
            </div>
        </div>
    `;

    $(page.main).empty().append( /* nosemgrep */ html);

    function status_pill(status) {
        var s = (status || 'Draft').toString().toLowerCase();
        var cls = 'draft';
        if (['submitted', 'pending approval', 'pending'].indexOf(s) !== -1) cls = 'submitted';
        else if (['approved', 'paid'].indexOf(s) !== -1) cls = 'approved';
        else if (s === 'rejected') cls = 'rejected';
        else if (s === 'cancelled') cls = 'cancelled';
        return '<span class="ec-pill ' + cls + '">' + frappe.utils.escape_html(status || 'Draft') + '</span>';
    }

    function render_claims(data) {
        var wrap = $('#ec-table-wrap');
        if (!data || !data.claims || data.claims.length === 0) {
            wrap.html( /* nosemgrep */ '<div class="ec-empty">' +
                '<div style="font-size: 40px; margin-bottom: 12px;">🧾</div>' +
                '<div style="font-weight: 600;">No expense claims yet.</div>' +
                '<div style="font-size: 12px; margin-top: 4px;">Claims are generated automatically when a trip with distance is completed.</div>' +
                '</div>');
            $('#ec-stats').hide();
            return;
        }

        var rows = data.claims.map(function (c) {
            return '<tr data-name="' + frappe.utils.escape_html(c.name) + '">' +
                '<td>' + frappe.utils.escape_html(c.employee_name || c.employee || '-') + '</td>' +
                '<td>' + frappe.utils.escape_html(c.trip_date || '-') + '</td>' +
                '<td>' + (c.distance_km || 0) + ' km</td>' +
                '<td>' + (c.rate_per_km || 0) + '</td>' +
                '<td style="font-weight: 600;">' + (c.total_amount || 0) + '</td>' +
                '<td>' + status_pill(c.status) + '</td>' +
                '<td class="ec-link">' + frappe.utils.escape_html(c.custom_reference_trip || '') + '</td>' +
                '</tr>';
        }).join('');

        wrap.html( /* nosemgrep */ '<table class="ec-table">' +
            '<thead><tr>' +
            '<th>Employee Name</th><th>Trip Date</th><th>Distance (km)</th>' +
            '<th>Rate / km</th><th>Total Amount</th><th>Status</th><th>Reference Trip</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>');

        $('#ec-count').text(data.totals.count);
        $('#ec-distance').text(data.totals.distance_km + ' km');
        $('#ec-amount').text(data.totals.amount);
        $('#ec-stats').show();

        wrap.find('tr[data-name]').on('click', function () {
            var name = $(this).attr('data-name');
            if (name) {
                frappe.set_route('Form', 'Expense Claim', name);
            }
        });
    }

    function load_claims() {
        $('#ec-table-wrap').html( /* nosemgrep */ '<div class="ec-empty">' +
            '<div class="loader-spinner" style="margin: 0 auto 12px;"></div>Loading expense claims...</div>');

        frappe.call({
            method: "netranext_client.netranext.page.netranext_expense_claims.netranext_expense_claims.get_expense_claims",
            args: {
                employee: employee_field.get_value() || ''
            },
            callback: function (response) {
                if (response.message) {
                    render_claims(response.message);
                } else {
                    render_claims(null);
                }
            },
            error: function () {
                $('#ec-table-wrap').html( /* nosemgrep */ '<div class="ec-empty">Failed to load expense claims.</div>');
            }
        });
    }

    load_claims();
};
