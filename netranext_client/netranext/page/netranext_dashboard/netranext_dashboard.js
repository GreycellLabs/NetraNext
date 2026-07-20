// NetraNext Dashboard - Premium UI (Based on FaceTrace Dashboard Design)

// Store data globally for filtering
window.dashboardData = {
    journeys: [],
    attendance: [],
    summary: {}
};

// Helper: Get today's date in YYYY-MM-DD format
function get_today_date() {
    var today = new Date();
    var dd = String(today.getDate()).padStart(2, '0');
    var mm = String(today.getMonth() + 1).padStart(2, '0');
    var yyyy = today.getFullYear();
    return yyyy + '-' + mm + '-' + dd;
}

var todayDate = get_today_date();

// Store current filters including pagination
window.currentFilters = {
    journey: { status: 'all', dateFrom: todayDate, dateTo: todayDate, employee: '', page: 1 },
    attendance: { status: 'all', dateFrom: todayDate, dateTo: todayDate, employee: '', page: 1 },
    limit: 10
};

// Helper: Format time to 12-hour (AM/PM)
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

// Filtering helper functions
function filter_journeys(data, status) {
    if (!data) return [];
    if (!status || status === 'all') return data;
    return data.filter(j => j.status === status);
}

function filter_attendance(data, status) {
    if (!data) return [];
    if (!status || status === 'all') return data;
    return data.filter(a => a.log_type === status);
}

function filter_by_employee(data, employee) {
    if (!data) return [];
    if (!employee) return data;
    return data.filter(item => (item.employee === employee || item.employee_name === employee));
}

function filter_by_date(data, from, to, type) {
    if (!data) return [];
    var dateField = type === 'journey' ? 'start_time' : 'attendance_date';
    return data.filter(item => {
        var val = item[dateField] || '';
        var dateVal = val.split(' ')[0];
        if (from && dateVal < from) return false;
        if (to && dateVal > to) return false;
        return true;
    });
}

