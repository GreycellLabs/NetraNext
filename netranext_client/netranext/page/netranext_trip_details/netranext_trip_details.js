frappe.pages['netranext-trip-details'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('Trip Details'),
        single_column: true
    });

    var html = `
    <div class="netranext-trip-details-container">
        
        <!-- VIEW 1: ALL TRIPS LIST VIEW (Matches Frappe DocType List View) -->
        <div id="view-all-trips-list">
            
            <!-- FILTER TOOLBAR -->
            <div class="frappe-card filter-toolbar" style="padding: 12px 15px; margin-bottom: 15px; background: #ffffff; border-radius: 6px; border: 1px solid #e5e7eb; display: flex; flex-wrap: wrap; align-items: center; gap: 10px;">
                <div style="flex: 1; min-width: 200px;">
                    <input type="text" id="filter-search" class="form-control input-sm" placeholder="Search ID, Employee, Journey..." style="height: 32px; font-size: 13px;">
                </div>
                <div style="width: 140px;">
                    <select id="filter-status" class="form-control input-sm" style="height: 32px; font-size: 13px;">
                        <option value="">All Statuses</option>
                        <option value="Completed">Completed</option>
                        <option value="In Progress">In Progress</option>
                        <option value="Cancelled">Cancelled</option>
                    </select>
                </div>
                <div style="width: 150px;">
                    <input type="text" id="filter-employee" class="form-control input-sm" placeholder="Employee ID..." style="height: 32px; font-size: 13px;">
                </div>
                <div style="width: 140px;">
                    <input type="date" id="filter-date" class="form-control input-sm" style="height: 32px; font-size: 13px;">
                </div>
                <div style="display: flex; gap: 6px;">
                    <button class="btn btn-default btn-sm" id="btn-clear-filter" style="height: 32px; padding: 4px 12px;">
                        Clear
                    </button>
                </div>
            </div>

            <!-- TRIPS TABLE CARD -->
            <div class="frappe-card" style="padding: 0; border-radius: 6px; overflow: hidden;">
                <div class="table-responsive">
                    <table class="table table-bordered table-hover trips-table" style="margin-bottom: 0;">
                        <thead>
                            <tr style="background: #f9fafb;">
                                <th>ID</th>
                                <th>Status</th>
                                <th>Employee</th>
                                <th>Start Time</th>
                                <th>Distance (km)</th>
                                <th>Duration</th>
                            </tr>
                        </thead>
                        <tbody id="trips-table-body">
                            <tr>
                                <td colspan="6" class="text-center text-muted" style="padding: 20px;">Loading trips list...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div class="list-pagination-bar" style="padding: 10px 15px; background: #f9fafb; border-top: 1px solid #e5e7eb; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span class="text-muted" style="font-size: 12px; font-weight: 600;">Rows:</span>
                        <button class="btn btn-default btn-xs btn-limit active-limit" data-limit="20">20</button>
                        <button class="btn btn-default btn-xs btn-limit" data-limit="100">100</button>
                        <button class="btn btn-default btn-xs btn-limit" data-limit="500">500</button>
                        <button class="btn btn-default btn-xs btn-limit" data-limit="2500">2500</button>
                    </div>
                    <span id="trips-count-badge" class="text-muted" style="font-size: 12px; font-weight: 500;">-</span>
                </div>
            </div>
        </div>

        <!-- VIEW 2: SINGLE TRIP DETAILS & MAP VIEW (Hidden by Default) -->
        <div id="view-single-trip-details" style="display: none;">
            <div class="frappe-card">
                <div class="trip-detail-header">
                    <div>
                        <button class="btn btn-default btn-xs" id="btn-back-to-list" title="Back to All Trips List" style="padding: 4px 10px;">
                            <i class="fa fa-arrow-left"></i>
                        </button>
                        <span id="single-trip-title" style="display: inline-block; margin-left: 10px; font-weight: 500; font-size: 13px; color: #64748b;"></span>
                    </div>
                    <span id="single-trip-status-badge" class="indicator-pill green">Completed</span>
                </div>

                <div class="metric-box-grid">
                    <div class="metric-box">
                        <div class="label">Employee</div>
                        <div class="value" id="single-trip-employee">-</div>
                    </div>
                    <div class="metric-box">
                        <div class="label">Date</div>
                        <div class="value" id="single-trip-date">-</div>
                    </div>
                    <div class="metric-box">
                        <div class="label">Distance</div>
                        <div class="value" id="single-trip-distance">-</div>
                    </div>
                    <div class="metric-box">
                        <div class="label">Duration</div>
                        <div class="value" id="single-trip-duration">-</div>
                    </div>
                </div>
                <!-- Start/End Location cards removed: locations are shown in the Event Timeline -->
            </div>

            <!-- Two-Column Grid: Timeline & Telemetry Left, Map Right -->
            <div class="split-view-grid">
                <!-- Left Panel: Event Timeline & Telemetry -->
                <div style="display: flex; flex-direction: column; gap: 15px;">
                    <!-- Event Timeline Card -->
                    <div class="frappe-card collapsible-card">
                        <div class="card-expand-header" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; padding-bottom: 2px;">
                            <h5 style="font-weight: 600; margin: 0; font-size: 13px; color: #334155;">
                                <i class="fa fa-history text-info"></i> Event Timeline
                            </h5>
                            <i class="fa fa-chevron-up toggle-chevron" style="color: #94a3b8; font-size: 11px; transition: transform 0.2s ease;"></i>
                        </div>
                        <div class="card-expand-content" style="margin-top: 12px;">
                            <ul class="timeline-container" id="single-trip-timeline-list">
                                <li class="timeline-event-item">
                                    <div class="timeline-event-box">Loading trip details...</div>
                                </li>
                            </ul>
                        </div>
                    </div>

                    <!-- Odometer & Verification Details Card -->
                    <div class="frappe-card collapsible-card" id="single-trip-odometer-card" style="display: none;">
                        <div class="card-expand-header" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; padding-bottom: 2px;">
                            <h5 style="font-weight: 600; margin: 0; font-size: 13px; color: #334155;">
                                <i class="fa fa-tachometer-alt text-warning"></i> Odometer & Verification Details
                            </h5>
                            <i class="fa fa-chevron-up toggle-chevron" style="color: #94a3b8; font-size: 11px; transition: transform 0.2s ease;"></i>
                        </div>
                        <div class="card-expand-content" style="margin-top: 12px;">
                            <div id="single-trip-odometer-container"></div>
                        </div>
                    </div>

                    <!-- Device & Telemetry Details Card -->
                    <div class="frappe-card collapsible-card">
                        <div class="card-expand-header" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; padding-bottom: 2px;">
                            <h5 style="font-weight: 600; margin: 0; font-size: 13px; color: #334155;">
                                <i class="fa fa-mobile-alt text-primary"></i> Device & Telemetry Details
                            </h5>
                            <i class="fa fa-chevron-up toggle-chevron" style="color: #94a3b8; font-size: 11px; transition: transform 0.2s ease;"></i>
                        </div>
                        <div class="card-expand-content" style="margin-top: 12px;">
                            <div id="single-trip-telemetry-container">
                                <div style="color: #94a3b8; font-size: 12px;">Loading telemetry data...</div>
                            </div>
                        </div>
                    </div>

                    <!-- Trip Health Log card removed: health log data is server-side only -->
                </div>

                <!-- Right Panel: Interactive Leaflet Map -->
                <div class="frappe-card collapsible-card">
                    <div class="card-expand-header" style="cursor: pointer; display: flex; justify-content: space-between; align-items: center; user-select: none; padding-bottom: 2px;">
                        <h5 style="font-weight: 600; margin: 0; font-size: 13px; color: #334155;">
                            <i class="fa fa-map-marked-alt text-primary"></i> Route Path & Location Events
                        </h5>
                        <i class="fa fa-chevron-up toggle-chevron" style="color: #94a3b8; font-size: 11px; transition: transform 0.2s ease;"></i>
                    </div>
                    <div class="card-expand-content" style="margin-top: 12px;">
                        <div id="single-trip-map-container" style="height: 480px; width: 100%; border-radius: 6px; border: 1px solid #e5e7eb;"></div>
                    </div>
                </div>
            </div>
        </div>

    </div>
    `;

    $(wrapper).find('.layout-main-section').html(html);

    page.trip_map = null;
    page.current_limit = 20;

    // Helper to dynamically load Leaflet assets asynchronously when map is needed
    function ensureLeaflet(callback) {
        if (typeof L !== 'undefined') {
            callback();
            return;
        }

        $('<link>')
            .attr('rel', 'stylesheet')
            .attr('href', '/assets/frappe/js/lib/leaflet/leaflet.css')
            .appendTo('head');

        $.getScript('/assets/frappe/js/lib/leaflet/leaflet.js')
            .done(function() {
                callback();
            })
            .fail(function() {
                $.getScript('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js')
                    .done(function() {
                        callback();
                    })
                    .fail(function() {
                        callback(); // Continue even if map library fails to load
                    });
            });
    }

    page.init_page = function() {
        // Pagination Limit Buttons
        $('.btn-limit').on('click', function() {
            $('.btn-limit').removeClass('active-limit btn-primary').addClass('btn-default');
            $(this).removeClass('btn-default').addClass('btn-primary active-limit');
            page.current_limit = $(this).data('limit');
            page.load_all_trips();
        });

        // Filter event listeners
        $('#btn-clear-filter').on('click', function() {
            $('#filter-search').val('');
            $('#filter-status').val('');
            $('#filter-employee').val('');
            $('#filter-date').val('');
            page.load_all_trips();
        });

        $('#filter-search, #filter-employee').on('input keyup', function() {
            page.load_all_trips();
        });

        $('#filter-status, #filter-date').on('change', function() {
            page.load_all_trips();
        });

        $('#btn-back-to-list').on('click', function() {
            page.show_list_view();
        });

        // Collapsible Card Expand/Collapse Toggle
        $(wrapper).on('click', '.card-expand-header', function() {
            var content = $(this).next('.card-expand-content');
            var chevron = $(this).find('.toggle-chevron');
            content.slideToggle(200, function() {
                if (page.trip_map && typeof L !== 'undefined') {
                    page.trip_map.invalidateSize();
                }
            });
            if (chevron.hasClass('fa-chevron-up')) {
                chevron.removeClass('fa-chevron-up').addClass('fa-chevron-down');
            } else {
                chevron.removeClass('fa-chevron-down').addClass('fa-chevron-up');
            }
        });

        // Check if a specific trip_id was requested
        var requestedTripId = null;
        if (frappe.route_options && frappe.route_options.trip_id) {
            requestedTripId = frappe.route_options.trip_id;
        } else {
            var urlParams = new URLSearchParams(window.location.search);
            requestedTripId = urlParams.get('trip_id');
        }

        if (requestedTripId) {
            page.load_single_trip(requestedTripId);
        } else {
            page.show_list_view();
        }
    };

    // --- VIEW 1: LOAD ALL TRIPS LIST (Frappe DocType List Style) ---
    page.show_list_view = function() {
        $('#view-single-trip-details').hide();
        $('#view-all-trips-list').show();
        page.set_title(__('Trip Details'));
        page.load_all_trips();
    };

    page.load_all_trips = function() {
        $('#trips-table-body').html('<tr><td colspan="6" class="text-center text-muted" style="padding: 20px;">Loading trips...</td></tr>');

        frappe.call({
            method: 'netranext_client.netranext.page.netranext_trip_details.netranext_trip_details.get_all_trips_summary',
            args: {
                search: $('#filter-search').val(),
                status: $('#filter-status').val(),
                employee: $('#filter-employee').val(),
                date: $('#filter-date').val(),
                limit: page.current_limit
            },
            callback: function(r) {
                var trips = r.message || [];
                page.render_trips_table(trips);
            }
        });
    };

    page.render_trips_table = function(trips) {
        var tbody = $('#trips-table-body');
        tbody.empty();

        $('#trips-count-badge').text(trips.length + ' trip' + (trips.length === 1 ? '' : 's') + ' found');

        if (trips.length === 0) {
            tbody.html('<tr><td colspan="6" class="text-center text-muted" style="padding: 20px;">No matching trip records found.</td></tr>');
            return;
        }

        trips.forEach(function(t) {
            var statusBadge = t.status === 'Completed'
                ? '<span class="indicator-pill green">Completed</span>'
                : '<span class="indicator-pill orange">In Progress</span>';

            var rowHtml = `
                <tr class="clickable-trip-row" data-trip-id="${t.name}">
                    <td><span style="font-weight: 500; color: #2563eb; cursor: pointer;">${t.name}</span></td>
                    <td>${statusBadge}</td>
                    <td>${t.employee || '-'}</td>
                    <td>${t.start_time_formatted || '-'}</td>
                    <td>${t.distance_formatted}</td>
                    <td>${t.duration_formatted}</td>
                </tr>
            `;
            tbody.append(rowHtml);
        });

        // Clicking any row opens the single trip details page
        $('.clickable-trip-row').on('click', function(e) {
            var tripId = $(this).data('trip-id');
            if (tripId) {
                page.load_single_trip(tripId);
            }
        });
    };

    // --- VIEW 2: LOAD SINGLE TRIP DETAILS ---
    page.load_single_trip = function(trip_id) {
        $('#view-all-trips-list').hide();
        $('#view-single-trip-details').show();
        page.set_title(__('Trip Details: ') + trip_id);

        ensureLeaflet(function() {
            frappe.call({
                method: 'netranext_client.netranext.page.netranext_trip_details.netranext_trip_details.get_trip_telemetry_details',
                args: { trip_id: trip_id },
                callback: function(r) {
                    if (r.message) {
                        page.render_single_trip_details(r.message);
                    } else {
                        frappe.msgprint(__('Unable to load details for trip ') + trip_id);
                    }
                }
            });
        });
    };

    page.render_single_trip_details = function(data) {
        // Fill Header & Metrics
        var journeySubtitle = '';
        if (data.journey_name && data.journey_name !== data.trip_id) {
            journeySubtitle = data.journey_name;
        } else if (data.flutter_journey_id && data.flutter_journey_id !== data.trip_id) {
            journeySubtitle = data.flutter_journey_id;
        }
        $('#single-trip-title').text(journeySubtitle ? '(' + journeySubtitle + ')' : '');
        $('#single-trip-employee').text(data.employee_name || data.employee_id);
        $('#single-trip-date').text(data.journey_date || 'N/A');
        $('#single-trip-distance').text((data.distance_km ? data.distance_km.toFixed(2) : '0.00') + ' km');

        // Status badge
        var badge = $('#single-trip-status-badge');
        badge.text(data.status);
        if (data.status === 'Completed') {
            badge.attr('class', 'indicator-pill green');
        } else {
            badge.attr('class', 'indicator-pill orange');
        }

        // Duration formatting
        var durationText = 'N/A';
        if (data.duration_seconds) {
            var mins = Math.floor(data.duration_seconds / 60);
            var secs = data.duration_seconds % 60;
            durationText = mins + 'm ' + secs + 's';
        }
        $('#single-trip-duration').text(durationText);

        // Render Chronological Timeline (Left)
        page.render_timeline(data.timeline_events);

        // Render Odometer & Verification Details (Left)
        page.render_odometer(data);

        // Render Telemetry & Device Info (Left)
        page.render_telemetry(data.telemetry);

        // Render Leaflet Map (Right)
        page.render_map(data.raw_gps_data);
    };

    page.render_odometer = function(data) {
        var card = $('#single-trip-odometer-card');
        var container = $('#single-trip-odometer-container');
        container.empty();

        var hasOdo = data.start_odometer !== undefined && data.start_odometer !== null ||
                     data.end_odometer !== undefined && data.end_odometer !== null ||
                     data.start_notes || data.end_notes ||
                     data.start_odometer_photo || data.end_odometer_photo;

        if (!hasOdo) {
            card.hide();
            return;
        }

        card.show();

        var calcDist = data.calculated_odometer_distance !== undefined && data.calculated_odometer_distance !== null
            ? data.calculated_odometer_distance.toFixed(2) + ' km'
            : 'N/A';

        // Clickable thumbnail that opens the full-size photo in a dialog.
        // Falls back to "No Photos" when the trip genuinely has no photo.
        function photoHtml(photoUrl, label) {
            if (!photoUrl) {
                return '<span style="color: #94a3b8; font-size: 11px;">No Photos</span>';
            }
            return `
                <div style="margin-top: 6px;">
                    <a href="${photoUrl}" class="odometer-photo-link" title="View full-size photo" style="display: inline-block; text-decoration: none;">
                        <img src="${photoUrl}" alt="${label} photo"
                            style="max-width: 100%; max-height: 120px; border-radius: 6px; border: 1px solid #cbd5e1; cursor: zoom-in;" />
                        <div style="font-size: 11px; color: #2563eb; margin-top: 3px; cursor: pointer;"><i class="fa fa-search-plus"></i> View Photo</div>
                    </a>
                </div>
            `;
        }

        var startPhotoHtml = photoHtml(data.start_odometer_photo, 'Start odometer');
        var endPhotoHtml = photoHtml(data.end_odometer_photo, 'End odometer');

        var html = `
            <div style="display: flex; flex-direction: column; gap: 10px;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <!-- Start Odometer Box -->
                    <div style="background: #f8fafc; padding: 10px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <div style="font-size: 11px; font-weight: 700; color: #1e293b; text-transform: uppercase; margin-bottom: 4px;">
                            <i class="fa fa-play text-success"></i> Start Odometer
                        </div>
                        <div style="font-size: 16px; font-weight: 700; color: #047857;">${data.start_odometer !== undefined && data.start_odometer !== null ? data.start_odometer + ' km' : 'N/A'}</div>
                        <div style="font-size: 11px; color: #64748b; margin-top: 4px;"><strong>Notes:</strong> ${data.start_notes || 'N/A'}</div>
                        ${startPhotoHtml}
                    </div>

                    <!-- End Odometer Box -->
                    <div style="background: #f8fafc; padding: 10px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                        <div style="font-size: 11px; font-weight: 700; color: #1e293b; text-transform: uppercase; margin-bottom: 4px;">
                            <i class="fa fa-flag-checkered text-danger"></i> End Odometer
                        </div>
                        <div style="font-size: 16px; font-weight: 700; color: #b91c1c;">${data.end_odometer !== undefined && data.end_odometer !== null ? data.end_odometer + ' km' : 'N/A'}</div>
                        <div style="font-size: 11px; color: #64748b; margin-top: 4px;"><strong>Notes:</strong> ${data.end_notes || 'N/A'}</div>
                        ${endPhotoHtml}
                    </div>
                </div>

                <div style="background: #ecfdf5; padding: 8px 12px; border-radius: 6px; border: 1px solid #a7f3d0; font-size: 12px; color: #065f46; display: flex; justify-content: space-between; align-items: center;">
                    <span><strong>Calculated Odometer Difference:</strong></span>
                    <strong style="font-size: 14px;">${calcDist}</strong>
                </div>
            </div>
        `;

        container.html(html);

        // Open the clicked odometer photo full-size in a dialog
        container.off('click', '.odometer-photo-link').on('click', '.odometer-photo-link', function(e) {
            e.preventDefault();
            var src = $(this).find('img').attr('src');
            if (!src) return;
            var d = new frappe.ui.Dialog({
                title: __('Odometer Photo'),
                size: 'large'
            });
            d.$body.html(
                '<img src="' + src + '" alt="Odometer photo" style="width: 100%; border-radius: 6px; border: 1px solid #e2e8f0;" />'
            );
            d.show();
        });
    };

    page.render_telemetry = function(telemetry) {
        var container = $('#single-trip-telemetry-container');
        container.empty();

        var device = (telemetry && telemetry.device) || {};
        var battery = (telemetry && telemetry.battery) || {};
        var gps = (telemetry && telemetry.gps_stats) || {};

        if (!Object.keys(device).length && !Object.keys(battery).length && !Object.keys(gps).length) {
            container.html('<div style="color: #94a3b8; font-size: 12px; font-style: italic; padding: 6px 0;">No device telemetry recorded for this trip.</div>');
            return;
        }

        var model = device.model || 'Unknown';
        var osVersion = device.os_version || 'N/A';
        var netStart = device.network_type_at_start || 'N/A';

        var batStart = battery.start_level !== undefined && battery.start_level !== null ? battery.start_level + '%' : 'N/A';
        var batEnd = battery.end_level !== undefined && battery.end_level !== null ? battery.end_level + '%' : 'N/A';
        var batConsumed = battery.total_consumed_pct !== undefined && battery.total_consumed_pct !== null ? battery.total_consumed_pct + '%' : '0%';
        var batOpt = battery.battery_optimization_active === true ? 'Active (risk)'
            : (battery.battery_optimization_active === false ? 'Exempt' : 'N/A');

        var totalPts = gps.total_points_captured !== undefined ? gps.total_points_captured : 'N/A';
        var accuracy = gps.accuracy_range_meters || 'N/A';

        var html = `
            <div style="display: flex; flex-direction: column; gap: 10px;">
                <!-- Device Details Box -->
                <div style="background: #f8fafc; padding: 10px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                    <div class="card-expand-header" style="cursor: pointer; font-size: 11px; font-weight: 700; color: #475569; text-transform: uppercase; display: flex; justify-content: space-between; align-items: center; user-select: none;">
                        <span><i class="fa fa-mobile-alt text-primary"></i> Device Information</span>
                        <i class="fa fa-chevron-up toggle-chevron" style="font-size: 10px; color: #94a3b8; transition: transform 0.2s ease;"></i>
                    </div>
                    <div class="card-expand-content" style="margin-top: 8px;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 12px;">
                            <div><span style="color: #64748b;">Model:</span> <strong style="color: #0f172a;">${model}</strong></div>
                            <div><span style="color: #64748b;">Network Start:</span> <strong style="color: #0f172a;">${netStart}</strong></div>
                            <div style="grid-column: span 2; word-break: break-all;"><span style="color: #64748b;">OS Version:</span> <strong style="color: #0f172a; font-size: 11px;">${osVersion}</strong></div>
                        </div>
                    </div>
                </div>

                <!-- Battery & GPS Details Box -->
                <div style="background: #f8fafc; padding: 10px 12px; border-radius: 6px; border: 1px solid #e2e8f0;">
                    <div class="card-expand-header" style="cursor: pointer; font-size: 11px; font-weight: 700; color: #475569; text-transform: uppercase; display: flex; justify-content: space-between; align-items: center; user-select: none;">
                        <span><i class="fa fa-battery-half text-success"></i> Battery & GPS Telemetry</span>
                        <i class="fa fa-chevron-up toggle-chevron" style="font-size: 10px; color: #94a3b8; transition: transform 0.2s ease;"></i>
                    </div>
                    <div class="card-expand-content" style="margin-top: 8px;">
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 12px;">
                            <div><span style="color: #64748b;">Battery Level:</span> <strong style="color: #0f172a;">${batStart} ➔ ${batEnd}</strong></div>
                            <div><span style="color: #64748b;">Battery Used:</span> <strong style="color: #0f172a;">${batConsumed}</strong></div>
                            <div><span style="color: #64748b;">GPS Points:</span> <strong style="color: #0f172a;">${totalPts} points</strong></div>
                            <div><span style="color: #64748b;">Accuracy:</span> <strong style="color: #0f172a;">${accuracy}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        container.html(html);
    };

    page.render_timeline = function(events) {
        var listContainer = $('#single-trip-timeline-list');
        listContainer.empty();

        if (!events || events.length === 0) {
            listContainer.append('<li class="timeline-event-item"><div class="timeline-event-box">No events recorded</div></li>');
            return;
        }

        function formatTimeOnly(ts) {
            if (!ts || ts === 'N/A' || ts === 'In Progress') return ts || '';
            var str = String(ts).trim();
            if (str.includes(' ')) {
                return str.split(' ')[1];
            } else if (str.includes('T')) {
                var tPart = str.split('T')[1];
                return tPart.split('.')[0].replace('Z', '');
            }
            return str;
        }

        events.forEach(function(ev) {
            var timeOnly = formatTimeOnly(ev.timestamp);
            // End reason is displayed as a second line inside the Trip Ended
            // event (server sends it as `reason`), not as a separate item.
            var reasonHtml = ev.reason
                ? `<div style="margin-top: 4px; font-size: 12px; color: #6b7280;"><strong style="color: #374151;">Reason:</strong> ${ev.reason}</div>`
                : '';
            var itemHtml = `
                <li class="timeline-event-item">
                    <div class="timeline-event-dot">
                        <i class="fa ${ev.icon}"></i>
                    </div>
                    <div class="timeline-event-box">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                            <span class="timeline-event-title" style="font-weight: 700; font-size: 14px; color: #111827;">${ev.title}</span>
                            <span class="timeline-event-time" style="font-size: 12px; color: #6b7280; font-weight: 600;">${timeOnly}</span>
                        </div>
                        <div class="timeline-event-desc">${ev.details}</div>
                        ${reasonHtml}
                    </div>
                </li>
            `;
            listContainer.append(itemHtml);
        });
    };

    page.render_map = function(gps_data) {
        if (typeof L === 'undefined') {
            $('#single-trip-map-container').html('<div style="padding: 20px; text-align: center; color: #6b7280;">Leaflet Map library not loaded.</div>');
            return;
        }

        if (page.trip_map) {
            page.trip_map.remove();
            page.trip_map = null;
        }

        if (!gps_data || gps_data.length === 0) {
            $('#single-trip-map-container').html('<div style="padding: 20px; text-align: center; color: #6b7280;">No GPS coordinate points available for map rendering.</div>');
            return;
        }

        var firstPt = gps_data[0];
        var initialLat = firstPt.latitude || firstPt.lat || (Array.isArray(firstPt) ? firstPt[0] : 0);
        var initialLng = firstPt.longitude || firstPt.lng || (Array.isArray(firstPt) ? firstPt[1] : 0);

        page.trip_map = L.map('single-trip-map-container').setView([initialLat, initialLng], 14);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(page.trip_map);

        var latLngs = [];
        gps_data.forEach(function(pt) {
            var lat = pt.latitude || pt.lat || (Array.isArray(pt) ? pt[0] : null);
            var lng = pt.longitude || pt.lng || (Array.isArray(pt) ? pt[1] : null);
            if (lat && lng) {
                latLngs.push([lat, lng]);
            }
        });

        if (latLngs.length > 0) {
            var polyline = L.polyline(latLngs, { color: '#2563eb', weight: 4, opacity: 0.8 }).addTo(page.trip_map);
            page.trip_map.fitBounds(polyline.getBounds(), { padding: [30, 30] });

            // Fetch free OSRM road matching to snap line smoothly onto openstreetmap roads
            (function(targetPolyline, originalCoords) {
                if (!originalCoords || originalCoords.length < 2) return;
                
                var sampleStep = Math.max(1, Math.floor(originalCoords.length / 80));
                var sampled = [];
                for (var i = 0; i < originalCoords.length; i += sampleStep) {
                    sampled.push(originalCoords[i]);
                }
                if (sampled[sampled.length - 1] !== originalCoords[originalCoords.length - 1]) {
                    sampled.push(originalCoords[originalCoords.length - 1]);
                }

                var osrmCoordsStr = sampled.map(function(c) { return c[1] + ',' + c[0]; }).join(';');
                var osrmUrl = 'https://router.project-osrm.org/match/v1/driving/' + osrmCoordsStr + '?overview=full&geometries=geojson';

                fetch(osrmUrl)
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data && data.matchings && data.matchings[0] && data.matchings[0].geometry) {
                            var matchedGeo = data.matchings[0].geometry.coordinates;
                            var snappedLatLngs = matchedGeo.map(function(pt) { return [pt[1], pt[0]]; });
                            if (snappedLatLngs && snappedLatLngs.length > 1) {
                                targetPolyline.setLatLngs(snappedLatLngs);
                            }
                        }
                    })
                    .catch(function(err) {
                        console.warn('OSRM free match fallback (using raw coords):', err);
                    });
            })(polyline, latLngs);

            L.marker(latLngs[0]).addTo(page.trip_map)
                .bindPopup('<b>🚀 Trip Start</b><br>' + latLngs[0][0] + ', ' + latLngs[0][1]);

            if (latLngs.length > 1) {
                L.marker(latLngs[latLngs.length - 1]).addTo(page.trip_map)
                    .bindPopup('<b>🛑 Trip End</b><br>' + latLngs[latLngs.length - 1][0] + ', ' + latLngs[latLngs.length - 1][1]);
            }
        }
    };

    // Initialize page immediately
    page.init_page();
};
