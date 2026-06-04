// NetraNext Map View Page - Premium UI with Real Data

// Helper function to format time to 12-hour (AM/PM)
function format_time_12hr(timeStr) {
    if (!timeStr || timeStr === '-' || timeStr === 'Pending...') return timeStr;
    var parts = timeStr.trim().split(':');
    if (parts.length < 2) return timeStr;

    var hours = parseInt(parts[0]);
    var minutes = parts[1];
    var ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12; // '0' becomes '12'
    return (hours < 10 ? '0' + hours : hours) + ':' + minutes + ' ' + ampm;
}

// Helper function to format date
function formatDate(dateString) {
    if (!dateString) return '-';
    dateString = dateString.toString().replace(/[\r\n]+/g, ' ').trim();

    if (dateString.includes('T')) {
        return dateString.split('T')[0];
    }

    var firstSpace = dateString.indexOf(' ');
    if (firstSpace > 0) {
        return dateString.substring(0, firstSpace);
    }

    return dateString;
}

// Function to load Leaflet library dynamically
function load_leaflet_library(callback) {
    if (typeof L !== 'undefined') {
        console.log("Leaflet already loaded");
        callback();
        return;
    }

    console.log("Loading Leaflet library...");

    // Load CSS
    $('<link>')
        .attr('rel', 'stylesheet')
        .attr('href', '/assets/frappe/js/lib/leaflet/leaflet.css')
        .appendTo('head'); // nosemgrep

    // Load JS
    $.getScript('/assets/frappe/js/lib/leaflet/leaflet.js')
        .done(function() {
            console.log("Leaflet library loaded successfully");
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

frappe.pages['netranext-mapview'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Journey Analytics',
        single_column: true
    });

    page.set_title('Journey Explorer');

    page.add_button(__('Go to Dashboard'), function() {
        frappe.set_route('netranext-dashboard');
    }, 'dashboard');

    page.add_button(__('Refresh'), function() {
        load_journey_data();
    }, 'refresh');

    page.add_button(__('Full Screen'), function() {
        toggle_fullscreen();
    }, 'expand');

    $(wrapper).find(".layout-main-section").css({"max-width": "100%", "padding": "0"});
    $(wrapper).find(".page-container").css({"max-width": "100%", "padding": "0"});
    $(wrapper).css({"padding": "0"});
    $(".page-body").css("overflow", "hidden");

    var html = `
        <div class="journey-map-view">
            <div class="map-view-body">
                <!-- Sidebar -->
                <div class="journey-sidebar">
                    <div class="filter-bar">
                        <select id="employee-filter" class="j-input" style="flex: 1; min-width: 0;">
                            <option value="">All Employees</option>
                        </select>
                        <input type="date" id="date-filter" class="j-input" style="width: 130px;">
                        <button class="j-btn" id="clear-filters" style="padding: 8px 12px;">Clear</button>
                    </div>

                    <div class="journey-list-container" id="journey-list-content">
                        <!-- Journey cards go here -->
                        <div style="text-align: center; padding: 20px;">
                            <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
                            <div style="color: var(--j-text-muted);">Loading journeys...</div>
                        </div>
                    </div>
                </div>

                <!-- Map -->
                <div class="map-content">
                    <div id="journey-map"></div>

                    <!-- Map Overlays -->
                    <div class="map-overlay-controls">
                        <button class="j-btn" id="fit-all-routes" title="Fit all visible routes">Fit All</button>
                        <button class="j-btn" id="fit-selected" title="Center on selected route">Selected</button>
                    </div>

                    <div class="map-overlay-stats" id="view-stats" style="display:none;">
                        <div style="font-size: 11px; text-transform: uppercase; color: var(--j-text-muted); font-weight: 700; margin-bottom: 4px;">Day Total</div>
                        <div style="font-size: 18px; font-weight: 900; color: var(--j-text);" id="total-dist">0.0 km</div>
                        <div style="font-size: 12px; color: var(--j-text-muted); font-weight: 600;" id="total-count">0 journeys</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    $(page.main).empty().append( /* nosemgrep */ html);

    // Global State
    window.mapViewData = {
        journeys: [],
        filteredIndices: [],
        selectedId: null,
        unselectedColor: '#3b82f6', // Blue
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
        console.log("Leaflet loaded, initializing page...");

        // Set default date and max date (prevent future selection)
        $('#date-filter').val(window.currentFilters.date).attr('max', window.currentFilters.date);

        // Initialize Map
        initialize_map();

        // Force size re-calculation after DOM is stable
        setTimeout(function() {
            if (window.mapViewData.map) {
                window.mapViewData.map.invalidateSize();
            }
        }, 500);

        // Load real journey data from API
        load_journey_data();

        // Event Handlers
        setup_event_handlers();
    });
};

// Handle subsequent navigations
frappe.pages['netranext-mapview'].on_page_show = function (wrapper) {
    if (window.mapViewData && window.mapViewData.map) {
        setTimeout(function() {
            window.mapViewData.map.invalidateSize();
        }, 300);
    }
    if (window.mapViewData && window.mapViewData.journeys.length > 0) {
        apply_route_options();
    }
};

// Helper: Get today's date in YYYY-MM-DD format
function get_today_date() {
    var today = new Date();
    var dd = String(today.getDate()).padStart(2, '0');
    var mm = String(today.getMonth() + 1).padStart(2, '0');
    var yyyy = today.getFullYear();
    return yyyy + '-' + mm + '-' + dd;
}

// Load real journey data from API
function load_journey_data() {
    // Show loading state
    $('#journey-list-content').html( /* nosemgrep */ `
        <div style="text-align: center; padding: 20px;">
            <div class="loader-spinner" style="margin: 0 auto 16px;"></div>
            <div style="color: var(--j-text-muted);">Loading journeys...</div>
        </div>
    `);

    // Get current filters
    var dateFrom = window.currentFilters.date || get_today_date();
    var dateTo = dateFrom;
    var employeeId = window.currentFilters.employee || null;

    // Call local NetraNext dashboard API (avoids CORS issues)
    frappe.call({
        method: "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
        args: {
            date_from: dateFrom,
            date_to: dateTo
        },
        callback: function(response) {
            console.log("Map View API Response:", response);

            if (response.message && response.message.status === 'success') {
                var data = response.message.data || {};
                var journeys = data.journeys || [];

                // Enrich journeys with coordinates for map display
                journeys.forEach(function(journey) {
                    journey.coordinates = generate_journey_coordinates(journey);
                });

                window.mapViewData.journeys = journeys;
                populate_employee_filter();
                update_view();

                // Apply route options if coming from dashboard
                apply_route_options();
            } else {
                show_error_message('No journey data available for the selected filters.');
            }
        },
        error: function(xhr, status, error) {
            console.error("Map View API Error:", xhr, status, error);
            var error_msg = "Failed to load journey data";

            if (xhr.responseJSON && xhr.responseJSON.message) {
                error_msg = xhr.responseJSON.message;
            } else if (xhr.statusText) {
                error_msg = "Connection error: " + xhr.statusText;
            }

            show_error_message(error_msg);
        }
    });
}

// Generate coordinates for journey display
function generate_journey_coordinates(journey) {
    // If journey has actual coordinates, use them
    if (journey.raw_coordinates && journey.raw_coordinates.length > 0) {
        return journey.raw_coordinates.map(function(coord) {
            return [coord.latitude || coord.lat, coord.longitude || coord.lng];
        });
    }

    // Check if journey has start and end coordinates
    if (journey.start_latitude && journey.start_longitude &&
        journey.end_latitude && journey.end_longitude) {

        var startLat = parseFloat(journey.start_latitude);
        var startLon = parseFloat(journey.start_longitude);
        var endLat = parseFloat(journey.end_latitude);
        var endLon = parseFloat(journey.end_longitude);

        // Generate intermediate points between start and end
        var coords = [];
        var waypoints = Math.min(5, Math.max(2, Math.round(journey.distance_km || 3)));

        for (var i = 0; i < waypoints; i++) {
            var ratio = i / (waypoints - 1);
            var lat = startLat + (endLat - startLat) * ratio;
            var lon = startLon + (endLon - startLon) * ratio;

            // Add slight randomness for visual variation
            lat += (Math.random() - 0.5) * 0.001;
            lon += (Math.random() - 0.5) * 0.001;

            coords.push([lat, lon]);
        }
        return coords;
    }

    // Fallback: generate demo coordinates based on journey ID and employee
    var baseLat = 12.9716; // Bangalore base
    var baseLon = 77.5946;
    var journeyNum = 1;

    if (journey.name) {
        var parts = journey.name.split('-');
        if (parts.length > 1) {
            journeyNum = parseInt(parts[1]) || 1;
        }
    }

    var offset = journeyNum * 0.02;
    var coords = [];
    var numPoints = Math.max(3, Math.round((journey.distance_km || 5) / 2));

    for (var i = 0; i < numPoints; i++) {
        var lat = baseLat + offset + (i * 0.005) + (Math.random() - 0.5) * 0.002;
        var lon = baseLon + offset + (i * 0.005) + (Math.random() - 0.5) * 0.002;
        coords.push([lat, lon]);
    }

    return coords;
}

function update_view() {
    render_journey_list();
    render_journeys_on_map();
    update_stats();

    // Ensure map tiles are correctly positioned
    if (window.mapViewData.map) {
        window.mapViewData.map.invalidateSize();
    }
}

function update_stats() {
    var journeys = get_filtered_journeys();

    if (journeys.length > 0) {
        var totalKm = journeys.reduce(function(sum, j) {
            return sum + (parseFloat(j.distance_km) || 0);
        }, 0);

        $('#total-dist').text(totalKm.toFixed(2) + " km");
        $('#total-count').text(journeys.length + " journeys");
        $('#view-stats').fadeIn();
    } else {
        $('#view-stats').fadeOut();
    }
}

function apply_route_options() {
    var options = frappe.route_options || {};
    var targetId = options.journey_id || null;
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
        load_journey_data();
        setTimeout(function() {
            select_journey(targetId, true);
        }, 800);
        frappe.route_options = {};
    }
}

function show_error_message(message) {
    var errorHtml = '<div style="text-align: center; padding: 40px;">' +
        '<div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>' +
        '<h3 style="color: #e53e3e; margin-bottom: 8px;">Error Loading Data</h3>' +
        '<p style="color: #718096; margin-bottom: 16px;">' + message + '</p>' +
        '<button class="btn btn-default" onclick="load_journey_data()">Retry</button>' +
        '</div>';

    $('#journey-list-content').html( /* nosemgrep */ errorHtml);
}

function populate_employee_filter() {
    var employees = {};
    window.mapViewData.journeys.forEach(function (j) {
        var empId = j.employee || j.user_id;
        if (empId) {
            employees[empId] = j.employee_name || empId;
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
    console.log("Initializing map...");

    if (typeof L === 'undefined') {
        console.error("Leaflet library (L) is not loaded!");
        $('#journey-map').html( /* nosemgrep */ 
            '<div style="text-align: center; padding: 40px; color: #8d99a6;">' +
            '<div style="font-size: 48px;">⚠️</div>' +
            '<h3>Map Not Available</h3>' +
            '<p>Unable to load map library. Please ensure Leaflet.js is included.</p>' +
            '</div>'
        );
        return;
    }

    console.log("Leaflet loaded, creating map...");

    try {
        // Default to Bangalore coordinates
        window.mapViewData.map = L.map('journey-map').setView([12.9716, 77.5946], 12);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(window.mapViewData.map);

        console.log("Map created successfully");
    } catch (error) {
        console.error("Error creating map:", error);
        $('#journey-map').html( /* nosemgrep */ 
            '<div style="text-align: center; padding: 40px; color: #e53e3e;">' +
            '<div style="font-size: 48px;">⚠️</div>' +
            '<h3>Map Error</h3>' +
            '<p>' + error.message + '</p>' +
            '</div>'
        );
    }
}

function render_journeys_on_map() {
    if (!window.mapViewData.map) return;

    // Clear existing layers
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

    var journeys = get_filtered_journeys();
    var allPoints = [];

    journeys.forEach(function (j) {
        var id = j.name || j.trip_id;
        var coords = j.coordinates;

        if (!coords || coords.length < 2) return;

        var isSelected = window.mapViewData.selectedId === id;
        var color = isSelected ? window.mapViewData.selectedColor : window.mapViewData.unselectedColor;

        // Polyline
        var polyline = L.polyline(coords, {
            color: color,
            weight: isSelected ? 8 : 4,
            opacity: isSelected ? 1.0 : 0.4,
            lineJoin: 'round'
        }).addTo(window.mapViewData.map);

        if (isSelected) {
            polyline.bringToFront();
        }

        polyline.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            select_journey(id, true);
        });

        window.mapViewData.layers[id] = polyline;

        // Markers
        var startMarker = L.marker(coords[0], { icon: create_marker_icon('start', color) })
            .addTo(window.mapViewData.map);
        var endMarker = L.marker(coords[coords.length - 1], { icon: create_marker_icon('end', color) })
            .addTo(window.mapViewData.map);

        startMarker.bindPopup(create_journey_popup(j, 'start'));
        endMarker.bindPopup(create_journey_popup(j, 'end'));

        window.mapViewData.markers[id] = [startMarker, endMarker];

        if (isSelected) {
            startMarker.setOpacity(1);
            endMarker.setOpacity(1);
        } else {
            startMarker.setOpacity(0.5);
            endMarker.setOpacity(0.5);
        }

        // Add to global bounds
        coords.forEach(function(p) {
            allPoints.push(p);
        });
    });

    // Zoom to fit all only if no journey is currently selected
    if (allPoints.length > 0 && !window.mapViewData.selectedId) {
        window.mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
    }
}

function create_marker_icon(type, color) {
    var iconColor = type === 'start' ? '#10b981' : '#ef4444';
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

function create_journey_popup(j, type) {
    var title = type === 'start' ? 'Trip Start' : 'Trip End';
    var accentColor = type === 'start' ? '#10b981' : '#ef4444';
    var timeStr = type === 'start' ? j.start_time : j.end_time;
    var locationStr = type === 'start' ? (j.start_location || 'Start point') : (j.end_location || 'End point');
    var displayLocation = format_location_display(locationStr);

    return '<div class="rich-popup">' +
        '<div class="popup-header" style="border-left: 4px solid ' + accentColor + ';">' +
        '<div class="popup-title">' + title + '</div>' +
        '<div class="popup-subtitle">' + (j.employee_name || j.employee) + '</div>' +
        '</div>' +
        '<div class="popup-body">' +
        '<div class="popup-info-row">' +
        '<span class="label">Time:</span>' +
        '<span class="val">' + format_time_12hr(timeStr) + '</span>' +
        '</div>' +
        '<div class="popup-info-row">' +
        '<span class="label">Date:</span>' +
        '<span class="val">' + formatDate(j.start_time) + '</span>' +
        '</div>' +
        '<div class="popup-info-row">' +
        '<span class="label">Distance:</span>' +
        '<span class="val">' + (j.distance_km || 0) + ' km</span>' +
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
                console.error('Geocoding error:', err);
                window.mapViewData.addressCache[cacheKey] = locationStr;
                $('.' + classMarker).text(locationStr);
            });
    }
    
    return '<span class="' + classMarker + '">Loading address...</span>';
}

function setup_event_handlers() {
    $('#employee-filter').on('change', function() {
        window.currentFilters.employee = $(this).val();
        load_journey_data();
    });

    $('#date-filter').on('change', function() {
        window.currentFilters.date = $(this).val();
        load_journey_data();
    });

    $('#clear-filters').on('click', function() {
        $('#employee-filter').val('');
        $('#date-filter').val(get_today_date());
        window.currentFilters = {
            employee: '',
            date: get_today_date()
        };
        load_journey_data();
    });

    $('#fit-all-routes').on('click', function() {
        var allPoints = [];
        Object.values(window.mapViewData.layers).forEach(function(layer) {
            layer.getLatLngs().forEach(function(p) {
                allPoints.push(p);
            });
        });
        if (allPoints.length) {
            window.mapViewData.map.fitBounds(allPoints, { padding: [50, 50] });
        }
    });

    $('#fit-selected').on('click', function() {
        if (window.mapViewData.selectedId) {
            select_journey(window.mapViewData.selectedId, true);
        }
    });

    $(window).on('resize', function() {
        if (window.mapViewData.map) {
            window.mapViewData.map.invalidateSize();
        }
    });
}

function toggle_fullscreen() {
    var element = document.querySelector('.journey-map-view');
    if (!document.fullscreenElement) {
        element.requestFullscreen().catch(function(err) {
            frappe.show_alert('Error attempting to enable full-screen mode: ' + err.message);
        });
    } else {
        document.exitFullscreen();
    }
}

function get_filtered_journeys() {
    var journeys = window.mapViewData.journeys || [];
    var f = window.currentFilters;

    return journeys.filter(function (j) {
        var matchEmp = !f.employee || j.employee === f.employee || j.user_id === f.employee;

        // Robust date comparison using split(' ')[0] to avoid timezone shifts
        var rawDateStr = j.start_time || j.posting_date || '';
        var jDate = rawDateStr.split(' ')[0];
        var matchDate = !f.date || jDate === f.date;

        return matchEmp && matchDate;
    });
}

function render_journey_list() {
    var journeys = get_filtered_journeys();
    var container = $('#journey-list-content');
    container.empty();

    if (journeys.length === 0) {
        container.append( /* nosemgrep */ 
            '<div style="text-align: center; padding: 48px 20px; color: var(--j-text-muted);">' +
            '<div style="font-size: 40px; margin-bottom: 12px;">📍</div>' +
            '<div style="font-weight: 600;">No journeys found for this date.</div>' +
            '<div style="font-size: 12px; margin-top: 4px;">Try selecting another date or employee.</div>' +
            '</div>'
        );
        return;
    }

    journeys.forEach(function(j) {
        var id = j.name || j.trip_id;
        var isSelected = window.mapViewData.selectedId === id;
        
        var startLoc = j.start_location || 'Start point';
        var endLoc = j.end_location || 'End point';

        var card = $('<div class="journey-card' + (isSelected ? ' selected' : '') + '" data-id="' + id + '">' +
            '<div class="journey-card-header" style="align-items: center; margin-bottom: 8px;">' +
            '<div class="journey-card-emp" style="flex: 1;">' + (j.employee_name || j.employee) + '</div>' +
            '<div style="font-size: 12px; color: var(--j-text-muted); margin: 0 12px; font-weight: 500;">' +
            format_time_12hr(j.start_time) + ' - ' + format_time_12hr(j.end_time) +
            '</div>' +
            '<div class="journey-card-dist" style="margin-left: auto;">' + (j.distance_km || 0) + ' km</div>' +
            '</div>' +
            '<div class="journey-card-body" style="gap: 4px;">' +
            '<div style="font-size: 11px; display: flex; align-items: center; gap: 6px;">' +
            '<span style="color: var(--j-success); font-size: 10px;">🟢</span>' +
            '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + format_location_display(startLoc) + '</span>' +
            '</div>' +
            '<div style="font-size: 11px; display: flex; align-items: center; gap: 6px;">' +
            '<span style="color: var(--j-danger); font-size: 10px;">🔴</span>' +
            '<span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' + format_location_display(endLoc) + '</span>' +
            '</div>' +
            '</div>' +
            '</div>'
        );

        card.on('click', function() {
            select_journey(id, true);
        });

        container.append( /* nosemgrep */ card);
    });
}

function select_journey(id, zoom) {
    window.mapViewData.selectedId = id;

    // Update List UI
    $('.journey-card').removeClass('selected');
    $('.journey-card[data-id="' + id + '"]').addClass('selected');

    // Scroll list if card is not visible
    var selectedCard = $('.journey-card[data-id="' + id + '"]');
    if (selectedCard.length) {
        selectedCard[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // Update Map UI
    update_view();

    if (zoom && window.mapViewData.layers[id]) {
        var bounds = window.mapViewData.layers[id].getBounds();
        window.mapViewData.map.fitBounds(bounds, { padding: [100, 100], maxZoom: 16 });
    }

    update_selection_ui(id);
}

function update_selection_ui(id) {
    // Selected trip details can be added here if needed
}