frappe.pages['netranext-dashboard'].on_page_load = function (wrapper) {
    // Standard Frappe Page Initialization
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('NetraNext Dashboard'),
        single_column: true
    });

    // Clear wrapper to prevent duplicate content
    $(page.main).empty();

    // Add primary actions
    page.set_primary_action(__('Refresh'), () => refresh_dashboard_data(), 'refresh');

    // Create sections in standard Frappe layout
    var main_section = $(`
        <div class="netranext-dashboard">
            <div id="stats-section" class="section">
                <div id="number-cards" class="stats-grid"></div>
            </div>

            <div id="journey-table" class="section">
                <div class="section-header">
                    <h3 style="cursor: pointer; color: #1a202c;" onclick="frappe.set_route('netranext-trip-history')" onmouseover="this.style.color='#6366f1'" onmouseout="this.style.color='#1a202c'">
                        Trips <i class="fa fa-map-o" style="font-size: 14px; margin-left: 4px; vertical-align: middle; opacity: 0.7;"></i>
                    </h3>
                    <div class="filter-controls">
                        <div class="right-filters">
                            <select id="journey-employee" class="employee-select">
                                <option value="">All Employees</option>
                            </select>
                            <div class="date-filters">
                                <input type="date" id="journey-date-from" class="date-input" placeholder="From">
                                <input type="date" id="journey-date-to" class="date-input" placeholder="To">
                                <button class="clear-date-btn" data-type="journey">Clear</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div id="journey-content"></div>
            </div>

            <div id="attendance-table" class="section">
                <div class="section-header">
                    <h3>Attendance Logs</h3>
                    <div class="filter-controls">
                        <div class="right-filters">
                            <select id="attendance-employee" class="employee-select">
                                <option value="">All Employees</option>
                            </select>
                            <div class="date-filters">
                                <input type="date" id="attendance-date-from" class="date-input" placeholder="From">
                                <input type="date" id="attendance-date-to" class="date-input" placeholder="To">
                                <button class="clear-date-btn" data-type="attendance">Clear</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div id="attendance-content"></div>
            </div>

            <div id="quick-links-section" class="section">
                <div class="shortcuts-columns">
                    <div class="shortcut-group">
                        <h4 class="group-title">Employee Onboard Flow</h4>
                        <div id="onboard-flow-content" class="shortcut-list"></div>
                    </div>
                    <div class="shortcut-group">
                        <h4 class="group-title">Helpful Links</h4>
                        <div id="helpful-links-content" class="shortcut-list"></div>
                    </div>
                </div>
            </div>
        </div>
    `).appendTo(page.main); // nosemgrep

    // Initial loader skeleton
    if (!$('#dashboard-loader').length) {
        $('body').append( /* nosemgrep */ `
            <div id="dashboard-loader">
                <div class="loader-spinner"></div>
                <div class="loader-text">Loading Dashboard...</div>
            </div>
        `);
    }

    // Initialize default dates in UI
    $('#journey-date-from').val(window.currentFilters.journey.dateFrom);
    $('#journey-date-to').val(window.currentFilters.journey.dateTo);
    $('#attendance-date-from').val(window.currentFilters.attendance.dateFrom);
    $('#attendance-date-to').val(window.currentFilters.attendance.dateTo);

    // Load dashboard data from API
    refresh_dashboard_data();

    // Event listeners
    $(document).off('change', '#journey-employee').on('change', '#journey-employee', function () {
        window.currentFilters.journey.employee = $(this).val();
        window.currentFilters.journey.page = 1;
        refresh_dashboard_data();
    });

    $(document).off('change', '#attendance-employee').on('change', '#attendance-employee', function () {
        window.currentFilters.attendance.employee = $(this).val();
        window.currentFilters.attendance.page = 1;
        refresh_dashboard_data();
    });

    $(document).off('change', '#journey-date-from, #journey-date-to').on('change', '#journey-date-from, #journey-date-to', function () {
        window.currentFilters.journey.dateFrom = $('#journey-date-from').val();
        window.currentFilters.journey.dateTo = $('#journey-date-to').val();
        window.currentFilters.journey.page = 1;
        refresh_dashboard_data();
    });

    $(document).off('change', '#attendance-date-from, #attendance-date-to').on('change', '#attendance-date-from, #attendance-date-to', function () {
        window.currentFilters.attendance.dateFrom = $('#attendance-date-from').val();
        window.currentFilters.attendance.dateTo = $('#attendance-date-to').val();
        window.currentFilters.attendance.page = 1;
        refresh_dashboard_data();
    });

    $(document).off('click', '.pagination-btn').on('click', '.pagination-btn', function () {
        var type = $(this).data('type');
        var direction = $(this).data('direction');
        if (direction === 'next') window.currentFilters[type].page++;
        else if (direction === 'prev' && window.currentFilters[type].page > 1) window.currentFilters[type].page--;
        refresh_dashboard_data();
    });

    $(document).off('click', '.clear-date-btn').on('click', '.clear-date-btn', function () {
        var type = $(this).data('type');
        $(`#${type}-date-from`).val('');
        $(`#${type}-date-to`).val('');
        window.currentFilters[type].dateFrom = '';
        window.currentFilters[type].dateTo = '';
        window.currentFilters[type].page = 1;
        refresh_dashboard_data();
    });

    console.log("NetraNext Dashboard loaded successfully with premium UI");
};

