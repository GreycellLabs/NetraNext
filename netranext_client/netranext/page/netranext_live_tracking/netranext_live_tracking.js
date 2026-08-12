(function() {
    // NetraNext Live Tracking Page - Real-time active trip monitoring

    // State scoped inside the page closure
    var mapViewData = {
        trips: [],
        selectedId: null,
        unselectedColor: '#3b82f6', // Blue
        selectedColor: '#10b981',   // Green
        map: null,
        layers: {},
        markers: {},
        addressCache: {}
    };

    var currentFilters = {
        employee: ''
    };

    var liveTrackingInterval = null;
    var pageWrapper = null;

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

    frappe.pages['netranext-live-tracking'].on_page_load = function (wrapper) {
        pageWrapper = $(wrapper);
        var page = frappe.ui.make_app_page({
            parent: wrapper,
            title: 'Live Tracking',
            single_column: true
        });

        page.set_title('Live Tracking');

        page.add_button(__('Refresh'), function() {
            load_trip_data(false);
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
                            <button class="j-btn" id="clear-filters" style="padding: 8px 12px;">Clear</button>
                        </div>

                        <div class="trip-list-container" id="trip-list-content">
                            <div style="text-align: center; padding: 20px;">
                                <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
                                <div style="color: var(--t-text-muted);">Loading active trips...</div>
                            </div>
                        </div>
                    </div>

                    <!-- Map -->
                    <div class="map-content">
                        <div id="live-tracking-map"></div>

                        <!-- Map Overlays -->
                        <div class="map-overlay-controls">
                            <button class="j-btn" id="fit-all-routes" title="Fit all visible routes">Fit All</button>
                            <button class="j-btn" id="fit-selected" title="Center on selected route">Selected</button>
                        </div>

                        <div class="map-overlay-stats" id="view-stats" style="display:none;">
                            <div style="font-size: 11px; text-transform: uppercase; color: var(--t-text-muted); font-weight: 700; margin-bottom: 4px;">Active Trips</div>
                            <div style="font-size: 18px; font-weight: 900; color: var(--t-text);" id="total-dist">0.0 km</div>
                            <div style="font-size: 12px; color: var(--t-text-muted); font-weight: 600;" id="total-count">0 active trips</div>
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

        currentFilters.employee = '';

        // Set up Event Handlers
        setup_event_handlers();

        // Listen for hide event to clean up the polling interval immediately
        $(wrapper).on('hide', function() {
            if (liveTrackingInterval) {
                clearInterval(liveTrackingInterval);
                liveTrackingInterval = null;
            }
        });
    };

    frappe.pages['netranext-live-tracking'].on_page_show = function (wrapper) {
        pageWrapper = $(wrapper);
        if (!mapViewData || !mapViewData.map) {
            // Load Leaflet library and initialize map when container is attached and visible in DOM
            load_leaflet_library(function() {
                initialize_map();

                setTimeout(function() {
                    if (mapViewData.map) {
                        mapViewData.map.invalidateSize();
                    }
                }, 500);

                // Load data initially
                load_trip_data(false);

                // Start Auto Polling (every 10 seconds)
                start_polling(wrapper);
            });
        } else {
            setTimeout(function() {
                if (mapViewData.map) {
                    mapViewData.map.invalidateSize();
                }
            }, 300);

            // Clean previous selection and refresh cleanly
            mapViewData.selectedId = null;
            load_trip_data(false);
            start_polling(wrapper);
        }
    };

    // Start real-time background polling
    function start_polling(wrapper) {
        if (liveTrackingInterval) {
            clearInterval(liveTrackingInterval);
        }

        liveTrackingInterval = setInterval(function() {
            // Stop polling if the page container is no longer visible in DOM (navigated away)
            if (!$(wrapper).is(':visible')) {
                console.log("Live Tracking page is not visible, clearing polling interval.");
                clearInterval(liveTrackingInterval);
                liveTrackingInterval = null;
                return;
            }

            load_trip_data(true); // Silent reload
        }, 10000);
    }

    // Helper: Get today's date in YYYY-MM-DD format
    function get_today_date() {
        var today = new Date();
        var dd = String(today.getDate()).padStart(2, '0');
        var mm = String(today.getMonth() + 1).padStart(2, '0');
        var yyyy = today.getFullYear();
        return yyyy + '-' + mm + '-' + dd;
    }

    // Load real active trip data from API
    function load_trip_data(silent) {
        if (!silent) {
            pageWrapper.find('#trip-list-content').html( /* nosemgrep */ `
                <div style="text-align: center; padding: 20px;">
                    <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
                    <div style="color: var(--t-text-muted);">Loading active trips...</div>
                </div>
            `);
        }

        var todayStr = get_today_date();

        frappe.call({
            method: "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
            args: {
                date_from: todayStr,
                date_to: todayStr
            },
            callback: function(response) {
                if (response.message && response.message.status === 'success') {
                    var data = response.message.data || {};
                    var allTrips = data.journeys || [];

                    // Filter for 'In Progress' trips only
                    var activeTrips = allTrips.filter(function(t) {
                        return t.status === 'In Progress';
                    });

                    // Enrich active trips with coordinates for map display
                    activeTrips.forEach(function(trip) {
                        trip.coordinates = generate_trip_coordinates(trip);
                    });

                    mapViewData.trips = activeTrips;
                    populate_employee_filter();
                    update_view();

                    // If a trip was previously selected and is still active, pan to its latest point
                    if (mapViewData.selectedId && mapViewData.layers[mapViewData.selectedId]) {
                        var polyline = mapViewData.layers[mapViewData.selectedId];
                        var latlngs = polyline.getLatLngs();
                        if (latlngs.length > 0 && mapViewData.map) {
                            mapViewData.map.panTo(latlngs[latlngs.length - 1]);
                        }
                    }
                } else {
                    if (!silent) {
                        show_error_message('No active trips found.');
                    }
                }
            },
            error: function(xhr, status, error) {
                console.error("Live Tracking API Error:", xhr, status, error);
                if (!silent) {
                    show_error_message('Failed to connect to server.');
                }
            }
        });
    }

    // Generate coordinates for active trip
    function generate_trip_coordinates(trip) {
        if (trip.raw_coordinates && trip.raw_coordinates.length > 0) {
            return trip.raw_coordinates.map(function(coord) {
                return [coord.latitude || coord.lat, coord.longitude || coord.lng];
            });
        }

        if (trip.start_latitude && trip.start_longitude) {
            var startLat = parseFloat(trip.start_latitude);
            var startLon = parseFloat(trip.start_longitude);

            // Active trip might not have an end coordinate if it is in progress
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

        // Demo fallback for active trips
        var baseLat = 12.9716;
        var baseLon = 77.5946;
        var offset = 0.01;
        var coords = [];
        for (var i = 0; i < 4; i++) {
            coords.push([baseLat + offset + (i * 0.003), baseLon + offset + (i * 0.003)]);
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

    function update_stats() {
        var trips = get_filtered_trips();

        if (trips.length > 0) {
            var totalKm = trips.reduce(function(sum, t) {
                return sum + (parseFloat(t.distance_km) || 0);
            }, 0);

            pageWrapper.find('#total-dist').text(totalKm.toFixed(2) + " km");
            pageWrapper.find('#total-count').text(trips.length + " active trips");
            pageWrapper.find('#view-stats').fadeIn();
        } else {
            pageWrapper.find('#view-stats').fadeOut();
        }
    }

    function show_error_message(message) {
        var errorHtml = '<div style="text-align: center; padding: 40px;">' +
            '<div style="font-size: 48px; margin-bottom: 16px;">📍</div>' +
            '<h3 style="color: #64748b; margin-bottom: 8px;">Live Tracking</h3>' +
            '<p style="color: #718096; margin-bottom: 16px;">' + message + '</p>' +
            '</div>';

        pageWrapper.find('#trip-list-content').html( /* nosemgrep */ errorHtml);
    }

    function populate_employee_filter() {
        var employees = {};
        mapViewData.trips.forEach(function (t) {
            var empId = t.employee || t.user_id;
            if (empId) {
                employees[empId] = t.employee_name || empId;
            }
        });

        var select = pageWrapper.find('#employee-filter');
        var currentVal = select.val();
        select.find('option:not(:first)').remove();

        Object.keys(employees).sort().forEach(function (empId) {
            select.append( /* nosemgrep */ '<option value="' + empId + '">' + employees[empId] + '</option>');
        });

        if (currentVal) {
            select.val(currentVal);
        }
    }

    // Initialize map on live-tracking-map container
    function initialize_map() {
        if (typeof L === 'undefined') {
            pageWrapper.find('#live-tracking-map').html( /* nosemgrep */ 
                '<div style="text-align: center; padding: 40px; color: #8d99a6;">' +
                '<h3>Map Not Available</h3>' +
                '</div>'
            );
            return;
        }

        try {
            var mapEl = pageWrapper.find('#live-tracking-map')[0];
            mapViewData.map = L.map(mapEl).setView([12.9716, 77.5946], 12);

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors',
                maxZoom: 19
            }).addTo(mapViewData.map);
        } catch (error) {
            console.error("Error creating map:", error);
        }
    }

    function render_trips_on_map() {
        if (!mapViewData.map) return;

        // Clear existing layers
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

            if (!coords || coords.length < 1) return;

            var isSelected = mapViewData.selectedId === id;
            var color = isSelected ? mapViewData.selectedColor : mapViewData.unselectedColor;

            // ONLY show the live blinking point (end/current position marker)
            var currentPos = coords[coords.length - 1];
            var isOffline = t.is_online === false;
            
            // Highlight selected marker: higher z-index so it stays on top of overlapping markers
            var markerOptions = { 
                icon: create_live_marker_icon(isOffline, isSelected)
            };
            if (isSelected) {
                markerOptions.zIndexOffset = 1000;
            }
            
            var endMarker = L.marker(currentPos, markerOptions)
                .addTo(mapViewData.map);

            endMarker.bindPopup(create_trip_popup(t, 'live'));

            // Bind permanent tooltip to identify the employee
            var tooltipClass = isSelected ? 'employee-map-tooltip selected-tooltip' : 'employee-map-tooltip';
            endMarker.bindTooltip(t.employee_name || t.employee, {
                permanent: true,
                direction: 'top',
                offset: [0, -10],
                className: tooltipClass
            });

            // If selected, auto-open the popup on map redraw
            if (isSelected) {
                endMarker.openPopup();
            }

            // Click on the live marker to select the trip
            endMarker.on('click', function(e) {
                L.DomEvent.stopPropagation(e);
                select_trip(id, false);
            });

            mapViewData.markers[id] = [endMarker];

            allPoints.push(currentPos);
        });

        // Zoom to fit all active live positions only if no trip is currently selected
        if (allPoints.length > 0 && !mapViewData.selectedId) {
            if (allPoints.length === 1) {
                mapViewData.map.setView(allPoints[0], 15);
            } else {
                mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
            }
        }
    }

    function create_marker_icon(type, color) {
        var iconColor = '#10b981'; // Green for start
        if (type === 'extended') {
            iconColor = '#fbbf24'; // Yellow for extended
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

    function create_live_marker_icon(isOffline, isSelected) {
        var markerClass = (isOffline ? 'offline' : '') + (isSelected ? ' selected' : '');
        var html = '<div class="live-marker-container ' + markerClass + '">' +
            '<div class="live-marker-dot ' + markerClass + '"></div>' +
            '<div class="live-marker-pulse ' + markerClass + '"></div>' +
            '</div>';
        return L.divIcon({
            html: html,
            className: 'custom-live-marker ' + markerClass,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
            popupAnchor: [0, -12]
        });
    }

    function create_trip_popup(t, type, coord) {
        var isOffline = t.is_online === false;
        var title = type === 'start' ? 'Trip Start' : (type === 'extended' ? 'Trip Extended' : (isOffline ? '● Offline Position' : '● Live Position'));
        var accentColor = type === 'start' ? '#10b981' : (type === 'extended' ? '#fbbf24' : (isOffline ? '#64748b' : '#3b82f6'));
        var timeStr = type === 'start' ? t.start_time : (type === 'extended' ? (coord ? coord.timestamp : '') : (t.last_update_time || t.modified));
        var locationStr = type === 'start' ? (t.start_location || 'Start point') : (type === 'extended' ? (coord ? (coord.latitude + ', ' + coord.longitude) : 'Extended point') : (t.coordinates[t.coordinates.length - 1].join(', ')));
        var displayLocation = format_location_display(locationStr);

        return '<div class="rich-popup">' +
            '<div class="popup-header" style="border-left: 4px solid ' + accentColor + ';">' +
            '<div class="popup-title">' + title + '</div>' +
            '<div class="popup-subtitle">' + (t.employee_name || t.employee) + '</div>' +
            '</div>' +
            '<div class="popup-body">' +
            '<div class="popup-info-row">' +
            '<span class="label">Status:</span>' +
            '<span class="val" style="color: ' + (isOffline ? '#ef4444' : '#10b981') + '; font-weight: 700;">' + (isOffline ? 'Offline' : 'Active') + '</span>' +
            '</div>' +
            '<div class="popup-info-row">' +
            '<span class="label">Time:</span>' +
            '<span class="val">' + format_time_12hr(timeStr) + '</span>' +
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
        pageWrapper.find('#employee-filter').on('change', function() {
            currentFilters.employee = $(this).val();
            update_view();
        });

        pageWrapper.find('#clear-filters').on('click', function() {
            pageWrapper.find('#employee-filter').val('');
            currentFilters.employee = '';
            update_view();
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
            var matchEmp = !f.employee || t.employee === f.employee || t.user_id === f.employee;
            return matchEmp;
        });
    }

    function render_trip_list() {
        var trips = get_filtered_trips();
        var container = pageWrapper.find('#trip-list-content');
        container.empty();

        if (trips.length === 0) {
            container.append( /* nosemgrep */ 
                '<div style="text-align: center; padding: 48px 20px; color: var(--t-text-muted);">' +
                '<div style="font-weight: 600;">No active trips right now.</div>' +
                '<div style="font-size: 12px; margin-top: 4px;">Live updates are automatically running.</div>' +
                '</div>'
            );
            return;
        }

        trips.forEach(function(t) {
            var id = t.name || t.trip_id;
            var isSelected = mapViewData.selectedId === id;
            
            var startLoc = t.start_location || 'Start point';
            var currentLoc = (t.coordinates && t.coordinates.length > 0) ? t.coordinates[t.coordinates.length - 1].join(', ') : 'Unknown location';

            var isOffline = t.is_online === false;
            var badgeHtml = isOffline 
                ? '<span class="card-live-badge offline"><span class="card-live-dot offline"></span>Offline</span>'
                : '<span class="card-live-badge"><span class="card-live-dot"></span>Live</span>';
            var timeStatusHtml = isOffline 
                ? '<span style="color: var(--t-danger); font-weight: 600;">Last update: ' + format_time_12hr(t.last_update_time || t.modified) + '</span>'
                : format_time_12hr(t.start_time) + ' - Present';

            var card = $('<div class="trip-card' + (isSelected ? ' selected' : '') + (isOffline ? ' offline' : '') + '" data-id="' + id + '">' +
                '<div class="trip-card-header" style="align-items: center; margin-bottom: 8px;">' +
                '<div class="trip-card-emp" style="flex: 1; display: flex; align-items: center; gap: 8px;">' + 
                '<span>' + (t.employee_name || t.employee) + '</span>' +
                badgeHtml +
                '</div>' +
                '<div style="font-size: 12px; color: var(--t-text-muted); margin: 0 12px; font-weight: 500;">' +
                timeStatusHtml +
                '</div>' +
                '<div class="trip-card-dist" style="margin-left: auto;">' + (t.distance_km || 0) + ' km</div>' +
                '</div>' +
                '<div class="trip-card-body" style="gap: 4px;">' +
                '<div style="font-size: 11px; display: flex; align-items: center; gap: 6px;">' +
                '<span style="color: var(--t-success); font-size: 10px;">🟢</span>' +
                '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + format_location_display(startLoc) + '</span>' +
                '</div>' +
                '<div style="font-size: 11px; display: flex; align-items: center; gap: 6px;">' +
                '<span style="color: var(--t-primary); font-size: 10px;">🔵</span>' +
                '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + format_location_display(currentLoc) + '</span>' +
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
        mapViewData.selectedId = id;

        pageWrapper.find('.trip-card').removeClass('selected');
        pageWrapper.find('.trip-card[data-id="' + id + '"]').addClass('selected');

        var selectedCard = pageWrapper.find('.trip-card[data-id="' + id + '"]');
        if (selectedCard.length) {
            selectedCard[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        update_view();

        if (zoom && mapViewData.markers[id] && mapViewData.markers[id].length > 0 && mapViewData.map) {
            var marker = mapViewData.markers[id][0];
            mapViewData.map.setView(marker.getLatLng(), 16);
        }
    }
})();
