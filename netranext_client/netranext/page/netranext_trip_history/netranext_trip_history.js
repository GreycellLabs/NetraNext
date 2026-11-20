(function() {
    // NetraNext Trip History Page - Historical trip logs viewer

    // State scoped inside the page closure
    var mapViewData = {
        trips: [],
        selectedId: null,
        unselectedColor: '#6366f1', // Indigo
        selectedColor: '#10b981',   // Green
        map: null,
        layers: {},
        markers: {},
        addressCache: {}
    };

    var currentFilters = {
        user: '',
        date: ''
    };

    var pageWrapper = null;

    // One explicit conversion per timestamp: aware ISO values (carrying 'Z'
    // or a ±HH:MM offset from the server) are parsed to an instant and
    // formatted in the browser's timezone. Legacy naive strings keep the
    // wall-clock display they always had.
    function parse_aware_instant(str) {
        if (!str) return null;
        var s = String(str).trim();
        var hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(s);
        if (!hasOffset) return null;
        // 'Date' parsing needs the ISO 'T' separator (space fails on Safari)
        var normalized = s.indexOf('T') === -1 ? s.replace(' ', 'T') : s;
        var d = new Date(normalized);
        return isNaN(d.getTime()) ? null : d;
    }

    function format_12h_from_date(date) {
        var hours = date.getHours();
        var minutes = date.getMinutes();
        var ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12;
        var hrStr = hours < 10 ? '0' + hours : hours;
        var minStr = minutes < 10 ? '0' + minutes : minutes;
        return hrStr + ':' + minStr + ' ' + ampm;
    }

    // Helper function to format time to 12-hour (AM/PM) in local timezone
    function format_time_12hr(timeStr) {
        if (!timeStr || timeStr === '-' || timeStr === 'Pending...') return timeStr || '-';
        // Attendance-trip start points written by older code carry epoch-ms
        // numbers; String methods below would throw and abort rendering.
        if (typeof timeStr === 'number') timeStr = new Date(timeStr).toISOString();
        timeStr = String(timeStr);

        if (timeStr.includes('AM') || timeStr.includes('PM')) {
            return timeStr;
        }

        var instant = parse_aware_instant(timeStr);
        if (instant) {
            return format_12h_from_date(instant);
        }

        try {
            var date;
            var formattedStr = timeStr.toString().trim();

            if (formattedStr.includes('-') && (formattedStr.includes(':') || formattedStr.includes('T'))) {
                // Legacy naive wall time in the deployment (system) timezone
                if (formattedStr.includes('T')) {
                    formattedStr = formattedStr.replace('T', ' ');
                }
                var parts = formattedStr.split(' ');
                var dateParts = parts[0].split('-');
                var timeParts = parts[1].split(':');
                date = new Date(
                    parseInt(dateParts[0]),
                    parseInt(dateParts[1]) - 1,
                    parseInt(dateParts[2]),
                    parseInt(timeParts[0]),
                    parseInt(timeParts[1]),
                    parseInt(timeParts[2] || 0)
                );
            } else {
                var today = new Date();
                var timeParts = formattedStr.split(':');
                date = new Date(
                    today.getFullYear(),
                    today.getMonth(),
                    today.getDate(),
                    parseInt(timeParts[0]),
                    parseInt(timeParts[1]),
                    parseInt(timeParts[2] || 0)
                );
            }

            if (isNaN(date.getTime())) {
                return fallback_parse_time(timeStr);
            }

            return format_12h_from_date(date);
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
            var dateStr = dateString.toString().replace(/[\r\n]+/g, ' ').trim();

            // Viewer-local calendar date derived from the same instant the
            // time display uses (aware ISO carries the source offset).
            var instant = parse_aware_instant(dateStr);
            if (instant) {
                var dd = String(instant.getDate()).padStart(2, '0');
                var mm = String(instant.getMonth() + 1).padStart(2, '0');
                return instant.getFullYear() + '-' + mm + '-' + dd;
            }

            if (dateStr.includes('T')) {
                return dateStr.split('T')[0];
            }
            var firstSpace = dateStr.indexOf(' ');
            if (firstSpace > 0) {
                return dateStr.substring(0, firstSpace);
            }
            return dateStr;
        } catch (e) {
            console.error("Error formatting date:", e);
            return String(dateString);
        }
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
        pageWrapper = $(wrapper);
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
                            <select id="user-filter" class="form-control input-xs" style="flex: 1; min-width: 0;">
                                <option value="">${__('All Users')}</option>
                            </select>
                            <input type="date" id="date-filter" class="form-control input-xs" style="width: 130px;">
                            <button class="btn btn-default btn-xs" id="clear-filters">${__('Clear')}</button>
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
                        <div id="trip-history-map"></div>

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

        // Reset Page Local State
        mapViewData.trips = [];
        mapViewData.selectedId = null;
        mapViewData.layers = {};
        mapViewData.markers = {};

        currentFilters.user = '';
        currentFilters.date = ''; // Show all by default

        setup_event_handlers();

        $(wrapper).on('hide', function() {
            // Clean up any remaining references
        });
    };

    frappe.pages['netranext-trip-history'].on_page_show = function (wrapper) {
        pageWrapper = $(wrapper);
        
        // Reset selected ID on navigation display
        mapViewData.selectedId = null;

        // Set max attribute on date input so future dates cannot be selected
        var todayVal = get_today_date();
        pageWrapper.find('#date-filter').val(currentFilters.date).attr('max', todayVal);

        if (!mapViewData || !mapViewData.map) {
            load_leaflet_library(function() {
                initialize_map();

                setTimeout(function() {
                    if (mapViewData.map) {
                        mapViewData.map.invalidateSize();
                    }
                }, 500);

                load_trip_data();
                apply_route_options();
            });
        } else {
            setTimeout(function() {
                if (mapViewData.map) {
                    mapViewData.map.invalidateSize();
                }
            }, 300);

            load_trip_data();
            apply_route_options();
        }
    };

    function get_today_date() {
        var today = new Date();
        var dd = String(today.getDate()).padStart(2, '0');
        var mm = String(today.getMonth() + 1).padStart(2, '0');
        var yyyy = today.getFullYear();
        return yyyy + '-' + mm + '-' + dd;
    }

    // Deduplicate trips by unique trip ID and timestamp signature.
    //
    // Offline sync replays / concurrent background syncs can deliver the same
    // physical journey more than once (identical or near-identical records).
    // Primary key: the record ID (name / trip_id).
    // Fallback signature: (employee, start_time, end_time, distance_km) — two
    // entries sharing that combination are the same trip; keep only the most
    // complete record (Completed with end time beats a stale partial row).
    function deduplicate_trips(allTrips) {
        var seenTripIds = new Set();
        var deduplicatedTrips = [];

        allTrips.forEach(function(trip) {
            var tripId = trip.name || trip.trip_id;

            // Deduplicate strictly by unique database record ID
            if (tripId) {
                if (seenTripIds.has(tripId)) {
                    return;
                }
                seenTripIds.add(tripId);
            }

            deduplicatedTrips.push(trip);
        });

        return deduplicatedTrips;
    }

    // Load static and open trip logs
    function load_trip_data() {
        pageWrapper.find('#trip-list-content').html( /* nosemgrep */ `
            <div style="text-align: center; padding: 20px;">
                <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
                <div style="color: var(--t-text-muted);">Loading trips...</div>
            </div>
        `);

        var args = {};
        if (currentFilters.date) {
            args.date_from = currentFilters.date;
            args.date_to = currentFilters.date;
        } else {
            args.ignore_dates = 1;
        }

        frappe.call({
            method: "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
            args: args,
            callback: function(response) {
                if (response.message && response.message.status === 'success') {
                    var data = response.message.data || {};
                    var allTrips = data.journeys || [];

                    // Show all trips (both In Progress and Completed/Cancelled),
                    // with duplicate sync records filtered out before storing.
                    var tripsToShow = deduplicate_trips(allTrips);

                    tripsToShow.forEach(function(trip) {
                        trip.coordinates = generate_trip_coordinates(trip);
                    });

                    mapViewData.trips = tripsToShow;
                    populate_user_filter();
                    update_view();

                    apply_route_options();
                } else {
                    show_error_message(currentFilters.date ? 'No recorded trips found for this date.' : 'No recorded trips found.');
                }
            },
            error: function(xhr, status, error) {
                console.error("Trip History API Error:", xhr, status, error);
                show_error_message('Failed to load recorded trips.');
            }
        });
    }

    function generate_trip_coordinates(trip) {
        if (trip.snapped_coordinates) {
            try {
                var snapped = typeof trip.snapped_coordinates === 'string'
                    ? JSON.parse(trip.snapped_coordinates)
                    : trip.snapped_coordinates;
                if (snapped && Array.isArray(snapped) && snapped.length > 0) {
                    return snapped;
                }
            } catch (e) {
                console.error("Error parsing snapped_coordinates:", e);
            }
        }

        if (trip.raw_coordinates && trip.raw_coordinates.length > 0) {
            return trip.raw_coordinates.map(function(coord) {
                return [coord.latitude || coord.lat, coord.longitude || coord.lng];
            });
        }

        if (trip.start_latitude && trip.start_longitude) {
            var startLat = parseFloat(trip.start_latitude);
            var startLon = parseFloat(trip.start_longitude);
            var endLat = trip.end_latitude ? parseFloat(trip.end_latitude) : (startLat + 0.005);
            var endLon = trip.end_longitude ? parseFloat(trip.end_longitude) : (startLon + 0.005);

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

        if (mapViewData.map) {
            mapViewData.map.invalidateSize();
        }
    }

    // Accumulates total distance correctly
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
        // 'user' is the trip owner's User ID. 'employee' is still accepted
        // because the NetraNext Journey form links here with an Employee ID;
        // it maps to that employee's user once trips are loaded.
        var targetUser = options.user || options.user_id || null;
        var targetEmp = options.employee || null;
        var targetDate = options.date || null;

        if (!targetUser && targetEmp) {
            var empTrip = (mapViewData.trips || []).find(function(t) {
                return t.employee === targetEmp;
            });
            targetUser = empTrip ? trip_owner_key(empTrip) : targetEmp;
        }

        if (targetUser) {
            currentFilters.user = targetUser;
            pageWrapper.find('#user-filter').val(targetUser);
        }

        if (targetDate) {
            currentFilters.date = targetDate;
            pageWrapper.find('#date-filter').val(targetDate);
        }

        if (targetId) {
            setTimeout(function() {
                select_trip(targetId, true);
            }, 500);
            frappe.route_options = {};
        }
    }

    // Handles display error cleanly
    function show_error_message(message) {
        var errorHtml = '<div style="text-align: center; padding: 40px;">' +
            '<div style="font-size: 48px; margin-bottom: 16px;">📂</div>' +
            '<h3 style="color: #64748b; margin-bottom: 8px;">Trip History</h3>' +
            '<p style="color: #718096; margin-bottom: 16px;">' + message + '</p>' +
            '</div>';

        pageWrapper.find('#trip-list-content').html( /* nosemgrep */ errorHtml);
    }

    // Trip owner = the User linked to the trip. The API resolves user_id from
    // the journey (falling back to the Employee's linked user) and user_name
    // from User.full_name. Trips with no linked user fall back to the employee.
    function trip_owner_key(t) {
        return t.user_id || t.employee || '';
    }

    function trip_owner_label(t) {
        return t.user_name || t.user_id || t.employee_name || t.employee || '-';
    }

    function populate_user_filter() {
        var users = {};
        mapViewData.trips.forEach(function (t) {
            var key = trip_owner_key(t);
            if (key) {
                users[key] = trip_owner_label(t);
            }
        });

        var select = pageWrapper.find('#user-filter');
        var currentVal = select.val() || currentFilters.user;
        select.find('option:not(:first)').remove();

        Object.keys(users).sort(function(a, b) {
            return String(users[a]).localeCompare(String(users[b]));
        }).forEach(function (key) {
            $('<option>').attr('value', key).text(users[key]).appendTo(select);
        });

        if (currentVal) {
            select.val(currentVal);
        }
    }

    // Initialize map on trip-history-map container
    function initialize_map() {
        if (typeof L === 'undefined') {
            pageWrapper.find('#trip-history-map').html( /* nosemgrep */ 
                '<div style="text-align: center; padding: 40px; color: #8d99a6;">' +
                '<h3>Map Not Available</h3>' +
                '</div>'
            );
            return;
        }

        try {
            var mapEl = pageWrapper.find('#trip-history-map')[0];
            mapViewData.map = L.map(mapEl).setView([12.9716, 77.5946], 12);

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 19
            }).addTo(mapViewData.map);
        } catch (error) {
            console.error("Error creating map:", error);
        }
    }

    function render_trips_on_map() {
        if (!mapViewData.map) return;

        Object.values(mapViewData.layers).forEach(function(layer) {
            mapViewData.map.removeLayer(layer);
        });

        Object.values(mapViewData.markers).forEach(function(markers) {
            markers.forEach(function(m) {
                mapViewData.map.removeLayer(m);
            });
        });

        mapViewData.layers = {};
        mapViewData.markers = {};

        var trips = get_filtered_trips();
        var allPoints = [];

        trips.forEach(function (t) {
            var id = t.name || t.trip_id;
            var coords = t.coordinates;

            if (!coords || coords.length < 2) return;

            var isSelected = mapViewData.selectedId === id;
            var color = isSelected ? mapViewData.selectedColor : mapViewData.unselectedColor;

            var polyline = L.polyline(coords, {
                color: color,
                weight: isSelected ? 8 : 4,
                opacity: isSelected ? 1.0 : 0.5,
                lineJoin: 'round'
            }).addTo(mapViewData.map);

            // Fetch free OSRM road matching to snap line smoothly onto openstreetmap roads
            (function(targetPolyline, originalCoords) {
                if (!originalCoords || originalCoords.length < 2) return;
                
                // Format coordinates as lng,lat;lng,lat for OSRM Match API
                // OSRM match URL accepts max 100 waypoints per request chunk
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
            })(polyline, coords);

            if (isSelected) {
                polyline.bringToFront();
            }

            polyline.on('click', function(e) {
                L.DomEvent.stopPropagation(e);
                select_trip(id, true);
            });

            mapViewData.layers[id] = polyline;

            var isLive = t.status === 'In Progress';
            var endMarkerType = isLive ? 'live' : 'end';

            var startMarker = L.marker(coords[0], { icon: create_marker_icon('start', color) })
                .addTo(mapViewData.map);
            var endMarker = L.marker(coords[coords.length - 1], { icon: create_marker_icon(endMarkerType, color) })
                .addTo(mapViewData.map);

            startMarker.bindPopup(create_trip_popup(t, 'start'));
            endMarker.bindPopup(create_trip_popup(t, endMarkerType));

            var tripMarkers = [startMarker, endMarker];

            if (t.raw_coordinates && t.raw_coordinates.length > 0) {
                t.raw_coordinates.forEach(function(coord) {
                    if (coord.label === 'Trip Extended' || coord.label === 'Extended') {
                        var lat = coord.latitude || coord.lat;
                        var lng = coord.longitude || coord.lng;
                        var extendMarker = L.marker([lat, lng], { icon: create_marker_icon('extended', color) })
                            .addTo(mapViewData.map);
                        
                        extendMarker.bindPopup(create_trip_popup(t, 'extended', coord));
                        extendMarker.setOpacity(isSelected ? 1 : 0.6);
                        tripMarkers.push(extendMarker);
                    }
                });
            }

            mapViewData.markers[id] = tripMarkers;

            startMarker.setOpacity(isSelected ? 1 : 0.6);
            endMarker.setOpacity(isSelected ? 1 : 0.6);

            coords.forEach(function(p) {
                allPoints.push(p);
            });
        });

        if (allPoints.length > 0 && !mapViewData.selectedId) {
            mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
        }
    }

    function create_marker_icon(type, color) {
        var iconColor = '#ef4444'; // Red for end
        if (type === 'start') {
            iconColor = '#10b981'; // Green for start
        } else if (type === 'extended') {
            iconColor = '#fbbf24'; // Yellow for extended
        } else if (type === 'live') {
            iconColor = '#3b82f6'; // Blue for live/in progress
        }
        
        var svg = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
            '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="' + iconColor + '"/>' +
            '<circle cx="12" cy="9" r="3" fill="white"/>' +
            '</svg>';

        return L.divIcon({
            html: svg,
            className: 'custom-map-marker',
            iconSize: [32, 32],
            iconAnchor: [16, 32],
            popupAnchor: [0, -32]
        });
    }

    function create_trip_popup(t, type, coord) {
        var isLive = type === 'live';
        var title = type === 'start' ? 'Trip Start' : (type === 'extended' ? 'Trip Extended' : (isLive ? 'Current Position' : 'Trip End'));
        var accentColor = type === 'start' ? '#10b981' : (type === 'extended' ? '#fbbf24' : (isLive ? '#3b82f6' : '#ef4444'));
        var timeStr = type === 'start' ? t.start_time : (type === 'extended' ? (coord ? coord.timestamp : '') : (isLive ? t.modified : t.end_time));
        var locationStr = type === 'start' ? (t.start_location || 'Start point') : (type === 'extended' ? (coord ? (coord.latitude + ', ' + coord.longitude) : 'Extended point') : (isLive ? (t.coordinates[t.coordinates.length - 1].join(', ')) : (t.end_location || 'End point')));
        var displayLocation = format_location_display(locationStr);

        return '<div class="rich-popup">' +
            '<div class="popup-header" style="border-left: 4px solid ' + accentColor + ';">' +
            '<div class="popup-title">' + title + '</div>' +
            '<div class="popup-subtitle">' + frappe.utils.escape_html(trip_owner_label(t)) + '</div>' +
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
        if (mapViewData.addressCache[cacheKey]) {
            return mapViewData.addressCache[cacheKey];
        }
        
        var classMarker = 'loc-' + cacheKey.replace(/[^a-zA-Z0-9]/g, '');
        
        if (mapViewData.addressCache[cacheKey] === undefined) {
            mapViewData.addressCache[cacheKey] = null; 
            var parts = locationStr.split(',');
            var url = 'https://nominatim.openstreetmap.org/reverse?format=json&lat=' + parts[0].trim() + '&lon=' + parts[1].trim();
            
            fetch(url)
                .then(res => res.json())
                .then(data => {
                    if (data && data.display_name) {
                        var parts = data.display_name.split(',');
                        var shortAddr = parts.slice(0, Math.min(3, parts.length)).join(',').trim();
                        mapViewData.addressCache[cacheKey] = shortAddr;
                        pageWrapper.find('.' + classMarker).text(shortAddr);
                    } else {
                        mapViewData.addressCache[cacheKey] = locationStr;
                        pageWrapper.find('.' + classMarker).text(locationStr);
                    }
                })
                .catch(err => {
                    mapViewData.addressCache[cacheKey] = locationStr;
                    pageWrapper.find('.' + classMarker).text(locationStr);
                });
        }
        
        return '<span class="' + classMarker + '">Loading address...</span>';
    }

    function setup_event_handlers() {
        pageWrapper.find('#user-filter').on('change', function() {
            currentFilters.user = $(this).val();
            load_trip_data();
        });

        pageWrapper.find('#date-filter').on('change', function() {
            currentFilters.date = $(this).val();
            load_trip_data();
        });

        pageWrapper.find('#clear-filters').on('click', function() {
            pageWrapper.find('#user-filter').val('');
            pageWrapper.find('#date-filter').val('');
            currentFilters.user = '';
            currentFilters.date = '';
            load_trip_data();
        });

        pageWrapper.find('#fit-all-routes').on('click', function() {
            var allPoints = [];
            Object.values(mapViewData.layers).forEach(function(layer) {
                layer.getLatLngs().forEach(function(p) {
                    allPoints.push(p);
                });
            });
            if (allPoints.length && mapViewData.map) {
                mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
            }
        });

        pageWrapper.find('#fit-selected').on('click', function() {
            if (mapViewData.selectedId) {
                select_trip(mapViewData.selectedId, true);
            }
        });

        $(window).on('resize', function() {
            if (mapViewData.map) {
                mapViewData.map.invalidateSize();
            }
        });
    }

    // Handles fullscreen requests
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
        var trips = mapViewData.trips || [];
        var f = currentFilters;

        return trips.filter(function (t) {
            var matchUser = !f.user || trip_owner_key(t) === f.user || t.employee === f.user;

            var rawDateStr = t.start_time || t.posting_date || '';
            var tDate = formatDate(rawDateStr);
            var matchDate = !f.date || tDate === f.date;

            return matchUser && matchDate;
        });
    }

    // Same indicator colours as the NetraNext Journey list view
    // (netranext_journey_list.js) so status pills read the same everywhere.
    var STATUS_INDICATOR = {
        'Completed': 'green',
        'In Progress': 'orange',
        'Cancelled': 'red'
    };

    // Renders the trip list with Frappe's own list-view markup/classes
    // (frappe-list > result > list-row-head / list-row-container > list-row)
    // so it inherits the standard DocType list styling.
    function render_trip_list() {
        var trips = get_filtered_trips();
        var container = pageWrapper.find('#trip-list-content');
        var esc = frappe.utils.escape_html;
        container.empty();

        if (trips.length === 0) {
            container.append( /* nosemgrep */
                '<div class="no-result text-muted text-center" style="padding: 48px 20px;">' +
                '<p>' + __('No trips found.') + '</p>' +
                '<p class="small">' + __('Try selecting another date or user.') + '</p>' +
                '</div>'
            );
            return;
        }

        var $result = $('<div class="result"></div>');
        $result.append( /* nosemgrep */
            '<header class="level list-row-head text-muted">' +
                '<div class="level-left list-header-subject">' +
                    '<div class="list-row-col ellipsis list-subject level">' +
                        '<span class="level-item">' + __('User') + '</span>' +
                    '</div>' +
                    '<div class="list-row-col ellipsis hidden-xs trip-col-status"><span>' + __('Status') + '</span></div>' +
                    '<div class="list-row-col ellipsis text-right trip-col-distance"><span>' + __('Distance') + '</span></div>' +
                '</div>' +
                '<div class="level-right">' +
                    '<span class="list-count"><span>' +
                        __('{0} of {1}', [trips.length, (mapViewData.trips || []).length]) +
                    '</span></span>' +
                '</div>' +
            '</header>'
        );

        trips.forEach(function(t) {
            var id = t.name || t.trip_id;
            var isSelected = mapViewData.selectedId === id;
            var isLive = t.status === 'In Progress';
            var status = t.status || 'Completed';
            var indicator = STATUS_INDICATOR[status] || 'gray';
            var owner = trip_owner_label(t);
            var ownerTitle = t.user_id && t.user_id !== owner ? owner + ' (' + t.user_id + ')' : owner;
            var timeRange = format_time_12hr(t.start_time) + ' - ' +
                (isLive ? __('In Progress') : format_time_12hr(t.end_time));
            var tripDate = formatDate(t.start_time);
            var displayDate = (tripDate && tripDate !== '-' && frappe.datetime && frappe.datetime.str_to_user)
                ? frappe.datetime.str_to_user(tripDate) : tripDate;
            var distance = (parseFloat(t.distance_km) || 0).toFixed(2) + ' km';

            var $row = $(
                '<div class="list-row-container' + (isSelected ? ' selected' : '') + '" tabindex="1">' +
                    '<div class="level list-row">' +
                        '<div class="level-left ellipsis">' +
                            '<div class="list-row-col ellipsis list-subject level">' +
                                '<span class="level-item bold ellipsis">' +
                                    '<a class="ellipsis"></a>' +
                                '</span>' +
                            '</div>' +
                            '<div class="list-row-col hidden-xs ellipsis trip-col-status">' +
                                '<span class="indicator-pill ' + indicator + ' filterable ellipsis">' +
                                    '<span class="ellipsis">' + esc(__(status)) + '</span>' +
                                '</span>' +
                            '</div>' +
                            '<div class="list-row-col ellipsis text-right trip-col-distance">' + esc(distance) + '</div>' +
                        '</div>' +
                        '<div class="level-right text-muted ellipsis">' +
                            '<div class="level-item list-row-activity">' +
                                '<span class="frappe-timestamp"></span>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="list-row-border"></div>' +
                '</div>'
            );
            $row.attr('data-id', id);
            $row.find('.list-row').attr('title', ownerTitle + ' \u00b7 ' + displayDate + ' \u00b7 ' + timeRange);
            $row.find('.list-subject a').text(owner).attr('title', ownerTitle);
            $row.find('.frappe-timestamp').text(displayDate);

            $row.on('click', function() {
                select_trip(id, true);
            });

            $result.append( /* nosemgrep */ $row);
        });

        container.append($('<div class="frappe-list"></div>').append($result));
    }

    function select_trip(id, zoom) {
        mapViewData.selectedId = id;

        var rows = pageWrapper.find('.list-row-container');
        rows.removeClass('selected');
        var selectedCard = rows.filter(function() {
            return $(this).attr('data-id') === String(id);
        });
        selectedCard.addClass('selected');

        if (selectedCard.length) {
            selectedCard[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        update_view();

        if (zoom && mapViewData.layers[id] && mapViewData.map) {
            var bounds = mapViewData.layers[id].getBounds();
            mapViewData.map.fitBounds(bounds, { padding: [100, 100], maxZoom: 16 });
        }
    }
})();