// Populate employee dropdowns with all system employees
function populate_employee_dropdowns() {
    var employees = {};

    // Use all_employees from API response to ensure complete coverage
    (window.dashboardData.all_employees || []).forEach(function (emp) {
        if (emp.name) {
            employees[emp.name] = emp.employee_name || emp.name;
        }
    });

    // Fallback: Check journeys and attendance if all_employees is empty
    if (Object.keys(employees).length === 0) {
        (window.dashboardData.journeys || []).forEach(function (j) {
            if (j.employee) {
                var empName = j.employee_name || j.employee;
                employees[j.employee] = empName;
            }
        });
        (window.dashboardData.attendance || []).forEach(function (a) {
            if (a.employee) {
                var empName = a.employee_name || a.employee;
                employees[a.employee] = empName;
            }
        });
    }

    // Populate journey dropdown
    var journeySelect = $('#journey-employee');
    journeySelect.find('option:not(:first)').remove();
    Object.keys(employees).sort().forEach(function (empId) {
        var empName = employees[empId];
        journeySelect.append( /* nosemgrep */ '<option value="' + empId + '">' + empName + '</option>');
    });

    // Populate attendance dropdown
    var attendanceSelect = $('#attendance-employee');
    attendanceSelect.find('option:not(:first)').remove();
    Object.keys(employees).sort().forEach(function (empId) {
        var empName = employees[empId];
        attendanceSelect.append( /* nosemgrep */ '<option value="' + empId + '">' + empName + '</option>');
    });
}

// Toggle loading overlay
function set_loading(show) {
    if (show) {
        $('#dashboard-loader').css('display', 'flex').hide().fadeIn(200);
    } else {
        $('#dashboard-loader').fadeOut(200);
    }
}

// Refresh data from server based on current filters and pages
function refresh_dashboard_data() {
    set_loading(true);

    // Use frappe.call to call local API which calls backend
    frappe.call({
        method: "netranext_client.netranext.apis.v1.dashboard.get_dashboard_data",
        args: {
            date_from: window.currentFilters.journey.dateFrom || get_today_date(),
            date_to: window.currentFilters.journey.dateTo || get_today_date(),
            limit: window.currentFilters.limit,
            journey_page: window.currentFilters.journey.page,
            journey_employee: window.currentFilters.journey.employee,
            attendance_page: window.currentFilters.attendance.page,
            attendance_employee: window.currentFilters.attendance.employee
        },
        callback: function(response) {
            console.log("API Response:", response);

            if (response.message && response.message.status === 'success') {
                var responseData = response.message.data;
                var isInitialLoad = !window.dashboardData || !window.dashboardData.all_employees || window.dashboardData.all_employees.length === 0;

                window.dashboardData = {
                    journeys: responseData.journeys || [],
                    attendance: responseData.attendance || [],
                    summary: responseData.summary || {},
                    all_employees: responseData.all_employees || [],
                    total_journeys: responseData.total_journeys || 0,
                    total_attendance: responseData.total_attendance || 0
                };

                if (isInitialLoad) {
                    populate_employee_dropdowns();
                }

                render_dashboard(responseData);
            } else {
                // Handle error responses
                var error_msg = "Failed to load dashboard data";
                if (response.message && response.message.message) {
                    error_msg = response.message.message;
                }
                show_error_state(error_msg);
            }
            set_loading(false);
        },
        error: function(xhr, status, error) {
            console.error("API Error:", xhr, status, error);
            var error_msg = "Failed to connect to dashboard API";
            if (xhr.responseJSON && xhr.responseJSON.message) {
                error_msg = xhr.responseJSON.message;
            } else if (xhr.statusText) {
                error_msg = xhr.statusText;
            }
            show_error_state(error_msg);
            set_loading(false);
        }
    });
}

