// NetraNext Trip History Page - Historical trip logs viewer

// Helper function to format time to 12-hour (AM/PM) in local timezone
function format_time_12hr(timeStr) {
    if (!timeStr || timeStr === '-' || timeStr === 'Pending...') return timeStr;
    
    if (timeStr.includes('AM') || timeStr.includes('PM')) {
        return timeStr;
    }

    try {
        var date;
        var formattedStr = timeStr.toString().trim();
        
        if (formattedStr.includes('-') && (formattedStr.includes(':') || formattedStr.includes('T'))) {
            if (!formattedStr.includes('T')) {
                formattedStr = formattedStr.replace(' ', 'T');
            }
            if (!formattedStr.endsWith('Z') && !formattedStr.includes('+')) {
                formattedStr += 'Z';
            }
            date = new Date(formattedStr);
        } else {
            var today = new Date();
            var yyyy = today.getFullYear();
            var mm = String(today.getMonth() + 1).padStart(2, '0');
            var dd = String(today.getDate()).padStart(2, '0');
            date = new Date(yyyy + '-' + mm + '-' + dd + 'T' + formattedStr + 'Z');
        }

        if (isNaN(date.getTime())) {
            return fallback_parse_time(timeStr);
        }

        var hours = date.getHours();
        var minutes = date.getMinutes();
        var ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12;
        
        var hrStr = hours < 10 ? '0' + hours : hours;
        var minStr = minutes < 10 ? '0' + minutes : minutes;
        
        return hrStr + ':' + minStr + ' ' + ampm;
    } catch (e) {
        console.error("Error formatting time:", e);
        return fallback_parse_time(timeStr);
    }
}

function fallback_parse_time(timeStr) {
    var timePart = timeStr;
    if (timeStr.includes('T')) {
        timePart = timeStr.split('T')[1];
    } else if (timeStr.includes(' ')) {
        timePart = timeStr.split(' ')[1];
    }
    
    if (!timePart) return timeStr;
    var parts = timePart.trim().split(':');
    if (parts.length < 2) return timeStr;

    var hours = parseInt(parts[0]);
    var minutes = parts[1].split('.')[0].replace('Z', '');
    if (isNaN(hours)) return timeStr;
    
    var ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    return (hours < 10 ? '0' + hours : hours) + ':' + minutes + ' ' + ampm;
}

function formatDate(dateString) {
    if (!dateString) return '-';
    try {
        var formattedStr = dateString.toString().replace(/[\r\n]+/g, ' ').trim();
        if (formattedStr.includes('-') && (formattedStr.includes(':') || formattedStr.includes('T'))) {
            if (!formattedStr.includes('T')) {
                formattedStr = formattedStr.replace(' ', 'T');
            }
            if (!formattedStr.endsWith('Z') && !formattedStr.includes('+')) {
                formattedStr += 'Z';
            }
            var date = new Date(formattedStr);
            if (!isNaN(date.getTime())) {
                var yyyy = date.getFullYear();
                var mm = String(date.getMonth() + 1).padStart(2, '0');
                var dd = String(date.getDate()).padStart(2, '0');
                return yyyy + '-' + mm + '-' + dd;
            }
        }
    } catch (e) {
        console.error("Error formatting date:", e);
    }
    
    var dateStr = dateString.toString().replace(/[\r\n]+/g, ' ').trim();
    if (dateStr.includes('T')) {
        return dateStr.split('T')[0];
    }
    var firstSpace = dateStr.indexOf(' ');
    if (firstSpace > 0) {
        return dateStr.substring(0, firstSpace);
    }
    return dateStr;
}

function load_leaflet_library(callback) {
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
            console.error("Failed to load Leaflet library");
            frappe.msgprint({
                title: 'Map Library Error',
                message: 'Failed to load the map library. Please refresh the page.',
                indicator: 'red'
            });
        });
}

