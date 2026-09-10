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
            <div class="frappe-card" style="padding: 0; border-radius: 6px; overflow: hidden;">
                <div class="table-responsive">
                    <table class="table table-bordered table-hover trips-table" style="margin-bottom: 0;">
                        <thead>
                            <tr style="background: #f9fafb;">
                                <th style="width: 40px; text-align: center;"><input type="checkbox" id="select-all-trips"></th>
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
                                <td colspan="7" class="text-center text-muted" style="padding: 20px;">Loading trips list...</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div class="list-pagination-bar" style="padding: 10px 15px; background: #f9fafb; border-top: 1px solid #e5e7eb; display: flex; align-items: center; gap: 8px;">
                    <span class="text-muted" style="font-size: 12px; font-weight: 600;">Rows:</span>
                    <button class="btn btn-default btn-xs btn-limit active-limit" data-limit="20">20</button>
                    <button class="btn btn-default btn-xs btn-limit" data-limit="100">100</button>
                    <button class="btn btn-default btn-xs btn-limit" data-limit="500">500</button>
                    <button class="btn btn-default btn-xs btn-limit" data-limit="2500">2500</button>
                </div>
            </div>
        </div>

        <!-- VIEW 2: SINGLE TRIP DETAILS & MAP VIEW (Hidden by Default) -->
        <div id="view-single-trip-details" style="display: none;">
            <div class="frappe-card">
                <div class="trip-detail-header">
                    <div>
                        <button class="btn btn-default btn-xs" id="btn-back-to-list">
                            <i class="fa fa-arrow-left"></i> Back to All Trips List
                        </button>
                        <h3 id="single-trip-title" style="display: inline-block; margin-left: 12px; font-weight: 700; font-size: 18px;">Trip Details</h3>
                    </div>
                    <span id="single-trip-status-badge" class="indicator-pill green">Completed</span>
                </div>

                <div class="end-reason-callout" id="single-trip-end-reason-box">
                    <strong>🛑 End Reason:</strong> <span id="single-trip-end-reason">User manually tapped End Journey</span>
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
            </div>

            <!-- Two-Column Grid: Timeline Left, Map Right -->
            <div class="split-view-grid">
                <!-- Left Panel: Chronological Event Timeline -->
                <div class="frappe-card">
                    <h5 style="font-weight: 700; margin-bottom: 16px; font-size: 15px;">
                        <i class="fa fa-history text-info"></i> Chronological Event Timeline
                    </h5>
                    <ul class="timeline-container" id="single-trip-timeline-list">
                        <li class="timeline-event-item">
                            <div class="timeline-event-box">Loading trip details...</div>
                        </li>
                    </ul>
                </div>

                <!-- Right Panel: Interactive Leaflet Map -->
                <div class="frappe-card">
                    <h5 style="font-weight: 700; margin-bottom: 16px; font-size: 15px;">
                        <i class="fa fa-map-marked-alt text-primary"></i> Route Path & Location Events
                    </h5>
                    <div id="single-trip-map-container" style="height: 440px; width: 100%; border-radius: 6px; border: 1px solid #e5e7eb;"></div>
                </div>
            </div>
        </div>

    </div>
    `;

    $(wrapper).find('.layout-main-section').html(html);

    page.trip_map = null;
    page.current_limit = 20;

    // Helper to dynamically load Leaflet assets
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
                    });
            });
    }

    ensureLeaflet(function() {
        page.init_page();
    });

    page.init_page = function() {
        // Pagination Limit Buttons
        $('.btn-limit').on('click', function() {
            $('.btn-limit').removeClass('active-limit btn-primary').addClass('btn-default');
            $(this).removeClass('btn-default').addClass('btn-primary active-limit');
            page.current_limit = $(this).data('limit');
            page.load_all_trips();
        });

        $('#btn-back-to-list').on('click', function() {
            page.show_list_view();
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
        $('#trips-table-body').html('<tr><td colspan="8" class="text-center text-muted" style="padding: 20px;">Loading trips...</td></tr>');

        frappe.call({
            method: 'netranext_client.netranext.page.netranext_trip_details.netranext_trip_details.get_all_trips_summary',
            args: {
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

        if (trips.length === 0) {
            tbody.html('<tr><td colspan="7" class="text-center text-muted" style="padding: 20px;">No trip records found.</td></tr>');
            return;
        }

        trips.forEach(function(t) {
            var statusBadge = t.status === 'Completed'
                ? '<span class="indicator-pill green">Completed</span>'
                : '<span class="indicator-pill orange">In Progress</span>';

            var rowHtml = `
                <tr class="clickable-trip-row" data-trip-id="${t.name}">
                    <td style="text-align: center;"><input type="checkbox" onclick="event.stopPropagation();"></td>
                    <td><strong style="color: #1f2937; cursor: pointer;">${t.name}</strong></td>
                    <td>${statusBadge}</td>
                    <td>${t.employee}</td>
                    <td>${t.start_time_formatted}</td>
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
    };

    page.render_single_trip_details = function(data) {
        // Fill Header & Metrics
        $('#single-trip-title').text(data.trip_id + (data.flutter_journey_id ? ' (' + data.flutter_journey_id + ')' : ''));
        $('#single-trip-employee').text(data.employee_name || data.employee_id);
        $('#single-trip-date').text(data.journey_date || 'N/A');
        $('#single-trip-distance').text((data.distance_km ? data.distance_km.toFixed(2) : '0.00') + ' km');
        $('#single-trip-end-reason').text(data.end_reason || 'N/A');

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

        // Render Leaflet Map (Right)
        page.render_map(data.raw_gps_data);
    };

    page.render_timeline = function(events) {
        var listContainer = $('#single-trip-timeline-list');
        listContainer.empty();

        if (!events || events.length === 0) {
            listContainer.append('<li class="timeline-event-item"><div class="timeline-event-box">No events recorded</div></li>');
            return;
        }

        events.forEach(function(ev) {
            var itemHtml = `
                <li class="timeline-event-item">
                    <div class="timeline-event-dot">
                        <i class="fa ${ev.icon}"></i>
                    </div>
                    <div class="timeline-event-box">
                        <div class="timeline-event-time">${ev.timestamp}</div>
                        <div class="timeline-event-title">${ev.title}</div>
                        <div class="timeline-event-desc">${ev.details}</div>
                    </div>
                </li>
            `;
            listContainer.append(itemHtml);
        });
    };

    page.render_map = function(gps_data) {
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

            L.marker(latLngs[0]).addTo(page.trip_map)
                .bindPopup('<b>🚀 Trip Start</b><br>' + latLngs[0][0] + ', ' + latLngs[0][1]);

            if (latLngs.length > 1) {
                L.marker(latLngs[latLngs.length - 1]).addTo(page.trip_map)
                    .bindPopup('<b>🛑 Trip End</b><br>' + latLngs[latLngs.length - 1][0] + ', ' + latLngs[latLngs.length - 1][1]);
            }
        }
    };
};