// Render pagination controls
function render_pagination(type, totalCount, currentPage) {
    var limit = window.currentFilters.limit;
    var totalPages = Math.ceil(totalCount / limit) || 1;
    var start = ((currentPage - 1) * limit) + 1;
    var end = Math.min(currentPage * limit, totalCount);

    if (totalCount === 0) return '';

    return `
        <div class="pagination-container" style="display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: #fafbfc; border-top: 1px solid #f0f0f0;">
            <div class="pagination-info" style="font-size: 13px; color: #718096; font-weight: 500;">
                Showing <span style="color: #4a5568; font-weight: 700;">${start}-${end}</span> of <span style="color: #4a5568; font-weight: 700;">${totalCount}</span> records
            </div>
            <div class="pagination-actions" style="display: flex; gap: 8px;">
                <button class="pagination-btn" data-type="${type}" data-direction="prev" ${currentPage === 1 ? 'disabled' : ''}
                    style="padding: 6px 14px; border-radius: 6px; border: 1px solid #e2e8f0; background: ${currentPage === 1 ? '#f8fafc' : '#fff'}; cursor: ${currentPage === 1 ? 'not-allowed' : 'pointer'}; color: ${currentPage === 1 ? '#cbd5e0' : '#4a5568'}; font-size: 12px; font-weight: 600; transition: all 0.2s;">
                    ← Previous
                </button>
                <div style="display: flex; align-items: center; padding: 0 10px; font-size: 13px; color: #4a5568; font-weight: 600;">
                    Page ${currentPage} of ${totalPages}
                </div>
                <button class="pagination-btn" data-type="${type}" data-direction="next" ${currentPage >= totalPages ? 'disabled' : ''}
                    style="padding: 6px 14px; border-radius: 6px; border: 1px solid #e2e8f0; background: ${currentPage >= totalPages ? '#f8fafc' : '#fff'}; cursor: ${currentPage >= totalPages ? 'not-allowed' : 'pointer'}; color: ${currentPage >= totalPages ? '#cbd5e0' : '#4a5568'}; font-size: 12px; font-weight: 600; transition: all 0.2s;">
                    Next →
                </button>
            </div>
        </div>
    `;
}

function render_dashboard(data) {
    console.log("Dashboard data received:", data);

    var summary = data.summary || {};

    // Render Statistics (Number Card Style)
    var statsHTML = '';
    var cardMetrics = [
        { label: 'TOTAL EMPLOYEES', value: summary.total_employees, color: '#6366f1' },
        { label: 'NEW HIRES (YEAR)', value: summary.new_hires_this_year, color: '#a855f7' },
        { label: 'PRESENT TODAY', value: summary.present_today, color: '#3b82f6' }
    ];

    cardMetrics.forEach(m => {
        statsHTML += `
            <div class="stat-card-premium">
                <div class="stat-card-header">
                    <span class="stat-label">${__(m.label)}</span>
                </div>
                <div class="stat-value-large">${m.value || 0}</div>
            </div>
        `;
    });
    document.getElementById("number-cards").innerHTML /* nosemgrep */ = statsHTML;

    // Render Your Shortcuts - Column 1: Employee Onboard Flow
    var onboardHTML = `
        <div class="shortcut-item" onclick="frappe.new_doc('User')">
            <span class="shortcut-label">Add User</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.set_route('List', 'User')">
            <span class="shortcut-label">All Users</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.new_doc('Employee')">
            <span class="shortcut-label">Add Employee</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.set_route('List', 'Employee')">
            <span class="shortcut-label">All Employees</span>
            <span class="shortcut-arrow">↗</span>
        </div>
    `;

    // Render Your Shortcuts - Column 2: Helpful Links
    var helpfulHTML = `
        <div class="shortcut-item" onclick="frappe.set_route('netranext-live-tracking')">
            <span class="shortcut-label">Live Tracking</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.set_route('netranext-trip-history')">
            <span class="shortcut-label">Trip History</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.set_route('List', 'Employee Checkin')">
            <span class="shortcut-label">Attendance Logs</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.set_route('List', 'NetraNext Face Registration Request')">
            <span class="shortcut-label">Face Registration Requests</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="frappe.set_route('List', 'NetraNext Journey')">
            <span class="shortcut-label">Employee Trips</span>
            <span class="shortcut-arrow">↗</span>
        </div>
        <div class="shortcut-item" onclick="show_schedule_trip_dialog()">
            <span class="shortcut-label">Schedule Trip</span>
            <span class="shortcut-arrow">↗</span>
        </div>
    `;

    document.getElementById("onboard-flow-content").innerHTML /* nosemgrep */ = onboardHTML;
    document.getElementById("helpful-links-content").innerHTML /* nosemgrep */ = helpfulHTML;

    // Render tables
    render_journey_table(data.journeys || []);
    render_attendance_table(data.attendance || []);
}