frappe.pages['netranext-trip-history'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Trip History',
        single_column: true
    });

    page.set_title('Trip History');

    page.add_button(__('Go to Dashboard'), function() {
        frappe.set_route('netranext-dashboard');
    }, 'dashboard');

    page.add_button(__('Refresh'), function() {
        load_trip_data();
    }, 'refresh');

    page.add_button(__('Full Screen'), function() {
        toggle_fullscreen();
    }, 'expand');

    $(wrapper).find(".layout-main-section").css({"max-width": "100%", "padding": "0"});
    $(wrapper).find(".page-container").css({"max-width": "100%", "padding": "0"});
    $(wrapper).css({"padding": "0"});
    $(".page-body").css("overflow", "hidden");

    var html = `
        <div class="trip-map-view">
            <div class="map-view-body">
                <!-- Sidebar -->
                <div class="trip-sidebar">
                    <div class="filter-bar">
                        <select id="employee-filter" class="j-input" style="flex: 1; min-width: 0;">
                            <option value="">All Employees</option>
                        </select>
                        <input type="date" id="date-filter" class="j-input" style="width: 130px;">
                        <button class="j-btn" id="clear-filters" style="padding: 8px 12px;">Clear</button>
                    </div>

                    <div class="trip-list-container" id="trip-list-content">
                        <div style="text-align: center; padding: 20px;">
                            <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
                            <div style="color: var(--t-text-muted);">Loading trips...</div>
                        </div>
                    </div>
                </div>

                <!-- Map -->
                <div class="map-content">
                    <div id="trip-map"></div>

                    <!-- Map Overlays -->
                    <div class="map-overlay-controls">
                        <button class="j-btn" id="fit-all-routes" title="Fit all visible routes">Fit All</button>
                        <button class="j-btn" id="fit-selected" title="Center on selected route">Selected</button>
                    </div>

                    <div class="map-overlay-stats" id="view-stats" style="display:none;">
                        <div style="font-size: 11px; text-transform: uppercase; color: var(--t-text-muted); font-weight: 700; margin-bottom: 4px;">Day Total</div>
                        <div style="font-size: 18px; font-weight: 900; color: var(--t-text);" id="total-dist">0.0 km</div>
                        <div style="font-size: 12px; color: var(--t-text-muted); font-weight: 600;" id="total-count">0 trips</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    $(page.main).empty().append( /* nosemgrep */ html);

    // Global State
    window.mapViewData = {
        trips: [],
        selectedId: null,
        unselectedColor: '#6366f1', // Indigo
        selectedColor: '#10b981',   // Green
        map: null,
        layers: {},
        markers: {},
        addressCache: {}
    };

    window.currentFilters = {
        employee: '',
        date: get_today_date()
    };

    // Load Leaflet library first, then initialize the page
    load_leaflet_library(function() {
        $('#date-filter').val(window.currentFilters.date).attr('max', window.currentFilters.date);

        initialize_map();

        setTimeout(function() {
            if (window.mapViewData.map) {
                window.mapViewData.map.invalidateSize();
            }
        }, 500);

        load_trip_data();

        setup_event_handlers();
    });

    $(wrapper).on('hide', function() {
        if (window.mapViewData && window.mapViewData.liveTrackingInterval) {
            clearInterval(window.mapViewData.liveTrackingInterval);
            window.mapViewData.liveTrackingInterval = null;
        }
    });
};

frappe.pages['netranext-trip-history'].on_page_show = function (wrapper) {
    if (window.mapViewData && window.mapViewData.map) {
        setTimeout(function() {
            window.mapViewData.map.invalidateSize();
        }, 300);
    }
<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
    if (window.mapViewData && window.mapViewData.journeys.length > 0) {
        apply_route_options();
        setup_live_tracking_timer();
    }
=======
    apply_route_options();
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js
};

function get_today_date() {
    var today = new Date();
    var dd = String(today.getDate()).padStart(2, '0');
    var mm = String(today.getMonth() + 1).padStart(2, '0');
    var yyyy = today.getFullYear();
    return yyyy + '-' + mm + '-' + dd;
}

// Load static completed trip logs
function load_trip_data() {
    $('#trip-list-content').html( /* nosemgrep */ `
        <div style="text-align: center; padding: 20px;">
            <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
            <div style="color: var(--t-text-muted);">Loading trips...</div>
        </div>
    `);

    var dateFrom = window.currentFilters.date || get_today_date();

    frappe.call({
        method: "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
        args: {
            date_from: dateFrom,
            date_to: dateFrom
        },
        callback: function(response) {
            if (response.message && response.message.status === 'success') {
                var data = response.message.data || {};
                var allTrips = data.journeys || [];

                // Filter out 'In Progress' trips to show completed historical records
                var completedTrips = allTrips.filter(function(t) {
                    return t.status !== 'In Progress';
                });

                completedTrips.forEach(function(trip) {
                    trip.coordinates = generate_trip_coordinates(trip);
                });

                window.mapViewData.trips = completedTrips;
                populate_employee_filter();
                update_view();

                apply_route_options();

                // Setup live tracking timer
                setup_live_tracking_timer();
            } else {
                show_error_message('No recorded trips found for this date.');
            }
        },
        error: function(xhr, status, error) {
            console.error("Trip History API Error:", xhr, status, error);
            show_error_message('Failed to load recorded trips.');
        }
    });
}

<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
// Setup live tracking auto-refresh timer if any active journeys exist
function setup_live_tracking_timer() {
    if (window.mapViewData.liveTrackingInterval) {
        clearInterval(window.mapViewData.liveTrackingInterval);
        window.mapViewData.liveTrackingInterval = null;
    }

    if (!$('#journey-map').length) {
        return;
    }

    var hasActive = window.mapViewData.journeys.some(function(j) {
        return j.status === 'In Progress';
    });

    if (hasActive) {
        console.log("Active journeys found, starting live tracking auto-refresh...");
        window.mapViewData.liveTrackingInterval = setInterval(function() {
            if (!$('#journey-map').length) {
                clearInterval(window.mapViewData.liveTrackingInterval);
                window.mapViewData.liveTrackingInterval = null;
                return;
            }
            console.log("Auto-refreshing live vehicle positions...");
            load_journey_data_quietly();
        }, 30000); // refresh every 30 seconds
    }
}

// Quietly fetch journey data in the background and update elements
function load_journey_data_quietly() {
    var dateFrom = window.currentFilters.date || get_today_date();
    var dateTo = dateFrom;

    frappe.call({
        method: "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
        args: {
            date_from: dateFrom,
            date_to: dateTo
        },
        callback: function(response) {
            if (response.message && response.message.status === 'success') {
                var data = response.message.data || {};
                var journeys = data.journeys || [];

                journeys.forEach(function(journey) {
                    journey.coordinates = generate_journey_coordinates(journey);
                });

                window.mapViewData.journeys = journeys;
                update_view();
                setup_live_tracking_timer();
            }
        }
    });
}

// Generate coordinates for journey display
function generate_journey_coordinates(journey) {
    // If journey has actual coordinates, use them
    if (journey.raw_coordinates && journey.raw_coordinates.length > 0) {
        return journey.raw_coordinates.map(function(coord) {
=======
function generate_trip_coordinates(trip) {
    if (trip.raw_coordinates && trip.raw_coordinates.length > 0) {
        return trip.raw_coordinates.map(function(coord) {
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js
            return [coord.latitude || coord.lat, coord.longitude || coord.lng];
        });
    }

    if (trip.start_latitude && trip.start_longitude &&
        trip.end_latitude && trip.end_longitude) {
        var startLat = parseFloat(trip.start_latitude);
        var startLon = parseFloat(trip.start_longitude);
        var endLat = parseFloat(trip.end_latitude);
        var endLon = parseFloat(trip.end_longitude);

        var coords = [];
        var waypoints = Math.min(5, Math.max(2, Math.round(trip.distance_km || 3)));

        for (var i = 0; i < waypoints; i++) {
            var ratio = i / (waypoints - 1);
            var lat = startLat + (endLat - startLat) * ratio;
            var lon = startLon + (endLon - startLon) * ratio;
            coords.push([lat, lon]);
        }
        return coords;
    }

    var baseLat = 12.9716;
    var baseLon = 77.5946;
    var offset = 0.02;
    var coords = [];
    var numPoints = Math.max(3, Math.round((trip.distance_km || 5) / 2));

    for (var i = 0; i < numPoints; i++) {
        coords.push([baseLat + offset + (i * 0.005), baseLon + offset + (i * 0.005)]);
    }
    return coords;
}

function update_view() {
    render_trip_list();
    render_trips_on_map();
    update_stats();

    if (window.mapViewData.map) {
        window.mapViewData.map.invalidateSize();
    }
}

function update_stats() {
    var trips = get_filtered_trips();

    if (trips.length > 0) {
        var totalKm = trips.reduce(function(sum, t) {
            return sum + (parseFloat(t.distance_km) || 0);
        }, 0);

        $('#total-dist').text(totalKm.toFixed(2) + " km");
        $('#total-count').text(trips.length + " trips");
        $('#view-stats').fadeIn();
    } else {
        $('#view-stats').fadeOut();
    }
}

function apply_route_options() {
    var options = frappe.route_options || {};
    var targetId = options.trip_id || options.journey_id || null;
    var targetEmp = options.employee || null;
    var targetDate = options.date || null;

    if (targetEmp) {
        window.currentFilters.employee = targetEmp;
        $('#employee-filter').val(targetEmp);
    }

    if (targetDate) {
        window.currentFilters.date = targetDate;
        $('#date-filter').val(targetDate);
    }

    if (targetId) {
        setTimeout(function() {
            select_trip(targetId, true);
        }, 500);
        frappe.route_options = {};
    }
}

function show_error_message(message) {
    var errorHtml = '<div style="text-align: center; padding: 40px;">' +
        '<div style="font-size: 48px; margin-bottom: 16px;">📂</div>' +
        '<h3 style="color: #64748b; margin-bottom: 8px;">Trip History</h3>' +
        '<p style="color: #718096; margin-bottom: 16px;">' + message + '</p>' +
        '</div>';

    $('#trip-list-content').html( /* nosemgrep */ errorHtml);
}

function populate_employee_filter() {
    var employees = {};
    window.mapViewData.trips.forEach(function (t) {
        var empId = t.employee || t.user_id;
        if (empId) {
            employees[empId] = t.employee_name || empId;
        }
    });

    var select = $('#employee-filter');
    var currentVal = select.val();
    select.find('option:not(:first)').remove();

    Object.keys(employees).sort().forEach(function (empId) {
        select.append( /* nosemgrep */ '<option value="' + empId + '">' + employees[empId] + '</option>');
    });

    if (currentVal) {
        select.val(currentVal);
    }
}

function initialize_map() {
    if (typeof L === 'undefined') {
        $('#trip-map').html( /* nosemgrep */ 
            '<div style="text-align: center; padding: 40px; color: #8d99a6;">' +
            '<h3>Map Not Available</h3>' +
            '</div>'
        );
        return;
    }

    try {
        window.mapViewData.map = L.map('trip-map').setView([12.9716, 77.5946], 12);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(window.mapViewData.map);
    } catch (error) {
        console.error("Error creating map:", error);
    }
}

function render_trips_on_map() {
    if (!window.mapViewData.map) return;

    Object.values(window.mapViewData.layers).forEach(function(layer) {
        window.mapViewData.map.removeLayer(layer);
    });

    Object.values(window.mapViewData.markers).forEach(function(markers) {
        markers.forEach(function(m) {
            window.mapViewData.map.removeLayer(m);
        });
    });

    window.mapViewData.layers = {};
    window.mapViewData.markers = {};

    var trips = get_filtered_trips();
    var allPoints = [];

    trips.forEach(function (t) {
        var id = t.name || t.trip_id;
        var coords = t.coordinates;

        if (!coords || coords.length < 2) return;

        var isSelected = window.mapViewData.selectedId === id;
        var color = isSelected ? window.mapViewData.selectedColor : window.mapViewData.unselectedColor;

        var polyline = L.polyline(coords, {
            color: color,
            weight: isSelected ? 8 : 4,
            opacity: isSelected ? 1.0 : 0.5,
            lineJoin: 'round'
        }).addTo(window.mapViewData.map);

        if (isSelected) {
            polyline.bringToFront();
        }

        polyline.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            select_trip(id, true);
        });

        window.mapViewData.layers[id] = polyline;

<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
        // Markers
        var endMarkerType = j.status === 'In Progress' ? 'live' : 'end';

=======
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js
        var startMarker = L.marker(coords[0], { icon: create_marker_icon('start', color) })
            .addTo(window.mapViewData.map);
        var endMarker = L.marker(coords[coords.length - 1], { icon: create_marker_icon(endMarkerType, color) })
            .addTo(window.mapViewData.map);

<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
        startMarker.bindPopup(create_journey_popup(j, 'start'));
        endMarker.bindPopup(create_journey_popup(j, endMarkerType));
=======
        startMarker.bindPopup(create_trip_popup(t, 'start'));
        endMarker.bindPopup(create_trip_popup(t, 'end'));
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js

        var tripMarkers = [startMarker, endMarker];

        if (t.raw_coordinates && t.raw_coordinates.length > 0) {
            t.raw_coordinates.forEach(function(coord) {
                if (coord.label === 'Trip Extended' || coord.label === 'Extended') {
                    var lat = coord.latitude || coord.lat;
                    var lng = coord.longitude || coord.lng;
                    var extendMarker = L.marker([lat, lng], { icon: create_marker_icon('extended', color) })
                        .addTo(window.mapViewData.map);
                    
                    extendMarker.bindPopup(create_trip_popup(t, 'extended', coord));
                    extendMarker.setOpacity(isSelected ? 1 : 0.6);
                    tripMarkers.push(extendMarker);
                }
            });
        }

        window.mapViewData.markers[id] = tripMarkers;

        startMarker.setOpacity(isSelected ? 1 : 0.6);
        endMarker.setOpacity(isSelected ? 1 : 0.6);

        coords.forEach(function(p) {
            allPoints.push(p);
        });
    });

    if (allPoints.length > 0 && !window.mapViewData.selectedId) {
        window.mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
    }
}

function create_marker_icon(type, color) {
    var iconColor = '#ef4444'; // Red for end
    if (type === 'start') {
        iconColor = '#10b981'; // Green for start
    } else if (type === 'extended') {
        iconColor = '#fbbf24'; // Yellow for extended
    } else if (type === 'live') {
        iconColor = '#3b82f6'; // Blue for live
    }
    
    var svg = '';
    if (type === 'live') {
        svg = '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
            '<circle cx="12" cy="12" r="10" fill="#3b82f6" fill-opacity="0.2"/>' +
            '<circle cx="12" cy="12" r="6" fill="#3b82f6" fill-opacity="0.4"/>' +
            '<path d="M12 2L4.5 20.29L5.21 21L12 18L18.79 21L19.5 20.29L12 2Z" fill="#1e40af" transform="scale(0.8) translate(3, 3)"/>' +
            '</svg>';
    } else {
        svg = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
            '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="' + iconColor + '"/>' +
            '<circle cx="12" cy="9" r="3" fill="white"/>' +
            '</svg>';
    }
<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
=======
    
    var svg = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
        '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="' + iconColor + '"/>' +
        '<circle cx="12" cy="9" r="3" fill="white"/>' +
        '</svg>';
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js

    return L.divIcon({
        html: svg,
        className: type === 'live' ? 'custom-map-marker live-marker-pulse' : 'custom-map-marker',
        iconSize: type === 'live' ? [40, 40] : [32, 32],
        iconAnchor: type === 'live' ? [20, 20] : [16, 32],
        popupAnchor: type === 'live' ? [0, -20] : [0, -32]
    });
}

<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
function create_journey_popup(j, type, coord) {
    var title = type === 'start' ? 'Trip Start' : (type === 'extended' ? 'Trip Extended' : (type === 'live' ? 'Current Position (Live)' : 'Trip End'));
    var accentColor = type === 'start' ? '#10b981' : (type === 'extended' ? '#fbbf24' : (type === 'live' ? '#3b82f6' : '#ef4444'));
    var timeStr = type === 'start' ? j.start_time : (type === 'extended' ? (coord ? coord.timestamp : '') : (type === 'live' ? (j.raw_coordinates && j.raw_coordinates.length ? j.raw_coordinates[j.raw_coordinates.length - 1].timestamp : '') : j.end_time));
    var locationStr = type === 'start' ? (j.start_location || 'Start point') : (type === 'extended' ? (coord ? (coord.latitude + ', ' + coord.longitude) : 'Extended point') : (type === 'live' ? (j.raw_coordinates && j.raw_coordinates.length ? (j.raw_coordinates[j.raw_coordinates.length - 1].latitude + ', ' + j.raw_coordinates[j.raw_coordinates.length - 1].longitude) : 'Live point') : (j.end_location || 'End point')));
=======
function create_trip_popup(t, type, coord) {
    var title = type === 'start' ? 'Trip Start' : (type === 'extended' ? 'Trip Extended' : 'Trip End');
    var accentColor = type === 'start' ? '#10b981' : (type === 'extended' ? '#fbbf24' : '#ef4444');
    var timeStr = type === 'start' ? t.start_time : (type === 'extended' ? (coord ? coord.timestamp : '') : t.end_time);
    var locationStr = type === 'start' ? (t.start_location || 'Start point') : (type === 'extended' ? (coord ? (coord.latitude + ', ' + coord.longitude) : 'Extended point') : (t.end_location || 'End point'));
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js
    var displayLocation = format_location_display(locationStr);

    return '<div class="rich-popup">' +
        '<div class="popup-header" style="border-left: 4px solid ' + accentColor + ';">' +
        '<div class="popup-title">' + title + '</div>' +
        '<div class="popup-subtitle">' + (t.employee_name || t.employee) + '</div>' +
        '</div>' +
        '<div class="popup-body">' +
        '<div class="popup-info-row">' +
        '<span class="label">Time:</span>' +
        '<span class="val">' + format_time_12hr(timeStr) + '</span>' +
        '</div>' +
        '<div class="popup-info-row">' +
        '<span class="label">Date:</span>' +
        '<span class="val">' + formatDate(t.start_time) + '</span>' +
        '</div>' +
        '<div class="popup-info-row">' +
        '<span class="label">Distance:</span>' +
        '<span class="val">' + (t.distance_km || 0) + ' km</span>' +
        '</div>' +
        '<div class="popup-info-row">' +
        '<span class="label">Location:</span>' +
        '<span class="val">' + displayLocation + '</span>' +
        '</div>' +
        '</div>' +
        '</div>';
}

function format_location_display(locationStr) {
    if (!locationStr || locationStr === 'Start point' || locationStr === 'End point') return locationStr;
    
    var regex = /^-?\d+\.\d+,\s?-?\d+\.\d+$/;
    if (!regex.test(locationStr)) {
        return locationStr;
    }
    
    var cacheKey = locationStr.replace(/\s+/g, '');
    if (window.mapViewData.addressCache[cacheKey]) {
        return window.mapViewData.addressCache[cacheKey];
    }
    
    var classMarker = 'loc-' + cacheKey.replace(/[^a-zA-Z0-9]/g, '');
    
    if (window.mapViewData.addressCache[cacheKey] === undefined) {
        window.mapViewData.addressCache[cacheKey] = null; 
        var parts = locationStr.split(',');
        var url = 'https://nominatim.openstreetmap.org/reverse?format=json&lat=' + parts[0].trim() + '&lon=' + parts[1].trim();
        
        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (data && data.display_name) {
                    var parts = data.display_name.split(',');
                    var shortAddr = parts.slice(0, Math.min(3, parts.length)).join(',').trim();
                    window.mapViewData.addressCache[cacheKey] = shortAddr;
                    $('.' + classMarker).text(shortAddr);
                } else {
                    window.mapViewData.addressCache[cacheKey] = locationStr;
                    $('.' + classMarker).text(locationStr);
                }
            })
            .catch(err => {
                window.mapViewData.addressCache[cacheKey] = locationStr;
                $('.' + classMarker).text(locationStr);
            });
    }
    
    return '<span class="' + classMarker + '">Loading address...</span>';
}

function setup_event_handlers() {
    $('#employee-filter').on('change', function() {
        window.currentFilters.employee = $(this).val();
        load_trip_data();
    });

    $('#date-filter').on('change', function() {
        window.currentFilters.date = $(this).val();
        load_trip_data();
    });

    $('#clear-filters').on('click', function() {
        $('#employee-filter').val('');
        $('#date-filter').val(get_today_date());
        window.currentFilters = {
            employee: '',
            date: get_today_date()
        };
        load_trip_data();
    });

    $('#fit-all-routes').on('click', function() {
        var allPoints = [];
        Object.values(window.mapViewData.layers).forEach(function(layer) {
            layer.getLatLngs().forEach(function(p) {
                allPoints.push(p);
            });
        });
        if (allPoints.length && window.mapViewData.map) {
            window.mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
        }
    });

    $('#fit-selected').on('click', function() {
        if (window.mapViewData.selectedId) {
            select_trip(window.mapViewData.selectedId, true);
        }
    });

    $(window).on('resize', function() {
        if (window.mapViewData.map) {
            window.mapViewData.map.invalidateSize();
        }
    });
}

function toggle_fullscreen() {
    var element = document.querySelector('.trip-map-view');
    if (!document.fullscreenElement) {
        element.requestFullscreen().catch(function(err) {
            frappe.show_alert('Error attempting to enable full-screen: ' + err.message);
        });
    } else {
        document.exitFullscreen();
    }
}

function get_filtered_trips() {
    var trips = window.mapViewData.trips || [];
    var f = window.currentFilters;

    return trips.filter(function (t) {
        var matchEmp = !f.employee || t.employee === f.employee || t.user_id === f.employee;

        var rawDateStr = t.start_time || t.posting_date || '';
        var tDate = formatDate(rawDateStr);
        var matchDate = !f.date || tDate === f.date;

        return matchEmp && matchDate;
    });
}

function render_trip_list() {
    var trips = get_filtered_trips();
    var container = $('#trip-list-content');
    container.empty();

    if (trips.length === 0) {
        container.append( /* nosemgrep */ 
            '<div style="text-align: center; padding: 48px 20px; color: var(--t-text-muted);">' +
            '<div style="font-size: 40px; margin-bottom: 12px;">📍</div>' +
            '<div style="font-weight: 600;">No trips found for this date.</div>' +
            '<div style="font-size: 12px; margin-top: 4px;">Try selecting another date or employee.</div>' +
            '</div>'
        );
        return;
    }

    trips.forEach(function(t) {
        var id = t.name || t.trip_id;
        var isSelected = window.mapViewData.selectedId === id;
        
        var startLoc = t.start_location || 'Start point';
        var endLoc = t.end_location || 'End point';

<<<<<<< HEAD:netranext_client/netranext/page/netranext_mapview/netranext_mapview.js
        var isLive = j.status === 'In Progress';
        var statusBadge = isLive ? '<span class="live-status-indicator">● LIVE</span>' : '';
        var endTimeDisplay = isLive ? 'Live' : format_time_12hr(j.end_time);

        var card = $('<div class="journey-card' + (isSelected ? ' selected' : '') + '" data-id="' + id + '">' +
            '<div class="journey-card-header" style="align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 4px;">' +
            '<div class="journey-card-emp" style="display: flex; align-items: center; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + (j.employee_name || j.employee) + statusBadge + '</div>' +
            '<div style="font-size: 12px; color: var(--j-text-muted); margin: 0 12px; font-weight: 500;">' +
            format_time_12hr(j.start_time) + ' - ' + endTimeDisplay +
=======
        var card = $('<div class="trip-card' + (isSelected ? ' selected' : '') + '" data-id="' + id + '">' +
            '<div class="trip-card-header" style="align-items: center; margin-bottom: 8px;">' +
            '<div class="trip-card-emp" style="flex: 1;">' + (t.employee_name || t.employee) + '</div>' +
            '<div style="font-size: 12px; color: var(--t-text-muted); margin: 0 12px; font-weight: 500;">' +
            format_time_12hr(t.start_time) + ' - ' + format_time_12hr(t.end_time) +
>>>>>>> 3dec311 (refactor: replace mapview with dedicated live tracking and trip history pages):netranext_client/netranext/page/netranext_trip_history/netranext_trip_history.js
            '</div>' +
            '<div class="trip-card-dist" style="margin-left: auto;">' + (t.distance_km || 0) + ' km</div>' +
            '</div>' +
            '<div class="trip-card-body" style="gap: 4px;">' +
            '<div style="font-size: 11px; display: flex; align-items: center; gap: 6px;">' +
            '<span style="color: var(--t-success); font-size: 10px;">🟢</span>' +
            '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + format_location_display(startLoc) + '</span>' +
            '</div>' +
            '<div style="font-size: 11px; display: flex; align-items: center; gap: 6px;">' +
            '<span style="color: var(--t-danger); font-size: 10px;">🔴</span>' +
            '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + format_location_display(endLoc) + '</span>' +
            '</div>' +
            '</div>' +
            '</div>'
        );

        card.on('click', function() {
            select_trip(id, true);
        });

        container.append( /* nosemgrep */ card);
    });
}

function select_trip(id, zoom) {
    window.mapViewData.selectedId = id;

    $('.trip-card').removeClass('selected');
    $('.trip-card[data-id="' + id + '"]').addClass('selected');

    var selectedCard = $('.trip-card[data-id="' + id + '"]');
    if (selectedCard.length) {
        selectedCard[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    update_view();

    if (zoom && window.mapViewData.layers[id] && window.mapViewData.map) {
        var bounds = window.mapViewData.layers[id].getBounds();
        window.mapViewData.map.fitBounds(bounds, { padding: [100, 100], maxZoom: 16 });
    }
}