// Render journey list in Frappe style
function render_journey_table(journeys) {
    var totalCount = window.dashboardData.total_journeys || 0;
    var currentPage = window.currentFilters.journey.page;

    var html = `
        <div class="list-main" style="border: 1px solid #ebf0f5; border-radius: 8px; overflow: hidden; background: #fff;">
            <div class="list-items">
                <div class="list-item-container list-item-header">
                    <div style="flex: 1.2;">ID / Employee</div>
                    <div style="flex: 1;">Date / Times</div>
                    <div style="flex: 2;">Route (Start → End)</div>
                    <div style="flex: 0.8; text-align: right;">Distance</div>
                </div>
    `;

    if (journeys.length > 0) {
        journeys.forEach(function (j) {
            var journeyId = j.name || '-';
            var empName = j.employee_name || j.employee || '-';
            var dateTime = (j.start_time || '').split(' ');
            var dateStr = dateTime[0] || '-';
            var startTime = dateTime[1] ? format_time_12hr(dateTime[1]) : '-';
            var endTime = j.end_time ? format_time_12hr(j.end_time.split(' ')[1]) : 'Active';
            var startAddr = j.start_location || '-';
            var endAddr = j.end_location || '-';
            var distance = j.distance_km ? `${j.distance_km} km` : '-';

            html += `
                <div class="list-item-container" onclick="frappe.set_route('netranext-trip-history', { trip_id: '${journeyId}' })" style="cursor: pointer; align-items: flex-start; padding: 14px 18px;">
                    <div style="flex: 1.2; padding-right: 15px;">
                        <span style="color: #6366f1; font-weight: 700; display: block; font-size: 14.5px;">${journeyId}</span>
                        <span style="font-size: 13px; color: #4a5568; margin-top: 2px; display: block;">${empName}</span>
                    </div>
                    <div style="flex: 1;">
                        <span style="font-weight: 700; color: #1a202c; display: block; font-size: 14px;">${dateStr}</span>
                        <span style="font-size: 13px; color: #718096; margin-top: 2px; display: block;">${startTime} - ${endTime}</span>
                    </div>
                    <div style="flex: 2; padding-right: 15px;">
                        <div style="font-size: 14px; color: #1a202c; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${startAddr}">
                            <i class="fa fa-map-marker" style="color: #10b981; width: 14px;"></i> ${startAddr}
                        </div>
                        <div style="font-size: 14px; color: #718096; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 5px;" title="${endAddr}">
                            <i class="fa fa-map-marker" style="color: #ef4444; width: 14px;"></i> ${endAddr}
                        </div>
                    </div>
                    <div style="flex: 0.8; text-align: right;">
                        <span class="badge" style="background: #f1f5f9; color: #475569; font-weight: 700; padding: 6px 10px; border-radius: 6px; font-size: 13px;">${distance}</span>
                    </div>
                </div>
            `;
        });
    } else {
        html += `
            <div style="padding: 60px 40px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 20px; opacity: 0.3;">
                    <i class="fa fa-route" style="color: #6366f1;"></i>
                </div>
                <div style="color: #1a202c; font-size: 16px; font-weight: 600; margin-bottom: 8px;">No Trip Records Found</div>
                <div style="color: #718096; font-size: 14px; margin-bottom: 20px;">Trip records will appear here when employees track their GPS routes.</div>
                <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
                    <button class="btn btn-primary btn-sm" onclick="frappe.set_route('List', 'NetraNext Journey')">
                        <i class="fa fa-plus" style="margin-right: 6px;"></i>Create Trip
                    </button>
                    <button class="btn btn-default btn-sm" onclick="show_schedule_trip_dialog()">
                        <i class="fa fa-calendar" style="margin-right: 6px;"></i>Schedule Trip
                    </button>
                    <button class="btn btn-default btn-sm" onclick="frappe.set_route('netranext-trip-history')">
                        <i class="fa fa-map" style="margin-right: 6px;"></i>View Map
                    </button>
                </div>
            </div>
        `;
    }

    html += `
            </div>
            <div class="list-footer">
                ${render_pagination('journey', totalCount, currentPage)}
            </div>
        </div>
    `;

    document.getElementById("journey-content").innerHTML /* nosemgrep */ = html;
}

// Render attendance list in Frappe style
function render_attendance_table(attendance) {
    var totalCount = window.dashboardData.total_attendance || 0;
    var currentPage = window.currentFilters.attendance.page;

    var html = `
        <div class="list-main" style="border: 1px solid #ebf0f5; border-radius: 8px; overflow: hidden; background: #fff;">
            <div class="list-items">
                <div class="list-item-container list-item-header">
                    <div style="flex: 1;">Employee</div>
                    <div style="flex: 0.8;">Date</div>
                    <div style="flex: 2;">Time Logs (In → Out)</div>
                    <div style="flex: 0.8; text-align: right;">Total Hours</div>
                </div>
    `;

    if (attendance.length > 0) {
        var now = new Date();
        var windowStart = 8 * 60; // 08:00 AM in minutes
        var windowEnd = 20 * 60;  // 08:00 PM in minutes
        var windowTotal = windowEnd - windowStart;

        attendance.forEach(function (entry) {
            var empName = entry.employee_name || entry.employee || '-';
            var dateStr = entry.attendance_date || '-';
            var timelineHTML = '';
            var totalMinutes = 0;

            if (entry.logs && entry.logs.length > 0) {
                var currentIn = null;
                var currentInTime = '';
                var segments = [];

                entry.logs.forEach(function (log) {
                    var logTime = log.time || '00:00:00';
                    var t = logTime.split(':');
                    var mins = parseInt(t[0]) * 60 + parseInt(t[1]);

                    if (log.log_type === 'IN') {
                        currentIn = mins;
                        currentInTime = logTime;
                    } else if (log.log_type === 'OUT' && currentIn !== null) {
                        var duration = mins - currentIn;
                        if (duration > 0) totalMinutes += duration;

                        segments.push({
                            in: currentInTime,
                            out: logTime,
                            duration: duration
                        });
                        currentIn = null;
                    }
                });

                // If still checked in
                if (currentIn !== null) {
                    var isToday = dateStr === get_today_date();
                    var endMins = isToday ? (now.getHours() * 60 + now.getMinutes()) : 1439;
                    var duration = endMins - currentIn;
                    if (duration > 0) totalMinutes += duration;

                    segments.push({
                        in: currentInTime,
                        out: 'Active',
                        duration: duration
                    });
                }

                timelineHTML = segments.map(s => {
                    var outStr = s.out === 'Active' ? '<span style="color: #10b981; font-weight: 700;">Active</span>' : format_time_12hr(s.out);
                    return `
                        <div style="display: inline-block; background: #f8fafc; border: 1px solid #e2e8f0; padding: 4px 10px; border-radius: 6px; margin: 0 6px 6px 0; font-size: 12.5px; color: #475569; font-weight: 600;">
                            ${format_time_12hr(s.in)} <span style="color: #cbd5e0; margin: 0 4px;">→</span> ${outStr}
                        </div>
                    `;
                }).join('');
            }

            var hours = Math.floor(totalMinutes / 60);
            var mins = totalMinutes % 60;
            var totalHoursStr = totalMinutes > 0 ? `${hours}h ${mins}m` : '-';

            html += `
                <div class="list-item-container" style="align-items: flex-start; padding: 14px 18px;">
                    <div style="flex: 1; font-weight: 700; color: #1a202c; font-size: 14.5px;">${empName}</div>
                    <div style="flex: 0.8; font-size: 14px; color: #718096;">${dateStr}</div>
                    <div style="flex: 2;">
                        <div style="display: flex; flex-wrap: wrap;">
                            ${timelineHTML || '<span style="color: #cbd5e0; font-style: italic; font-size: 13px;">No logs</span>'}
                        </div>
                    </div>
                    <div style="flex: 0.8; text-align: right;">
                        <span style="font-weight: 700; color: #475569; font-size: 14.5px;">${totalHoursStr}</span>
                    </div>
                </div>
            `;
        });
    } else {
        html += `
            <div style="padding: 60px 40px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 20px; opacity: 0.3;">
                    <i class="fa fa-clock-o" style="color: #6366f1;"></i>
                </div>
                <div style="color: #1a202c; font-size: 16px; font-weight: 600; margin-bottom: 8px;">No Attendance Records Found</div>
                <div style="color: #718096; font-size: 14px; margin-bottom: 20px;">Attendance records will appear here when employees mark their attendance.</div>
                <div style="display: flex; justify-content: center; gap: 12px; flex-wrap: wrap;">
                    <button class="btn btn-primary btn-sm" onclick="frappe.set_route('List', 'Employee Checkin')">
                        <i class="fa fa-plus" style="margin-right: 6px;"></i>Mark Attendance
                    </button>
                    <button class="btn btn-default btn-sm" onclick="frappe.set_route('List', 'NetraNext Face Registration Request')">
                        <i class="fa fa-user" style="margin-right: 6px;"></i>Face Registration Requests
                    </button>
                </div>
            </div>
        `;
    }

    html += `
            </div>
            <div class="list-footer">
                ${render_pagination('attendance', totalCount, currentPage)}
            </div>
        </div>
    `;

    document.getElementById("attendance-content").innerHTML /* nosemgrep */ = html;
}

function show_error_state(message) {
    var errorHtml = `
        <div style="text-align: center; padding: 40px; color: #e53e3e;">
            <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
            <h3 style="color: #e53e3e; margin-bottom: 8px;">Error Loading Data</h3>
            <p style="color: #718096; margin-bottom: 20px;">${message}</p>
            <button class="btn btn-primary" onclick="refresh_dashboard_data()">Retry</button>
        </div>
    `;

    // Set error state in journey and attendance sections
    document.getElementById("journey-content").innerHTML = errorHtml;
    document.getElementById("attendance-content").innerHTML = '<div style="padding: 20px; text-align: center; color: #cbd5e0;">Data loading failed</div>';
}

function show_schedule_trip_dialog() {
    var dialog = new frappe.ui.Dialog({
        title: 'Schedule Upcoming Trip',
        fields: [
            {
                fieldname: 'employee',
                label: 'Assign to Employee',
                fieldtype: 'Link',
                options: 'Employee',
                reqd: 1
            },
            {
                fieldname: 'destination_address',
                label: 'Destination Address',
                fieldtype: 'Link',
                options: 'Address',
                reqd: 1
            },
            {
                fieldname: 'scheduled_start_time',
                label: 'Start Date & Time',
                fieldtype: 'Datetime',
                reqd: 1
            },
            {
                fieldname: 'scheduled_end_time',
                label: 'End Date & Time',
                fieldtype: 'Datetime',
                reqd: 1
            }
        ],
        primary_action_label: 'Schedule Trip',
        primary_action(values) {
            frappe.call({
                method: "frappe.client.insert",
                args: {
                    doc: {
                        doctype: "Scheduled Trip",
                        employee: values.employee,
                        status: "Scheduled",
                        scheduled_start_time: values.scheduled_start_time,
                        scheduled_end_time: values.scheduled_end_time,
                        destination_address: values.destination_address
                    }
                },
                callback: function(r) {
                    if (!r.exc) {
                        frappe.show_alert({message: __('Trip Scheduled Successfully'), indicator: 'green'});
                        dialog.hide();
                        refresh_dashboard_data();
                    }
                }
            });
        }
    });
    dialog.show();
}